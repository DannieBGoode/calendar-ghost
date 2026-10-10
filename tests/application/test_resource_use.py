"""Each run's provider calls count toward its User's resource use, per provider and UTC day."""

from datetime import timedelta

import pytest

from calendar_sync.application.errors import ProviderFailure, ProviderFailureKind
from calendar_sync.application.ports import ProviderCallCounts, ProviderCallTally
from calendar_sync.application.providers import ProviderKind
from calendar_sync.domain.model import ProjectionHandling
from tests.application.test_run_logging import (
    CountedCalls,
    FailingCalendars,
    SteppedClock,
    reconcile_use_case,
    removal,
    use_case,
)
from tests.fake_calendar import FakeCalendars, enabled_rule_factory
from tests.helpers import NOW, event, rule

GOOGLE = ProviderKind.GOOGLE


def _calls(calls: int, rate_limited: int = 0, failed: int = 0) -> CountedCalls:
    counts = ProviderCallCounts(calls, rate_limited, failed)
    return CountedCalls(ProviderCallTally(calls=calls, providers={GOOGLE: counts}))


def test_a_sync_run_adds_its_calls_to_its_users_day() -> None:
    factory = enabled_rule_factory()
    calendars = FakeCalendars()
    calendars.put(event())
    # Late in the evening west of UTC, which is already the next UTC day.
    clock = SteppedClock(NOW.replace(hour=23, minute=30) + timedelta(hours=1))

    use_case(factory, calendars, clock, _calls(4, 1, 1)).execute(rule().id)
    use_case(factory, calendars, clock, _calls(2)).execute(rule().id)

    assert factory.state.provider_calls == {
        (GOOGLE, clock.current.date()): ProviderCallCounts(6, 1, 1)
    }


def test_a_failed_sync_run_counts_the_calls_it_made() -> None:
    factory = enabled_rule_factory()
    calendars = FailingCalendars(ProviderFailure(ProviderFailureKind.TEMPORARY, "busy"))

    with pytest.raises(ProviderFailure):
        use_case(factory, calendars, calls=_calls(3, failed=3)).execute(rule().id)

    assert factory.state.provider_calls == {(GOOGLE, NOW.date()): ProviderCallCounts(3, 0, 3)}


def test_a_run_without_calls_records_nothing() -> None:
    factory = enabled_rule_factory()

    use_case(factory, FakeCalendars()).execute(rule().id)

    assert factory.state.provider_calls == {}


def test_reconciliation_and_removal_count_their_calls_too() -> None:
    factory = enabled_rule_factory()
    calendars = FakeCalendars()
    calendars.put(event())

    reconcile_use_case(factory, calendars, _calls(5)).execute(rule().id)
    removal(factory, calendars, _calls(2)).execute(rule().id, ProjectionHandling.DELETE)

    assert factory.state.provider_calls == {(GOOGLE, NOW.date()): ProviderCallCounts(7)}
