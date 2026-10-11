"""A Managed Projection someone invited people to in Outlook is never written again: updating,
deleting, or cancelling it would email them, and so would clearing its attendees. The write is
refused as a Conflict and the event is left as it is (ADR 0034)."""

from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest

from calendar_sync.application.sync.errors import ProviderFailure, UnsupportedProjection
from calendar_sync.domain.model import (
    EventId,
    EventProjection,
    EventRef,
    Recurrence,
    SyncRuleId,
    TimedInterval,
)
from calendar_sync.domain.providers import ProviderFailureKind
from tests.adapters.microsoft.test_calendar_provider_contract import outlook
from tests.fake_microsoft_graph_api import FakeMicrosoftGraph
from tests.helpers import endpoint

SOURCE = endpoint("personal-account", "personal-calendar")
DESTINATION = endpoint("work-account", "work-calendar")
RULE = SyncRuleId("rule-1")
# A Monday at 09:00 in Madrid, in summer time.
MONDAY = datetime(2026, 10, 12, 7, 0, tzinfo=UTC)
GUESTS = [{"emailAddress": {"address": "guest@example.test"}, "type": "required"}]


def _single(provider: Any) -> tuple[EventRef, EventRef]:
    source = EventRef(SOURCE, EventId("google-dentist"))
    projection = EventProjection(TimedInterval(MONDAY, MONDAY + timedelta(hours=1)), "Busy")
    created = provider.create_projection(DESTINATION, source, RULE, projection, "key-1")
    return created.destination_event.reference, source


def _series(provider: Any) -> tuple[EventRef, EventRef]:
    source = EventRef(SOURCE, EventId("google-series"))
    projection = EventProjection(
        TimedInterval(MONDAY, MONDAY + timedelta(minutes=30), "Europe/Madrid"),
        "Busy",
        recurrence=Recurrence(("RRULE:FREQ=WEEKLY;WKST=SU;BYDAY=MO",)),
    )
    created = provider.create_projection(DESTINATION, source, RULE, projection, "key-1")
    return created.destination_event.reference, source


def _invite(graph: FakeMicrosoftGraph, event: EventRef) -> None:
    """Someone adds guests to the event in Outlook, as only its owner can."""
    graph.events.stored[event.event_id.value].fields["attendees"] = GUESTS


def _writes(graph: FakeMicrosoftGraph) -> list[str]:
    return [method for method, _, _ in graph.events.writes]


def test_a_projection_with_guests_is_never_updated() -> None:
    provider, graph = outlook()
    destination, source = _single(provider)
    _invite(graph, destination)
    later = MONDAY + timedelta(hours=2)

    with pytest.raises(UnsupportedProjection) as refused:
        provider.update_projection(
            destination,
            source,
            RULE,
            EventProjection(TimedInterval(later, later + timedelta(hours=1)), "Busy"),
            "key-2",
        )

    assert _writes(graph) == ["POST"]
    assert graph.events.mail == []
    assert "guest@example.test" not in str(refused.value)


def test_a_projection_with_guests_is_never_deleted() -> None:
    provider, graph = outlook()
    destination, source = _single(provider)
    _invite(graph, destination)

    with pytest.raises(UnsupportedProjection):
        provider.delete_projection(destination, source, RULE, "key-2")

    assert destination.event_id.value in graph.events.stored
    assert _writes(graph) == ["POST"]
    assert graph.events.mail == []


def test_an_occurrence_of_a_series_with_guests_is_never_written_or_cancelled() -> None:
    provider, graph = outlook()
    destination, source = _series(provider)
    _invite(graph, destination)
    later = MONDAY + timedelta(days=7)
    moved = EventProjection(
        TimedInterval(later + timedelta(hours=2), later + timedelta(hours=3)), "Busy"
    )

    with pytest.raises(UnsupportedProjection):
        provider.write_occurrence(destination, later, source, RULE, moved, "key-2")
    with pytest.raises(UnsupportedProjection):
        provider.cancel_occurrence(destination, later, source, RULE, "key-3")

    assert _writes(graph) == ["POST"]
    assert graph.events.mail == []
    assert provider.get_occurrence(destination, later) is not None


def test_an_exception_someone_invited_guests_to_is_left_alone() -> None:
    provider, graph = outlook()
    destination, source = _series(provider)
    # Only the second Monday's occurrence has guests, as an exception of its own.
    series = graph.events.stored[destination.event_id.value]
    series.exceptions[date(2026, 10, 19)] = {"attendees": GUESTS}
    later = MONDAY + timedelta(days=7)

    with pytest.raises(UnsupportedProjection):
        provider.cancel_occurrence(destination, later, source, RULE, "key-2")
    provider.cancel_occurrence(destination, MONDAY, source, RULE, "key-3")

    # The occurrence without guests is cancelled as before; the one with guests stays.
    assert _writes(graph) == ["POST", "DELETE"]
    assert graph.events.mail == []
    assert provider.get_occurrence(destination, later) is not None


def test_a_series_with_an_exception_someone_invited_guests_to_is_never_updated_or_deleted() -> None:
    provider, graph = outlook()
    destination, source = _series(provider)
    # Only the second Monday's occurrence has guests; the series itself has none.
    series = graph.events.stored[destination.event_id.value]
    series.exceptions[date(2026, 10, 19)] = {"attendees": GUESTS}
    later = MONDAY + timedelta(hours=2)
    moved = EventProjection(
        TimedInterval(later, later + timedelta(minutes=30), "Europe/Madrid"),
        "Busy",
        recurrence=Recurrence(("RRULE:FREQ=WEEKLY;WKST=SU;BYDAY=MO",)),
    )

    with pytest.raises(UnsupportedProjection):
        provider.update_projection(destination, source, RULE, moved, "key-2")
    with pytest.raises(UnsupportedProjection):
        provider.delete_projection(destination, source, RULE, "key-3")

    assert destination.event_id.value in graph.events.stored
    assert _writes(graph) == ["POST"]
    assert graph.events.mail == []


def test_a_series_whose_exceptions_outlook_did_not_list_is_not_deleted_now() -> None:
    provider, graph = outlook()
    destination, source = _series(provider)
    serve = graph.handle

    def handle(request: httpx.Request) -> httpx.Response:
        if "exceptionOccurrences" in request.url.params.get("$expand", ""):
            graph.requests.append(request)
            # The exceptions continue on a page of their own, unread.
            return httpx.Response(
                200,
                json={
                    "id": destination.event_id.value,
                    "exceptionOccurrences": [],
                    "exceptionOccurrences@odata.nextLink": "https://graph.microsoft.com/v1.0/more",
                },
            )
        return serve(request)

    graph.handle = handle  # type: ignore[method-assign]

    with pytest.raises(ProviderFailure) as failed:
        provider.delete_projection(destination, source, RULE, "key-2")

    assert failed.value.kind is ProviderFailureKind.TEMPORARY
    assert _writes(graph) == ["POST"]


def test_a_series_whose_exceptions_outlook_listed_without_attendees_is_not_deleted_now() -> None:
    provider, graph = outlook()
    destination, source = _series(provider)
    series = graph.events.stored[destination.event_id.value]
    series.exceptions[date(2026, 10, 19)] = {"attendees": GUESTS}
    serve = graph.handle

    def handle(request: httpx.Request) -> httpx.Response:
        if "exceptionOccurrences" in request.url.params.get("$expand", ""):
            graph.requests.append(request)
            # The exception is listed, but without the attendees asked for.
            occurrence = f"{destination.event_id.value}.occ.2026-10-19"
            return httpx.Response(
                200,
                json={
                    "id": destination.event_id.value,
                    "exceptionOccurrences": [{"id": occurrence}],
                },
            )
        return serve(request)

    graph.handle = handle  # type: ignore[method-assign]

    with pytest.raises(ProviderFailure) as failed:
        provider.delete_projection(destination, source, RULE, "key-2")

    assert failed.value.kind is ProviderFailureKind.TEMPORARY
    assert _writes(graph) == ["POST"]
    assert graph.events.mail == []
