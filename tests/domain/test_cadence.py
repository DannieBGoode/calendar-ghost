"""A Sync Cadence says how soon a User's rules run; with Plans off, everyone's is the default.
Scheduled Sync lists a rule polled more slowly than its passes once per window of its interval."""

import hashlib
from collections import Counter
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from zoneinfo import ZoneInfo

import pytest

from calendar_sync.domain.cadence import (
    DEFAULT_CADENCE,
    SCHEDULED_EVERY,
    SyncCadence,
    scheduled_run_due,
)
from calendar_sync.domain.errors import DomainValidationError
from tests.helpers import NOW

SLOW_INTERVALS = [timedelta(minutes=minutes) for minutes in (10, 15, 30, 60)]
HOUR = timedelta(hours=1)
MIDNIGHT = datetime(2026, 8, 31, tzinfo=UTC)


def _listings(poll_every: timedelta, rule_id: str, passes: list[datetime]) -> list[datetime]:
    """The passes that list a rule never listed before the first of them, when nothing else
    makes it due."""
    listings: list[datetime] = []
    for begins in passes:
        listed = listings[-1] if listings else None
        if scheduled_run_due(
            poll_every, rule_id, begins, listed, always_due=False, full_pass_due=False
        ):
            listings.append(begins)
    return listings


def _window(poll_every: timedelta, rule_id: str, at: datetime) -> int:
    """Which window of its interval `at` falls in for a rule: windows follow one another from the
    Unix epoch, each shifted by the rule's phase, a SHA-256 of its id."""
    seconds = int(poll_every.total_seconds())
    phase = int.from_bytes(hashlib.sha256(rule_id.encode()).digest()[:8], "big") % seconds
    return (int(at.timestamp()) - phase) // seconds


def test_the_default_cadence_syncs_instantly_and_polls_every_five_minutes() -> None:
    assert (DEFAULT_CADENCE.instant, DEFAULT_CADENCE.poll_every) == (True, SCHEDULED_EVERY)
    assert timedelta(minutes=5) == SCHEDULED_EVERY


@pytest.mark.parametrize("poll_every", [timedelta(0), timedelta(minutes=-5)])
def test_a_cadence_must_poll_after_some_time(poll_every: timedelta) -> None:
    with pytest.raises(DomainValidationError):
        SyncCadence(instant=False, poll_every=poll_every)


def test_a_five_minute_or_instant_rule_is_due_at_every_pass() -> None:
    listed = NOW - timedelta(minutes=1)

    assert scheduled_run_due(
        DEFAULT_CADENCE.poll_every, "rule-1", NOW, listed, always_due=False, full_pass_due=False
    )


def test_a_rule_always_due_is_due_whatever_its_window() -> None:
    listed = NOW - timedelta(minutes=1)

    assert scheduled_run_due(HOUR, "rule-1", NOW, listed, always_due=True, full_pass_due=False)


@pytest.mark.parametrize("poll_every", SLOW_INTERVALS, ids=lambda every: f"{every}")
def test_a_rule_listed_after_the_pass_begins_is_due_once_the_clock_is_set_back(
    poll_every: timedelta,
) -> None:
    """A clock set back six hours leaves a mark from a later window: the rule is due at once,
    not once the clock catches up."""
    listed = NOW + timedelta(hours=6)

    assert scheduled_run_due(
        poll_every, "rule-1", NOW, listed, always_due=False, full_pass_due=False
    )


@pytest.mark.parametrize("poll_every", SLOW_INTERVALS, ids=lambda every: f"{every}")
def test_a_slow_rule_is_listed_once_per_window_of_its_interval(poll_every: timedelta) -> None:
    span = timedelta(hours=6)
    passes = [NOW + timedelta(minutes=minute) for minute in range(span // timedelta(minutes=1) + 1)]

    for rule in range(10):
        listings = _listings(poll_every, f"rule-{rule}", passes)

        assert listings[0] == NOW
        after_the_first = listings[1:]
        assert len(after_the_first) == span // poll_every
        assert all(later - earlier == poll_every for earlier, later in pairwise(after_the_first))


@pytest.mark.parametrize("poll_every", SLOW_INTERVALS, ids=lambda every: f"{every}")
def test_irregular_pass_begins_list_a_rule_once_per_window(poll_every: timedelta) -> None:
    apart = timedelta(minutes=5, seconds=40)
    before_gap = [NOW + apart * number for number in range(40)]
    after_gap = [before_gap[-1] + timedelta(minutes=70) + apart * number for number in range(40)]
    passes = before_gap + after_gap

    for rule in (f"rule-{number}" for number in range(20)):
        listings = _listings(poll_every, rule, passes)

        listed_windows = [_window(poll_every, rule, listing) for listing in listings]
        assert len(listed_windows) == len(set(listed_windows))
        assert set(listed_windows) == {_window(poll_every, rule, begins) for begins in passes}
        assert after_gap[0] in listings


@pytest.mark.parametrize("full_pass_due", [False, True])
@pytest.mark.parametrize(
    "poll_every", [SCHEDULED_EVERY, *SLOW_INTERVALS], ids=lambda every: f"{every}"
)
def test_windows_follow_the_instant_not_its_time_zone(
    poll_every: timedelta, full_pass_due: bool
) -> None:
    honolulu = ZoneInfo("Pacific/Honolulu")
    passes = [MIDNIGHT - timedelta(hours=2) + timedelta(minutes=7) * step for step in range(40)]
    since = [timedelta(minutes=minutes) for minutes in (1, 7, 16, 31, 61)]

    for rule in (f"rule-{number}" for number in range(5)):
        for begins in passes:
            for ago in since:
                in_utc = scheduled_run_due(
                    poll_every,
                    rule,
                    begins,
                    begins - ago,
                    always_due=False,
                    full_pass_due=full_pass_due,
                )
                in_honolulu = scheduled_run_due(
                    poll_every,
                    rule,
                    begins.astimezone(honolulu),
                    (begins - ago).astimezone(honolulu),
                    always_due=False,
                    full_pass_due=full_pass_due,
                )
                assert in_utc == in_honolulu


def test_three_thousand_hourly_rules_spread_over_the_hour() -> None:
    rules = [f"rule-{number}" for number in range(3000)]
    # Every rule ran at one pass, as when their Plan changed to hourly just before it.
    listed = dict.fromkeys(rules, NOW - SCHEDULED_EVERY)
    listed_per_pass: list[int] = []

    for step in range(12):
        begins = NOW + SCHEDULED_EVERY * step
        due = [
            rule
            for rule in rules
            if scheduled_run_due(
                HOUR, rule, begins, listed[rule], always_due=False, full_pass_due=False
            )
        ]
        listed.update(dict.fromkeys(due, begins))
        listed_per_pass.append(len(due))

    assert all(listed[rule] >= NOW for rule in rules)
    assert sum(listed_per_pass) == len(rules)
    assert max(listed_per_pass) <= 400


def test_a_full_pass_due_waits_for_the_rules_phase_after_midnight() -> None:
    first_due: Counter[int] = Counter()
    late_in_the_day = MIDNIGHT + timedelta(hours=14)

    for rule in (f"rule-{number}" for number in range(3000)):
        due = [
            scheduled_run_due(
                HOUR,
                rule,
                MIDNIGHT + timedelta(minutes=minute),
                MIDNIGHT + timedelta(minutes=minute - 1),
                always_due=False,
                full_pass_due=True,
            )
            for minute in range(1, 61)
        ]

        # Not due before its phase; from its phase on, due at every pass until its full pass runs.
        assert True in due
        waits = due.index(True)
        assert not any(due[:waits])
        assert all(due[waits:])
        # Still due hours later, so a restart or Sync Now after 01:00 cannot starve it.
        assert scheduled_run_due(
            HOUR,
            rule,
            late_in_the_day,
            late_in_the_day - timedelta(minutes=1),
            always_due=False,
            full_pass_due=True,
        )
        first_due[waits + 1] += 1

    assert max(first_due.values()) <= 100
