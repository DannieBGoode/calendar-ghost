"""The Outlook adapter against the fake Graph API: series kept as series, cancelled occurrences
found by the pattern, changes followed incrementally, writes that email nobody, and refusals
translated without Microsoft's words (ADR 0032)."""

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from calendar_sync.application.errors import (
    ProjectionOwnershipMismatch,
    ProviderFailure,
    ProviderFailureKind,
    UnsupportedProjection,
)
from calendar_sync.application.providers import ProviderKind
from calendar_sync.domain.model import (
    AllDayRange,
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
from calendar_sync.infrastructure.provider_calls import ContextProviderCallStats
from tests.adapters.microsoft.test_calendar_provider_contract import MAILBOXES, outlook
from tests.fake_microsoft_graph_api import FakeMicrosoftGraph, graph_error
from tests.helpers import endpoint

SOURCE = endpoint("personal-account", "personal-calendar")
DESTINATION = endpoint("work-account", "work-calendar")
RULE = SyncRuleId("rule-1")
# A Monday at 09:00 in Paris, in summer time.
MONDAY = datetime(2026, 10, 12, 7, 0, tzinfo=UTC)
WINDOW = MONDAY - timedelta(days=1)


def _seed(graph: FakeMicrosoftGraph, calendar: str = "personal-calendar", **fields: Any) -> str:
    address = MAILBOXES["personal-account" if calendar == "personal-calendar" else "work-account"][
        0
    ]
    item = {
        "subject": "Standup",
        "body": {"contentType": "text", "content": ""},
        "isAllDay": False,
        "start": {"dateTime": "2026-10-12T07:00:00", "timeZone": "UTC"},
        "end": {"dateTime": "2026-10-12T07:30:00", "timeZone": "UTC"},
        **fields,
    }
    return graph.events.seed(address, calendar, item)


def _weekly_series(graph: FakeMicrosoftGraph, **range_: Any) -> str:
    return _seed(
        graph,
        start={"dateTime": "2026-10-12T09:00:00", "timeZone": "Romance Standard Time"},
        end={"dateTime": "2026-10-12T09:30:00", "timeZone": "Romance Standard Time"},
        recurrence={
            "pattern": {
                "type": "weekly",
                "interval": 1,
                "daysOfWeek": ["monday"],
                "firstDayOfWeek": "sunday",
            },
            "range": {
                "type": "noEnd",
                "startDate": "2026-10-12",
                "recurrenceTimeZone": "Romance Standard Time",
                **range_,
            },
        },
    )


def _ref(event_id: str, calendar: Any = SOURCE) -> EventRef:
    return EventRef(calendar, EventId(event_id))


def _occurrence_id(series_id: str, day: str) -> str:
    return f"{series_id}.occ.{day}"


def test_a_full_listing_keeps_a_series_with_its_moved_and_cancelled_occurrences() -> None:
    provider, graph = outlook()
    series = _weekly_series(graph)
    mailbox, calendar = MAILBOXES["personal-account"][0], "personal-calendar"
    graph.events._delete(mailbox, calendar, _occurrence_id(series, "2026-10-19"))
    graph.events._patch(
        mailbox,
        calendar,
        _occurrence_id(series, "2026-10-26"),
        {
            "start": {"dateTime": "2026-10-27T10:00:00", "timeZone": "UTC"},
            "end": {"dateTime": "2026-10-27T10:30:00", "timeZone": "UTC"},
        },
    )

    listing = provider.changes(SOURCE, None, WINDOW)

    assert listing.complete
    by_kind = {
        ("master" if e.recurrence else e.status.value): e
        for e in listing.events
        if e.reference.event_id.value == series or e.occurrence
    }
    master = next(e for e in listing.events if e.reference.event_id.value == series)
    assert master.recurrence == Recurrence(("RRULE:FREQ=WEEKLY;BYDAY=MO",))
    assert isinstance(master.time, TimedInterval)
    assert master.time.time_zone == "Europe/Paris"
    occurrences = {e.occurrence.original_start: e for e in listing.events if e.occurrence}
    assert occurrences[MONDAY + timedelta(days=7)].status is EventStatus.CANCELLED
    # After the change to winter time, 09:00 in Paris is 08:00 UTC.
    moved = occurrences[MONDAY + timedelta(days=14, hours=1)]
    assert moved.status is EventStatus.CONFIRMED
    assert isinstance(moved.time, TimedInterval)
    assert moved.time.starts_at == datetime(2026, 10, 27, 10, 0, tzinfo=UTC)
    assert by_kind


def test_an_incremental_feed_reports_what_changed_and_what_was_removed() -> None:
    provider, graph = outlook()
    kept = _seed(graph, subject="Kept")
    removed = _seed(graph, subject="Removed")
    series = _weekly_series(graph)
    first = provider.changes(SOURCE, None, WINDOW)
    mailbox, calendar = MAILBOXES["personal-account"][0], "personal-calendar"
    added = _seed(graph, subject="Added")
    graph.events._delete(mailbox, calendar, removed)
    graph.events._delete(mailbox, calendar, _occurrence_id(series, "2026-10-19"))

    later = provider.changes(SOURCE, first.next_cursor, WINDOW)

    reported = {e.reference.event_id.value: e for e in later.events}
    assert not later.complete
    assert reported[added].title == "Added"
    assert reported[removed].status is EventStatus.CANCELLED
    # What changed shortly before the last run may be reported again; replays change nothing.
    assert reported.get(kept) is None or reported[kept].title == "Kept"
    # The series is read again, with the occurrence Outlook no longer lists.
    cancelled = [e for e in later.events if e.occurrence and e.status is EventStatus.CANCELLED]
    assert [e.occurrence.original_start for e in cancelled if e.occurrence] == [
        MONDAY + timedelta(days=7)
    ]
    assert later.next_cursor != first.next_cursor


def test_a_delta_link_graph_no_longer_accepts_starts_over_with_a_full_listing() -> None:
    provider, graph = outlook()
    native = _seed(graph)
    first = provider.changes(SOURCE, None, WINDOW)
    graph.events.expired = True

    again = provider.changes(SOURCE, first.next_cursor, WINDOW)

    assert again.complete
    assert native in {e.reference.event_id.value for e in again.events}


def test_a_single_event_that_ended_before_the_window_is_left_out_of_a_listing() -> None:
    provider, graph = outlook()
    old = _seed(
        graph,
        start={"dateTime": "2026-01-05T07:00:00", "timeZone": "UTC"},
        end={"dateTime": "2026-01-05T08:00:00", "timeZone": "UTC"},
    )

    listed = provider.list_events(SOURCE, WINDOW)

    assert old not in {e.reference.event_id.value for e in listed}


def test_an_occurrence_is_found_cancelled_or_absent_by_its_pattern() -> None:
    provider, graph = outlook()
    series = _weekly_series(graph)
    graph.events._delete(
        MAILBOXES["personal-account"][0], "personal-calendar", _occurrence_id(series, "2026-10-19")
    )

    found = provider.get_occurrence(_ref(series), MONDAY)
    cancelled = provider.get_occurrence(_ref(series), MONDAY + timedelta(days=7))
    absent = provider.get_occurrence(_ref(series), MONDAY + timedelta(days=1))

    assert found is not None
    assert found.status is EventStatus.CONFIRMED
    assert cancelled is not None
    assert cancelled.status is EventStatus.CANCELLED
    assert absent is None
    # A cancelled occurrence read by its name is the same cancellation.
    assert provider.get_event(cancelled.reference) == cancelled


def test_an_occurrence_of_a_series_outlook_cannot_read_is_never_proven_absent() -> None:
    provider, _ = outlook()

    with pytest.raises(ProviderFailure) as raised:
        provider.get_occurrence(_ref("missing-series"), MONDAY)

    assert raised.value.kind is ProviderFailureKind.TEMPORARY


def test_exceptions_reaching_the_window_include_cancelled_occurrences() -> None:
    provider, graph = outlook()
    series = _weekly_series(graph)
    graph.events._delete(
        MAILBOXES["personal-account"][0], "personal-calendar", _occurrence_id(series, "2026-11-02")
    )

    exceptions = provider.occurrence_exceptions(_ref(series), WINDOW)

    assert [(e.status, e.occurrence.original_start) for e in exceptions if e.occurrence] == [
        (EventStatus.CANCELLED, datetime(2026, 11, 2, 8, 0, tzinfo=UTC))
    ]


def test_a_series_with_occurrences_left_is_live_and_one_without_is_not() -> None:
    provider, graph = outlook()
    live = _weekly_series(graph, type="numbered", numberOfOccurrences=2)
    gone = _weekly_series(graph, type="numbered", numberOfOccurrences=2)
    for day in ("2026-10-12", "2026-10-19"):
        graph.events._delete(
            MAILBOXES["personal-account"][0], "personal-calendar", _occurrence_id(gone, day)
        )

    policy = TransformationPolicy()
    assert provider.has_live_occurrences(_ref(live), policy)
    assert not provider.has_live_occurrences(_ref(gone), policy)


def test_an_endless_series_is_never_proven_empty() -> None:
    provider, graph = outlook()
    series = _weekly_series(graph, type="endDate", endDate="2026-10-12")
    endless = _weekly_series(graph)

    graph.events._delete(
        MAILBOXES["personal-account"][0], "personal-calendar", _occurrence_id(series, "2026-10-12")
    )

    assert not provider.has_live_occurrences(_ref(series), TransformationPolicy())
    assert provider.has_live_occurrences(_ref(endless), TransformationPolicy())


def _series_projection(
    lines: tuple[str, ...] = ("RRULE:FREQ=WEEKLY;WKST=SU;BYDAY=MO",),
) -> EventProjection:
    return EventProjection(
        TimedInterval(MONDAY, MONDAY + timedelta(minutes=30), "Europe/Madrid"),
        "Busy",
        recurrence=Recurrence(lines),
    )


def test_a_series_projection_reads_back_exactly_as_it_was_written() -> None:
    provider, graph = outlook()
    source = _ref("google-series")
    projection = _series_projection()

    created = provider.create_projection(DESTINATION, source, RULE, projection, "key-1")
    read = provider.get_event(created.destination_event.reference)

    assert read is not None
    assert read.recurrence == projection.recurrence
    assert read.time == projection.time
    assert read.managed_origin == ManagedOrigin(RULE, source)
    assert graph.events.mail == []


def test_a_projection_outlook_cannot_hold_writes_nothing() -> None:
    provider, graph = outlook()

    with pytest.raises(UnsupportedProjection):
        provider.create_projection(
            DESTINATION,
            _ref("google-series"),
            RULE,
            _series_projection(("RRULE:FREQ=HOURLY",)),
            "key-1",
        )

    assert [method for method, _, _ in graph.events.writes] == []


def _destination_series(provider: Any, graph: FakeMicrosoftGraph) -> tuple[EventRef, EventRef]:
    source = _ref("google-series")
    created = provider.create_projection(DESTINATION, source, RULE, _series_projection(), "key-1")
    return created.destination_event.reference, source


def test_an_occurrence_is_written_and_cancelled_without_emailing_anyone() -> None:
    provider, graph = outlook()
    destination, source = _destination_series(provider, graph)
    later = MONDAY + timedelta(days=7)
    moved = EventProjection(
        TimedInterval(later + timedelta(hours=2), later + timedelta(hours=3)), "Busy"
    )

    written = provider.write_occurrence(destination, later, source, RULE, moved, "key-2")
    provider.cancel_occurrence(
        destination, MONDAY + timedelta(days=14, hours=1), source, RULE, "key-3"
    )

    assert written.time == moved.time
    assert written.managed_origin == ManagedOrigin(RULE, source)
    cancelled = provider.get_occurrence(destination, MONDAY + timedelta(days=14, hours=1))
    assert cancelled is not None
    assert cancelled.status is EventStatus.CANCELLED
    assert graph.events.mail == []
    assert all("attendees" not in body for _, _, body in graph.events.writes)


def test_an_occurrence_outlook_cancelled_cannot_be_restored_and_is_left_alone() -> None:
    provider, graph = outlook()
    destination, source = _destination_series(provider, graph)
    provider.cancel_occurrence(destination, MONDAY, source, RULE, "key-2")
    writes = len(graph.events.writes)

    with pytest.raises(UnsupportedProjection):
        provider.write_occurrence(
            destination,
            MONDAY,
            source,
            RULE,
            EventProjection(TimedInterval(MONDAY, MONDAY + timedelta(hours=1)), "Busy"),
            "key-3",
        )

    assert len(graph.events.writes) == writes


def test_an_occurrence_moved_past_its_neighbour_is_unsupported() -> None:
    provider, graph = outlook()
    destination, source = _destination_series(provider, graph)
    past = MONDAY + timedelta(days=8)

    with pytest.raises(UnsupportedProjection):
        provider.write_occurrence(
            destination,
            MONDAY,
            source,
            RULE,
            EventProjection(TimedInterval(past, past + timedelta(hours=1)), "Busy"),
            "key-2",
        )


def test_an_occurrence_of_another_rules_series_is_never_written() -> None:
    provider, graph = outlook()
    destination, source = _destination_series(provider, graph)

    with pytest.raises(ProviderFailure) as raised:
        provider.cancel_occurrence(destination, MONDAY, source, SyncRuleId("rule-2"), "key-2")

    assert raised.value.kind is ProviderFailureKind.PERMANENT
    assert provider.get_occurrence(destination, MONDAY) is not None


def test_a_native_event_is_never_updated_or_deleted() -> None:
    provider, graph = outlook()
    native = _seed(graph, calendar="work-calendar")

    with pytest.raises(ProjectionOwnershipMismatch):
        provider.delete_projection(_ref(native, DESTINATION), _ref("source"), RULE, "key-1")
    assert native in graph.events.stored


def test_an_all_day_projection_stays_all_day() -> None:
    provider, _ = outlook()
    day = AllDayRange(date(2026, 10, 12), date(2026, 10, 13))

    created = provider.create_projection(
        DESTINATION, _ref("s"), RULE, EventProjection(day, "Busy"), "k"
    )
    read = provider.get_event(created.destination_event.reference)

    assert read is not None
    assert read.time == day


@pytest.mark.parametrize(
    ("status", "code", "kind"),
    [
        (429, "TooManyRequests", ProviderFailureKind.RATE_LIMIT),
        (503, "ServiceNotAvailable", ProviderFailureKind.TEMPORARY),
        (401, "InvalidAuthenticationToken", ProviderFailureKind.AUTHENTICATION),
        (403, "ErrorAccessDenied", ProviderFailureKind.PERMANENT),
        (403, "Authorization_RequestDenied", ProviderFailureKind.AUTHORIZATION),
        (404, "ErrorItemNotFound", ProviderFailureKind.PERMANENT),
    ],
)
def test_a_refusal_says_what_to_do_without_microsofts_words(
    status: int, code: str, kind: ProviderFailureKind
) -> None:
    provider, graph = outlook()
    graph.refuse(graph_error(status, code, **{"Retry-After": "7"}))

    with pytest.raises(ProviderFailure) as raised:
        provider.changes(SOURCE, None, WINDOW)

    failure = raised.value
    assert failure.kind is kind
    assert failure.provider is ProviderKind.OUTLOOK
    assert failure.account_id is not None
    assert failure.account_id.value == "personal-account"
    assert "private-marker" not in str(failure)
    assert "private-marker" not in failure.summary


def test_a_rate_limit_waits_as_long_as_microsoft_asks() -> None:
    provider, graph = outlook()
    graph.refuse(graph_error(429, "TooManyRequests", **{"Retry-After": "7"}))

    with pytest.raises(ProviderFailure) as raised:
        provider.get_event(_ref("anything"))

    assert (raised.value.retryable, raised.value.retry_after_seconds) == (True, 7)


def test_every_call_is_tallied_for_outlook_by_its_operation_alone() -> None:
    provider, graph = outlook()
    _seed(graph)

    with ContextProviderCallStats().measure() as tally:
        provider.changes(SOURCE, None, WINDOW)

    assert tally.calls == len(graph.requests) > 0
    assert set(tally.providers) == {ProviderKind.OUTLOOK}


def test_managed_events_list_only_live_projections_reaching_the_window() -> None:
    provider, _ = outlook()
    old = EventProjection(
        TimedInterval(MONDAY - timedelta(days=60), MONDAY - timedelta(days=60, hours=-1)), "Busy"
    )
    current = provider.create_projection(
        DESTINATION,
        _ref("a"),
        RULE,
        EventProjection(TimedInterval(MONDAY, MONDAY + timedelta(hours=1)), "Busy"),
        "k1",
    )
    provider.create_projection(DESTINATION, _ref("b"), RULE, old, "k2")
    series = provider.create_projection(DESTINATION, _ref("c"), RULE, _series_projection(), "k3")

    listed = provider.managed_events(DESTINATION, RULE, WINDOW)

    assert {e.reference for e in listed} == {
        current.destination_event.reference,
        series.destination_event.reference,
    }


def test_a_source_projection_of_a_reverse_rule_is_known_by_its_origin() -> None:
    provider, _ = outlook()
    created = provider.create_projection(
        SOURCE,
        _ref("work-event", DESTINATION),
        SyncRuleId("reverse"),
        EventProjection(TimedInterval(MONDAY, MONDAY + timedelta(hours=1)), "Busy"),
        "k",
    )

    listed = provider.changes(SOURCE, None, WINDOW)

    projection: CalendarEvent = next(
        e for e in listed.events if e.reference == created.destination_event.reference
    )
    assert projection.managed_origin == ManagedOrigin(
        SyncRuleId("reverse"), _ref("work-event", DESTINATION)
    )
