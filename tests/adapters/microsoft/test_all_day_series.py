"""An all-day occurrence is named by the date it falls on in its series' own time zone, so Monday
in Paris stays Monday, though Graph answers its original start in UTC, on Sunday evening. A series
in a zone this release cannot name has occurrences it cannot name either, so none of them is ever
inferred cancelled (ADR 0034)."""

from datetime import date, timedelta

import pytest

from calendar_sync.application.sync.errors import ProviderFailure
from calendar_sync.domain.model import EventId, EventRef, EventStatus, TransformationPolicy
from calendar_sync.domain.providers import ProviderFailureKind
from tests.adapters.microsoft.test_calendar_provider_contract import MAILBOXES, outlook
from tests.fake_microsoft_graph_api import FakeMicrosoftGraph
from tests.helpers import NOW, endpoint

SOURCE = endpoint("personal-account", "personal-calendar")
MAILBOX = MAILBOXES["personal-account"][0]
MONDAY = date(2026, 10, 12)


def _weekly_all_day_in_paris(
    graph: FakeMicrosoftGraph, zone: str = "Romance Standard Time", created_in: str | None = None
) -> EventRef:
    series = graph.events.seed(
        MAILBOX,
        "personal-calendar",
        {
            "subject": "Office day",
            "body": {"contentType": "text", "content": ""},
            "isAllDay": True,
            "start": {"dateTime": "2026-10-12T00:00:00", "timeZone": created_in or zone},
            "end": {"dateTime": "2026-10-13T00:00:00", "timeZone": created_in or zone},
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
                    "recurrenceTimeZone": zone,
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


def test_no_occurrence_of_an_all_day_series_in_a_custom_zone_is_inferred_cancelled() -> None:
    provider, graph = outlook()
    # Monday there begins on Sunday at 22:00 UTC.
    series = _weekly_all_day_in_paris(graph, "Customized Time Zone")
    second = MONDAY + timedelta(days=7)

    with pytest.raises(ProviderFailure) as failed:
        provider.get_occurrence(series, second)

    assert failed.value.kind is ProviderFailureKind.TEMPORARY
    assert provider.occurrence_exceptions(series, NOW) == ()
    assert provider.has_live_occurrences(series, TransformationPolicy())


def test_an_occurrence_of_a_series_in_a_custom_zone_is_never_named_by_its_creation_zone() -> None:
    provider, graph = outlook()
    # Created in UTC, but repeating in a zone two hours ahead: Monday's original start is Sunday
    # at 22:00 UTC, and its `originalStartTimeZone` says UTC.
    series = _weekly_all_day_in_paris(graph, "Customized Time Zone", created_in="UTC")
    sunday = MONDAY + timedelta(days=6)

    with pytest.raises(ProviderFailure):
        provider.get_occurrence(series, sunday)
    assert provider.list_occurrences(series, {sunday}) == {}
