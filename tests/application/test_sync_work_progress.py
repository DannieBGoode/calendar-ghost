"""A running Sync Run reports how many of the reported events it has handled, out of how many."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from calendar_sync.application.locking import RuleLocks
from calendar_sync.application.ports import CreatedProjection
from calendar_sync.application.synchronization import ExecuteSyncRule
from calendar_sync.domain.model import (
    CalendarEndpoint,
    CalendarEvent,
    EventProjection,
    EventRef,
    SyncRuleId,
)
from calendar_sync.domain.services import (
    EventProjector,
    ProjectionFingerprinter,
    SyncDecisionService,
)
from calendar_sync.infrastructure.identifiers import UuidRunIdGenerator
from calendar_sync.infrastructure.persistence.memory import InMemoryUnitOfWorkFactory
from tests.application.test_run_logging import SteppedClock
from tests.fake_calendar import FakeCalendars, enabled_rule_factory
from tests.helpers import event, rule


@dataclass
class WatchedCalendars(FakeCalendars):
    """Records the rule's reported work at every create and single-event read."""

    locks: RuleLocks = field(default_factory=RuleLocks)
    clock: SteppedClock | None = None
    seen: list[tuple[int, int | None]] = field(default_factory=list)

    def _watch(self) -> None:
        work = self.locks.current_work(rule().id)
        assert work is not None
        self.seen.append((work.done, work.total))
        if self.clock is not None:
            self.clock.advance(20)

    def create_projection(
        self,
        destination: CalendarEndpoint,
        source: EventRef,
        rule_id: SyncRuleId,
        projection: EventProjection,
        operation_key: str,
    ) -> CreatedProjection:
        self._watch()
        return super().create_projection(destination, source, rule_id, projection, operation_key)

    def get_event(self, reference: EventRef) -> CalendarEvent | None:
        if self.locks.current_work(rule().id) is not None:
            self._watch()
        return super().get_event(reference)


def use_case(factory: InMemoryUnitOfWorkFactory, calendars: WatchedCalendars) -> ExecuteSyncRule:
    fingerprinter = ProjectionFingerprinter()
    return ExecuteSyncRule(
        factory,
        calendars,
        SyncDecisionService(EventProjector(), fingerprinter),
        fingerprinter,
        calendars.clock or SteppedClock(),
        UuidRunIdGenerator(),
        calendars.locks,
    )


def test_a_run_counts_each_listed_event_it_handles() -> None:
    calendars = WatchedCalendars()
    for index in range(3):
        calendars.put(event(f"event-{index}"))

    use_case(enabled_rule_factory(), calendars).execute(rule().id)

    assert calendars.seen == [(0, 3), (1, 3), (2, 3)]
    assert calendars.locks.current_work(rule().id) is None


def test_reprojection_adds_the_mappings_the_feeds_did_not_report() -> None:
    calendars = WatchedCalendars()
    calendars.put(event("kept"))
    calendars.put(event("gone"))
    factory = enabled_rule_factory()
    execute = use_case(factory, calendars)
    execute.execute(rule().id)
    # The source can no longer be read, so only reprojection reaches its mapping.
    del calendars.events[event("gone").reference]
    with factory() as uow:
        uow.rules.save(replace(rule(), reprojection_required=True))
        uow.commit()
    calendars.seen.clear()

    execute.execute(rule().id)

    # One source event and two projections were listed; reprojection then adds the unread one.
    assert calendars.seen[-1] == (3, 4)
    assert all(total is not None and done <= total for done, total in calendars.seen)
