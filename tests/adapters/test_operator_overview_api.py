"""The Operator Overview over the Web API: what an administrator and each User see (ADR 0030)."""

import logging
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from calendar_sync.application.installation_health import (
    InstallationIncident,
    InstallationNotifications,
)
from calendar_sync.application.ports import (
    AuditAction,
    AuditEntry,
    AuditOutcome,
    CalendarAccess,
    DiscoveredCalendar,
    ProviderCallCounts,
    RecordedEvent,
    SchedulerProgress,
)
from calendar_sync.application.providers import ProviderKind
from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import build_adapters, compose
from calendar_sync.domain.access import UserId
from calendar_sync.domain.model import ConnectedAccountId, SyncRuleId, SyncRuleState
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.scheduling import SchedulerWatch, SystemClock
from calendar_sync.interfaces.api.app import create_app
from calendar_sync.interfaces.api.dependencies import SESSION_COOKIE
from tests.helpers import endpoint, rule
from tests.users import OTHER_USER, add_user, administrator, session_for, sqlite_units

MEMBER_EMAIL = "member@example.test"


@dataclass(frozen=True, slots=True)
class Person:
    """A User whose calendars, accounts, and events carry markers no overview may show."""

    user: UserId
    marker: str

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
        )

    def email(self, account: str) -> str:
        return f"{account}-email@mail.example"


def _seed(database: Path, person: Person) -> None:
    """A stopped rule and a running one between calendars named, identified, and holding events
    with the person's markers, in accounts whose emails carry them too."""
    units = sqlite_units(database, user=person.user, accounts=person.accounts)
    with transaction(database) as connection:
        for account in person.accounts:
            connection.execute(
                "UPDATE connected_accounts SET email = ?, display_name = ? WHERE id = ?",
                (person.email(account), person.marker, account),
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

    def as_member(self) -> None:
        self.client.cookies.set(SESSION_COOKIE, session_for(self.database, self.member.user))

    def as_admin(self) -> None:
        self.client.cookies.set(SESSION_COOKIE, session_for(self.database, self.admin.user))


@pytest.fixture
def installation(tmp_path: Path) -> Iterator[Installation]:
    database = tmp_path / "test.db"
    settings = Settings(database)
    adapters = build_adapters(settings)
    admin = Person(administrator(adapters), "alpha")
    member = Person(add_user(database, OTHER_USER, role="user", email=MEMBER_EMAIL), "bravo")
    for person in (admin, member):
        _seed(database, person)
    with TestClient(create_app(compose(settings, adapters))) as client:
        yielded = Installation(database, admin, member, client)
        yielded.as_admin()
        yield yielded


def _person_row(page: Any, user: UserId) -> Any:
    return next(row for row in page["users"] if row["id"] == user.value)


def test_people_shows_each_users_verdict_problems_last_sync_and_resource_use(
    installation: Installation,
) -> None:
    page = installation.client.get("/api/v1/users").json()

    member = _person_row(page, installation.member.user)
    # Without a master key no scheduler runs, so every User with an enabled rule reads stalled.
    assert member["verdict"] == "stalled"
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

    stalled = client.get("/api/v1/users", params={"verdict": "stalled"}).json()
    healthy = client.get("/api/v1/users", params={"verdict": "healthy"}).json()
    sorted_page = client.get("/api/v1/users", params={"sort": "verdict", "page_size": 1}).json()

    assert stalled["total"] == 2
    assert (healthy["total"], healthy["users"]) == (0, [])
    assert (sorted_page["total"], len(sorted_page["users"])) == (2, 1)


def test_a_user_sees_exactly_what_an_administrator_sees_about_them(
    installation: Installation,
) -> None:
    client = installation.client
    seen_by_admin = client.get(f"/api/v1/users/{installation.member.user.value}/overview")
    installation.as_member()
    seen_by_member = client.get("/api/v1/account/overview")

    assert seen_by_admin.status_code == seen_by_member.status_code == 200
    assert seen_by_admin.headers["cache-control"] == "no-store"
    admin_view, own_view = seen_by_admin.json(), seen_by_member.json()
    for view in (admin_view, own_view):
        view["status"].pop("checked_at")
    assert admin_view == own_view
    assert admin_view["user"]["email"] == MEMBER_EMAIL
    assert [rule["name"] for rule in admin_view["status"]["rules"]] == [
        "Calendar 2 → Calendar 1",
        "Calendar 1 → Calendar 2",
    ]


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
        client.get("/api/v1/account/overview").text,
    ]
    installation.as_member()
    shown.append(client.get("/api/v1/account/overview").text)
    notifications = RecordingNotifications()
    SchedulerWatch(Stalled(), notifications, SystemClock()).check()
    shown.append(repr(notifications.sent))
    shown.append("\n".join(record.getMessage() for record in caplog.records))

    assert notifications.sent
    for marker in (*installation.admin.markers, *installation.member.markers):
        for text in shown:
            assert marker not in text
    assert MEMBER_EMAIL in shown[0]
