"""Manual runs counted in memory per User, over a sliding window (ADR 0038)."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Barrier

from calendar_sync.application.sync.manual_runs import RunThrottle
from calendar_sync.domain.access import UserId
from calendar_sync.infrastructure.throttle import MemoryRunThrottle

NOW = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)
ALICE = UserId("alice")
BOB = UserId("bob")


@dataclass
class MovableClock:
    moment: datetime

    def now(self) -> datetime:
        return self.moment


def test_twelve_runs_are_admitted_and_the_thirteenth_waits_for_the_oldest_to_leave_the_window() -> (
    None
):
    clock = MovableClock(NOW)
    throttle: RunThrottle = MemoryRunThrottle(clock)
    for minute in range(12):
        clock.moment = NOW + timedelta(minutes=minute)
        assert throttle.admit(ALICE) == 0.0

    clock.moment = NOW + timedelta(minutes=12)

    assert throttle.admit(ALICE) == timedelta(minutes=48).total_seconds()


def test_each_user_has_their_own_count() -> None:
    throttle = MemoryRunThrottle(MovableClock(NOW), limit=2)

    assert [throttle.admit(ALICE) for _ in range(3)] == [0.0, 0.0, 3600.0]
    assert throttle.admit(BOB) == 0.0


def test_a_refused_run_is_not_recorded() -> None:
    clock = MovableClock(NOW)
    throttle = MemoryRunThrottle(clock, limit=2, window=timedelta(minutes=10))
    throttle.admit(ALICE)
    clock.moment = NOW + timedelta(minutes=1)
    throttle.admit(ALICE)
    clock.moment = NOW + timedelta(minutes=2)

    waits = {throttle.admit(ALICE) for _ in range(100)}

    assert waits == {timedelta(minutes=8).total_seconds()}
    clock.moment = NOW + timedelta(minutes=10)
    assert throttle.admit(ALICE) == 0.0


def test_the_window_slides() -> None:
    clock = MovableClock(NOW)
    throttle = MemoryRunThrottle(clock, limit=2, window=timedelta(minutes=10))
    throttle.admit(ALICE)
    clock.moment = NOW + timedelta(minutes=4)
    throttle.admit(ALICE)

    clock.moment = NOW + timedelta(minutes=10)

    assert throttle.admit(ALICE) == 0.0
    # The run at minute 4 is now the oldest, so the next run waits until minute 14.
    assert throttle.admit(ALICE) == timedelta(minutes=4).total_seconds()


def test_a_clock_set_back_never_asks_for_more_than_the_window() -> None:
    clock = MovableClock(NOW)
    throttle = MemoryRunThrottle(clock, limit=1)
    throttle.admit(ALICE)

    clock.moment = NOW - timedelta(days=1)

    assert throttle.admit(ALICE) == timedelta(hours=1).total_seconds()


def test_threads_racing_for_the_last_places_admit_exactly_the_limit() -> None:
    throttle = MemoryRunThrottle(MovableClock(NOW), limit=12)
    for _ in range(11):
        throttle.admit(ALICE)
    start = Barrier(24, timeout=5)

    def race(_: int) -> float:
        start.wait()
        return throttle.admit(ALICE)

    with ThreadPoolExecutor(max_workers=24) as pool:
        waits = list(pool.map(race, range(24)))

    assert waits.count(0.0) == 1
