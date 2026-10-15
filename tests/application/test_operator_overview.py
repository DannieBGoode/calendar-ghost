"""The Operator Overview shows each User's Installation Status with calendars by neutral labels."""

import logging
from collections.abc import Collection, Mapping
from dataclasses import replace
from datetime import date, datetime, timedelta

import pytest

from calendar_sync.application.identity.administration import AdministratorRequired, UserNotFound
from calendar_sync.application.identity.ports import AssignmentChange, UserQuery
from calendar_sync.application.operations.operator_overview import (
    OperatorOverview,
    OverviewQuery,
    UserStatuses,
    calendar_labels,
)
from calendar_sync.application.operations.ports import (
    InstallationUnitOfWork,
    InstallationUnitOfWorkFactory,
    ProviderCallUse,
    ResourceUse,
)
from calendar_sync.application.operations.status import StatusVerdict
from calendar_sync.application.sync.locking import RuleLocks
from calendar_sync.application.sync.ports import (
    Allowances,
    CalendarAccess,
    DiscoveredCalendar,
    ProviderCallCounts,
)
from calendar_sync.domain.access import Role, User, UserId, UserState
from calendar_sync.domain.accounts import ConnectedAccountState, ProviderKind
from calendar_sync.domain.model import ConnectedAccountId, SyncRuleId, SyncRuleState
from calendar_sync.domain.plans import Allowance, AllowanceBasis, AssignmentSource
from calendar_sync.domain.runs import RuleRunOutcome, RunKind
from calendar_sync.infrastructure.persistence.memory import InMemoryUnitOfWorkFactory
from tests.helpers import NOW, RecentSchedulerHeartbeat, endpoint, rule
from tests.identity_fakes import BrokenAllowances, MemoryPlans, MemoryUsers
from tests.plans import FAMILY as FAMILY_PLAN
from tests.plans import FREE, plans_on
from tests.users import OTHER_USER, USER, memory_units, rule_accounts

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
    memory_units(units, accounts=rule_accounts(created_first, created_second))
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
        state.providers[account.connected_account_id] = ProviderKind.GOOGLE
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
        state = units.for_user(owner.id).state
        for account in endpoints:
            state.accounts[account.connected_account_id] = ConnectedAccountState.CONNECTED
            state.providers[account.connected_account_id] = ProviderKind.GOOGLE
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
    plans = MemoryPlans(users=users)
    return OperatorOverview(
        users,
        UserStatuses(units.installation(), RuleLocks(), clock, RecentSchedulerHeartbeat(clock)),
        units.installation(),
        clock,
        plans,
        plans,
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


class CountedResourceReads:
    """An installation unit factory that records whose resource use was read."""

    def __init__(self, inner: InstallationUnitOfWorkFactory) -> None:
        self.inner = inner
        self.read: list[list[UserId]] = []

    def __call__(self) -> InstallationUnitOfWork:
        unit = self.inner()
        read = self.read
        original = unit.resource_use

        def resource_use(users: Collection[UserId], since: date) -> Mapping[UserId, ResourceUse]:
            read.append(list(users))
            return original(users, since)

        unit.resource_use = resource_use  # type: ignore[method-assign]
        return unit


def test_sorting_by_verdict_reads_resource_use_only_for_the_page_shown() -> None:
    overview = _installation()
    counted = CountedResourceReads(overview.installation)
    overview.installation = counted

    page = overview.page(ADMIN.id, OverviewQuery(UserQuery(limit=1), by_verdict=True))

    assert [entry.user.id for entry in page.users] == [ALICE.id]
    assert counted.read == [[ALICE.id]]


def test_filtering_by_verdict_reads_everyone_who_matches_whatever_the_count_said() -> None:
    """A person who joins between counting and reading is still assessed (review on PR 68)."""
    overview = _installation()
    users = overview.users
    assert isinstance(users, MemoryUsers)

    class StaleCount(MemoryUsers):
        def count(self) -> int:
            return 1

    stale = StaleCount(users.users, users.hashes)
    overview.users = stale

    page = overview.page(ADMIN.id, OverviewQuery(by_verdict=True))

    assert page.total == 3
    assert [entry.user.id for entry in page.users] == [ALICE.id, ADMIN.id, BOB.id]


def _plans(overview: OperatorOverview) -> MemoryPlans:
    """The installation's Plans, which `_installation` keeps in memory."""
    assert isinstance(overview.plans, MemoryPlans)
    return overview.plans


def _allowances(overview: OperatorOverview) -> dict[UserId, Allowance | None]:
    page = overview.page(ADMIN.id, OverviewQuery())
    return {entry.user.id: entry.allowance for entry in page.users}


def _bob_on_family(overview: OperatorOverview) -> None:
    """Free is the default, and Bob has Family as his own Plan."""
    plans = _plans(overview)
    plans_on(plans, FREE, FAMILY_PLAN)
    plans.assign(
        BOB.id, FAMILY_PLAN.key, AssignmentChange(AssignmentSource.ADMINISTRATOR, ADMIN.id, NOW)
    )


def test_no_plan_shows_while_no_plan_exists() -> None:
    overview = _installation()
    # Nothing reads Allowances while no Plan exists, so not even a failing read is noticed.
    overview.allowances = BrokenAllowances()

    assert _allowances(overview) == {ADMIN.id: None, ALICE.id: None, BOB.id: None}
    assert overview.of(ADMIN.id, ALICE.id).allowance is None


def test_every_person_shows_what_their_plan_allows_once_plans_are_on() -> None:
    overview = _installation()
    _bob_on_family(overview)

    assert _allowances(overview) == {
        ADMIN.id: Allowance(AllowanceBasis.ADMINISTRATOR),
        ALICE.id: Allowance(AllowanceBasis.PLAN, plan=FREE, on_default=True),
        BOB.id: Allowance(AllowanceBasis.PLAN, plan=FAMILY_PLAN, assigned=FAMILY_PLAN),
    }
    assert overview.of(ADMIN.id, BOB.id).allowance == Allowance(
        AllowanceBasis.PLAN, plan=FAMILY_PLAN, assigned=FAMILY_PLAN
    )


def test_every_person_shows_their_own_plan_while_plans_are_off() -> None:
    """An administrator can prepare Plans before turning them on."""
    overview = _installation()
    _bob_on_family(overview)
    _plans(overview).change_settings(False, FREE.key)

    assert _allowances(overview) == {
        ADMIN.id: Allowance(AllowanceBasis.PLANS_OFF),
        ALICE.id: Allowance(AllowanceBasis.PLANS_OFF),
        BOB.id: Allowance(AllowanceBasis.PLANS_OFF, assigned=FAMILY_PLAN),
    }


class CountedAllowances:
    """The installation's Allowances, recording each read."""

    def __init__(self, inner: Allowances) -> None:
        self.inner = inner
        self.read: list[list[UserId]] = []

    def of(self, user: UserId) -> Allowance:
        raise AssertionError("the overview reads a page of Users at once")

    def of_users(self, users: Collection[UserId]) -> Mapping[UserId, Allowance]:
        self.read.append(list(users))
        return self.inner.of_users(users)


def test_a_page_reads_its_peoples_allowances_at_once() -> None:
    overview = _installation()
    _bob_on_family(overview)
    counted = CountedAllowances(overview.allowances)
    overview.allowances = counted

    overview.page(ADMIN.id, OverviewQuery(UserQuery(limit=2)))

    assert counted.read == [[ADMIN.id, ALICE.id]]


class UnreadablePlans(MemoryPlans):
    """Plans whose catalog cannot be read, as a locked or failing database would."""

    def any_plans(self) -> bool:
        raise RuntimeError("database is locked")


@pytest.mark.parametrize("fault", ["allowances", "catalog"])
def test_a_plans_fault_shows_no_plan_and_never_fails_people(
    fault: str, caplog: pytest.LogCaptureFixture
) -> None:
    overview = _installation()
    _bob_on_family(overview)
    if fault == "allowances":
        overview.allowances = BrokenAllowances()
    else:
        overview.plans = UnreadablePlans(users=_plans(overview).users)

    with caplog.at_level(logging.WARNING):
        shown = _allowances(overview)
        person = overview.of(ADMIN.id, BOB.id)

    assert shown == {ADMIN.id: None, ALICE.id: None, BOB.id: None}
    assert (person.user.id, person.allowance) == (BOB.id, None)
    assert "could not read Plans" in caplog.text
    # Only the error's class: its text could say more than the overview may log.
    assert "RuntimeError" in caplog.text
    assert "database is locked" not in caplog.text
