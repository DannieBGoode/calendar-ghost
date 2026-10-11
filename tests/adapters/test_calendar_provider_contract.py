"""The test fake and the router honor the Calendar Provider contract (ADR 0022)."""

from dataclasses import replace

import pytest

from calendar_sync.application.sync.ports import CalendarProvider
from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.model import CalendarEvent, ConnectedAccountId, EventStatus
from calendar_sync.infrastructure.providers.routing import RoutingCalendarProvider
from tests.contracts.calendar_provider import (
    CalendarProviderContract,
    ProviderHarness,
    daily_starts,
)
from tests.fake_calendar import FakeCalendars


class AllGoogle:
    def provider_of(self, account_id: ConnectedAccountId) -> ProviderKind | None:
        return ProviderKind.GOOGLE


def fake_harness(calendars: FakeCalendars, provider: CalendarProvider) -> ProviderHarness:
    """The fake's backend: a seeded or removed event reaches the calendar's next change feed."""

    def seed(native: CalendarEvent) -> None:
        calendars.put(native)
        calendars.report(native)

    def remove(native: CalendarEvent) -> None:
        del calendars.events[native.reference]
        calendars.report(replace(native, status=EventStatus.CANCELLED))

    return ProviderHarness(
        provider,
        seed,
        remove,
        calendars.expired.add,
        lambda series: calendars.put(series, starts=daily_starts(series)),
    )


class TestFakeCalendars(CalendarProviderContract):
    @pytest.fixture
    def harness(self) -> ProviderHarness:
        calendars = FakeCalendars()
        return fake_harness(calendars, calendars)


class TestRoutingCalendarProvider(CalendarProviderContract):
    @pytest.fixture
    def harness(self) -> ProviderHarness:
        calendars = FakeCalendars()
        router = RoutingCalendarProvider(AllGoogle(), {ProviderKind.GOOGLE: calendars})
        return fake_harness(calendars, router)
