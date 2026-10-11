"""Every PATCH and DELETE is conditional on the version the adapter just read and found without
guests (`If-Match` with its `changeKey`). Someone may invite guests in between; the write then
fails with 412 Precondition Failed and emails nobody, and the next run reads the guests and leaves
the event (ADR 0034).

Graph answers each Outlook item with `@odata.etag`, `W/"<changeKey>"`, and refuses a write whose
`If-Match` names an older version with 412 and `ErrorIrresolvableConflict`, Exchange's "the change
key passed in the request does not match the current change key for the item". ADR 0034 lists
confirming this with real accounts.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from calendar_sync.application.sync.errors import ProviderFailure
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
MONDAY = datetime(2026, 10, 12, 7, 0, tzinfo=UTC)
GUESTS = [{"emailAddress": {"address": "guest@example.test"}, "type": "required"}]
WEEKLY = Recurrence(("RRULE:FREQ=WEEKLY;WKST=SU;BYDAY=MO",))


def _invited_just_before(graph: FakeMicrosoftGraph, method: str, event_id: str) -> None:
    """Someone invites guests to the event after the adapter read it, just before it writes."""
    serve = graph.handle

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == method and not graph.events.mail:
            graph.events.invite(event_id, GUESTS)
        return serve(request)

    graph.handle = handle  # type: ignore[method-assign]


def _created(provider: object, recurrence: Recurrence | None = None) -> tuple[EventRef, EventRef]:
    source = EventRef(SOURCE, EventId("google-dentist"))
    projection = EventProjection(
        TimedInterval(MONDAY, MONDAY + timedelta(hours=1), "Europe/Madrid"),
        "Busy",
        recurrence=recurrence,
    )
    created = provider.create_projection(  # type: ignore[attr-defined]
        DESTINATION, source, RULE, projection, "key-1"
    )
    return created.destination_event.reference, source


def _refused_for_now(write: Callable[[], object]) -> None:
    with pytest.raises(ProviderFailure) as failed:
        write()
    assert failed.value.kind is ProviderFailureKind.TEMPORARY


def test_an_update_after_someone_invited_guests_emails_nobody() -> None:
    provider, graph = outlook()
    destination, source = _created(provider)
    _invited_just_before(graph, "PATCH", destination.event_id.value)
    later = MONDAY + timedelta(hours=2)
    moved = EventProjection(TimedInterval(later, later + timedelta(hours=1)), "Busy")

    _refused_for_now(lambda: provider.update_projection(destination, source, RULE, moved, "key-2"))

    assert graph.events.mail == []
    assert [method for method, _, _ in graph.events.writes] == ["POST"]


def test_a_deletion_after_someone_invited_guests_emails_nobody() -> None:
    provider, graph = outlook()
    destination, source = _created(provider)
    _invited_just_before(graph, "DELETE", destination.event_id.value)

    _refused_for_now(lambda: provider.delete_projection(destination, source, RULE, "key-2"))

    assert graph.events.mail == []
    assert destination.event_id.value in graph.events.stored


def test_an_occurrence_written_after_someone_invited_guests_to_its_series_emails_nobody() -> None:
    provider, graph = outlook()
    destination, source = _created(provider, WEEKLY)
    _invited_just_before(graph, "PATCH", destination.event_id.value)
    later = MONDAY + timedelta(days=7)
    moved = EventProjection(
        TimedInterval(later + timedelta(hours=2), later + timedelta(hours=3)), "Busy"
    )

    _refused_for_now(
        lambda: provider.write_occurrence(destination, later, source, RULE, moved, "key-2")
    )

    assert graph.events.mail == []


def test_an_occurrence_cancelled_after_someone_invited_guests_to_its_series_emails_nobody() -> None:
    provider, graph = outlook()
    destination, source = _created(provider, WEEKLY)
    _invited_just_before(graph, "DELETE", destination.event_id.value)
    later = MONDAY + timedelta(days=7)

    _refused_for_now(lambda: provider.cancel_occurrence(destination, later, source, RULE, "key-2"))

    assert graph.events.mail == []
    assert provider.get_occurrence(destination, later) is not None
