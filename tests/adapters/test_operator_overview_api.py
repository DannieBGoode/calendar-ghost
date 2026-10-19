"""The Operator Overview over the Web API: what an administrator and each User see (ADR 0030)."""

import logging
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from calendar_sync.application.identity.ports import AssignmentChange
from calendar_sync.application.operations.installation_health import (
    InstallationIncident,
    InstallationNotifications,
)
from calendar_sync.application.operations.ports import SchedulerProgress
from calendar_sync.application.sync.errors import ProviderFailure
from calendar_sync.application.sync.ports import (
    CalendarAccess,
    DiscoveredCalendar,
    ProviderCallCounts,
)
from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import Container, build_adapters, compose
from calendar_sync.domain.access import UserId
from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.audit import AuditAction, AuditEntry, AuditOutcome, RecordedEvent
from calendar_sync.domain.causes import Cause
from calendar_sync.domain.model import ConnectedAccountId, SyncRuleId, SyncRuleState
from calendar_sync.domain.plans import AssignmentSource
from calendar_sync.domain.providers import ProviderFailureKind
from calendar_sync.infrastructure.clock import SystemClock
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.persistence.plans import SqlitePlans
from calendar_sync.infrastructure.scheduling import SchedulerWatch
from calendar_sync.interfaces.api.app import create_app
from calendar_sync.interfaces.api.dependencies import SESSION_COOKIE
from tests.adapters.microsoft.test_calendar_provider_contract import outlook
from tests.adapters.test_notifications import RecordingSmtp
from tests.fake_microsoft_graph_api import Refusal
from tests.helpers import NOW, endpoint, rule
from tests.plans import FAMILY, FREE, plans_on
from tests.users import OTHER_USER, add_user, administrator, session_for, sqlite_units

MEMBER_EMAIL = "member@example.test"
OUTLOOK_EMAIL = "outlook-person@example.test"
OUTLOOK_USER = UserId("user-outlook")


@dataclass(frozen=True, slots=True)
class Person:
    """A User whose calendars, accounts, and events carry markers no overview may show."""

    user: UserId
    marker: str
    provider: ProviderKind = ProviderKind.GOOGLE

    @property
    def accounts(self) -> tuple[str, str]:
        return (f"{self.marker}-personal-account", f"{self.marker}-work-account")

    @property
    def markers(self) -> tuple[str, ...]:
        return (
            f"{self.marker}-calendar-name",
            *(self.email(account) for account in self.accounts),
            f"{self.marker}-calendar-id",
            f"{self.marker}-event-title",
            self.google_message,
        )

    @property
    def microsoft_message(self) -> str:
        """What Microsoft's own message might say, quoting the request: never repeated."""
        return f"{self.marker}-microsoft-message about {self.marker}-calendar-id"

    @property
    def google_message(self) -> str:
        """What Google's own message might say, quoting the request: never repeated anywhere."""
        return f"{self.marker}-google-message about {self.marker}-calendar-id"

    def email(self, account: str) -> str:
        return f"{account}-email@mail.example"


def _seed(database: Path, person: Person) -> None:
    """A stopped rule and a running one between calendars named, identified, and holding events
    with the person's markers, in accounts whose emails carry them too."""
    units = sqlite_units(database, user=person.user, accounts=person.accounts)
    with transaction(database) as connection:
        for account in person.accounts:
            connection.execute(
                "UPDATE connected_accounts SET email = ?, display_name = ?, provider = ? "
                "WHERE id = ?",
                (person.email(account), person.marker, person.provider.value, account),
            )
    calendar = f"{person.marker}-calendar-id"
    source, destination = (endpoint(account, calendar) for account in person.accounts)
    stopped = replace(
        rule(),
        id=SyncRuleId(f"{person.marker}-rule"),
        source=source,
        destination=destination,
        state=SyncRuleState.DEGRADED,
    )
    running = replace(
        stopped,
        id=SyncRuleId(f"{person.marker}-other-rule"),
        source=destination,
        destination=source,
        state=SyncRuleState.ENABLED,
    )
    with units() as uow:
        uow.rules.add(stopped)
        uow.rules.add(running)
        for account in person.accounts:
            uow.calendar_names.remember(
                ConnectedAccountId(account),
                [
                    DiscoveredCalendar(
                        calendar, f"{person.marker}-calendar-name", CalendarAccess.OWNER, False
                    )
                ],
            )
        uow.audit.append(
            AuditEntry(
                datetime.now(UTC),
                stopped.id,
                AuditAction.CONFLICT,
                AuditOutcome.BLOCKED,
                f"{person.marker}-event",
                event=RecordedEvent(f"{person.marker}-event-title"),
            )
        )
        uow.provider_calls.add(
            datetime.now(UTC).date(), ProviderKind.GOOGLE, ProviderCallCounts(9, 2, 1)
        )
        uow.commit()


def _fail(container: Container, person: Person) -> None:
    """The provider refused the person's work account, with a message that quotes their calendar:
    Google because the Calendar API is turned off, and Microsoft, answering the Outlook adapter
    itself, because the calendar is closed to the account."""
    services = container.for_user(person.user)
    with services.rule_health.unit_of_work() as uow:
        stopped = uow.rules.get(SyncRuleId(f"{person.marker}-other-rule"))
    assert stopped is not None
    account = ConnectedAccountId(person.accounts[1])
    if person.provider is ProviderKind.OUTLOOK:
        failure = replace(_outlook_refusal(person), account_id=account)
    else:
        failure = ProviderFailure(
            ProviderFailureKind.AUTHORIZATION,
            f"<HttpError 403 returned {person.google_message!r}>",
            account_id=account,
            provider=ProviderKind.GOOGLE,
            cause=Cause.API_DISABLED,
        )
    services.rule_health.record_failure(stopped, failure)


def _outlook_refusal(person: Person) -> ProviderFailure:
    provider, graph = outlook()
    graph.refuse(
        Refusal(
            403,
            {"error": {"code": "ErrorAccessDenied", "message": person.microsoft_message}},
        )
    )
    try:
        provider.list_events(endpoint("work-account", "work-calendar"), datetime.now(UTC))
    except ProviderFailure as failure:
        return failure
    raise AssertionError("the fake was told to refuse")


@dataclass
class RecordingNotifications(InstallationNotifications):
    sent: list[InstallationIncident] = field(default_factory=list)

    def installation_incident_opened(self, incident: InstallationIncident) -> None:
        self.sent.append(incident)


@dataclass(frozen=True, slots=True)
class Stalled:
    def progress(self) -> SchedulerProgress:
        long_ago = datetime.now(UTC) - timedelta(hours=1)
        return SchedulerProgress(long_ago, None, long_ago)


@dataclass(frozen=True, slots=True)
class Installation:
    database: Path
    admin: Person
    member: Person
    client: TestClient
    outlook: Person
    """Someone whose accounts are Microsoft accounts."""

    def as_member(self) -> None:
        self.client.cookies.set(SESSION_COOKIE, session_for(self.database, self.member.user))

    def as_admin(self) -> None:
        self.client.cookies.set(SESSION_COOKIE, session_for(self.database, self.admin.user))


@pytest.fixture
def installation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Installation]:
    RecordingSmtp.sent = []
    monkeypatch.setattr("calendar_sync.infrastructure.notifications.smtplib.SMTP", RecordingSmtp)
    database = tmp_path / "test.db"
    # The installation sends email, linking each person to their next step.
    settings = Settings(
        database,
        smtp_host="smtp.example.test",
        smtp_sender="ghost@example.test",
        public_url="https://ghost.example.test",
    )
    adapters = build_adapters(settings)
    admin = Person(administrator(adapters), "alpha")
    member = Person(add_user(database, OTHER_USER, role="user", email=MEMBER_EMAIL), "bravo")
    outlook_user = add_user(database, OUTLOOK_USER, role="user", email=OUTLOOK_EMAIL)
    outlook_person = Person(outlook_user, "charlie", ProviderKind.OUTLOOK)
    for person in (admin, member, outlook_person):
        _seed(database, person)
    container = compose(settings, adapters)
    for person in (admin, member, outlook_person):
        _fail(container, person)
    with TestClient(create_app(container)) as client:
        yielded = Installation(database, admin, member, client, outlook_person)
        yielded.as_admin()
        yield yielded


def _person_row(page: Any, user: UserId) -> Any:
    return next(row for row in page["users"] if row["id"] == user.value)


def test_people_shows_each_users_verdict_problems_last_sync_and_resource_use(
    installation: Installation,
) -> None:
    response = installation.client.get("/api/v1/users")
    page = response.json()

    assert response.headers["cache-control"] == "no-store"

    member = _person_row(page, installation.member.user)
    # Google refused one of each User's accounts, which stopped both of their rules.
    assert member["verdict"] == "stopped"
    assert member["problems"] >= 2
    assert member["last_synced_at"] is None
    assert member["resources"] == {
        "rules": 2,
        "connected_accounts": 2,
        "activity_entries": 1,
        "provider_calls": [{"provider": "google", "calls": 9, "rate_limited": 2, "failed": 1}],
        "since": (datetime.now(UTC).date() - timedelta(days=29)).isoformat(),
    }


def test_people_filter_and_sort_by_verdict(installation: Installation) -> None:
    client = installation.client

    stopped = client.get("/api/v1/users", params={"verdict": "stopped"}).json()
    healthy = client.get("/api/v1/users", params={"verdict": "healthy"}).json()
    sorted_page = client.get("/api/v1/users", params={"sort": "verdict", "page_size": 1}).json()

    # Everyone's rules stopped: two people's at Google, one person's at Outlook.
    assert stopped["total"] == 3
    assert (healthy["total"], healthy["users"]) == (0, [])
    assert (sorted_page["total"], len(sorted_page["users"])) == (3, 1)


def test_an_administrator_sees_each_calendar_only_by_its_number(
    installation: Installation,
) -> None:
    seen = installation.client.get(f"/api/v1/users/{installation.member.user.value}/overview")

    assert seen.status_code == 200
    assert seen.headers["cache-control"] == "no-store"
    view = seen.json()
    assert view["user"]["email"] == MEMBER_EMAIL
    assert [rule["name"] for rule in view["status"]["rules"]] == [
        "Calendar 2 → Calendar 1",
        "Calendar 1 → Calendar 2",
    ]
    # Each calendar's number, so the Web UI can name it in the reader's language.
    assert [
        (rule["source"]["number"], rule["destination"]["number"])
        for rule in view["status"]["rules"]
    ] == [(2, 1), (1, 2)]


def test_a_user_has_no_route_to_read_the_overview_about_them(installation: Installation) -> None:
    # Settings no longer shows a User what administrators see; they read their own status.
    installation.as_member()

    assert installation.client.get("/api/v1/account/overview").status_code == 404


def test_a_users_own_status_names_calendars_and_numbers_none(installation: Installation) -> None:
    installation.as_member()
    rules = installation.client.get("/api/v1/status").json()["rules"]

    assert {rule["source"]["number"] for rule in rules} == {None}


def test_nobody_else_learns_whether_a_user_exists(installation: Installation) -> None:
    client = installation.client
    unknown = client.get("/api/v1/users/nobody/overview")
    installation.as_member()
    theirs = client.get(f"/api/v1/users/{installation.admin.user.value}/overview")
    nobody = client.get("/api/v1/users/nobody/overview")
    own = client.get(f"/api/v1/users/{installation.member.user.value}/overview")

    assert {response.status_code for response in (unknown, theirs, nobody)} == {404}
    assert {response.json()["code"] for response in (unknown, theirs, nobody)} == {"user_not_found"}
    # Even their own, by identifier: People is an administrator's.
    assert own.status_code == 404


def test_no_calendar_account_or_event_reaches_the_overview_health_notifications_or_logs(
    installation: Installation, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger="calendar_sync")
    client = installation.client
    shown = [
        client.get("/api/v1/users").text,
        client.get("/api/v1/users", params={"sort": "verdict"}).text,
        client.get(f"/api/v1/users/{installation.admin.user.value}/overview").text,
        client.get(f"/api/v1/users/{installation.member.user.value}/overview").text,
        client.get("/api/v1/installation/health").text,
        client.get(f"/api/v1/users/{installation.outlook.user.value}/overview").text,
    ]
    installation.as_member()
    # A User's own status names their own calendars, but never repeats what Google said.
    own = [client.get(path).text for path in ("/api/v1/status", "/api/v1/incidents")]
    notifications = RecordingNotifications()
    SchedulerWatch(Stalled(), notifications, SystemClock()).check()
    shown.append(repr(notifications.sent))
    shown.append("\n".join(record.getMessage() for record in caplog.records))
    emails = [message.get_content() for message in RecordingSmtp.sent]
    shown.extend(emails)

    assert notifications.sent
    people = (installation.admin, installation.member, installation.outlook)
    for marker in (
        *(m for person in people for m in person.markers),
        installation.outlook.microsoft_message,
    ):
        for text in shown:
            assert marker not in text
    assert MEMBER_EMAIL in shown[0]
    # Each person heard of their own lapse, with a link to their dashboard and nothing more.
    assert len(emails) == 3
    assert all("What to do next: https://ghost.example.test/" in email for email in emails)
    # The Outlook person's problem is theirs: its Cause, from the adapter, says so.
    assert '"cause":"calendar_forbidden"' in shown[5]
    assert '"provider":"outlook"' in shown[5]
    for text in own:
        assert installation.member.google_message not in text
        assert '"cause":"api_disabled"' in text
    # The Cause and its hint reached them, without what Google said.
    assert '"cause":"api_disabled"' in shown[3]
    assert '"anchor":"the-google-calendar-api-is-turned-off"' in shown[4]


def test_installation_health_hints_a_cause_people_share_without_naming_them(
    installation: Installation,
) -> None:
    health = installation.client.get("/api/v1/installation/health").json()

    assert health["hints"] == [
        {
            "kind": "shared_cause",
            "cause": "api_disabled",
            "users": 2,
            "anchor": "the-google-calendar-api-is-turned-off",
            "provider": "google",
        }
    ]


def test_each_problem_says_its_cause_and_when_it_was_last_tried(
    installation: Installation,
) -> None:
    client = installation.client
    seen_by_admin = client.get(f"/api/v1/users/{installation.member.user.value}/overview").json()
    installation.as_member()
    status = client.get("/api/v1/status").json()
    incidents = client.get("/api/v1/incidents").json()

    lapsed = [p for p in seen_by_admin["status"]["problems"] if p["kind"] == "stopped"]
    assert lapsed
    assert {problem["cause"] for problem in lapsed} == {"api_disabled"}
    assert all(problem["last_tried_at"] for problem in lapsed)
    assert {p["cause"] for p in status["problems"] if p["kind"] == "stopped"} == {"api_disabled"}
    assert {incident["cause"] for incident in status["incidents"]} == {"api_disabled"}
    assert {incident["cause"] for incident in incidents} == {"api_disabled"}
    # Problems no provider failure explains name no Cause.
    assert {p["cause"] for p in status["problems"] if p["kind"] == "blocked"} == {None}
    assert "next_pass_at" in status["scheduler"]


def test_the_person_page_shows_no_plan_until_one_exists(installation: Installation) -> None:
    client = installation.client
    seen = client.get(f"/api/v1/users/{installation.member.user.value}/overview").json()
    people = client.get("/api/v1/users").json()["users"]

    assert seen["plan"] is None
    assert [row["plan"] for row in people] == [None, None, None]


def test_the_person_page_shows_the_plan_that_limits_them_and_their_own(
    installation: Installation,
) -> None:
    client = installation.client
    plans = SqlitePlans(installation.database)
    plans_on(plans, FREE, FAMILY)
    admin = installation.admin.user
    given = AssignmentChange(AssignmentSource.ADMINISTRATOR, admin, datetime.now(UTC))
    assigned = plans.assign_all([admin], FAMILY.key, given)

    def plan_of(user: UserId) -> Any:
        return client.get(f"/api/v1/users/{user.value}/overview").json()["plan"]

    member_while_on = plan_of(installation.member.user)
    admin_while_on = plan_of(admin)
    people_while_on = client.get("/api/v1/users").json()["users"]
    plans.change_settings(False, FREE.key, NOW)
    member_while_off = plan_of(installation.member.user)

    free = {"key": "free", "name": "Free", "on_default": True}
    # The member's two calendar accounts, where Free allows one.
    accounts_over = [{"limit": "connected_accounts", "in_use": 2, "allowed": 1}]
    # The rule the refused authorization stopped keeps its place; the other one gave it up.
    free_use = {
        "rules": {"in_use": 1, "allowed": 1},
        "connected_accounts": {"in_use": 2, "allowed": 1},
        "integration_tokens": {"in_use": 0, "allowed": 0},
        "sync_interval": "5_minutes",
    }
    assert assigned
    assert member_while_on == {
        "basis": "plan",
        "plan": free,
        "assigned": None,
        "has": free,
        "over": accounts_over,
        "assigned_by": None,
        "assigned_at": None,
        "use": free_use,
    }
    # No Plan limits an administrator; the one they were given waits until they stop. Their
    # page still says who gave it, and how much of it they use.
    assert admin_while_on == {
        "basis": "administrator",
        "plan": None,
        "assigned": {"key": "family", "name": "Family"},
        "has": {"key": "family", "name": "Family", "on_default": False},
        "over": [],
        "assigned_by": "admin@example.test",
        "assigned_at": given.at.isoformat(),
        "use": {
            "rules": {"in_use": 1, "allowed": 5},
            "connected_accounts": {"in_use": 2, "allowed": 3},
            "integration_tokens": {"in_use": 0, "allowed": 2},
            "sync_interval": "instant",
        },
    }
    # Once a Plan exists, the person page shows it even while Plans are off, with what the Plan
    # they have would say once Plans are on.
    assert member_while_off == {
        "basis": "plans_off",
        "plan": None,
        "assigned": None,
        "has": free,
        "over": accounts_over,
        "assigned_by": None,
        "assigned_at": None,
        "use": free_use,
    }
    # Each row of People shows the Plan as the person's page does.
    assert _person_row({"users": people_while_on}, admin)["plan"] == admin_while_on
    assert _person_row({"users": people_while_on}, installation.member.user)["plan"] == (
        member_while_on
    )


def test_people_are_found_by_the_plan_they_have(installation: Installation) -> None:
    client = installation.client
    plans = SqlitePlans(installation.database)
    plans_on(plans, FREE, FAMILY)
    member = installation.member.user
    given = AssignmentChange(AssignmentSource.ADMINISTRATOR, installation.admin.user, NOW)
    plans.assign_all([member], FAMILY.key, given)

    def having(plan: str, **query: str) -> set[str]:
        page = client.get("/api/v1/users", params={"plan": plan, **query}).json()
        assert page["total"] == len(page["users"])
        return {row["id"] for row in page["users"]}

    malformed = client.get("/api/v1/users", params={"plan": "Not a key"})

    assert having("family") == {member.value}
    # The default is everyone's without a Plan of their own, an administrator's too.
    assert having("free") == {installation.admin.user.value, OUTLOOK_USER.value}
    assert having("free", role="user") == {OUTLOOK_USER.value}
    assert having("gold") == set()
    assert (malformed.status_code, malformed.json()["code"]) == (422, "invalid_request")
