"""Every PATCH is conditional on the version the adapter just read and found without guests
(`If-Match` with its `changeKey`). Someone may invite guests in between, or Outlook may change the
item itself, as it does shortly after creating a series; the PATCH then fails with 412 Precondition
Failed and emails nobody. The adapter reads the item again, with every guest check, and writes that
version once more: an item that now has guests is left alone (ADR 0034).

Graph answers each Outlook item with `@odata.etag`, `W/"<changeKey>"`, and refuses a PATCH whose
`If-Match` names an older version with 412 and `ErrorIrresolvableConflict`. It ignored `If-Match`
on DELETE when tried with a real account on 2026-10-12, so a deletion racing an invitation is not
stopped; ADR 0034 accepts that window.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from calendar_sync.application.sync.errors import ProviderFailure, UnsupportedProjection
from calendar_sync.domain.model import (
    EventId,
    EventProjection,
    EventRef,
    Recurrence,
    SyncReason,
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


def _blocked_for_guests(write: Callable[[], object]) -> None:
    with pytest.raises(UnsupportedProjection) as refused:
        write()
    assert refused.value.reason is SyncReason.PROJECTION_HAS_GUESTS


def _changed_by_outlook_just_before(graph: FakeMicrosoftGraph, event_id: str) -> None:
    """Outlook changes the item itself after the adapter read it, once, as after a create."""
    serve = graph.handle
    changed: list[bool] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "PATCH" and not changed:
            changed.append(True)
            graph.events._touch(graph.events.stored[event_id])
        return serve(request)

    graph.handle = handle  # type: ignore[method-assign]


def test_an_update_after_someone_invited_guests_emails_nobody() -> None:
    provider, graph = outlook()
    destination, source = _created(provider)
    _invited_just_before(graph, "PATCH", destination.event_id.value)
    later = MONDAY + timedelta(hours=2)
    moved = EventProjection(TimedInterval(later, later + timedelta(hours=1)), "Busy")

    _blocked_for_guests(
        lambda: provider.update_projection(destination, source, RULE, moved, "key-2")
    )

    assert graph.events.mail == []
    assert [method for method, _, _ in graph.events.writes] == ["POST"]


def test_an_update_after_outlook_changed_the_event_is_written_to_its_new_version() -> None:
    provider, graph = outlook()
    destination, source = _created(provider)
    _changed_by_outlook_just_before(graph, destination.event_id.value)
    later = MONDAY + timedelta(hours=2)
    moved = EventProjection(TimedInterval(later, later + timedelta(hours=1)), "Busy")

    provider.update_projection(destination, source, RULE, moved, "key-2")

    assert [method for method, _, _ in graph.events.writes] == ["POST", "PATCH"]


def test_a_deletion_racing_an_invitation_is_not_stopped_by_graph() -> None:
    # Graph ignores If-Match on DELETE, so a guest invited in the moment between the guest read
    # and the deletion gets Outlook's cancellation. ADR 0034 accepts this window.
    provider, graph = outlook()
    destination, source = _created(provider)
    _invited_just_before(graph, "DELETE", destination.event_id.value)

    provider.delete_projection(destination, source, RULE, "key-2")

    assert destination.event_id.value not in graph.events.stored


def test_an_occurrence_written_after_someone_invited_guests_to_its_series_emails_nobody() -> None:
    provider, graph = outlook()
    destination, source = _created(provider, WEEKLY)
    _invited_just_before(graph, "PATCH", destination.event_id.value)
    later = MONDAY + timedelta(days=7)
    moved = EventProjection(
        TimedInterval(later + timedelta(hours=2), later + timedelta(hours=3)), "Busy"
    )

    _blocked_for_guests(
        lambda: provider.write_occurrence(destination, later, source, RULE, moved, "key-2")
    )

    assert graph.events.mail == []


def test_an_occurrence_written_after_outlook_changed_its_series_is_written() -> None:
    provider, graph = outlook()
    destination, source = _created(provider, WEEKLY)
    _changed_by_outlook_just_before(graph, destination.event_id.value)
    later = MONDAY + timedelta(days=7)
    moved = EventProjection(
        TimedInterval(later + timedelta(hours=2), later + timedelta(hours=3)), "Busy"
    )

    written = provider.write_occurrence(destination, later, source, RULE, moved, "key-2")

    assert written.time == moved.time


def test_an_occurrence_cancellation_racing_an_invitation_is_not_stopped_by_graph() -> None:
    # As for a deletion: Graph ignores If-Match on DELETE, an accepted window (ADR 0034).
    provider, graph = outlook()
    destination, source = _created(provider, WEEKLY)
    _invited_just_before(graph, "DELETE", destination.event_id.value)
    later = MONDAY + timedelta(days=7)

    provider.cancel_occurrence(destination, later, source, RULE, "key-2")

    assert [method for method, _, _ in graph.events.writes] == ["POST", "DELETE"]
