"""A projection is created once per Operation Key (ADR 0034).

Looking a projection up by its key reads every page Graph answers. Graph may answer a page with
fewer items than `$top` and an `@odata.nextLink`, so a first page without a match proves nothing
("Paging Microsoft Graph data in your app", https://learn.microsoft.com/en-us/graph/paging).

Every create also sends a `transactionId` derived from the key, so Graph answers a retried POST
with the event it already stored, even before the key's filter can see it.
"""

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from calendar_sync.application.sync.errors import ProjectionOwnershipMismatch, ProviderFailure
from calendar_sync.domain.model import (
    EventId,
    EventProjection,
    EventRef,
    SyncRuleId,
    TimedInterval,
)
from calendar_sync.infrastructure.microsoft.translation import OPERATION_PROPERTY, RULE_PROPERTY
from tests.adapters.microsoft.test_calendar_provider_contract import MAILBOXES, outlook
from tests.fake_microsoft_graph_api import FakeMicrosoftGraph
from tests.helpers import endpoint

SOURCE = endpoint("personal-account", "personal-calendar")
DESTINATION = endpoint("work-account", "work-calendar")
RULE = SyncRuleId("rule-1")
MONDAY = datetime(2026, 10, 12, 7, 0, tzinfo=UTC)
PROJECTION = EventProjection(TimedInterval(MONDAY, MONDAY + timedelta(hours=1)), "Busy")


def _empty_first_page(graph: FakeMicrosoftGraph) -> None:
    """Answer the next Operation Key lookup with an empty page that links to the real one."""
    serve = graph.handle
    used: list[bool] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if not used and "$filter" in request.url.params and request.method == "GET":
            used.append(True)
            graph.requests.append(request)
            following = request.url.copy_add_param("$skiptoken", "page-2")
            return httpx.Response(200, json={"value": [], "@odata.nextLink": str(following)})
        return serve(request)

    graph.handle = handle  # type: ignore[method-assign]


def test_a_projection_on_a_later_page_is_found_and_never_created_twice() -> None:
    provider, graph = outlook()
    source = EventRef(SOURCE, EventId("google-dentist"))
    first = provider.create_projection(DESTINATION, source, RULE, PROJECTION, "key-1")
    _empty_first_page(graph)

    again = provider.create_projection(DESTINATION, source, RULE, PROJECTION, "key-1")

    assert again.destination_event.reference == first.destination_event.reference
    assert [method for method, _, _ in graph.events.writes] == ["POST"]


def test_a_create_that_timed_out_after_graph_stored_it_is_not_made_twice() -> None:
    provider, graph = outlook()
    source = EventRef(SOURCE, EventId("google-dentist"))
    serve = graph.handle
    seen: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and "POST" not in seen:
            seen.append("POST")
            serve(request)
            # Graph stored the event, but its answer never arrived.
            raise httpx.ReadTimeout("synthetic timeout", request=request)
        if "$filter" in request.url.params and seen == ["POST"]:
            seen.append("filter")
            graph.requests.append(request)
            # The key's filter does not list the new event yet.
            return httpx.Response(200, json={"value": []})
        return serve(request)

    graph.handle = handle  # type: ignore[method-assign]

    with pytest.raises(ProviderFailure):
        provider.create_projection(DESTINATION, source, RULE, PROJECTION, "key-1")
    retried = provider.create_projection(DESTINATION, source, RULE, PROJECTION, "key-1")

    (stored,) = graph.events.in_calendar(*MAILBOXES["work-account"])
    assert retried.destination_event.reference.event_id.value == stored.id
    posted = [body for method, _, body in graph.events.writes if method == "POST"]
    assert [body.get("transactionId") for body in posted] == [posted[0]["transactionId"]]
    assert posted[0]["transactionId"]


def test_an_event_a_retried_create_answers_with_is_adopted_only_if_it_is_still_owned() -> None:
    provider, graph = outlook()
    source = EventRef(SOURCE, EventId("google-dentist"))
    first = provider.create_projection(DESTINATION, source, RULE, PROJECTION, "key-1")
    stored = graph.events.stored[first.destination_event.reference.event_id.value]
    # Since then, the event lost its Operation Key and was claimed by another rule, so the key's
    # filter misses it; Graph still answers the repeated transactionId with it.
    stored.fields["singleValueExtendedProperties"] = [
        {"id": RULE_PROPERTY, "value": "foreign-rule"} if each["id"] == RULE_PROPERTY else each
        for each in stored.fields["singleValueExtendedProperties"]
        if each["id"] != OPERATION_PROPERTY
    ]

    with pytest.raises(ProjectionOwnershipMismatch):
        provider.create_projection(DESTINATION, source, RULE, PROJECTION, "key-1")
