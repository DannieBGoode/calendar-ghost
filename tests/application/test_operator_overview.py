"""The Operator Overview shows each User's Installation Status with calendars by neutral labels."""

from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from calendar_sync.application.administration import AdministratorRequired, UserNotFound
from calendar_sync.application.locking import RuleLocks
from calendar_sync.application.operator_overview import (
    OperatorOverview,
    OverviewQuery,
    UserStatuses,
    calendar_labels,
)
from calendar_sync.application.ports import (
    CalendarAccess,
    ConnectedAccountState,
    DiscoveredCalendar,
    ProviderCallCounts,
    ProviderCallUse,
    RuleRunOutcome,
    RunKind,
    UserQuery,
)
from calendar_sync.application.providers import ProviderKind
from calendar_sync.application.status import StatusVerdict
from calendar_sync.domain.access import Role, User, UserId, UserState
from calendar_sync.domain.model import ConnectedAccountId, SyncRuleId, SyncRuleState
from calendar_sync.infrastructure.persistence.memory import InMemoryUnitOfWorkFactory
from tests.helpers import NOW, RecentSchedulerHeartbeat, endpoint, rule
from tests.identity_fakes import MemoryUsers
from tests.users import OTHER_USER, USER

DAY = timedelta(days=1)


class FixedClock:
    def now(self) -> datetime:
        return NOW


FAMILY = endpoint("personal-account", "family@group.calendar.example")
WORK = endpoint("work-account", "work-calendar")
TRIPS = endpoint("personal-account", "trips-calendar")


def _statuses(units: InMemoryUnitOfWorkFactory) -> UserStatuses:
    return UserStatuses(
        units.installation(), RuleLocks(), FixedClock(), RecentSchedulerHeartbeat(FixedClock())
    )


def test_calendars_are_numbered_in_the_order_their_rules_were_created() -> None:
    first = replace(rule(), id=SyncRuleId("rule-z"), source=FAMILY, destination=WORK)
    second = replace(rule(), id=SyncRuleId("rule-a"), source=WORK, destination=TRIPS)

    assert calendar_labels([first, second]) == {
        FAMILY: "Calendar 1",
        WORK: "Calendar 2",
        TRIPS: "Calendar 3",
    }


def test_each_users_status_names_calendars_only_by_their_labels() -> None:
    units = InMemoryUnitOfWorkFactory()
    created_first = replace(rule(), id=SyncRuleId("rule-z"), source=FAMILY, destination=WORK)
    created_second = replace(rule(), id=SyncRuleId("rule-a"), source=WORK, destination=TRIPS)
    with units.for_user(USER)() as uow:
        uow.rules.add(created_first)
        uow.rules.add(created_second)
        uow.calendar_names.remember(
            ConnectedAccountId("work-account"),
            [DiscoveredCalendar("work-calendar", "Secret project", CalendarAccess.OWNER, False)],
        )
        uow.commit()

    statuses = _statuses(units).of([USER, OTHER_USER])

    names = {status.summary.rule.id.value: status.name for status in statuses[USER].rules}
    assert names == {"rule-a": "Calendar 2 → Calendar 3", "rule-z": "Calendar 1 → Calendar 2"}
    assert "Secret project" not in repr(statuses)
    assert statuses[OTHER_USER].rules == ()


def test_a_users_verdict_and_problems_are_their_own_overviews() -> None:
    units = InMemoryUnitOfWorkFactory()
    stopped = replace(rule(), state=SyncRuleState.DEGRADED)
    state = units.for_user(USER).state
    for account in (FAMILY, WORK):
        state.accounts[account.connected_account_id] = ConnectedAccountState.CONNECTED
    with units.for_user(USER)() as uow:
        uow.rules.add(stopped)
        uow.run_outcomes.record(
            RuleRunOutcome(stopped.id, RunKind.SYNC, NOW - timedelta(days=2), True)
        )
        uow.commit()

    status = _statuses(units).of([USER])[USER]

    assert status.health is StatusVerdict.STOPPED
    assert [(problem.kind.value, problem.rule_id) for problem in status.problems] == [
        ("stopped", stopped.id.value)
    ]
    assert status.summary == "Calendar 1 → Calendar 2: Stopped syncing."


ADMIN = User(
    UserId("admin"), "admin@example.test", Role.INSTALLATION_ADMINISTRATOR, UserState.ACTIVE, NOW
)
ALICE = User(UserId("alice"), "alice@example.test", Role.USER, UserState.ACTIVE, NOW + DAY)
BOB = User(UserId("bob"), "bob@example.test", Role.USER, UserState.ACTIVE, NOW + 2 * DAY)


def _installation() -> OperatorOverview:
    """Alice's rule stopped, Bob's runs, and the administrator has not set anything up."""
    units = InMemoryUnitOfWorkFactory()
    users = MemoryUsers()
    for user in (ADMIN, ALICE, BOB):
        users.add(user, "hash")
    bobs = (endpoint("bob-personal", "personal"), endpoint("bob-work", "work"))
    for owner, endpoints in ((ALICE, (FAMILY, WORK)), (BOB, bobs)):
        accounts = units.for_user(owner.id).state.accounts
        for account in endpoints:
            accounts[account.connected_account_id] = ConnectedAccountState.CONNECTED
    with units.for_user(ALICE.id)() as uow:
        uow.rules.add(replace(rule(), state=SyncRuleState.DEGRADED))
        uow.commit()
    with units.for_user(BOB.id)() as uow:
        running = replace(rule(), id=SyncRuleId("bob-rule"), source=bobs[0], destination=bobs[1])
        uow.rules.add(running)
        uow.run_outcomes.record(RuleRunOutcome(running.id, RunKind.SYNC, NOW, True))
        uow.provider_calls.add(NOW.date(), ProviderKind.GOOGLE, ProviderCallCounts(12, 1, 2))
        uow.commit()
    clock = FixedClock()
    return OperatorOverview(
        users,
        UserStatuses(units.installation(), RuleLocks(), clock, RecentSchedulerHeartbeat(clock)),
        units.installation(),
        clock,
    )


def _page(overview: OperatorOverview, **query: object) -> list[tuple[str, str]]:
    found = overview.page(ADMIN.id, OverviewQuery(**query))  # type: ignore[arg-type]
    return [(entry.user.id.value, entry.status.health.value) for entry in found.users]


def test_an_administrator_sees_each_users_verdict_and_resource_use() -> None:
    overview = _installation()

    page = overview.page(ADMIN.id, OverviewQuery())

    assert [(entry.user.id, entry.status.health) for entry in page.users] == [
        (ADMIN.id, StatusVerdict.SETUP),
        (ALICE.id, StatusVerdict.STOPPED),
        (BOB.id, StatusVerdict.HEALTHY),
    ]
    bob = page.users[2]
    assert (bob.resources.rules, bob.resources.activity_entries) == (1, 0)
    assert bob.resources.provider_calls == (ProviderCallUse(ProviderKind.GOOGLE, 12, 1, 2),)
    assert bob.calls_since == NOW.date() - timedelta(days=29)
    assert page.total == 3
    members = overview.page(ADMIN.id, OverviewQuery(UserQuery(role=Role.USER)))
    assert [entry.user.id for entry in members.users] == [ALICE.id, BOB.id]


def test_people_filter_and_sort_by_verdict_across_every_page() -> None:
    overview = _installation()

    assert _page(overview, verdict=StatusVerdict.STOPPED) == [("alice", "stopped")]
    assert _page(overview, by_verdict=True) == [
        ("alice", "stopped"),
        ("admin", "setup"),
        ("bob", "healthy"),
    ]
    assert _page(overview, users=UserQuery(descending=True), by_verdict=True)[0] == (
        "bob",
        "healthy",
    )
    second = overview.page(ADMIN.id, OverviewQuery(UserQuery(offset=1, limit=1), by_verdict=True))
    assert ([entry.user.id for entry in second.users], second.total) == ([ADMIN.id], 3)
    healthy = overview.page(
        ADMIN.id, OverviewQuery(UserQuery(limit=1), verdict=StatusVerdict.HEALTHY)
    )
    assert healthy.total == 1


def test_only_an_administrator_lists_people() -> None:
    with pytest.raises(AdministratorRequired):
        _installation().page(ALICE.id, OverviewQuery())


def test_a_user_sees_exactly_what_an_administrator_sees_about_them() -> None:
    overview = _installation()

    assert overview.own(ALICE.id) == overview.of(ADMIN.id, ALICE.id)
    assert overview.own(ALICE.id).status.health is StatusVerdict.STOPPED


def test_nobody_else_learns_whether_a_user_exists() -> None:
    overview = _installation()

    # Not even Bob's own overview through People, which is an administrator's.
    for actor, subject in (
        (BOB.id, ALICE.id),
        (BOB.id, BOB.id),
        (BOB.id, UserId("nobody")),
        (ADMIN.id, UserId("nobody")),
    ):
        with pytest.raises(UserNotFound):
            overview.of(actor, subject)
