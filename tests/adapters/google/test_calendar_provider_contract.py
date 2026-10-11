"""The Google adapter honors the Calendar Provider contract, through the fake Google API."""

import pytest

from calendar_sync.domain.model import CalendarEvent, TimedInterval
from calendar_sync.infrastructure.google.provider import GoogleCalendarProvider
from tests.contracts.calendar_provider import CalendarProviderContract, ProviderHarness
from tests.fake_google_calendar_api import EventJson, FakeGoogleCalendarApi


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
            lambda native: api.remove(native.reference.calendar, native.reference.event_id.value),
            lambda _calendar: setattr(api, "refused_tokens", True),
            # Google expands a series from its recurrence; nothing to tell it.
            lambda _series: None,
            # A sync token orders changes by version, not time, so nothing needs to age.
            lambda _native: None,
        )
