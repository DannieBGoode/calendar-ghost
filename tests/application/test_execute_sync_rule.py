from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from threading import Lock, Thread
from time import sleep

import pytest

from calendar_sync.application.errors import ProviderFailure, ProviderFailureKind, RuleNotExecutable
from calendar_sync.application.locking import RuleLocks
from calendar_sync.application.ports import (
    CreatedProjection,
    ProviderChangeSet,
    RunKind,
    UnitOfWorkFactory,
)
from calendar_sync.application.synchronization import ExecuteSyncRule
from calendar_sync.domain.model import (
    CalendarEndpoint,
    CalendarEvent,
    EventId,
    EventMapping,
    EventMappingId,
    EventProjection,
    EventRef,
    EventStatus,
    ManagedOrigin,
    OccurrenceStart,
    ProjectionContent,
    ProjectionFingerprint,
    SyncReason,
    SyncRuleId,
    SyncRuleState,
    TransformationPolicy,
)
from calendar_sync.domain.services import (
    EventProjector,
    ProjectionFingerprinter,
    SyncDecisionService,
)
from calendar_sync.infrastructure.persistence.memory import InMemoryUnitOfWorkFactory
from calendar_sync.infrastructure.persistence.sqlite import (
    SqliteUnitOfWorkFactory,
    initialize_database,
)
from tests.helpers import NOW, event, rule


@dataclass
class FixedClock:
    def now(self) -> datetime:
        return NOW


class FakeCalendarProvider:
    def __init__(self, source: CalendarEvent) -> None:
        self.source = source
        self.source_changes: tuple[CalendarEvent, ...] = (source,)
        self.destination_changes: tuple[CalendarEvent, ...] = ()
        self.destination: CalendarEvent | None = None
        self.operation_keys: list[str] = []
        self.requested_endpoints: list[CalendarEndpoint] = []
        self.requested_cursors: list[str | None] = []
        self.updated = 0
        self.deleted = 0
        self.failure: ProviderFailure | None = None

    def changes(
        self, source: CalendarEndpoint, cursor: str | None, not_ended_before: datetime
    ) -> ProviderChangeSet:
        self.requested_endpoints.append(source)
        self.requested_cursors.append(cursor)
        if self.failure is not None:
            raise self.failure
        if source == self.source.reference.calendar:
            return ProviderChangeSet(self.source_changes, "source-cursor-1")
        return ProviderChangeSet(self.destination_changes, "destination-cursor-1")

    def get_event(self, reference: EventRef) -> CalendarEvent | None:
        if self.source.reference == reference:
            return self.source
        return (
            self.destination
            if self.destination and self.destination.reference == reference
            else None
        )

    def find_projection(
        self, destination: CalendarEndpoint, operation_key: str
    ) -> CalendarEvent | None:
        return None

    def create_projection(
        self,
        destination: CalendarEndpoint,
        source: EventRef,
        rule_id: SyncRuleId,
        projection: EventProjection,
        operation_key: str,
    ) -> CreatedProjection:
        self.operation_keys.append(operation_key)
        self.destination = CalendarEvent(
            EventRef(destination, EventId("managed-destination")),
            projection.time,
            "destination-revision",
            title=projection.title,
            description=projection.description,
            location=projection.location,
            recurrence=projection.recurrence,
            managed_origin=ManagedOrigin(rule_id, source),
        )
        return CreatedProjection(self.destination)

    def update_projection(
        self,
        destination: EventRef,
        source: EventRef,
        rule_id: SyncRuleId,
        projection: EventProjection,
        operation_key: str,
    ) -> CalendarEvent:
        self.operation_keys.append(operation_key)
        self.updated += 1
        self.destination = CalendarEvent(
            destination,
            projection.time,
            "destination-updated",
            title=projection.title,
            description=projection.description,
            location=projection.location,
            recurrence=projection.recurrence,
            managed_origin=ManagedOrigin(rule_id, source),
        )
        return self.destination

    def delete_projection(
        self,
        destination: EventRef,
        source: EventRef,
        rule_id: SyncRuleId,
        operation_key: str,
    ) -> None:
        self.operation_keys.append(operation_key)
        self.deleted += 1
        self.destination = None

    def get_occurrence(
        self, series: EventRef, original_start: OccurrenceStart
    ) -> CalendarEvent | None:
        return None

    def occurrence_exceptions(
        self, series: EventRef, not_ended_before: datetime
    ) -> tuple[CalendarEvent, ...]:
        return ()

    def has_live_occurrences(self, series: EventRef, *, include_all_day: bool) -> bool:
        return True

    def write_occurrence(
        self,
        destination_series: EventRef,
        original_start: OccurrenceStart,
        source_series: EventRef,
        rule_id: SyncRuleId,
        projection: EventProjection,
        operation_key: str,
    ) -> CalendarEvent:
        raise AssertionError("single-event tests never write occurrences")

    def cancel_occurrence(
        self,
        destination_series: EventRef,
        original_start: OccurrenceStart,
        source_series: EventRef,
        rule_id: SyncRuleId,
        operation_key: str,
    ) -> None:
        raise AssertionError("single-event tests never cancel occurrences")

    def managed_events(
        self, destination: CalendarEndpoint, rule_id: SyncRuleId
    ) -> tuple[CalendarEvent, ...]:
        return (self.destination,) if self.destination else ()


class ConcurrencyRecordingProvider(FakeCalendarProvider):
    def __init__(self, source: CalendarEvent) -> None:
        super().__init__(source)
        self.active_source_reads = 0
        self.max_active_source_reads = 0
        self._guard = Lock()

    def changes(
        self, source: CalendarEndpoint, cursor: str | None, not_ended_before: datetime
    ) -> ProviderChangeSet:
        if source == self.source.reference.calendar:
            with self._guard:
                self.active_source_reads += 1
                self.max_active_source_reads = max(
                    self.max_active_source_reads, self.active_source_reads
                )
            sleep(0.03)
            with self._guard:
                self.active_source_reads -= 1
        return super().changes(source, cursor, not_ended_before)


def test_complete_create_use_case_persists_mapping_cursor_and_audit() -> None:
    unit_of_work = InMemoryUnitOfWorkFactory()
    unit_of_work.state.rules[rule().id] = rule()
    provider = FakeCalendarProvider(event())
    fingerprinter = ProjectionFingerprinter()
    use_case = ExecuteSyncRule(
        unit_of_work,
        provider,
        SyncDecisionService(EventProjector(), fingerprinter),
        fingerprinter,
        FixedClock(),
    )

    result = use_case.execute(rule().id)

    assert result.created == 1
    assert unit_of_work.state.cursors[rule().id] == "source-cursor-1"
    assert unit_of_work.state.destination_cursors[rule().id] == "destination-cursor-1"
    assert len(unit_of_work.state.mappings) == 1
    assert unit_of_work.state.audit[0].action == "create"
    assert unit_of_work.state.audit[0].reason == SyncReason.SOURCE_CREATED
    assert unit_of_work.state.audit[0].run_id
    assert unit_of_work.state.audit[0].source_event_id == "source-event"
    assert provider.operation_keys[0]


def test_full_reconciliation_does_not_use_incremental_cursor() -> None:
    unit_of_work = InMemoryUnitOfWorkFactory()
    unit_of_work.state.rules[rule().id] = rule()
    unit_of_work.state.cursors[rule().id] = "previous-cursor"
    unit_of_work.state.destination_cursors[rule().id] = "previous-destination-cursor"
    provider = FakeCalendarProvider(event())
    fingerprinter = ProjectionFingerprinter()
    use_case = ExecuteSyncRule(
        unit_of_work,
        provider,
        SyncDecisionService(EventProjector(), fingerprinter),
        fingerprinter,
        FixedClock(),
    )

    use_case.execute(rule().id, full=True)

    assert provider.requested_cursors == [None, None]
    assert unit_of_work.state.cursors[rule().id] == "source-cursor-1"
    assert unit_of_work.state.destination_cursors[rule().id] == "destination-cursor-1"


def test_destination_drift_is_updated_and_mapping_revision_advances() -> None:
    unit_of_work = InMemoryUnitOfWorkFactory()
    unit_of_work.state.rules[rule().id] = rule()
    source = event(revision="revision-2")
    destination = event(
        "managed-destination",
        calendar=rule().destination,
        title="Edited on destination",
    )
    destination = replace(destination, managed_origin=ManagedOrigin(rule().id, source.reference))
    provider = FakeCalendarProvider(source)
    provider.destination = destination
    mapping = EventMapping(
        EventMappingId("mapping-1"),
        rule().id,
        source.reference,
        destination.reference,
        "revision-1",
        ProjectionFingerprint("previous-fingerprint"),
    )
    unit_of_work.state.mappings[(rule().id, source.reference)] = mapping
    fingerprinter = ProjectionFingerprinter()
    use_case = ExecuteSyncRule(
        unit_of_work,
        provider,
        SyncDecisionService(EventProjector(), fingerprinter),
        fingerprinter,
        FixedClock(),
    )

    result = use_case.execute(rule().id)

    saved = unit_of_work.state.mappings[(rule().id, source.reference)]
    assert result.updated == 1
    assert provider.updated == 1
    assert provider.destination is not None
    assert provider.destination.title == "Busy"
    assert saved.source_revision == "revision-2"


def test_destination_only_edit_is_repaired_on_the_next_incremental_sync() -> None:
    unit_of_work = InMemoryUnitOfWorkFactory()
    unit_of_work.state.rules[rule().id] = rule()
    unit_of_work.state.cursors[rule().id] = "source-before"
    unit_of_work.state.destination_cursors[rule().id] = "destination-before"
    source = event(revision="revision-2")
    destination = event(
        "managed-destination",
        calendar=rule().destination,
        title="Edited only on destination",
    )
    destination = replace(destination, managed_origin=ManagedOrigin(rule().id, source.reference))
    provider = FakeCalendarProvider(source)
    provider.source_changes = ()
    provider.destination_changes = (destination,)
    provider.destination = destination
    mapping = EventMapping(
        EventMappingId("mapping-1"),
        rule().id,
        source.reference,
        destination.reference,
        "revision-2",
        ProjectionFingerprint("previous-fingerprint"),
    )
    unit_of_work.state.mappings[(rule().id, source.reference)] = mapping
    fingerprinter = ProjectionFingerprinter()
    use_case = ExecuteSyncRule(
        unit_of_work,
        provider,
        SyncDecisionService(EventProjector(), fingerprinter),
        fingerprinter,
        FixedClock(),
    )

    result = use_case.execute(rule().id)

    assert result.updated == 1
    assert provider.destination is not None
    assert provider.destination.title == "Busy"
    assert provider.requested_cursors == ["source-before", "destination-before"]
    assert unit_of_work.state.destination_cursors[rule().id] == "destination-cursor-1"


def test_destination_only_deletion_restores_projection_with_same_mapping_identity() -> None:
    unit_of_work = InMemoryUnitOfWorkFactory()
    unit_of_work.state.rules[rule().id] = rule()
    source = event(revision="revision-2")
    destination = replace(
        event("managed-destination", calendar=rule().destination),
        status=EventStatus.CANCELLED,
        time=None,
        revision="destination-deleted",
        managed_origin=ManagedOrigin(rule().id, source.reference),
    )
    provider = FakeCalendarProvider(source)
    provider.source_changes = ()
    provider.destination_changes = (destination,)
    mapping = EventMapping(
        EventMappingId("original-mapping"),
        rule().id,
        source.reference,
        destination.reference,
        "revision-2",
        ProjectionFingerprint("previous-fingerprint"),
    )
    unit_of_work.state.mappings[(rule().id, source.reference)] = mapping
    fingerprinter = ProjectionFingerprinter()
    use_case = ExecuteSyncRule(
        unit_of_work,
        provider,
        SyncDecisionService(EventProjector(), fingerprinter),
        fingerprinter,
        FixedClock(),
    )

    result = use_case.execute(rule().id)

    restored = unit_of_work.state.mappings[(rule().id, source.reference)]
    assert result.created == 1
    assert restored.id == EventMappingId("original-mapping")
    assert provider.destination is not None
    assert provider.destination.title == "Busy"


def test_destination_change_does_not_delete_when_source_cannot_be_verified() -> None:
    unit_of_work = InMemoryUnitOfWorkFactory()
    unit_of_work.state.rules[rule().id] = rule()
    source = event(revision="revision-2")
    destination = replace(
        event("managed-destination", calendar=rule().destination),
        managed_origin=ManagedOrigin(rule().id, source.reference),
    )
    provider = FakeCalendarProvider(source)
    provider.source = event("different-source")
    provider.source_changes = ()
    provider.destination_changes = (destination,)
    provider.destination = destination
    mapping = EventMapping(
        EventMappingId("mapping-1"),
        rule().id,
        source.reference,
        destination.reference,
        "revision-2",
        ProjectionFingerprint("previous-fingerprint"),
    )
    unit_of_work.state.mappings[(rule().id, source.reference)] = mapping
    fingerprinter = ProjectionFingerprinter()
    use_case = ExecuteSyncRule(
        unit_of_work,
        provider,
        SyncDecisionService(EventProjector(), fingerprinter),
        fingerprinter,
        FixedClock(),
    )

    result = use_case.execute(rule().id)

    assert result.conflicts == 1
    assert provider.deleted == 0
    assert provider.destination == destination
    assert unit_of_work.state.audit[-1].outcome == "blocked"
    assert unit_of_work.state.audit[-1].reason == SyncReason.SOURCE_UNVERIFIABLE


def test_cancelled_source_deletes_only_its_owned_mapping() -> None:
    unit_of_work = InMemoryUnitOfWorkFactory()
    unit_of_work.state.rules[rule().id] = rule()
    source = replace(event(), status=EventStatus.CANCELLED, time=None, revision="cancelled-2")
    destination = replace(
        event("managed-destination", calendar=rule().destination),
        managed_origin=ManagedOrigin(rule().id, source.reference),
    )
    provider = FakeCalendarProvider(source)
    provider.destination = destination
    mapping = EventMapping(
        EventMappingId("mapping-1"),
        rule().id,
        source.reference,
        destination.reference,
        "revision-1",
        ProjectionFingerprint("previous-fingerprint"),
    )
    unit_of_work.state.mappings[(rule().id, source.reference)] = mapping
    fingerprinter = ProjectionFingerprinter()
    use_case = ExecuteSyncRule(
        unit_of_work,
        provider,
        SyncDecisionService(EventProjector(), fingerprinter),
        fingerprinter,
        FixedClock(),
    )

    result = use_case.execute(rule().id)

    assert result.deleted == 1
    assert provider.deleted == 1
    assert unit_of_work.state.mappings == {}


def test_managed_source_is_ignored_without_destination_write() -> None:
    unit_of_work = InMemoryUnitOfWorkFactory()
    unit_of_work.state.rules[rule().id] = rule()
    source = replace(
        event(),
        managed_origin=ManagedOrigin(rule().id, event("original-source").reference),
    )
    provider = FakeCalendarProvider(source)
    fingerprinter = ProjectionFingerprinter()
    use_case = ExecuteSyncRule(
        unit_of_work,
        provider,
        SyncDecisionService(EventProjector(), fingerprinter),
        fingerprinter,
        FixedClock(),
    )

    result = use_case.execute(rule().id)

    assert result.ignored == 1
    assert provider.operation_keys == []
    # Loop prevention is counted on the run but explains nothing worth an Audit Entry.
    assert unit_of_work.state.audit == []


def test_each_run_groups_its_audit_entries() -> None:
    unit_of_work = InMemoryUnitOfWorkFactory()
    unit_of_work.state.rules[rule().id] = rule()
    managed = replace(event("managed"), managed_origin=ManagedOrigin(rule().id, event().reference))
    provider = FakeCalendarProvider(event())
    provider.source_changes = (event(), managed)
    fingerprinter = ProjectionFingerprinter()
    run_ids = iter(("run-1", "run-2"))
    use_case = ExecuteSyncRule(
        unit_of_work,
        provider,
        SyncDecisionService(EventProjector(), fingerprinter),
        fingerprinter,
        FixedClock(),
        new_run_id=lambda: next(run_ids),
    )

    first = use_case.execute(rule().id)
    changed = event(revision="revision-2")
    provider.source = changed
    provider.source_changes = (changed, managed)
    use_case.execute(rule().id)

    assert first.created == 1
    assert first.ignored == 1
    assert first.conflicts == 0
    assert [
        (entry.run_id, entry.action, entry.outcome, entry.reason)
        for entry in (unit_of_work.state.audit)
    ] == [
        ("run-1", "create", "completed", SyncReason.SOURCE_CREATED),
        ("run-2", "update", "completed", SyncReason.SOURCE_CHANGED),
    ]
    # Entries name the event by title and time (ADR 0014) but keep no other content.
    assert [entry.event and entry.event.title for entry in unit_of_work.state.audit] == [
        "Private appointment",
        "Private appointment",
    ]
    assert all("Sensitive" not in repr(entry) for entry in unit_of_work.state.audit)


@pytest.mark.parametrize(
    "state", [SyncRuleState.DRAFT, SyncRuleState.PAUSED, SyncRuleState.DEGRADED]
)
def test_non_enabled_rule_is_rejected(state: SyncRuleState) -> None:
    unit_of_work = InMemoryUnitOfWorkFactory()
    unit_of_work.state.rules[rule().id] = rule(state=state)
    provider = FakeCalendarProvider(event())
    fingerprinter = ProjectionFingerprinter()
    use_case = ExecuteSyncRule(
        unit_of_work,
        provider,
        SyncDecisionService(EventProjector(), fingerprinter),
        fingerprinter,
        FixedClock(),
    )

    with pytest.raises(RuleNotExecutable, match="not enabled"):
        use_case.execute(rule().id)


def test_provider_failure_does_not_advance_cursor_or_write_audit() -> None:
    unit_of_work = InMemoryUnitOfWorkFactory()
    unit_of_work.state.rules[rule().id] = rule()
    unit_of_work.state.cursors[rule().id] = "cursor-before-failure"
    provider = FakeCalendarProvider(event())
    provider.failure = ProviderFailure(ProviderFailureKind.TEMPORARY, "outage")
    fingerprinter = ProjectionFingerprinter()
    use_case = ExecuteSyncRule(
        unit_of_work,
        provider,
        SyncDecisionService(EventProjector(), fingerprinter),
        fingerprinter,
        FixedClock(),
    )

    with pytest.raises(ProviderFailure, match="outage"):
        use_case.execute(rule().id)

    assert unit_of_work.state.cursors[rule().id] == "cursor-before-failure"
    assert unit_of_work.state.audit == []


def test_concurrent_requests_for_the_same_rule_are_serialized() -> None:
    unit_of_work = InMemoryUnitOfWorkFactory()
    unit_of_work.state.rules[rule().id] = rule()
    provider = ConcurrencyRecordingProvider(event())
    fingerprinter = ProjectionFingerprinter()
    use_case = ExecuteSyncRule(
        unit_of_work,
        provider,
        SyncDecisionService(EventProjector(), fingerprinter),
        fingerprinter,
        FixedClock(),
    )
    failures: list[BaseException] = []

    def synchronize() -> None:
        try:
            use_case.execute(rule().id)
        except BaseException as error:
            failures.append(error)

    workers = [Thread(target=synchronize), Thread(target=synchronize)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()

    assert failures == []
    assert provider.max_active_source_reads == 1
    assert len(unit_of_work.state.mappings) == 1


DETAILS = TransformationPolicy(content=ProjectionContent.DETAILS)


def _use_case(unit_of_work: UnitOfWorkFactory, provider: FakeCalendarProvider) -> ExecuteSyncRule:
    fingerprinter = ProjectionFingerprinter()
    return ExecuteSyncRule(
        unit_of_work,
        provider,
        SyncDecisionService(EventProjector(), fingerprinter),
        fingerprinter,
        FixedClock(),
    )


def _mapped_busy_projection(provider: FakeCalendarProvider, source: CalendarEvent) -> EventMapping:
    provider.destination = replace(
        event("managed-destination", calendar=rule().destination, title="Busy"),
        description="",
        location="",
        managed_origin=ManagedOrigin(rule().id, source.reference),
    )
    return EventMapping(
        EventMappingId("mapping-1"),
        rule().id,
        source.reference,
        provider.destination.reference,
        source.revision,
        ProjectionFingerprint("busy-fingerprint"),
    )


def test_policy_change_reprojects_mappings_outside_the_window_and_clears_the_flag() -> None:
    unit_of_work = InMemoryUnitOfWorkFactory()
    changed = replace(rule().change_policy(DETAILS), state=SyncRuleState.ENABLED)
    unit_of_work.state.rules[rule().id] = changed
    unit_of_work.state.cursors[rule().id] = "source-before"
    unit_of_work.state.destination_cursors[rule().id] = "destination-before"
    source = event()
    provider = FakeCalendarProvider(source)
    provider.source_changes = ()  # the source ended before the Initial Sync Window
    mapping = _mapped_busy_projection(provider, source)
    unit_of_work.state.mappings[(rule().id, source.reference)] = mapping

    result = _use_case(unit_of_work, provider).execute(rule().id)

    assert provider.requested_cursors == [None, None]
    assert result.updated == 1
    assert provider.destination is not None
    assert provider.destination.title == "Private appointment"
    assert unit_of_work.state.rules[rule().id].reprojection_required is False
    outcome = unit_of_work.state.outcomes[(rule().id, RunKind.SYNC)]
    assert outcome.succeeded
    assert outcome.full_run
    assert outcome.updated == 1


def test_unverifiable_source_during_reprojection_is_a_conflict_not_a_deletion() -> None:
    unit_of_work = InMemoryUnitOfWorkFactory()
    unit_of_work.state.rules[rule().id] = replace(
        rule().change_policy(DETAILS), state=SyncRuleState.ENABLED
    )
    mapped_source = event("vanished-source")
    provider = FakeCalendarProvider(event("unrelated"))
    provider.source_changes = ()
    unit_of_work.state.mappings[(rule().id, mapped_source.reference)] = _mapped_busy_projection(
        provider, mapped_source
    )

    result = _use_case(unit_of_work, provider).execute(rule().id)

    assert result.conflicts == 1
    assert provider.deleted == 0
    assert (rule().id, mapped_source.reference) in unit_of_work.state.mappings
    assert unit_of_work.state.audit[-1].outcome == "blocked"


def test_edit_during_a_run_keeps_reprojection_pending(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    factory = SqliteUnitOfWorkFactory(database)
    with factory() as uow:
        uow.rules.add(replace(rule().change_policy(DETAILS), state=SyncRuleState.ENABLED))
        uow.commit()

    class EditingProvider(FakeCalendarProvider):
        edited = False

        def changes(
            self, source: CalendarEndpoint, cursor: str | None, not_ended_before: datetime
        ) -> ProviderChangeSet:
            if not self.edited:
                self.edited = True
                with factory() as concurrent:
                    current = concurrent.rules.get(rule().id)
                    assert current is not None
                    concurrent.rules.save(current.change_policy(TransformationPolicy()))
                    concurrent.commit()
            return super().changes(source, cursor, not_ended_before)

    provider = EditingProvider(event())
    provider.source_changes = ()

    _use_case(factory, provider).execute(rule().id)

    with factory() as uow:
        current = uow.rules.get(rule().id)
    assert current is not None
    assert current.reprojection_required is True
    assert current.state is SyncRuleState.PAUSED


def test_changed_rule_does_not_synchronize_until_enabled_again() -> None:
    unit_of_work = InMemoryUnitOfWorkFactory()
    unit_of_work.state.rules[rule().id] = rule().change_policy(DETAILS)

    with pytest.raises(RuleNotExecutable):
        _use_case(unit_of_work, FakeCalendarProvider(event())).execute(rule().id)
    assert unit_of_work.state.outcomes == {}


def test_failed_run_records_failure_kind_without_detail() -> None:
    unit_of_work = InMemoryUnitOfWorkFactory()
    unit_of_work.state.rules[rule().id] = rule()
    provider = FakeCalendarProvider(event())
    provider.failure = ProviderFailure(ProviderFailureKind.RATE_LIMIT, "quota for person@x")

    with pytest.raises(ProviderFailure):
        _use_case(unit_of_work, provider).execute(rule().id)

    outcome = unit_of_work.state.outcomes[(rule().id, RunKind.SYNC)]
    assert outcome.succeeded is False
    assert outcome.failure_kind == "rate_limit"


def test_run_stops_before_writing_when_the_rule_changes_mid_run(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    factory = SqliteUnitOfWorkFactory(database)
    with factory() as uow:
        uow.rules.add(rule(state=SyncRuleState.ENABLED))
        uow.commit()

    class EditingProvider(FakeCalendarProvider):
        edited = False

        def changes(
            self, source: CalendarEndpoint, cursor: str | None, not_ended_before: datetime
        ) -> ProviderChangeSet:
            if not self.edited:
                self.edited = True
                with factory() as concurrent:
                    current = concurrent.rules.get(rule().id)
                    assert current is not None
                    concurrent.rules.save(current.change_policy(DETAILS))
                    concurrent.commit()
            return super().changes(source, cursor, not_ended_before)

    provider = EditingProvider(event())

    with pytest.raises(RuleNotExecutable):
        _use_case(factory, provider).execute(rule().id)

    assert provider.destination is None
    assert provider.operation_keys == []
    with factory() as uow:
        assert uow.cursors.get(rule().id) is None
        assert uow.mappings.count_for_rule(rule().id) == 0


def test_provider_writes_hold_the_rule_write_lock() -> None:
    unit_of_work = InMemoryUnitOfWorkFactory()
    unit_of_work.state.rules[rule().id] = rule()
    locks = RuleLocks()
    observed: list[bool] = []

    class ObservingProvider(FakeCalendarProvider):
        def create_projection(
            self,
            destination: CalendarEndpoint,
            source: EventRef,
            rule_id: SyncRuleId,
            projection: EventProjection,
            operation_key: str,
        ) -> CreatedProjection:
            observed.append(locks.for_writes(rule_id).locked())
            return super().create_projection(
                destination, source, rule_id, projection, operation_key
            )

    fingerprinter = ProjectionFingerprinter()
    ExecuteSyncRule(
        unit_of_work,
        ObservingProvider(event()),
        SyncDecisionService(EventProjector(), fingerprinter),
        fingerprinter,
        FixedClock(),
        locks,
    ).execute(rule().id)

    assert observed == [True]
    assert not locks.for_writes(rule().id).locked()
