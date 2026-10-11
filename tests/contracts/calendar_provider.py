"""What every Calendar Provider adapter must honor, asked only through the provider ports.

An adapter passes this suite before it is composed (ADR 0022). A subclass supplies a harness
that can place and remove a Native Event in its backend, as the calendar's owner would.

Recurring series follow ADR 0011: an occurrence is written or cancelled only in a series this rule
owns, and only an answered lookup may prove an occurrence absent, because absence can authorize
cancelling one in a destination.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from calendar_sync.application.sync.errors import ProjectionOwnershipMismatch, ProviderFailure
from calendar_sync.application.sync.ports import CalendarProvider
from calendar_sync.domain.model import (
    CalendarEndpoint,
    CalendarEvent,
    EventId,
    EventProjection,
    EventRef,
    EventStatus,
    ManagedOrigin,
    Recurrence,
    SyncRuleId,
    TimedInterval,
    TransformationPolicy,
)
from calendar_sync.domain.providers import ProviderFailureKind
from tests.helpers import NOW, endpoint, event

SOURCE = endpoint("personal-account", "personal-calendar")
DESTINATION = endpoint("work-account", "work-calendar")
RULE_ID = SyncRuleId("rule-1")
OTHER_RULE_ID = SyncRuleId("rule-2")
WINDOW_START = NOW - timedelta(days=1)
POLICY = TransformationPolicy()
DAILY_THREE_TIMES = Recurrence(("RRULE:FREQ=DAILY;COUNT=3",))
SERIES_STARTS = tuple(NOW + timedelta(days=day) for day in range(3))
SOURCE_SERIES = CalendarEvent(
    reference=EventRef(SOURCE, EventId("source-series")),
    time=TimedInterval(NOW, NOW + timedelta(hours=1), "UTC"),
    revision="series-revision-1",
    title="Daily private sync",
    recurrence=DAILY_THREE_TIMES,
)


def daily_starts(series: CalendarEvent) -> tuple[datetime, ...]:
    """The original starts of a contract series, for a backend that does not expand one."""
    assert series.recurrence == DAILY_THREE_TIMES
    assert isinstance(series.time, TimedInterval)
    return tuple(series.time.starts_at.astimezone(UTC) + timedelta(days=d) for d in range(3))


@dataclass(frozen=True, slots=True)
class ProviderHarness:
    provider: CalendarProvider
    seed: Callable[[CalendarEvent], object]
    """Place a Native Event in the provider, as the calendar's owner would create it."""
    remove: Callable[[CalendarEvent], object]
    """Delete a Native Event the harness seeded, as the calendar's owner would."""
    expire_cursors: Callable[[CalendarEndpoint], object]
    """Make the provider refuse every cursor it gave for the calendar, as one that expired."""
    know_series: Callable[[CalendarEvent], object]
    """Let the backend expand a source series, if it cannot read the recurrence itself."""
    backdate: Callable[[CalendarEvent], object]
    """Make a seeded event read as last changed a day ago, for a backend that re-reads events
    changed shortly before a cursor, as Outlook does for clocks that disagree."""


def _projection(title: str = "Busy") -> EventProjection:
    return EventProjection(time=TimedInterval(NOW, NOW + timedelta(hours=1)), title=title)


def _series(harness: ProviderHarness, key: str, rule_id: SyncRuleId = RULE_ID) -> EventRef:
    """A Managed Projection of the contract series, in the destination."""
    harness.know_series(SOURCE_SERIES)
    projection = EventProjection(
        time=TimedInterval(NOW, NOW + timedelta(hours=1), "UTC"),
        title="Busy",
        recurrence=DAILY_THREE_TIMES,
    )
    created = harness.provider.create_projection(
        DESTINATION, SOURCE_SERIES.reference, rule_id, projection, key
    )
    return created.destination_event.reference


def _or_failure[T](lookup: Callable[[], T]) -> T | None:
    """A lookup's answer, or None where it failed, as a series that cannot be read may."""
    try:
        return lookup()
    except ProviderFailure:
        return None


def _occurrence_projection(start: datetime, title: str) -> EventProjection:
    return EventProjection(time=TimedInterval(start, start + timedelta(hours=1)), title=title)


def _write(
    harness: ProviderHarness,
    series: EventRef,
    start: datetime,
    key: str,
    source: EventRef = SOURCE_SERIES.reference,
) -> None:
    harness.provider.write_occurrence(
        series, start, source, RULE_ID, _occurrence_projection(start, "Moved"), key
    )


def _cancel(
    harness: ProviderHarness,
    series: EventRef,
    start: datetime,
    source: EventRef = SOURCE_SERIES.reference,
) -> None:
    harness.provider.cancel_occurrence(
        series, start, source, RULE_ID, f"cancel-{start.isoformat()}"
    )


def _assert_refused(harness: ProviderHarness, series: EventRef, source: EventRef) -> None:
    """Writing or cancelling an occurrence of `series` for `source` and RULE_ID fails, and the
    occurrence stays as it was."""
    with pytest.raises(ProviderFailure) as written:
        _write(harness, series, SERIES_STARTS[1], "key-write", source)
    with pytest.raises(ProviderFailure) as cancelled:
        _cancel(harness, series, SERIES_STARTS[1], source)

    assert written.value.kind is ProviderFailureKind.PERMANENT
    assert cancelled.value.kind is ProviderFailureKind.PERMANENT
    kept = _occurrence(harness, series, SERIES_STARTS[1])
    assert (kept.status, kept.title) == (EventStatus.CONFIRMED, "Busy")


def _occurrence(harness: ProviderHarness, series: EventRef, start: datetime) -> CalendarEvent:
    found = harness.provider.get_occurrence(series, start)
    assert found is not None
    assert found.occurrence is not None
    assert found.occurrence.series_event_id == series.event_id
    assert found.occurrence.original_start == start
    return found


def _create(
    harness: ProviderHarness, key: str, rule_id: SyncRuleId = RULE_ID, source_id: str = "source"
) -> CalendarEvent:
    source = event(source_id, calendar=SOURCE).reference
    created = harness.provider.create_projection(DESTINATION, source, rule_id, _projection(), key)
    return created.destination_event


class CalendarProviderContract:
    @pytest.fixture
    def harness(self) -> ProviderHarness:
        raise NotImplementedError

    def test_a_created_projection_reads_back_owned_by_its_rule_and_source(
        self, harness: ProviderHarness
    ) -> None:
        created = _create(harness, "key-1")

        found = harness.provider.get_event(created.reference)

        assert found is not None
        assert found.status is EventStatus.CONFIRMED
        assert found.title == "Busy"
        assert found.managed_origin == ManagedOrigin(
            RULE_ID, event("source", calendar=SOURCE).reference
        )

    def test_one_operation_key_creates_one_projection(self, harness: ProviderHarness) -> None:
        first = _create(harness, "key-1")
        second = _create(harness, "key-1")

        listed = harness.provider.managed_events(DESTINATION, RULE_ID, WINDOW_START)

        assert second.reference == first.reference
        assert [projection.reference for projection in listed] == [first.reference]

    def test_only_a_known_operation_key_finds_a_projection(self, harness: ProviderHarness) -> None:
        created = _create(harness, "key-1")

        found = harness.provider.find_projection(DESTINATION, "key-1")

        assert found is not None
        assert found.reference == created.reference
        assert harness.provider.find_projection(DESTINATION, "key-never-used") is None

    def test_managed_events_list_only_this_rules_projections(
        self, harness: ProviderHarness
    ) -> None:
        harness.seed(event("native-event", calendar=DESTINATION))
        mine = _create(harness, "key-1")
        _create(harness, "key-2", OTHER_RULE_ID, "other-source")

        listed = harness.provider.managed_events(DESTINATION, RULE_ID, WINDOW_START)

        assert [projection.reference for projection in listed] == [mine.reference]

    def test_an_event_that_never_existed_reads_as_none(self, harness: ProviderHarness) -> None:
        missing = EventRef(DESTINATION, EventId("never-existed"))

        assert harness.provider.get_event(missing) is None

    def test_deleting_a_projection_twice_is_quiet(self, harness: ProviderHarness) -> None:
        created = _create(harness, "key-1")
        source = event("source", calendar=SOURCE).reference

        harness.provider.delete_projection(created.reference, source, RULE_ID, "key-delete")
        harness.provider.delete_projection(created.reference, source, RULE_ID, "key-delete")

        found = harness.provider.get_event(created.reference)
        assert found is None or found.status is EventStatus.CANCELLED

    def test_another_rules_projection_is_never_updated_or_deleted(
        self, harness: ProviderHarness
    ) -> None:
        theirs = _create(harness, "key-1", OTHER_RULE_ID)
        source = event("source", calendar=SOURCE).reference

        with pytest.raises(ProjectionOwnershipMismatch):
            harness.provider.update_projection(
                theirs.reference, source, RULE_ID, _projection("Changed"), "key-update"
            )
        with pytest.raises(ProjectionOwnershipMismatch):
            harness.provider.delete_projection(theirs.reference, source, RULE_ID, "key-delete")

        found = harness.provider.get_event(theirs.reference)
        assert found is not None
        assert found.title == "Busy"

    def test_a_projection_of_another_source_event_is_never_updated_or_deleted(
        self, harness: ProviderHarness
    ) -> None:
        theirs = _create(harness, "key-1", RULE_ID, "other-source")
        source = event("source", calendar=SOURCE).reference

        with pytest.raises(ProjectionOwnershipMismatch):
            harness.provider.update_projection(
                theirs.reference, source, RULE_ID, _projection("Changed"), "key-update"
            )
        with pytest.raises(ProjectionOwnershipMismatch):
            harness.provider.delete_projection(theirs.reference, source, RULE_ID, "key-delete")

        found = harness.provider.get_event(theirs.reference)
        assert found is not None
        assert found.status is EventStatus.CONFIRMED
        assert found.title == "Busy"
        assert found.revision == theirs.revision

    def test_a_full_listing_reports_native_events_without_a_managed_origin(
        self, harness: ProviderHarness
    ) -> None:
        native = event("native-event", calendar=SOURCE)
        harness.seed(native)

        listing = harness.provider.changes(SOURCE, None, WINDOW_START)

        reported = {item.reference: item for item in listing.events}
        assert listing.complete
        assert listing.next_cursor
        assert native.reference in reported
        assert reported[native.reference].managed_origin is None

    # Recurring series (ADR 0011) ---------------------------------------------------------

    def test_a_series_projection_resolves_each_occurrence_by_its_original_start(
        self, harness: ProviderHarness
    ) -> None:
        series = _series(harness, "key-series")

        for start in SERIES_STARTS:
            found = _occurrence(harness, series, start)
            assert found.status is EventStatus.CONFIRMED
            assert found.title == "Busy"
        listed = harness.provider.list_occurrences(series, SERIES_STARTS)
        # A start the listing lacks proves nothing, but whatever it answers names its own start.
        assert set(listed) <= set(SERIES_STARTS)
        for asked, answered in listed.items():
            assert answered.occurrence is not None
            assert answered.occurrence.original_start == asked

    def test_a_start_the_series_never_had_resolves_to_none(self, harness: ProviderHarness) -> None:
        series = _series(harness, "key-series")

        assert harness.provider.get_occurrence(series, NOW + timedelta(hours=12)) is None

    def test_a_series_that_cannot_be_read_never_proves_an_occurrence_absent(
        self, harness: ProviderHarness
    ) -> None:
        missing = EventRef(DESTINATION, EventId("never-existed"))

        with pytest.raises(ProviderFailure):
            harness.provider.get_occurrence(missing, NOW)
        # Each may fail instead, which proves nothing either; none may report an absence.
        assert _or_failure(lambda: harness.provider.list_occurrences(missing, SERIES_STARTS)) in (
            {},
            None,
        )
        exceptions = _or_failure(lambda: harness.provider.occurrence_exceptions(missing, NOW))
        assert exceptions is None or list(exceptions) == []
        live = _or_failure(lambda: harness.provider.has_live_occurrences(missing, POLICY))
        assert live is not False

    def test_writing_an_occurrence_changes_only_it_and_one_key_writes_it_once(
        self, harness: ProviderHarness
    ) -> None:
        series = _series(harness, "key-series")

        _write(harness, series, SERIES_STARTS[1], "key-write")
        _write(harness, series, SERIES_STARTS[1], "key-write")

        written = _occurrence(harness, series, SERIES_STARTS[1])
        assert written.status is EventStatus.CONFIRMED
        assert written.title == "Moved"
        for start in (SERIES_STARTS[0], SERIES_STARTS[2]):
            assert _occurrence(harness, series, start).title == "Busy"

    def test_cancelling_an_occurrence_cancels_only_it_and_twice_is_quiet(
        self, harness: ProviderHarness
    ) -> None:
        series = _series(harness, "key-series")

        _cancel(harness, series, SERIES_STARTS[1])
        _cancel(harness, series, SERIES_STARTS[1])

        assert _occurrence(harness, series, SERIES_STARTS[1]).status is EventStatus.CANCELLED
        for start in (SERIES_STARTS[0], SERIES_STARTS[2]):
            assert _occurrence(harness, series, start).status is EventStatus.CONFIRMED

    def test_another_rules_series_is_never_written_or_cancelled(
        self, harness: ProviderHarness
    ) -> None:
        theirs = _series(harness, "key-theirs", OTHER_RULE_ID)

        _assert_refused(harness, theirs, SOURCE_SERIES.reference)

    def test_a_series_of_another_source_is_never_written_or_cancelled(
        self, harness: ProviderHarness
    ) -> None:
        # The same rule, but the series projects another source: the source must match too.
        series = _series(harness, "key-series")

        _assert_refused(harness, series, EventRef(SOURCE, EventId("other-source-series")))

    def test_a_series_whose_every_occurrence_is_cancelled_has_none_live(
        self, harness: ProviderHarness
    ) -> None:
        series = _series(harness, "key-series")
        assert harness.provider.has_live_occurrences(series, POLICY) is True

        for start in SERIES_STARTS:
            _cancel(harness, series, start)

        assert harness.provider.has_live_occurrences(series, POLICY) is False

    def test_exceptions_are_the_occurrences_written_or_cancelled(
        self, harness: ProviderHarness
    ) -> None:
        series = _series(harness, "key-series")
        _write(harness, series, SERIES_STARTS[1], "key-write")
        _cancel(harness, series, SERIES_STARTS[2])

        exceptions = harness.provider.occurrence_exceptions(series, WINDOW_START)

        found = {
            (each.occurrence.original_start, each.status)
            for each in exceptions
            if each.occurrence is not None
        }
        assert found == {
            (SERIES_STARTS[1], EventStatus.CONFIRMED),
            (SERIES_STARTS[2], EventStatus.CANCELLED),
        }
        assert len(exceptions) == 2

    # Change feeds -------------------------------------------------------------------------

    def test_a_cursor_reports_what_was_added_and_removed_since_it(
        self, harness: ProviderHarness
    ) -> None:
        kept = event("native-kept", calendar=SOURCE)
        removed = event("native-removed", calendar=SOURCE)
        harness.seed(kept)
        harness.seed(removed)
        harness.backdate(kept)
        cursor = harness.provider.changes(SOURCE, None, WINDOW_START).next_cursor
        added = event("native-added", calendar=SOURCE)

        harness.seed(added)
        harness.remove(removed)
        later = harness.provider.changes(SOURCE, cursor, WINDOW_START)

        reported = {item.reference: item for item in later.events}
        assert not later.complete
        assert later.next_cursor
        assert reported[added.reference].status is EventStatus.CONFIRMED
        assert reported[removed.reference].status is EventStatus.CANCELLED
        # Only what changed since the cursor: an event left alone well before it is not reported
        # again, though one changed just before it may be, which a Sync Run decides by content.
        assert kept.reference not in reported

    def test_a_refused_cursor_answers_with_a_full_listing(self, harness: ProviderHarness) -> None:
        native = event("native-event", calendar=SOURCE)
        harness.seed(native)
        cursor = harness.provider.changes(SOURCE, None, WINDOW_START).next_cursor

        harness.expire_cursors(SOURCE)
        again = harness.provider.changes(SOURCE, cursor, WINDOW_START)

        assert again.complete
        assert native.reference in {item.reference for item in again.events}
