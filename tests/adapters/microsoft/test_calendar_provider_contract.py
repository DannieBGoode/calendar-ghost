"""The Outlook adapter honors the Calendar Provider contract, through the fake Graph API."""

from dataclasses import dataclass

import pytest

from calendar_sync.domain.model import CalendarEvent, ConnectedAccountId, TimedInterval
from calendar_sync.infrastructure.microsoft.graph import GraphHttp
from calendar_sync.infrastructure.microsoft.provider import OutlookCalendarProvider
from calendar_sync.infrastructure.scheduling import SystemClock
from tests.contracts.calendar_provider import CalendarProviderContract, ProviderHarness
from tests.fake_microsoft_graph_api import FakeCalendar, FakeMicrosoftGraph

# The contract's accounts, as mailboxes with the calendars it names.
MAILBOXES = {
    "personal-account": ("personal@example.test", "personal-calendar"),
    "work-account": ("work@example.test", "work-calendar"),
}


@dataclass
class IssuedTokens:
    """Access tokens the fake issued for each account, as stored credentials would hold them."""

    tokens: dict[str, str]

    def access_token(self, account_id: ConnectedAccountId) -> str:
        return self.tokens[account_id.value]


def outlook(
    graph: FakeMicrosoftGraph | None = None,
) -> tuple[OutlookCalendarProvider, FakeMicrosoftGraph]:
    graph = graph or FakeMicrosoftGraph()
    tokens = {}
    for account, (address, calendar) in MAILBOXES.items():
        graph.mailbox(address, calendars=[FakeCalendar(calendar, calendar.title(), default=True)])
        tokens[account] = graph.issue(address)["access_token"]
    provider = OutlookCalendarProvider(
        IssuedTokens(tokens), GraphHttp(graph.client()), SystemClock()
    )
    return provider, graph


def graph_json(native: CalendarEvent) -> dict[str, object]:
    """The contract's timed Native Event as its owner would have created it in Outlook."""
    assert isinstance(native.time, TimedInterval)
    return {
        "id": native.reference.event_id.value,
        "subject": native.title,
        "body": {"contentType": "text", "content": native.description},
        "location": {"displayName": native.location},
        "isAllDay": False,
        "start": {
            "dateTime": native.time.starts_at.strftime("%Y-%m-%dT%H:%M:%S"),
            "timeZone": "UTC",
        },
        "end": {"dateTime": native.time.ends_at.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "UTC"},
    }


def seed_into(graph: FakeMicrosoftGraph, native: CalendarEvent) -> str:
    address, calendar = MAILBOXES[native.reference.calendar.connected_account_id.value]
    return graph.events.seed(address, calendar, graph_json(native))


class TestOutlookCalendarProvider(CalendarProviderContract):
    @pytest.fixture
    def harness(self) -> ProviderHarness:
        provider, graph = outlook()
        return ProviderHarness(provider, lambda native: seed_into(graph, native))
