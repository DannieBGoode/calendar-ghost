"""Every Google call is counted and timed for the run that made it, and logged without content."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from threading import Barrier, Thread
from unittest.mock import MagicMock

import pytest

from calendar_sync.application.errors import ProviderFailure
from calendar_sync.application.ports import ProviderCallCounts, ProviderCallTally
from calendar_sync.application.providers import ProviderKind
from calendar_sync.domain.model import EventId, EventRef
from calendar_sync.infrastructure.google.provider import GoogleCalendarProvider
from calendar_sync.infrastructure.provider_calls import (
    ContextProviderCallStats,
    record_call,
    record_token_refresh,
)
from tests.adapters.google.test_provider import (
    google_event_payload,
    request_raising,
    request_returning,
)
from tests.helpers import endpoint

CALENDAR = endpoint("account-family", "family.secret@example.com")
EVENT = EventRef(CALENDAR, EventId("dentist-appointment"))


def timer(*durations: float) -> Iterator[float]:
    """Readings a monotonic timer gives for calls lasting `durations` seconds, one after another."""
    now = 1000.0
    for seconds in durations:
        yield now
        now += seconds
        yield now


def provider(events_api: MagicMock, *durations: float) -> GoogleCalendarProvider:
    service = MagicMock()
    service.events.return_value = events_api
    readings = timer(*durations)
    return GoogleCalendarProvider(lambda _account: service, timer=lambda: next(readings))


def test_a_measured_run_tallies_its_calls_and_how_they_went() -> None:
    events_api = MagicMock()
    events_api.get.side_effect = [
        request_returning(google_event_payload()),
        request_raising(404),
        request_raising(429),
        request_raising(403, reason="rateLimitExceeded"),
        request_raising(403),
        request_raising(503),
    ]
    google = provider(events_api, 0.2, 1.3, 0.1, 0.1, 0.1, 0.4)

    with ContextProviderCallStats().measure() as tally:
        google.get_event(EVENT)
        assert google.get_event(EVENT) is None
        for _ in range(4):
            with pytest.raises(ProviderFailure):
                google.get_event(EVENT)

    assert tally.calls == 6
    assert tally.seconds == pytest.approx(2.2)
    assert tally.slowest_seconds == pytest.approx(1.3)
    assert tally.rate_limited == 2
    assert tally.server_errors == 1
    # Not found is an answer; a refusal other than the rate limit, and a server error, failed.
    assert tally.providers == {
        ProviderKind.GOOGLE: ProviderCallCounts(calls=6, rate_limited=2, failed=2)
    }


def test_a_call_that_got_no_answer_failed() -> None:
    with ContextProviderCallStats().measure() as tally:
        record_call(ProviderKind.GOOGLE, "events.get", None, 0.1, rate_limited=False)
        record_call(ProviderKind.GOOGLE, "events.get", 410, 0.1, rate_limited=False)

    assert tally.providers == {ProviderKind.GOOGLE: ProviderCallCounts(calls=2, failed=1)}


def test_calls_outside_a_measured_run_are_not_tallied() -> None:
    stats = ContextProviderCallStats()
    record_call(ProviderKind.GOOGLE, "events.get", 200, 0.1, rate_limited=False)
    record_token_refresh()

    with stats.measure() as tally:
        record_token_refresh()
        record_call(ProviderKind.GOOGLE, "events.get", 200, 0.1, rate_limited=False)

    record_call(ProviderKind.GOOGLE, "events.get", 200, 0.1, rate_limited=False)
    assert tally == ProviderCallTally(
        1, 0.1, 0.1, 0, 0, 1, providers={ProviderKind.GOOGLE: ProviderCallCounts(calls=1)}
    )


def test_token_refreshes_count_toward_the_run_that_needed_them() -> None:
    with ContextProviderCallStats().measure() as tally:
        record_token_refresh()
        record_token_refresh()

    assert tally.token_refreshes == 2


def test_runs_on_different_threads_keep_separate_tallies() -> None:
    stats = ContextProviderCallStats()
    both_measuring = Barrier(2)
    tallies: dict[str, ProviderCallTally] = {}

    def run(name: str, calls: int) -> None:
        with stats.measure() as tally:
            both_measuring.wait()
            for _ in range(calls):
                record_call(ProviderKind.GOOGLE, "events.get", 200, 0.01, rate_limited=False)
            record_token_refresh()
            both_measuring.wait()
        tallies[name] = tally

    threads = [Thread(target=run, args=("one", 3)), Thread(target=run, args=("two", 5))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert (tallies["one"].calls, tallies["one"].token_refreshes) == (3, 1)
    assert (tallies["two"].calls, tallies["two"].token_refreshes) == (5, 1)


def test_every_call_is_logged_at_debug_by_operation_status_and_duration(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="calendar_sync")
    events_api = MagicMock()
    events_api.get.side_effect = [request_returning(google_event_payload()), request_raising(404)]
    events_api.list.return_value = request_returning({"items": [], "nextSyncToken": "token-9"})
    google = provider(events_api, 0.25, 0.05, 0.5)

    google.get_event(EVENT)
    google.get_event(EVENT)
    google.changes(CALENDAR, "sync-token-secret", datetime(2026, 7, 31, tzinfo=UTC))

    assert [(record.levelno, record.getMessage()) for record in caplog.records] == [
        (logging.DEBUG, "provider call provider=google op=events.get status=200 took=250ms"),
        (logging.DEBUG, "provider call provider=google op=events.get status=404 took=50ms"),
        (logging.DEBUG, "provider call provider=google op=events.list status=200 took=500ms"),
    ]
    for content in (
        "family.secret@example.com",
        "dentist-appointment",
        "account-family",
        "sync-token-secret",
        "Private appointment",
    ):
        assert content not in caplog.text


def test_a_slow_call_is_a_warning(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="calendar_sync")
    events_api = MagicMock()
    events_api.instances.return_value = request_returning({"items": []})
    google = provider(events_api, 12.4)

    google.get_occurrence(EVENT, datetime(2026, 9, 1, 8, tzinfo=UTC))

    [warning] = caplog.records
    assert warning.levelno == logging.WARNING
    assert (
        warning.getMessage()
        == "slow provider call provider=google op=events.instances status=200 took=12.4s"
    )


def test_a_call_without_an_answer_is_logged_without_a_status(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="calendar_sync")
    request = MagicMock()
    request.execute.side_effect = OSError("connection reset")
    events_api = MagicMock()
    events_api.get.return_value = request
    google = provider(events_api, 0.003)

    with ContextProviderCallStats().measure() as tally, pytest.raises(ProviderFailure):
        google.get_event(EVENT)

    assert caplog.messages == ["provider call provider=google op=events.get status=none took=3ms"]
    assert (tally.calls, tally.server_errors, tally.rate_limited) == (1, 0, 0)
