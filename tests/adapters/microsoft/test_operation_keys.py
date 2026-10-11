"""Looking a projection up by its Operation Key reads every page Graph answers. Graph may answer
a page with fewer items than `$top` and an `@odata.nextLink`, so a first page without a match
proves nothing ("Paging Microsoft Graph data in your app",
https://learn.microsoft.com/en-us/graph/paging): a projection on a later page is found, never
created twice (ADR 0034)."""

from datetime import UTC, datetime, timedelta

import httpx

from calendar_sync.domain.model import (
    EventId,
    EventProjection,
    EventRef,
    SyncRuleId,
    TimedInterval,
)
from tests.adapters.microsoft.test_calendar_provider_contract import outlook
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
