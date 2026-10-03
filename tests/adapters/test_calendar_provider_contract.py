"""The test fake and the router honor the Calendar Provider contract (ADR 0022)."""

import pytest

from calendar_sync.application.providers import ProviderKind
from calendar_sync.domain.model import ConnectedAccountId
from calendar_sync.infrastructure.providers.routing import RoutingCalendarProvider
from tests.contracts.calendar_provider import CalendarProviderContract, ProviderHarness
from tests.fake_calendar import FakeCalendars


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
