from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from threading import Lock, Thread
from time import sleep

import pytest

from calendar_sync.application.errors import ProviderFailure, ProviderFailureKind, RuleNotExecutable
from calendar_sync.application.ports import CreatedProjection, ProviderChangeSet
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
    ProjectionFingerprint,
    Recurrence,
    SyncAction,
    SyncReason,
    SyncRuleId,
    SyncRuleState,
)
from calendar_sync.domain.services import (
    EventProjector,
    ProjectionFingerprinter,
    SyncDecisionService,
)
from calendar_sync.infrastructure.persistence.memory import InMemoryUnitOfWorkFactory
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
    assert unit_of_work.state.audit[0].action == SyncAction.IGNORE.value


def test_each_run_groups_its_audit_entries_and_skips_recurring_events() -> None:
    unit_of_work = InMemoryUnitOfWorkFactory()
    unit_of_work.state.rules[rule().id] = rule()
    recurring = replace(event("weekly"), recurrence=Recurrence(("RRULE:FREQ=WEEKLY",)))
    provider = FakeCalendarProvider(event())
    provider.source_changes = (event(), recurring)
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
    provider.source_changes = (recurring,)
    use_case.execute(rule().id)

    assert first.created == 1
    assert first.ignored == 1
    assert first.conflicts == 0
    assert [
        (entry.run_id, entry.action, entry.outcome, entry.reason)
        for entry in (unit_of_work.state.audit)
    ] == [
        ("run-1", "create", "completed", SyncReason.SOURCE_CREATED),
        ("run-1", "ignore", "skipped", SyncReason.RECURRING_UNSUPPORTED),
        ("run-2", "ignore", "skipped", SyncReason.RECURRING_UNSUPPORTED),
    ]
    assert all("Private appointment" not in repr(entry) for entry in unit_of_work.state.audit)


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
