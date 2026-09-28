"""A provider fake that models series masters, their expansions, exceptions, and change feeds."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime

from calendar_sync.application.errors import (
    ProjectionOwnershipMismatch,
    ProviderFailure,
    ProviderFailureKind,
)
from calendar_sync.application.ports import CreatedProjection, ProviderChangeSet, UnitOfWorkFactory
from calendar_sync.application.synchronization import ExecuteSyncRule
from calendar_sync.domain.model import (
    AllDayRange,
    CalendarEndpoint,
    CalendarEvent,
    EventId,
    EventProjection,
    EventRef,
    EventStatus,
    ManagedOrigin,
    OccurrenceIdentity,
    OccurrenceStart,
    SyncRule,
    SyncRuleId,
    TimedInterval,
)
from calendar_sync.domain.services import (
    EventProjector,
    ProjectionFingerprinter,
    SyncDecisionService,
)
from calendar_sync.infrastructure.persistence.memory import InMemoryUnitOfWorkFactory
from tests.helpers import NOW, instance_id, rule


@dataclass
class FixedClock:
    def now(self) -> datetime:
        return NOW


def _owned(origin: ManagedOrigin | None, rule_id: SyncRuleId, source: EventRef) -> bool:
    return origin is not None and origin.rule_id == rule_id and origin.source == source


def _denied() -> ProviderFailure:
    return ProjectionOwnershipMismatch("incompatible ownership metadata")


@dataclass
class FakeCalendars:
    events: dict[EventRef, CalendarEvent] = field(default_factory=dict)
    expansions: dict[EventRef, tuple[OccurrenceStart, ...]] = field(default_factory=dict)
    feeds: dict[CalendarEndpoint, list[CalendarEvent]] = field(default_factory=dict)
    writes: list[tuple[str, str]] = field(default_factory=list)
    unreadable: set[EventRef] = field(default_factory=set)
    reads: list[EventRef] = field(default_factory=list)
    """Every single-event and single-occurrence lookup, in order."""
    operations: dict[str, EventRef] = field(default_factory=dict)
    created: int = 0

    def put(
        self, event: CalendarEvent, *, starts: tuple[OccurrenceStart, ...] = ()
    ) -> CalendarEvent:
        self.events[event.reference] = event
        if event.recurrence is not None:
            self.expansions[event.reference] = starts
        return event

    def report(self, *events: CalendarEvent) -> None:
        for event in events:
            self.feeds.setdefault(event.reference.calendar, []).append(event)

    def instances_of(self, series: EventRef) -> list[CalendarEvent]:
        return [
            event
            for event in self.events.values()
            if event.occurrence is not None
            and event.reference.calendar == series.calendar
            and event.occurrence.series_event_id == series.event_id
        ]

    def changes(
        self, source: CalendarEndpoint, cursor: str | None, not_ended_before: datetime
    ) -> ProviderChangeSet:
        if cursor is None:
            self.feeds.pop(source, None)
            items = tuple(
                event
                for event in self.events.values()
                if event.reference.calendar == source and self._in_window(event, not_ended_before)
            )
        else:
            items = tuple(self.feeds.pop(source, []))
        return ProviderChangeSet(items, f"cursor-{source.calendar_id.value}")

    @staticmethod
    def _in_window(event: CalendarEvent, not_ended_before: datetime) -> bool:
        # Series masters span their expansion; exceptions and singles are filtered by end.
        if event.recurrence is not None or event.time is None:
            return True
        if isinstance(event.time, AllDayRange):
            return event.time.ends_before >= not_ended_before.date()
        return event.time.ends_at >= not_ended_before

    def get_event(self, reference: EventRef) -> CalendarEvent | None:
        self.reads.append(reference)
        if reference in self.unreadable:
            return None
        return self.events.get(reference)

    def get_occurrence(
        self, series: EventRef, original_start: OccurrenceStart
    ) -> CalendarEvent | None:
        self.reads.append(series)
        master = self.events.get(series)
        if master is None:
            raise ProviderFailure(ProviderFailureKind.TEMPORARY, "series could not be read")
        if master.status is EventStatus.CANCELLED:
            return None
        if original_start not in self.expansions.get(series, ()):
            return None
        reference = EventRef(
            series.calendar, EventId(instance_id(series.event_id.value, original_start))
        )
        stored = self.events.get(reference)
        return stored if stored is not None else self._expand(master, original_start, reference)

    @staticmethod
    def _expand(
        master: CalendarEvent, start: OccurrenceStart, reference: EventRef
    ) -> CalendarEvent:
        if isinstance(master.time, TimedInterval):
            assert isinstance(start, datetime)
            time: TimedInterval | AllDayRange = TimedInterval(
                start, start + (master.time.ends_at - master.time.starts_at)
            )
        else:
            assert isinstance(master.time, AllDayRange) and not isinstance(start, datetime)
            time = AllDayRange(start, start + (master.time.ends_before - master.time.starts_on))
        return CalendarEvent(
            reference=reference,
            time=time,
            revision=master.revision,
            title=master.title,
            description=master.description,
            location=master.location,
            occurrence=OccurrenceIdentity(master.reference.event_id, start),
            managed_origin=master.managed_origin,
        )

    def find_projection(
        self, destination: CalendarEndpoint, operation_key: str
    ) -> CalendarEvent | None:
        reference = self.operations.get(operation_key)
        return None if reference is None else self.events.get(reference)

    def create_projection(
        self,
        destination: CalendarEndpoint,
        source: EventRef,
        rule_id: SyncRuleId,
        projection: EventProjection,
        operation_key: str,
    ) -> CreatedProjection:
        existing = self.find_projection(destination, operation_key)
        if existing is not None:
            return CreatedProjection(existing)
        self.created += 1
        reference = EventRef(destination, EventId(f"projection-{self.created}"))
        created = CalendarEvent(
            reference=reference,
            time=projection.time,
            revision=f"projection-{self.created}-r1",
            title=projection.title,
            description=projection.description,
            location=projection.location,
            recurrence=projection.recurrence,
            managed_origin=ManagedOrigin(rule_id, source),
        )
        self.events[reference] = created
        self.operations[operation_key] = reference
        if projection.recurrence is not None:
            self.expansions[reference] = self.expansions.get(source, ())
        self.writes.append(("create", reference.event_id.value))
        return CreatedProjection(created)

    def update_projection(
        self,
        destination: EventRef,
        source: EventRef,
        rule_id: SyncRuleId,
        projection: EventProjection,
        operation_key: str,
    ) -> CalendarEvent:
        existing = self.events.get(destination)
        if existing is None or not _owned(existing.managed_origin, rule_id, source):
            raise _denied()
        updated = replace(
            existing,
            time=projection.time,
            title=projection.title,
            description=projection.description,
            location=projection.location,
            recurrence=projection.recurrence,
            revision=f"{existing.revision}+",
            status=EventStatus.CONFIRMED,
        )
        self.events[destination] = updated
        if projection.recurrence is not None:
            starts = self.expansions.get(source, ())
            self.expansions[destination] = starts
            # Like Google, a series update drops exceptions that left the series.
            for instance in self.instances_of(destination):
                assert instance.occurrence is not None
                if instance.occurrence.original_start not in starts:
                    del self.events[instance.reference]
        self.writes.append(("update", destination.event_id.value))
        return updated

    def delete_projection(
        self, destination: EventRef, source: EventRef, rule_id: SyncRuleId, operation_key: str
    ) -> None:
        existing = self.events.get(destination)
        if existing is None or existing.status is EventStatus.CANCELLED:
            return
        if not _owned(existing.managed_origin, rule_id, source):
            raise _denied()
        for instance in self.instances_of(destination):
            del self.events[instance.reference]
        del self.events[destination]
        self.expansions.pop(destination, None)
        self.writes.append(("delete", destination.event_id.value))

    def write_occurrence(
        self,
        destination_series: EventRef,
        original_start: OccurrenceStart,
        source_series: EventRef,
        rule_id: SyncRuleId,
        projection: EventProjection,
        operation_key: str,
    ) -> CalendarEvent:
        instance = self._owned_occurrence(
            destination_series, original_start, source_series, rule_id
        )
        if instance is None:
            raise ProviderFailure(ProviderFailureKind.PERMANENT, "occurrence could not be resolved")
        written = replace(
            instance,
            time=projection.time,
            title=projection.title,
            description=projection.description,
            location=projection.location,
            status=EventStatus.CONFIRMED,
            revision=f"{instance.revision}+",
            managed_origin=ManagedOrigin(rule_id, source_series),
        )
        self.events[instance.reference] = written
        self.writes.append(("write_occurrence", instance.reference.event_id.value))
        return written

    def cancel_occurrence(
        self,
        destination_series: EventRef,
        original_start: OccurrenceStart,
        source_series: EventRef,
        rule_id: SyncRuleId,
        operation_key: str,
    ) -> None:
        instance = self._owned_occurrence(
            destination_series, original_start, source_series, rule_id
        )
        if instance is None or instance.status is EventStatus.CANCELLED:
            return
        # Google's cancelled exceptions carry no content and no private metadata.
        self.events[instance.reference] = replace(
            instance,
            status=EventStatus.CANCELLED,
            time=None,
            title="",
            description="",
            location="",
            managed_origin=None,
            revision=f"{instance.revision}+",
        )
        self.writes.append(("cancel_occurrence", instance.reference.event_id.value))

    def _owned_occurrence(
        self,
        destination_series: EventRef,
        original_start: OccurrenceStart,
        source_series: EventRef,
        rule_id: SyncRuleId,
    ) -> CalendarEvent | None:
        instance = self.get_occurrence(destination_series, original_start)
        if instance is None:
            return None
        master = self.events.get(destination_series)
        if master is None or not _owned(master.managed_origin, rule_id, source_series):
            raise _denied()
        if instance.managed_origin is not None and not _owned(
            instance.managed_origin, rule_id, source_series
        ):
            raise _denied()
        return instance

    def managed_events(
        self, destination: CalendarEndpoint, rule_id: SyncRuleId
    ) -> tuple[CalendarEvent, ...]:
        return tuple(
            event
            for event in self.events.values()
            if event.reference.calendar == destination
            and event.status is EventStatus.CONFIRMED
            and event.managed_origin is not None
            and event.managed_origin.rule_id == rule_id
        )


def enabled_rule_factory(rule_: SyncRule | None = None) -> InMemoryUnitOfWorkFactory:
    factory = InMemoryUnitOfWorkFactory()
    with factory() as uow:
        uow.rules.add(rule_ or rule())
        uow.commit()
    return factory


def sync_use_case(factory: UnitOfWorkFactory, calendars: FakeCalendars) -> ExecuteSyncRule:
    fingerprinter = ProjectionFingerprinter()
    return ExecuteSyncRule(
        factory,
        calendars,
        SyncDecisionService(EventProjector(), fingerprinter),
        fingerprinter,
        FixedClock(),
    )
