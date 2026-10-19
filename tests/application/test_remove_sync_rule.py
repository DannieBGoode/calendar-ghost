from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from threading import Thread

import pytest

from calendar_sync.application.sync.errors import (
    ConnectedAccountDisconnected,
    ConnectedAccountRequired,
    DuplicateDirectionalRelationship,
    NotACalendarChange,
    ProjectionOwnershipMismatch,
    ProviderFailure,
    RemovalInterrupted,
    RemovalRequiresAuthorization,
    RemovalRequiresProvider,
    ReplacementInterrupted,
)
from calendar_sync.application.sync.locking import RuleLocks
from calendar_sync.application.sync.ports import (
    AccountAuthorizations,
    ProjectionDeleter,
    UnitOfWorkFactory,
)
from calendar_sync.application.sync.removal import RemoveSyncRule
from calendar_sync.application.sync.rules import EnableSyncRule, ReplaceSyncRuleCalendars
from calendar_sync.domain.access import Role, User, UserState
from calendar_sync.domain.accounts import ConnectedAccountState, ProviderKind
from calendar_sync.domain.errors import InvalidStateTransition
from calendar_sync.domain.model import (
    CalendarEvent,
    ConnectedAccountId,
    EventId,
    EventMapping,
    EventMappingId,
    EventRef,
    EventStatus,
    ManagedOrigin,
    ProjectionContent,
    ProjectionFingerprint,
    ProjectionHandling,
    SyncRule,
    SyncRuleId,
    SyncRuleState,
    TransformationPolicy,
)
from calendar_sync.domain.providers import ProviderFailureKind
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.persistence.memory import (
    InMemoryUserUnitOfWorkFactory,
)
from calendar_sync.infrastructure.persistence.migrations import initialize_database
from tests.application.test_execute_sync_rule import FakeCalendarProvider, FixedClock
from tests.fake_calendar import FakeCalendars, enabled_rule_factory, sync_use_case
from tests.helpers import NOW, endpoint, event, occurrence, rule, series, week_start
from tests.identity_fakes import MemoryPlans, MemoryUsers
from tests.plans import FREE, plans_on
from tests.users import USER, memory_units, sqlite_units


class Accounts:
    def __init__(self, connected: bool = True) -> None:
        self.connected = connected

    def is_connected(self, account_id: ConnectedAccountId) -> bool:
        return self.connected


class RecordingProvider(FakeCalendarProvider):
    def __init__(self, fail_on_call: int | None = None) -> None:
        super().__init__(event())
        self.deleted_refs: list[EventRef] = []
        self.fail_on_call = fail_on_call

    def delete_projection(
        self,
        destination: EventRef,
        source: EventRef,
        rule_id: SyncRuleId,
        operation_key: str,
    ) -> None:
        if self.fail_on_call is not None and len(self.deleted_refs) + 1 == self.fail_on_call:
            raise ProviderFailure(ProviderFailureKind.AUTHORIZATION, "denied")
        self.deleted_refs.append(destination)


class DeleteOnlyCalendar:
    """Implements only ProjectionDeleter, the one provider role Rule Removal receives."""

    def __init__(self) -> None:
        self.deleted: list[EventRef] = []

    def delete_projection(
        self, destination: EventRef, source: EventRef, rule_id: SyncRuleId, operation_key: str
    ) -> None:
        self.deleted.append(destination)


class Ids:
    def new(self) -> str:
        return "replacement-rule"


def _with_mappings(
    count: int, state: SyncRuleState = SyncRuleState.ENABLED
) -> InMemoryUserUnitOfWorkFactory:
    unit_of_work = memory_units()
    unit_of_work.state.rules[rule().id] = rule(state=state)
    # Rule Replacement creates its draft under the same Connected Accounts.
    for endpoint_ in (rule().source, rule().destination):
        unit_of_work.state.accounts[endpoint_.connected_account_id] = (
            ConnectedAccountState.CONNECTED
        )
    _add_mappings(unit_of_work, count)
    return unit_of_work


def _add_mappings(unit_of_work: InMemoryUserUnitOfWorkFactory, count: int) -> None:
    """`count` mappings of rule-1, each to a projection of its own."""
    for index in range(count):
        source = EventRef(rule().source, EventId(f"source-{index}"))
        unit_of_work.state.mappings[(rule().id, source)] = EventMapping(
            EventMappingId(f"mapping-{index}"),
            rule().id,
            source,
            EventRef(rule().destination, EventId(f"destination-{index}")),
            "revision-1",
            ProjectionFingerprint("fingerprint"),
        )


def _remover(
    unit_of_work: InMemoryUserUnitOfWorkFactory,
    provider: ProjectionDeleter | None = None,
    accounts: AccountAuthorizations | None = None,
) -> RemoveSyncRule:
    return RemoveSyncRule(
        unit_of_work,
        provider if provider is not None else RecordingProvider(),
        accounts if accounts is not None else Accounts(),
        FixedClock(),
        RuleLocks(),
    )


def test_delete_removes_each_mapped_projection_then_the_rule() -> None:
    unit_of_work = _with_mappings(2)
    provider = RecordingProvider()

    result = _remover(unit_of_work, provider).execute(rule().id, ProjectionHandling.DELETE)

    assert (result.deleted, result.detached) == (2, 0)
    assert len(provider.deleted_refs) == 2
    assert unit_of_work.state.rules == {}
    assert unit_of_work.state.mappings == {}
    assert [entry.action for entry in unit_of_work.state.audit] == [
        "remove_projection",
        "remove_projection",
        "rule_removed",
    ]


def test_delete_needs_only_the_projection_deleter_role() -> None:
    unit_of_work = _with_mappings(2)
    calendar = DeleteOnlyCalendar()

    result = _remover(unit_of_work, calendar).execute(rule().id, ProjectionHandling.DELETE)

    assert (result.deleted, result.detached) == (2, 0)
    assert len(calendar.deleted) == 2
    assert unit_of_work.state.rules == {}


def test_running_removal_reports_its_handling_and_progress() -> None:
    unit_of_work = _with_mappings(3)
    locks = RuleLocks()
    seen: list[tuple[str | None, int | None, int]] = []

    class ObservingProvider(RecordingProvider):
        def delete_projection(
            self, destination: EventRef, source: EventRef, rule_id: SyncRuleId, operation_key: str
        ) -> None:
            work = locks.current_work(rule_id)
            assert work is not None
            seen.append((work.handling, work.total, work.done))
            super().delete_projection(destination, source, rule_id, operation_key)

    RemoveSyncRule(unit_of_work, ObservingProvider(), Accounts(), FixedClock(), locks).execute(
        rule().id, ProjectionHandling.DELETE
    )

    assert seen == [("delete", 3, 0), ("delete", 3, 1), ("delete", 3, 2)]
    assert locks.current_work(rule().id) is None


def test_detach_makes_no_provider_calls_even_without_google_configured() -> None:
    unit_of_work = _with_mappings(2)

    result = RemoveSyncRule(unit_of_work, None, None, FixedClock(), RuleLocks()).execute(
        rule().id, ProjectionHandling.DETACH
    )

    assert (result.deleted, result.detached) == (0, 2)
    assert unit_of_work.state.rules == {}
    assert unit_of_work.state.mappings == {}
    assert unit_of_work.state.audit[-1].action == "rule_removed"


def test_delete_is_blocked_when_destination_is_disconnected_or_provider_missing() -> None:
    unit_of_work = _with_mappings(1)
    provider = RecordingProvider()

    with pytest.raises(RemovalRequiresAuthorization):
        _remover(unit_of_work, provider, Accounts(connected=False)).execute(
            rule().id, ProjectionHandling.DELETE
        )
    with pytest.raises(RemovalRequiresProvider):
        RemoveSyncRule(unit_of_work, None, None, FixedClock(), RuleLocks()).execute(
            rule().id, ProjectionHandling.DELETE
        )
    assert provider.deleted_refs == []
    assert unit_of_work.state.rules[rule().id].state is SyncRuleState.ENABLED
    assert len(unit_of_work.state.mappings) == 1


def test_interrupted_delete_leaves_rule_inert_and_retry_completes() -> None:
    unit_of_work = _with_mappings(3)

    with pytest.raises(RemovalInterrupted) as interrupted:
        _remover(unit_of_work, RecordingProvider(fail_on_call=2)).execute(
            rule().id, ProjectionHandling.DELETE
        )

    assert (interrupted.value.processed, interrupted.value.remaining) == (1, 2)
    assert "retry" in str(interrupted.value)
    assert unit_of_work.state.rules[rule().id].state is SyncRuleState.REMOVING
    assert len(unit_of_work.state.mappings) == 2

    result = _remover(unit_of_work).execute(rule().id, ProjectionHandling.DETACH)

    assert result.detached == 2
    assert unit_of_work.state.rules == {}


def test_removal_interrupted_names_the_provider_that_failed() -> None:
    named = RemovalInterrupted(
        processed=1,
        remaining=2,
        failure=ProviderFailure(
            ProviderFailureKind.AUTHORIZATION,
            "denied",
            provider=ProviderKind.GOOGLE,
            provider_label="Example Calendar",
        ),
    )
    neutral = RemovalInterrupted(
        processed=1,
        remaining=2,
        failure=ProviderFailure(ProviderFailureKind.AUTHORIZATION, "denied"),
    )

    assert str(named) == (
        "removal stopped after 1 of 3 projections because Example Calendar reported "
        "authorization; retry to continue"
    )
    assert str(neutral) == (
        "removal stopped after 1 of 3 projections because the calendar provider reported "
        "authorization; retry to continue"
    )


REPLACEMENT = SyncRuleId("replacement-rule")
NEW_DESTINATION = endpoint("work-account", "other-calendar")


def _other(name: str) -> SyncRule:
    """Another enabled rule of the User, from a calendar of its own."""
    return SyncRule(
        SyncRuleId(name),
        endpoint("personal-account", f"{name}-calendar"),
        rule().destination,
        state=SyncRuleState.ENABLED,
    )


def _ordered(old: SyncRule) -> InMemoryUserUnitOfWorkFactory:
    """`old`, with two mappings, created between an older and a newer enabled rule."""
    unit_of_work = memory_units()
    with unit_of_work() as uow:
        for each in (_other("older"), old, _other("newer")):
            uow.rules.add(each)
        uow.commit()
    _add_mappings(unit_of_work, 2)
    return unit_of_work


def _counting(unit_of_work: InMemoryUserUnitOfWorkFactory) -> int:
    """How many of the User's rules count toward their Plan's rule limit."""
    return sum(each.counts_toward_plan for each in unit_of_work.state.rules.values())


def _replacer(
    unit_of_work: InMemoryUserUnitOfWorkFactory, remover: RemoveSyncRule | None = None
) -> ReplaceSyncRuleCalendars:
    return ReplaceSyncRuleCalendars(
        unit_of_work, remover if remover is not None else _remover(unit_of_work), Ids()
    )


def test_replacement_rejects_a_duplicate_relationship_before_removing_anything() -> None:
    unit_of_work = _with_mappings(1)
    unit_of_work.state.rules[SyncRuleId("existing")] = SyncRule(
        SyncRuleId("existing"), rule().source, NEW_DESTINATION
    )
    provider = RecordingProvider()

    with pytest.raises(DuplicateDirectionalRelationship):
        _replacer(unit_of_work, _remover(unit_of_work, provider)).execute(
            rule().id, rule().source, NEW_DESTINATION, ProjectionHandling.DELETE
        )

    assert provider.deleted_refs == []
    assert unit_of_work.state.rules[rule().id].state is SyncRuleState.ENABLED
    assert REPLACEMENT not in unit_of_work.state.rules


def test_replacement_rejects_unchanged_calendars() -> None:
    unit_of_work = _with_mappings(0)

    with pytest.raises(NotACalendarChange):
        _replacer(unit_of_work).execute(
            rule().id, rule().source, rule().destination, ProjectionHandling.DELETE
        )
    assert rule().id in unit_of_work.state.rules


def test_replacement_removes_the_rule_and_creates_a_draft_with_the_same_policy() -> None:
    unit_of_work = _with_mappings(1)
    details = TransformationPolicy(content=ProjectionContent.DETAILS)
    unit_of_work.state.rules[rule().id] = replace(rule(), transformation=details)

    replacement = _replacer(unit_of_work).execute(
        rule().id, rule().source, NEW_DESTINATION, ProjectionHandling.DETACH
    )

    assert replacement.removal.detached == 1
    assert list(unit_of_work.state.rules) == [REPLACEMENT]
    assert replacement.rule.state is SyncRuleState.DRAFT
    assert replacement.rule.transformation == details
    assert replacement.rule.destination == NEW_DESTINATION
    # The draft as inserted, with the place it took.
    assert replacement.rule == unit_of_work.state.rules[REPLACEMENT]
    assert replacement.removal.successor == replacement.rule


class CompetingRemoval(RemoveSyncRule):
    """Simulates another request creating the same relationship just after the checks pass."""

    def check(self, rule_id: SyncRuleId, handling: ProjectionHandling) -> None:
        RemoveSyncRule.check(self, rule_id, handling)
        with self.unit_of_work() as uow:
            uow.rules.add(SyncRule(SyncRuleId("competitor"), rule().source, NEW_DESTINATION))
            uow.commit()


def test_a_duplicate_that_appears_after_the_checks_is_refused_before_anything_changes() -> None:
    unit_of_work = _with_mappings(1)
    provider = RecordingProvider()
    remover = CompetingRemoval(unit_of_work, provider, Accounts(), FixedClock(), RuleLocks())

    with pytest.raises(DuplicateDirectionalRelationship):
        _replacer(unit_of_work, remover).execute(
            rule().id, rule().source, NEW_DESTINATION, ProjectionHandling.DELETE
        )

    assert provider.deleted_refs == []
    assert unit_of_work.state.rules[rule().id].state is SyncRuleState.ENABLED
    assert REPLACEMENT not in unit_of_work.state.rules
    assert len(unit_of_work.state.mappings) == 1


def test_replacement_creates_nothing_when_removal_cannot_start() -> None:
    unit_of_work = _with_mappings(1)
    remover = _remover(unit_of_work, accounts=Accounts(connected=False))

    with pytest.raises(RemovalRequiresAuthorization):
        _replacer(unit_of_work, remover).execute(
            rule().id, rule().source, NEW_DESTINATION, ProjectionHandling.DELETE
        )

    assert list(unit_of_work.state.rules) == [rule().id]


class LapsingAccounts:
    """Authorized for the replacement's own check, then lapsed when the removal begins."""

    def __init__(self) -> None:
        self.asked = 0

    def is_connected(self, account_id: ConnectedAccountId) -> bool:
        self.asked += 1
        return self.asked == 1


def test_a_check_that_fails_when_the_removal_begins_leaves_the_old_rule_and_no_draft() -> None:
    unit_of_work = _with_mappings(1)
    provider = RecordingProvider()
    remover = RemoveSyncRule(unit_of_work, provider, LapsingAccounts(), FixedClock(), RuleLocks())

    with pytest.raises(RemovalRequiresAuthorization):
        _replacer(unit_of_work, remover).execute(
            rule().id, rule().source, NEW_DESTINATION, ProjectionHandling.DELETE
        )

    assert provider.deleted_refs == []
    assert unit_of_work.state.rules == {rule().id: rule()}
    assert len(unit_of_work.state.mappings) == 1


def test_a_calendar_of_an_account_the_user_lacks_leaves_the_old_rule_and_no_draft() -> None:
    unit_of_work = _with_mappings(1)
    provider = RecordingProvider()

    with pytest.raises(ConnectedAccountRequired):
        _replacer(unit_of_work, _remover(unit_of_work, provider)).execute(
            rule().id,
            endpoint("someone-elses-account", "calendar"),
            rule().destination,
            ProjectionHandling.DELETE,
        )

    assert provider.deleted_refs == []
    assert unit_of_work.state.rules == {rule().id: rule()}
    assert len(unit_of_work.state.mappings) == 1


def test_no_draft_exists_before_the_old_rules_removal_begins() -> None:
    unit_of_work = _with_mappings(1)
    locks = RuleLocks()
    remover = RemoveSyncRule(unit_of_work, RecordingProvider(), Accounts(), FixedClock(), locks)
    running = locks.for_rule(rule().id)
    running.acquire()
    worker = Thread(
        target=_replacer(unit_of_work, remover).execute,
        args=(rule().id, rule().source, NEW_DESTINATION, ProjectionHandling.DETACH),
    )

    worker.start()
    worker.join(0.2)
    waited_for_the_run = worker.is_alive()
    rules_while_the_run_lasts = set(unit_of_work.state.rules)
    running.release()
    worker.join(5)

    assert waited_for_the_run
    assert rules_while_the_run_lasts == {rule().id}
    assert set(unit_of_work.state.rules) == {REPLACEMENT}


def test_the_draft_keeps_the_place_from_the_commit_that_begins_the_removal() -> None:
    unit_of_work = _ordered(rule())
    counting_before = _counting(unit_of_work)
    order = unit_of_work.state.rule_order[rule().id]
    seen: list[tuple[SyncRuleState, bool, int, int]] = []

    class ObservingProvider(RecordingProvider):
        def delete_projection(
            self, destination: EventRef, source: EventRef, rule_id: SyncRuleId, operation_key: str
        ) -> None:
            committed = unit_of_work.state
            seen.append(
                (
                    committed.rules[rule().id].state,
                    committed.rules[REPLACEMENT].keeps_place,
                    committed.rule_order[REPLACEMENT],
                    _counting(unit_of_work),
                )
            )
            super().delete_projection(destination, source, rule_id, operation_key)

    replacement = _replacer(unit_of_work, _remover(unit_of_work, ObservingProvider())).execute(
        rule().id, rule().source, NEW_DESTINATION, ProjectionHandling.DELETE
    )

    assert seen == [(SyncRuleState.REMOVING, True, order, counting_before)] * 2
    assert replacement.rule.keeps_place is True
    assert replacement.rule == unit_of_work.state.rules[REPLACEMENT]
    assert _counting(unit_of_work) == counting_before
    ranks = unit_of_work.state.rule_order
    assert ranks[SyncRuleId("older")] < ranks[REPLACEMENT] < ranks[SyncRuleId("newer")]


@pytest.mark.parametrize(
    ("old", "keeps_place"),
    [
        (rule(state=SyncRuleState.ENABLED), True),
        (rule().degrade(awaiting_reauthorization=True), True),
        (replace(rule(state=SyncRuleState.DRAFT), keeps_place=True), True),
        (rule(state=SyncRuleState.PAUSED), False),
        (rule(state=SyncRuleState.DEGRADED), False),
        (rule(state=SyncRuleState.DRAFT), False),
        (rule(state=SyncRuleState.PREVIEWED), False),
    ],
)
def test_the_draft_keeps_a_place_only_when_the_old_rule_counted(
    old: SyncRule, keeps_place: bool
) -> None:
    unit_of_work = _ordered(old)
    order = unit_of_work.state.rule_order[rule().id]

    replacement = _replacer(unit_of_work).execute(
        rule().id, rule().source, NEW_DESTINATION, ProjectionHandling.DETACH
    )

    assert replacement.rule.keeps_place is keeps_place
    ranks = unit_of_work.state.rule_order
    if keeps_place:
        assert ranks[REPLACEMENT] == order
    else:
        # It keeps its own new order, so it is the newest rule.
        assert ranks[REPLACEMENT] > ranks[SyncRuleId("newer")]


def test_a_successor_that_is_not_a_new_draft_is_refused_and_nothing_changes() -> None:
    unit_of_work = _with_mappings(1)
    enabled = SyncRule(REPLACEMENT, rule().source, NEW_DESTINATION, state=SyncRuleState.ENABLED)

    with pytest.raises(InvalidStateTransition):
        _remover(unit_of_work).execute(rule().id, ProjectionHandling.DETACH, successor=enabled)

    assert unit_of_work.state.rules == {rule().id: rule()}
    assert len(unit_of_work.state.mappings) == 1


def test_interrupted_replacement_keeps_the_new_draft_its_place_and_a_retryable_old_rule() -> None:
    unit_of_work = _with_mappings(2)

    with pytest.raises(ReplacementInterrupted) as interrupted:
        _replacer(unit_of_work, _remover(unit_of_work, RecordingProvider(fail_on_call=2))).execute(
            rule().id, rule().source, NEW_DESTINATION, ProjectionHandling.DELETE
        )

    assert interrupted.value.replacement_rule_id == REPLACEMENT
    assert "retry" in str(interrupted.value)
    draft = unit_of_work.state.rules[REPLACEMENT]
    assert (draft.state, draft.keeps_place) == (SyncRuleState.DRAFT, True)
    assert unit_of_work.state.rules[rule().id].state is SyncRuleState.REMOVING
    assert _counting(unit_of_work) == 1

    _remover(unit_of_work).execute(rule().id, ProjectionHandling.DETACH)

    assert unit_of_work.state.rules == {REPLACEMENT: draft}


class DisconnectedDestination(RecordingProvider):
    """The destination account lost its credentials once the removal began."""

    def delete_projection(
        self, destination: EventRef, source: EventRef, rule_id: SyncRuleId, operation_key: str
    ) -> None:
        raise ConnectedAccountDisconnected("reauthorize the account before using it")


def test_an_error_after_the_removal_began_keeps_the_draft() -> None:
    unit_of_work = _with_mappings(1)

    with pytest.raises(ConnectedAccountDisconnected):
        _replacer(unit_of_work, _remover(unit_of_work, DisconnectedDestination())).execute(
            rule().id, rule().source, NEW_DESTINATION, ProjectionHandling.DELETE
        )

    assert unit_of_work.state.rules[REPLACEMENT].keeps_place is True
    assert unit_of_work.state.rules[rule().id].state is SyncRuleState.REMOVING
    assert len(unit_of_work.state.mappings) == 1


def test_a_replacement_over_the_rule_limit_keeps_the_place_and_its_start_succeeds() -> None:
    users = MemoryUsers()
    users.add(User(USER, "member@example.test", Role.USER, UserState.ACTIVE, NOW), "x")
    plans = MemoryPlans(users=users)
    plans_on(plans, FREE)
    unit_of_work = _ordered(rule())
    assert plans.of(USER).limits.rules == 1
    assert _counting(unit_of_work) == 3

    _replacer(unit_of_work).execute(
        rule().id, rule().source, NEW_DESTINATION, ProjectionHandling.DETACH
    )
    with unit_of_work() as uow:
        draft = uow.rules.get(REPLACEMENT)
        assert draft is not None
        uow.rules.save(draft.mark_previewed())
        uow.commit()
    started = EnableSyncRule(unit_of_work, RuleLocks(), plans, USER).execute(REPLACEMENT)

    assert started.state is SyncRuleState.ENABLED
    assert started.keeps_place is False
    assert _counting(unit_of_work) == 3


def test_a_replacement_in_flight_keeps_its_place_when_plans_turn_on_during_the_removal() -> None:
    users = MemoryUsers()
    users.add(User(USER, "member@example.test", Role.USER, UserState.ACTIVE, NOW), "x")
    plans = MemoryPlans(users=users)
    unit_of_work = _ordered(rule())
    assert plans.of(USER).limits.rules is None

    class PlansTurnOn(RecordingProvider):
        """An administrator turns Plans on, with a one-rule default, while the removal runs."""

        def delete_projection(
            self, destination: EventRef, source: EventRef, rule_id: SyncRuleId, operation_key: str
        ) -> None:
            if not plans.enabled:
                plans_on(plans, FREE)
            super().delete_projection(destination, source, rule_id, operation_key)

    _replacer(unit_of_work, _remover(unit_of_work, PlansTurnOn())).execute(
        rule().id, rule().source, NEW_DESTINATION, ProjectionHandling.DELETE
    )
    with unit_of_work() as uow:
        draft = uow.rules.get(REPLACEMENT)
        assert draft is not None
        uow.rules.save(draft.mark_previewed())
        uow.commit()
    assert plans.of(USER).limits.rules == 1
    assert _counting(unit_of_work) == 3
    started = EnableSyncRule(unit_of_work, RuleLocks(), plans, USER).execute(REPLACEMENT)

    assert started.state is SyncRuleState.ENABLED
    assert _counting(unit_of_work) == 3


def _creation_orders(database: Path) -> dict[str, int]:
    """Each rule's creation order, which ranks the User's rules (ADR 0038)."""
    with transaction(database) as connection:
        rows = connection.execute("SELECT id, creation_order FROM sync_rules").fetchall()
    return {str(row["id"]): int(row["creation_order"]) for row in rows}


def _sqlite_replacer(units: UnitOfWorkFactory) -> ReplaceSyncRuleCalendars:
    return ReplaceSyncRuleCalendars(
        units, RemoveSyncRule(units, None, None, FixedClock(), RuleLocks()), Ids()
    )


def test_on_sqlite_the_draft_takes_the_place_and_rank_of_the_rule_it_replaces(
    tmp_path: Path,
) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    units = sqlite_units(database)
    with units() as uow:
        for each in (_other("older"), rule(), _other("newer")):
            uow.rules.add(each)
        uow.commit()
    order = _creation_orders(database)[rule().id.value]

    replacement = _sqlite_replacer(units).execute(
        rule().id, rule().source, NEW_DESTINATION, ProjectionHandling.DETACH
    )

    with units() as uow:
        stored = uow.rules.get(REPLACEMENT)
    assert stored == replacement.rule
    assert replacement.rule.keeps_place is True
    assert _creation_orders(database) == {
        "older": order - 1,
        REPLACEMENT.value: order,
        "newer": order + 1,
    }


def test_on_sqlite_a_refused_draft_rolls_back_the_start_of_the_removal(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    units = sqlite_units(database)
    with units() as uow:
        uow.rules.add(rule())
        uow.commit()

    with pytest.raises(ConnectedAccountRequired):
        _sqlite_replacer(units).execute(
            rule().id,
            endpoint("someone-elses-account", "calendar"),
            rule().destination,
            ProjectionHandling.DETACH,
        )

    with units() as uow:
        assert tuple(uow.rules.list()) == (rule(),)


def _synced_series() -> tuple[FakeCalendars, InMemoryUserUnitOfWorkFactory, EventRef]:
    calendars = FakeCalendars()
    master = calendars.put(series(), starts=tuple(week_start(w) for w in range(3)))
    calendars.put(occurrence(master, 1, status=EventStatus.CANCELLED))
    calendars.put(occurrence(master, 2, moved_by=timedelta(hours=1)))
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    return calendars, factory, factory.state.mappings[(rule().id, master.reference)].destination


def test_removing_a_series_deletes_only_its_destination_master() -> None:
    calendars, factory, destination = _synced_series()
    assert len(factory.state.occurrences) == 2
    before = len(calendars.writes)

    result = RemoveSyncRule(factory, calendars, Accounts(), FixedClock(), RuleLocks()).execute(
        rule().id, ProjectionHandling.DELETE
    )

    assert result.deleted == 1
    assert calendars.writes[before:] == [("delete", destination.event_id.value)]
    assert calendars.instances_of(destination) == []
    assert factory.state.occurrences == {}
    assert factory.state.mappings == {}


def test_detaching_a_series_keeps_it_ignored_by_a_reverse_rule() -> None:
    calendars, factory, destination = _synced_series()
    before = list(calendars.writes)

    RemoveSyncRule(factory, calendars, Accounts(), FixedClock(), RuleLocks()).execute(
        rule().id, ProjectionHandling.DETACH
    )
    reverse = SyncRule(
        SyncRuleId("reverse"), rule().destination, rule().source, state=SyncRuleState.ENABLED
    )
    reverse_factory = enabled_rule_factory(reverse)
    result = sync_use_case(reverse_factory, calendars).execute(reverse.id)

    assert calendars.writes == before
    assert factory.state.occurrences == {}
    assert result.created == result.updated == result.deleted == 0
    cancelled = calendars.get_occurrence(destination, week_start(1))
    assert cancelled is not None
    assert cancelled.managed_origin is None


def test_deleting_one_of_two_reverse_rules_removes_only_its_own_projections() -> None:
    calendars = FakeCalendars()
    forward_original = calendars.put(event("forward-original"))
    reverse_original = calendars.put(event("reverse-original", calendar=rule().destination))
    reverse = SyncRule(
        SyncRuleId("reverse"), rule().destination, rule().source, state=SyncRuleState.ENABLED
    )
    factory = enabled_rule_factory()
    with factory() as uow:
        uow.rules.add(reverse)
        uow.commit()
    sync_use_case(factory, calendars).execute(rule().id)
    sync_use_case(factory, calendars).execute(reverse.id)
    forward_projection = factory.state.mappings[(rule().id, forward_original.reference)]
    reverse_projection = factory.state.mappings[(reverse.id, reverse_original.reference)]
    before = len(calendars.writes)

    result = RemoveSyncRule(factory, calendars, Accounts(), FixedClock(), RuleLocks()).execute(
        rule().id, ProjectionHandling.DELETE
    )

    assert (result.deleted, result.conflicts) == (1, 0)
    assert calendars.writes[before:] == [("delete", forward_projection.destination.event_id.value)]
    assert set(calendars.events) == {
        forward_original.reference,
        reverse_original.reference,
        reverse_projection.destination,
    }
    assert calendars.events[forward_original.reference] == forward_original
    assert calendars.events[reverse_original.reference] == reverse_original
    assert set(factory.state.mappings) == {(reverse.id, reverse_original.reference)}
    # Google then reports the deletion in the reverse rule's source feed, without metadata.
    calendars.report(
        CalendarEvent(forward_projection.destination, None, "deleted", status=EventStatus.CANCELLED)
    )
    after_removal = len(calendars.writes)
    follow_up = sync_use_case(factory, calendars).execute(reverse.id)
    assert follow_up.created == follow_up.updated == follow_up.deleted == 0
    assert len(calendars.writes) == after_removal


class ScriptedProvider(RecordingProvider):
    """Raises the scripted failures for a destination, in order, before deleting it."""

    def __init__(self, failures: dict[str, list[ProviderFailure]]) -> None:
        super().__init__()
        self.failures = failures
        self.attempts: list[tuple[str, str]] = []

    def delete_projection(
        self,
        destination: EventRef,
        source: EventRef,
        rule_id: SyncRuleId,
        operation_key: str,
    ) -> None:
        self.attempts.append((destination.event_id.value, operation_key))
        pending = self.failures.get(destination.event_id.value)
        if pending:
            raise pending.pop(0)
        self.deleted_refs.append(destination)


class Incidents:
    def __init__(self) -> None:
        self.blocked: list[tuple[SyncRuleId, ProviderFailureKind]] = []

    def removal_blocked(
        self, rule_id: SyncRuleId, failure: ProviderFailure, *, attempted_at: datetime
    ) -> None:
        self.blocked.append((rule_id, failure.kind))


class Sleeps:
    def __init__(self) -> None:
        self.delays: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


def _retrying_remover(
    unit_of_work: InMemoryUserUnitOfWorkFactory,
    provider: ProjectionDeleter,
    incidents: Incidents | None = None,
    sleeps: Sleeps | None = None,
) -> RemoveSyncRule:
    return RemoveSyncRule(
        unit_of_work,
        provider,
        Accounts(),
        FixedClock(),
        RuleLocks(),
        incidents=incidents if incidents is not None else Incidents(),
        sleep=sleeps if sleeps is not None else Sleeps(),
    )


def _destination(event_id: str, origin: ManagedOrigin | None) -> CalendarEvent:
    return replace(event(event_id, calendar=rule().destination), managed_origin=origin)


def test_ownership_conflict_leaves_that_event_and_removal_completes() -> None:
    calendars = FakeCalendars()
    owned_source = EventRef(rule().source, EventId("source-0"))
    other_rule = ManagedOrigin(SyncRuleId("other-rule"), owned_source)
    calendars.put(_destination("destination-0", ManagedOrigin(rule().id, owned_source)))
    calendars.put(_destination("destination-1", other_rule))
    calendars.put(_destination("destination-2", None))
    unmapped = calendars.put(
        _destination("unmapped", ManagedOrigin(rule().id, EventRef(rule().source, EventId("x"))))
    )
    unit_of_work = _with_mappings(3)

    result = _retrying_remover(unit_of_work, calendars).execute(
        rule().id, ProjectionHandling.DELETE
    )

    assert (result.deleted, result.detached, result.conflicts) == (1, 0, 2)
    assert calendars.writes == [("delete", "destination-0")]
    remaining = {reference.event_id.value for reference in calendars.events}
    assert remaining == {"destination-1", "destination-2", unmapped.reference.event_id.value}
    assert unit_of_work.state.rules == {}
    assert unit_of_work.state.mappings == {}
    blocked = [entry for entry in unit_of_work.state.audit if entry.outcome == "blocked"]
    assert [entry.destination_event_id for entry in blocked] == ["destination-1", "destination-2"]
    assert {entry.action for entry in blocked} == {"removal_conflict"}
    completed = unit_of_work.state.audit[-1]
    assert completed.action == "rule_removed"
    assert "2 left because ownership could not be verified" in completed.detail
    assert all("Private appointment" not in entry.detail for entry in unit_of_work.state.audit)


def test_a_projection_its_provider_cannot_delete_quietly_is_left_and_removal_completes() -> None:
    calendars = FakeCalendars()
    sources = [EventRef(rule().source, EventId(f"source-{index}")) for index in range(2)]
    kept = calendars.put(_destination("destination-0", ManagedOrigin(rule().id, sources[0])))
    calendars.put(_destination("destination-1", ManagedOrigin(rule().id, sources[1])))
    # Someone invited guests to it, so deleting it would email them.
    calendars.undeletable.add(kept.reference)
    unit_of_work = _with_mappings(2)

    result = _retrying_remover(unit_of_work, calendars).execute(
        rule().id, ProjectionHandling.DELETE
    )

    assert (result.deleted, result.detached, result.conflicts) == (1, 0, 1)
    assert kept.reference in calendars.events
    assert calendars.writes == [("delete", "destination-1")]
    assert unit_of_work.state.rules == {}
    blocked = [entry for entry in unit_of_work.state.audit if entry.outcome == "blocked"]
    assert [entry.destination_event_id for entry in blocked] == ["destination-0"]
    completed = unit_of_work.state.audit[-1]
    assert "1 left because deleting them would notify someone" in completed.detail


def test_temporary_failures_retry_with_backoff_using_the_same_operation_key() -> None:
    unit_of_work = _with_mappings(2)
    provider = ScriptedProvider(
        {
            "destination-0": [
                ProviderFailure(ProviderFailureKind.TEMPORARY, "synthetic outage"),
                ProviderFailure(ProviderFailureKind.RATE_LIMIT, "slow down", 7),
            ]
        }
    )
    sleeps = Sleeps()
    incidents = Incidents()

    result = _retrying_remover(unit_of_work, provider, incidents, sleeps).execute(
        rule().id, ProjectionHandling.DELETE
    )

    assert result.deleted == 2
    first_attempts = [key for event_id, key in provider.attempts if event_id == "destination-0"]
    assert len(first_attempts) == 3
    assert len(set(first_attempts)) == 1
    assert len(sleeps.delays) == 2
    assert 1 <= sleeps.delays[0] < 1.25
    assert 7 <= sleeps.delays[1] < 7.25
    assert incidents.blocked == []
    assert unit_of_work.state.rules == {}


def test_exhausted_temporary_retries_interrupt_without_an_incident() -> None:
    unit_of_work = _with_mappings(2)
    outage = ProviderFailure(ProviderFailureKind.TEMPORARY, "synthetic outage")
    provider = ScriptedProvider({"destination-1": [outage, outage, outage]})
    sleeps = Sleeps()
    incidents = Incidents()

    with pytest.raises(RemovalInterrupted) as interrupted:
        _retrying_remover(unit_of_work, provider, incidents, sleeps).execute(
            rule().id, ProjectionHandling.DELETE
        )

    assert (interrupted.value.processed, interrupted.value.remaining) == (1, 1)
    assert len(sleeps.delays) == 2
    assert incidents.blocked == []
    assert unit_of_work.state.rules[rule().id].state is SyncRuleState.REMOVING
    assert len(unit_of_work.state.mappings) == 1


@pytest.mark.parametrize(
    "kind", [ProviderFailureKind.AUTHENTICATION, ProviderFailureKind.AUTHORIZATION]
)
def test_authorization_failure_stops_at_once_and_opens_an_incident(
    kind: ProviderFailureKind,
) -> None:
    unit_of_work = _with_mappings(2)
    provider = ScriptedProvider({"destination-0": [ProviderFailure(kind, "denied")]})
    sleeps = Sleeps()
    incidents = Incidents()

    with pytest.raises(RemovalInterrupted):
        _retrying_remover(unit_of_work, provider, incidents, sleeps).execute(
            rule().id, ProjectionHandling.DELETE
        )

    assert len(provider.attempts) == 1
    assert sleeps.delays == []
    assert incidents.blocked == [(rule().id, kind)]
    assert unit_of_work.state.rules[rule().id].state is SyncRuleState.REMOVING
    assert len(unit_of_work.state.mappings) == 2


def test_permanent_failure_other_than_ownership_still_interrupts_removal() -> None:
    unit_of_work = _with_mappings(1)
    provider = ScriptedProvider(
        {"destination-0": [ProviderFailure(ProviderFailureKind.PERMANENT, "bad request")]}
    )
    incidents = Incidents()

    with pytest.raises(RemovalInterrupted):
        _retrying_remover(unit_of_work, provider, incidents).execute(
            rule().id, ProjectionHandling.DELETE
        )

    assert incidents.blocked == []
    assert len(unit_of_work.state.mappings) == 1


def test_ownership_mismatch_is_not_retried() -> None:
    unit_of_work = _with_mappings(1)
    provider = ScriptedProvider(
        {"destination-0": [ProjectionOwnershipMismatch("incompatible ownership metadata")]}
    )
    sleeps = Sleeps()

    result = _retrying_remover(unit_of_work, provider, sleeps=sleeps).execute(
        rule().id, ProjectionHandling.DELETE
    )

    assert (result.deleted, result.conflicts) == (0, 1)
    assert len(provider.attempts) == 1
    assert sleeps.delays == []
