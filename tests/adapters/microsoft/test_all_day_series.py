"""An all-day occurrence is named by the date it falls on in its series' own time zone, so Monday
in Paris stays Monday, though Graph answers its original start in UTC, on Sunday evening
(ADR 0034)."""

from datetime import date, timedelta

from calendar_sync.domain.model import EventId, EventRef, EventStatus
from tests.adapters.microsoft.test_calendar_provider_contract import MAILBOXES, outlook
from tests.fake_microsoft_graph_api import FakeMicrosoftGraph
from tests.helpers import NOW, endpoint

SOURCE = endpoint("personal-account", "personal-calendar")
MAILBOX = MAILBOXES["personal-account"][0]
MONDAY = date(2026, 10, 12)


def _weekly_all_day_in_paris(graph: FakeMicrosoftGraph) -> EventRef:
    series = graph.events.seed(
        MAILBOX,
        "personal-calendar",
        {
            "subject": "Office day",
            "body": {"contentType": "text", "content": ""},
            "isAllDay": True,
            "start": {"dateTime": "2026-10-12T00:00:00", "timeZone": "Romance Standard Time"},
            "end": {"dateTime": "2026-10-13T00:00:00", "timeZone": "Romance Standard Time"},
            "recurrence": {
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
                },
            },
        },
    )
    return EventRef(SOURCE, EventId(series))


def test_an_all_day_occurrence_in_paris_is_named_by_its_monday() -> None:
    provider, graph = outlook()
    series = _weekly_all_day_in_paris(graph)
    second = MONDAY + timedelta(days=7)

    found = provider.get_occurrence(series, second)

    assert found is not None
    assert found.status is EventStatus.CONFIRMED
    assert found.occurrence is not None
    assert found.occurrence.original_start == second


def test_a_listing_reports_no_occurrence_of_an_all_day_series_in_paris_cancelled() -> None:
    provider, graph = outlook()
    series = _weekly_all_day_in_paris(graph)

    assert provider.occurrence_exceptions(series, NOW) == ()
