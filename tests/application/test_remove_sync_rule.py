from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from calendar_sync.application.errors import (
    DuplicateDirectionalRelationship,
    NotACalendarChange,
    ProjectionOwnershipMismatch,
    ProviderFailure,
    ProviderFailureKind,
    RemovalInterrupted,
    RemovalRequiresAuthorization,
    RemovalRequiresProvider,
    ReplacementInterrupted,
)
from calendar_sync.application.locking import RuleLocks
from calendar_sync.application.ports import (
    AccountAuthorizations,
    ConnectedAccountState,
    ProjectionDeleter,
)
from calendar_sync.application.providers import ProviderKind
from calendar_sync.application.removal import RemoveSyncRule
from calendar_sync.application.rules import CreateSyncRule, ReplaceSyncRuleCalendars
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
from calendar_sync.infrastructure.persistence.memory import (
    InMemoryUnitOfWorkFactory,
    InMemoryUserUnitOfWorkFactory,
)
from tests.application.test_execute_sync_rule import FakeCalendarProvider, FixedClock
from tests.fake_calendar import FakeCalendars, enabled_rule_factory, sync_use_case
from tests.helpers import endpoint, event, occurrence, rule, series, week_start
from tests.users import USER


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
    unit_of_work = InMemoryUnitOfWorkFactory().for_user(USER)
    unit_of_work.state.rules[rule().id] = rule(state=state)
    # Rule Replacement creates its draft under the same Connected Accounts.
    for endpoint_ in (rule().source, rule().destination):
        unit_of_work.state.accounts[endpoint_.connected_account_id] = (
            ConnectedAccountState.CONNECTED
        )
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
    return unit_of_work


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


def test_replacement_rejects_a_duplicate_relationship_before_removing_anything() -> None:
    unit_of_work = _with_mappings(1)
    new_destination = endpoint("work-account", "other-calendar")
    unit_of_work.state.rules[SyncRuleId("existing")] = SyncRule(
        SyncRuleId("existing"), rule().source, new_destination
    )
    provider = RecordingProvider()
    replace_rule = ReplaceSyncRuleCalendars(
        unit_of_work, _remover(unit_of_work, provider), CreateSyncRule(unit_of_work), Ids()
    )

    with pytest.raises(DuplicateDirectionalRelationship):
        replace_rule.execute(rule().id, rule().source, new_destination, ProjectionHandling.DELETE)

    assert provider.deleted_refs == []
    assert unit_of_work.state.rules[rule().id].state is SyncRuleState.ENABLED


def test_replacement_rejects_unchanged_calendars() -> None:
    unit_of_work = _with_mappings(0)
    replace_rule = ReplaceSyncRuleCalendars(
        unit_of_work, _remover(unit_of_work), CreateSyncRule(unit_of_work), Ids()
    )

    with pytest.raises(NotACalendarChange):
        replace_rule.execute(
            rule().id, rule().source, rule().destination, ProjectionHandling.DELETE
        )
    assert rule().id in unit_of_work.state.rules


def test_replacement_removes_the_rule_and_creates_a_draft_with_the_same_policy() -> None:
    unit_of_work = _with_mappings(1)
    details = TransformationPolicy(content=ProjectionContent.DETAILS)
    unit_of_work.state.rules[rule().id] = replace(rule(), transformation=details)
    new_destination = endpoint("work-account", "other-calendar")
    replace_rule = ReplaceSyncRuleCalendars(
        unit_of_work, _remover(unit_of_work), CreateSyncRule(unit_of_work), Ids()
    )

    replacement = replace_rule.execute(
        rule().id, rule().source, new_destination, ProjectionHandling.DETACH
    )

    assert replacement.removal.detached == 1
    assert list(unit_of_work.state.rules) == [SyncRuleId("replacement-rule")]
    assert replacement.rule.state is SyncRuleState.DRAFT
    assert replacement.rule.transformation == details
    assert replacement.rule.destination == new_destination


class CompetingCreate(CreateSyncRule):
    """Simulates another request creating the same relationship just before this one."""

    def execute(self, rule: SyncRule) -> SyncRule:
        self.unit_of_work.state.rules[SyncRuleId("competitor")] = SyncRule(  # type: ignore[attr-defined]
            SyncRuleId("competitor"), rule.source, rule.destination
        )
        return CreateSyncRule.execute(self, rule)


def test_replacement_reserves_the_new_rule_before_removing_the_old_one() -> None:
    unit_of_work = _with_mappings(1)
    provider = RecordingProvider()
    replace_rule = ReplaceSyncRuleCalendars(
        unit_of_work,
        _remover(unit_of_work, provider),
        CompetingCreate(unit_of_work),
        Ids(),
    )

    with pytest.raises(DuplicateDirectionalRelationship):
        replace_rule.execute(
            rule().id,
            rule().source,
            endpoint("work-account", "other-calendar"),
            ProjectionHandling.DELETE,
        )

    assert provider.deleted_refs == []
    assert unit_of_work.state.rules[rule().id].state is SyncRuleState.ENABLED
    assert len(unit_of_work.state.mappings) == 1


def test_replacement_creates_nothing_when_removal_cannot_start() -> None:
    unit_of_work = _with_mappings(1)
    replace_rule = ReplaceSyncRuleCalendars(
        unit_of_work,
        _remover(unit_of_work, accounts=Accounts(connected=False)),
        CreateSyncRule(unit_of_work),
        Ids(),
    )

    with pytest.raises(RemovalRequiresAuthorization):
        replace_rule.execute(
            rule().id,
            rule().source,
            endpoint("work-account", "other-calendar"),
            ProjectionHandling.DELETE,
        )

    assert list(unit_of_work.state.rules) == [rule().id]


def test_interrupted_replacement_keeps_the_new_draft_and_a_retryable_old_rule() -> None:
    unit_of_work = _with_mappings(2)
    replace_rule = ReplaceSyncRuleCalendars(
        unit_of_work,
        _remover(unit_of_work, RecordingProvider(fail_on_call=2)),
        CreateSyncRule(unit_of_work),
        Ids(),
    )

    with pytest.raises(ReplacementInterrupted) as interrupted:
        replace_rule.execute(
            rule().id,
            rule().source,
            endpoint("work-account", "other-calendar"),
            ProjectionHandling.DELETE,
        )

    assert interrupted.value.replacement_rule_id == SyncRuleId("replacement-rule")
    assert "retry" in str(interrupted.value)
    assert unit_of_work.state.rules[SyncRuleId("replacement-rule")].state is SyncRuleState.DRAFT
    assert unit_of_work.state.rules[rule().id].state is SyncRuleState.REMOVING


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
