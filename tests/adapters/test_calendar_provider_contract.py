"""The test fake, the router, and Google honor the Calendar Provider contract (ADR 0022)."""

import pytest

from calendar_sync.application.providers import ProviderKind
from calendar_sync.domain.model import CalendarEvent, ConnectedAccountId, TimedInterval
from calendar_sync.infrastructure.google.provider import GoogleCalendarProvider
from calendar_sync.infrastructure.providers.routing import RoutingCalendarProvider
from tests.contracts.calendar_provider import CalendarProviderContract, ProviderHarness
from tests.fake_calendar import FakeCalendars
from tests.fake_google_calendar_api import EventJson, FakeGoogleCalendarApi


class AllGoogle:
    def provider_of(self, account_id: ConnectedAccountId) -> ProviderKind | None:
        return ProviderKind.GOOGLE


class TestFakeCalendars(CalendarProviderContract):
    @pytest.fixture
    def harness(self) -> ProviderHarness:
        calendars = FakeCalendars()
        return ProviderHarness(calendars, calendars.put)


class TestRoutingCalendarProvider(CalendarProviderContract):
    @pytest.fixture
    def harness(self) -> ProviderHarness:
        calendars = FakeCalendars()
        router = RoutingCalendarProvider(AllGoogle(), {ProviderKind.GOOGLE: calendars})
        return ProviderHarness(router, calendars.put)


def google_json(native: CalendarEvent) -> EventJson:
    """The contract's timed Native Event as its owner would have created it in Google."""
    assert isinstance(native.time, TimedInterval)
    return {
        "id": native.reference.event_id.value,
        "summary": native.title,
        "description": native.description,
        "location": native.location,
        "start": {"dateTime": native.time.starts_at.isoformat()},
        "end": {"dateTime": native.time.ends_at.isoformat()},
    }


class TestGoogleCalendarProvider(CalendarProviderContract):
    @pytest.fixture
    def harness(self) -> ProviderHarness:
        api = FakeGoogleCalendarApi()
        return ProviderHarness(
            GoogleCalendarProvider(api.service_for),
            lambda native: api.seed(native.reference.calendar, google_json(native)),
        )
