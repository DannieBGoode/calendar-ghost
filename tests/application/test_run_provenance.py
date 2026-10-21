"""Each recorded entry says why its run read the calendars as it did, and which work found it."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from calendar_sync.application.sync.change_feeds import ChangeFeeds, run_reason
from calendar_sync.application.sync.errors import ProviderFailure
from calendar_sync.application.sync.locking import RuleLocks
from calendar_sync.application.sync.provider_ports import ProviderChangeSet
from calendar_sync.application.sync.reconciliation import ReconcileNow, ReconcileSyncRule
from calendar_sync.application.sync.sync_run import SyncRunContext
from calendar_sync.application.sync.synchronization import ExecuteSyncRule
from calendar_sync.domain.audit import AuditAction, AuditEntry, FoundBy, RunReason
from calendar_sync.domain.changes import ComparisonKind
from calendar_sync.domain.model import (
    EventId,
    EventRef,
    ManagedOrigin,
    ProjectionContent,
    SyncAction,
    SyncReason,
    SyncRuleState,
    TimedInterval,
    TransformationPolicy,
)
from calendar_sync.domain.runs import RunOrigin
from calendar_sync.domain.services import (
    EventProjector,
    ProjectionFingerprinter,
    ReconciliationService,
    SyncDecisionService,
)
from calendar_sync.infrastructure.identifiers import UuidRunIdGenerator
from calendar_sync.infrastructure.persistence.memory import InMemoryUserUnitOfWorkFactory
from tests.application.test_recurring_sync import _FailingExceptionListing
from tests.fake_calendar import FakeCalendars, FixedClock, enabled_rule_factory, sync_use_case
from tests.helpers import NOW, event, occurrence, rule, series, week_start

EMPTY = ProviderChangeSet((), "cursor", complete=False)
STARTS = tuple(week_start(week) for week in range(4))


def _feeds(source_listed: bool = False, destination_listed: bool = False) -> ChangeFeeds:
    return ChangeFeeds(EMPTY, EMPTY, source_listed, destination_listed)


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        (
            {"reproject": True, "origin": RunOrigin.RECONCILE_NOW, "full": True},
            RunReason.REPROJECTION,
        ),
        ({"origin": RunOrigin.RECONCILE_NOW, "full": True}, RunReason.RECONCILE_NOW),
        ({"full": True}, RunReason.DAILY_PASS),
        (
            {"saved_source": False, "saved_destination": False, "feeds": _feeds(True, True)},
            RunReason.FIRST_RUN,
        ),
        ({"feeds": _feeds(source_listed=True)}, RunReason.RELISTED),
        ({"feeds": _feeds(destination_listed=True)}, RunReason.RELISTED),
        (
            {"saved_destination": False, "feeds": _feeds(destination_listed=True)},
            RunReason.RELISTED,
        ),
        ({}, RunReason.CHANGES),
    ],
)
def test_the_first_reason_that_applies_names_the_run(
    kwargs: dict[str, object], expected: RunReason
) -> None:
    arguments: dict[str, object] = {
        "reproject": False,
        "origin": RunOrigin.SCHEDULED,
        "full": False,
        "saved_source": True,
        "saved_destination": True,
        "feeds": _feeds(),
    }
    arguments.update(kwargs)
    assert run_reason(**arguments) is expected  # type: ignore[arg-type]


def _synced() -> tuple[FakeCalendars, InMemoryUserUnitOfWorkFactory]:
    calendars = FakeCalendars()
    calendars.put(event())
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    return calendars, factory


def _provenance(entry: AuditEntry) -> tuple[RunReason | None, FoundBy | None]:
    return entry.run_reason, entry.found_by


def test_a_source_change_is_found_by_the_source_feed() -> None:
    calendars, factory = _synced()
    calendars.report(calendars.put(event(revision="revision-2", title="Renamed")))
    recorded = len(factory.state.audit)

    sync_use_case(factory, calendars).execute(rule().id)

    [entry] = factory.state.audit[recorded:]
    assert _provenance(entry) == (RunReason.CHANGES, FoundBy.SOURCE_FEED)
    assert entry.source_comparison is ComparisonKind.CHANGED


def test_an_edited_projection_is_found_by_the_destination_feed() -> None:
    calendars, factory = _synced()
    destination = factory.state.mappings[(rule().id, event().reference)].destination
    calendars.report(calendars.put(replace(calendars.events[destination], title="Edited")))
    recorded = len(factory.state.audit)

    sync_use_case(factory, calendars).execute(rule().id)

    [entry] = factory.state.audit[recorded:]
    assert entry.action is AuditAction.UPDATE
    assert _provenance(entry) == (RunReason.CHANGES, FoundBy.DESTINATION_FEED)


def test_a_daily_pass_entry_says_so() -> None:
    calendars, factory = _synced()
    recorded = len(factory.state.audit)

    sync_use_case(factory, calendars).execute(rule().id, full=True)

    [entry] = factory.state.audit[recorded:]
    assert _provenance(entry) == (RunReason.DAILY_PASS, FoundBy.SOURCE_FEED)


def test_the_first_run_says_so() -> None:
    _, factory = _synced()

    [entry] = factory.state.audit
    assert entry.reason is SyncReason.SOURCE_CREATED
    assert _provenance(entry) == (RunReason.FIRST_RUN, FoundBy.SOURCE_FEED)


def test_a_rejected_source_cursor_relists() -> None:
    calendars, factory = _synced()
    calendars.expired.add(rule().source)
    recorded = len(factory.state.audit)

    sync_use_case(factory, calendars).execute(rule().id)

    [entry] = factory.state.audit[recorded:]
    assert _provenance(entry) == (RunReason.RELISTED, FoundBy.SOURCE_FEED)


def _reconcile_now(
    factory: InMemoryUserUnitOfWorkFactory, calendars: FakeCalendars
) -> ReconcileNow:
    reconcile = ReconcileSyncRule(
        factory,
        calendars,
        EventProjector(),
        ReconciliationService(ProjectionFingerprinter()),
        FixedClock(),
        UuidRunIdGenerator(),
        locks=RuleLocks(),
    )
    return ReconcileNow(sync_use_case(factory, calendars), reconcile)


def test_reconcile_now_names_its_pass_and_its_own_entries() -> None:
    calendars = FakeCalendars()
    calendars.put(event())
    calendars.put(
        replace(
            event("orphan", calendar=rule().destination),
            title="Busy",
            managed_origin=ManagedOrigin(rule().id, EventRef(rule().source, EventId("gone"))),
        )
    )
    factory = enabled_rule_factory()

    _reconcile_now(factory, calendars).execute(rule().id)

    created, blocked = factory.state.audit
    assert created.reason is SyncReason.SOURCE_CREATED
    assert _provenance(created) == (RunReason.RECONCILE_NOW, FoundBy.SOURCE_FEED)
    assert blocked.reason is SyncReason.PROJECTION_UNMAPPED
    assert _provenance(blocked) == (None, FoundBy.RECONCILIATION)
    assert blocked.source_comparison is None


def test_a_direct_reconciliation_marks_its_entries_as_its_own() -> None:
    calendars, factory = _synced()
    calendars.unreadable.add(event().reference)

    _reconcile_now(factory, calendars).reconcile.execute(rule().id)

    entry = factory.state.audit[-1]
    assert entry.reason is SyncReason.SOURCE_UNVERIFIABLE
    assert _provenance(entry) == (None, FoundBy.RECONCILIATION)


class _EarlierClock:
    def now(self) -> datetime:
        return NOW - timedelta(days=60)


def test_a_reprojection_entry_says_the_rule_changed() -> None:
    calendars = FakeCalendars()
    factory = enabled_rule_factory()
    # Synchronized two months ago, so the full listing no longer reaches it; only reprojection does.
    old = calendars.put(
        replace(event(), time=TimedInterval(NOW - timedelta(days=60), NOW - timedelta(days=59)))
    )
    fingerprinter = ProjectionFingerprinter()
    ExecuteSyncRule(
        factory,
        calendars,
        SyncDecisionService(EventProjector(), fingerprinter),
        fingerprinter,
        _EarlierClock(),
        UuidRunIdGenerator(),
        locks=RuleLocks(),
    ).execute(rule().id)
    details = TransformationPolicy(content=ProjectionContent.DETAILS)
    with factory() as uow:
        uow.rules.save(replace(rule().change_policy(details), state=SyncRuleState.ENABLED))
        uow.commit()
    recorded = len(factory.state.audit)

    sync_use_case(factory, calendars).execute(rule().id)

    [entry] = factory.state.audit[recorded:]
    assert entry.source_event_id == old.reference.event_id.value
    assert entry.action is AuditAction.UPDATE
    assert _provenance(entry) == (RunReason.REPROJECTION, FoundBy.REPROJECTION)


def _new_series(calendars: FakeCalendars) -> EventRef:
    master = calendars.put(series(), starts=STARTS)
    moved = calendars.put(occurrence(master, 1, moved_by=timedelta(hours=1)))
    # Only the series is reported; its moved occurrence comes from the replay.
    calendars.report(master)
    return moved.reference


def _about(entries: list[AuditEntry], source: EventRef) -> list[AuditEntry]:
    return [entry for entry in entries if entry.source_event_id == source.event_id.value]


def test_a_pending_replay_is_found_by_the_replay() -> None:
    calendars = _FailingExceptionListing()
    factory = enabled_rule_factory()
    use_case = sync_use_case(factory, calendars)
    use_case.execute(rule().id)
    moved = _new_series(calendars)
    calendars.fail_next_listing = True
    with pytest.raises(ProviderFailure):
        use_case.execute(rule().id)
    recorded = len(factory.state.audit)

    use_case.execute(rule().id)

    [entry] = _about(factory.state.audit[recorded:], moved)
    assert entry.action is AuditAction.UPDATE
    assert _provenance(entry) == (RunReason.CHANGES, FoundBy.PENDING_REPLAY)


def test_an_immediate_replay_keeps_the_source_feed() -> None:
    calendars = FakeCalendars()
    factory = enabled_rule_factory()
    use_case = sync_use_case(factory, calendars)
    use_case.execute(rule().id)
    moved = _new_series(calendars)
    recorded = len(factory.state.audit)

    use_case.execute(rule().id)

    [entry] = _about(factory.state.audit[recorded:], moved)
    assert entry.action is AuditAction.UPDATE
    assert _provenance(entry) == (RunReason.CHANGES, FoundBy.SOURCE_FEED)


def test_an_unverifiable_source_is_recorded_with_its_provenance() -> None:
    calendars, factory = _synced()
    destination = factory.state.mappings[(rule().id, event().reference)].destination
    calendars.unreadable.add(event().reference)
    calendars.report(calendars.put(replace(calendars.events[destination], title="Edited")))
    recorded = len(factory.state.audit)

    sync_use_case(factory, calendars).execute(rule().id)

    [entry] = factory.state.audit[recorded:]
    assert entry.reason is SyncReason.SOURCE_UNVERIFIABLE
    assert _provenance(entry) == (RunReason.CHANGES, FoundBy.DESTINATION_FEED)


def test_finding_restores_the_outer_work_when_it_raises() -> None:
    factory = enabled_rule_factory()
    with factory() as uow:
        run = SyncRunContext(uow, rule(), "run", {action: 0 for action in SyncAction}, NOW)

    with run.finding(FoundBy.SOURCE_FEED):
        with pytest.raises(RuntimeError), run.finding(FoundBy.PENDING_REPLAY):
            raise RuntimeError
        assert run.found_by is FoundBy.SOURCE_FEED
    assert run.found_by is None
