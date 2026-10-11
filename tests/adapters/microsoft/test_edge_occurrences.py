"""A series' first or last occurrence has a neighbour on one side only, so Outlook lets it move any
distance the other way. It is never inferred cancelled from a window that cannot contain where it
may have moved (ADR 0034)."""

from datetime import UTC, datetime, timedelta

from calendar_sync.domain.model import EventId, EventRef, EventStatus, TimedInterval
from tests.adapters.microsoft.test_calendar_provider_contract import MAILBOXES, outlook
from tests.fake_microsoft_graph_api import FakeMicrosoftGraph
from tests.helpers import endpoint

SOURCE = endpoint("personal-account", "personal-calendar")
MAILBOX = MAILBOXES["personal-account"][0]
# Two Mondays at 09:00 in Paris: 12 and 19 October 2026, in summer time.
FIRST = datetime(2026, 10, 12, 7, 0, tzinfo=UTC)
LAST = datetime(2026, 10, 19, 7, 0, tzinfo=UTC)
# Three weeks after the last one, at 09:00 in Paris, in winter time.
MOVED = datetime(2026, 11, 9, 8, 0, tzinfo=UTC)
# Three years after it, further than a listing looks ahead for exceptions.
FAR = datetime(2029, 11, 12, 8, 0, tzinfo=UTC)


def _two_mondays(graph: FakeMicrosoftGraph) -> EventRef:
    series = graph.events.seed(
        MAILBOX,
        "personal-calendar",
        {
            "subject": "Standup",
            "body": {"contentType": "text", "content": ""},
            "isAllDay": False,
            "start": {"dateTime": "2026-10-12T09:00:00", "timeZone": "Romance Standard Time"},
            "end": {"dateTime": "2026-10-12T09:30:00", "timeZone": "Romance Standard Time"},
            "recurrence": {
                "pattern": {
                    "type": "weekly",
                    "interval": 1,
                    "daysOfWeek": ["monday"],
                    "firstDayOfWeek": "sunday",
                },
                "range": {
                    "type": "numbered",
                    "numberOfOccurrences": 2,
                    "startDate": "2026-10-12",
                    "recurrenceTimeZone": "Romance Standard Time",
                },
            },
        },
    )
    return EventRef(SOURCE, EventId(series))


def _move_last(graph: FakeMicrosoftGraph, series: EventRef, day: str = "2026-11-09") -> None:
    """Its owner moves the last Monday later, which Outlook allows: it has no following
    occurrence to stay before."""
    graph.events._patch(
        MAILBOX,
        "personal-calendar",
        f"{series.event_id.value}.occ.2026-10-19",
        {
            "start": {"dateTime": f"{day}T09:00:00", "timeZone": "Romance Standard Time"},
            "end": {"dateTime": f"{day}T09:30:00", "timeZone": "Romance Standard Time"},
        },
    )


def test_a_last_occurrence_moved_weeks_later_is_found_where_it_moved() -> None:
    provider, graph = outlook()
    series = _two_mondays(graph)
    _move_last(graph, series)

    found = provider.get_occurrence(series, LAST)

    assert found is not None
    assert found.status is EventStatus.CONFIRMED
    assert found.time == TimedInterval(MOVED, MOVED + timedelta(minutes=30))


def test_a_listing_never_reports_a_last_occurrence_moved_years_later_cancelled() -> None:
    provider, graph = outlook()
    series = _two_mondays(graph)
    _move_last(graph, series, "2029-11-12")

    exceptions = provider.occurrence_exceptions(series, FIRST - timedelta(days=1))

    (moved,) = exceptions
    assert moved.status is EventStatus.CONFIRMED
    assert moved.time == TimedInterval(FAR, FAR + timedelta(minutes=30))


def test_a_last_occurrence_listed_nowhere_it_may_have_moved_is_cancelled() -> None:
    provider, graph = outlook()
    series = _two_mondays(graph)
    graph.events._delete(MAILBOX, "personal-calendar", f"{series.event_id.value}.occ.2026-10-19")

    found = provider.get_occurrence(series, LAST)
    exceptions = provider.occurrence_exceptions(series, FIRST - timedelta(days=1))

    assert found is not None
    assert found.status is EventStatus.CANCELLED
    assert [event.status for event in exceptions] == [EventStatus.CANCELLED]


def test_an_edge_occurrence_is_looked_for_across_every_date_outlook_keeps() -> None:
    provider, graph = outlook()
    series = _two_mondays(graph)
    graph.events._delete(MAILBOX, "personal-calendar", f"{series.event_id.value}.occ.2026-10-19")
    calls = len(graph.requests)

    provider.get_occurrence(series, LAST)

    windows = [
        (request.url.params["startDateTime"], request.url.params["endDateTime"])
        for request in graph.requests[calls:]
        if request.url.path.endswith("/instances")
    ]
    # From the first Monday, which it never moves past, to the last date Outlook keeps.
    assert windows == [("2026-10-12T07:00:00Z", "4501-01-01T00:30:00Z")]
