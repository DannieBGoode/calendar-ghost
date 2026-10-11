"""An answer Graph sends with success but without what it documents, such as a 200 with no JSON
body or a listing without a list in `value`, is no answer: it fails for now and is retried, and
never reads as an empty, complete listing that could prove events gone (ADR 0034)."""

from collections.abc import Callable
from datetime import UTC, datetime

import httpx
import pytest

from calendar_sync.application.sync.errors import ProviderFailure
from calendar_sync.domain.model import EventId, EventRef
from calendar_sync.domain.providers import ProviderFailureKind
from tests.adapters.microsoft.test_calendar_provider_contract import MAILBOXES, outlook
from tests.fake_microsoft_graph_api import FakeMicrosoftGraph
from tests.helpers import NOW, endpoint

SOURCE = endpoint("personal-account", "personal-calendar")
MAILBOX = MAILBOXES["personal-account"][0]
MONDAY = datetime(2026, 10, 12, 7, 0, tzinfo=UTC)


def _answer_once(
    graph: FakeMicrosoftGraph, path_ends: str, answer: Callable[[], httpx.Response]
) -> None:
    """Answer the first Graph request whose path ends so with `answer`, then serve as before."""
    serve = graph.handle
    used: list[bool] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if not used and request.url.path.endswith(path_ends):
            used.append(True)
            graph.requests.append(request)
            return answer()
        return serve(request)

    graph.handle = handle  # type: ignore[method-assign]


def _no_json() -> httpx.Response:
    return httpx.Response(200, content=b"<html>maintenance</html>")


def _no_list() -> httpx.Response:
    return httpx.Response(200, json={"value": "unavailable"})


def _weekly_series(graph: FakeMicrosoftGraph) -> EventRef:
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
                    "type": "noEnd",
                    "startDate": "2026-10-12",
                    "recurrenceTimeZone": "Romance Standard Time",
                },
            },
        },
    )
    return EventRef(SOURCE, EventId(series))


@pytest.mark.parametrize("answer", [_no_json, _no_list], ids=["no JSON", "no list"])
def test_a_listing_answered_without_its_events_fails_for_now(
    answer: Callable[[], httpx.Response],
) -> None:
    provider, graph = outlook()
    graph.events.seed(
        MAILBOX,
        "personal-calendar",
        {
            "subject": "Dentist",
            "isAllDay": False,
            "start": {"dateTime": "2026-10-12T07:00:00", "timeZone": "UTC"},
            "end": {"dateTime": "2026-10-12T08:00:00", "timeZone": "UTC"},
        },
    )
    _answer_once(graph, "/personal-calendar/events", answer)

    with pytest.raises(ProviderFailure) as failed:
        provider.changes(SOURCE, None, NOW)

    assert failed.value.kind is ProviderFailureKind.TEMPORARY


@pytest.mark.parametrize("answer", [_no_json, _no_list], ids=["no JSON", "no list"])
def test_a_change_feed_answered_without_its_changes_fails_for_now(
    answer: Callable[[], httpx.Response],
) -> None:
    provider, graph = outlook()
    _answer_once(graph, "/calendarView/delta", answer)

    with pytest.raises(ProviderFailure) as failed:
        provider.changes(SOURCE, None, NOW)

    assert failed.value.kind is ProviderFailureKind.TEMPORARY


@pytest.mark.parametrize("answer", [_no_json, _no_list], ids=["no JSON", "no list"])
def test_occurrences_answered_without_a_list_never_prove_one_cancelled(
    answer: Callable[[], httpx.Response],
) -> None:
    provider, graph = outlook()
    series = _weekly_series(graph)
    _answer_once(graph, "/instances", answer)

    with pytest.raises(ProviderFailure) as failed:
        provider.get_occurrence(series, MONDAY)

    assert failed.value.kind is ProviderFailureKind.TEMPORARY


def test_an_event_answered_without_a_json_body_fails_for_now() -> None:
    provider, graph = outlook()
    series = _weekly_series(graph)
    _answer_once(graph, f"/events/{series.event_id.value}", _no_json)

    with pytest.raises(ProviderFailure) as failed:
        provider.get_event(series)

    assert failed.value.kind is ProviderFailureKind.TEMPORARY
