"""Instant Sync's loops beside the scheduler: the dispatcher that starts instant runs, the keeper
that runs watch upkeep, and how the service composes, starts, and stops them (ADR 0036)."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable, Collection
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient

from calendar_sync.application.operations.instant_sync import InstantRun
from calendar_sync.application.operations.scheduled_pass import ScheduledPass, ScheduledRun
from calendar_sync.application.sync.ports import ScheduledRule
from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import build_container, instant_sync_address
from calendar_sync.domain.access import UserId
from calendar_sync.domain.model import SyncRuleId
from calendar_sync.infrastructure.clock import SystemClock
from calendar_sync.infrastructure.scheduling import (
    InstantSyncDispatcher,
    SyncScheduler,
    WatchKeeper,
)
from calendar_sync.infrastructure.security import CredentialCipher
from calendar_sync.interfaces.api.app import create_app
from tests.helpers import rule
from tests.users import USER

ADDRESS = "https://ghost.example.test"


def _instant(rule_id: str) -> InstantRun:
    scheduled = ScheduledRule(USER, replace(rule(), id=SyncRuleId(rule_id)), None)
    return InstantRun(ScheduledRun(scheduled, full=False), seq=1)


async def _until(condition: Callable[[], bool], timeout: float = 5.0) -> None:
    async with asyncio.timeout(timeout):
        while not condition():
            await asyncio.sleep(0.005)


async def _running(dispatcher: InstantSyncDispatcher, condition: Callable[[], bool]) -> None:
    """Run the dispatcher until `condition` holds, then stop it as the service does."""
    task = asyncio.create_task(dispatcher.run_forever())
    try:
        await _until(condition)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


class Offering:
    """Offers each of its rules whenever it is not reserved, as rules whose notices keep coming,
    and records how many run at once."""

    def __init__(self, *rules: str, hold: float = 0.01, failing: bool = False) -> None:
        self.rules, self.hold, self.failing = rules, hold, failing
        self.running: dict[str, int] = {}
        self.most_of_one = 0
        self.most_at_once = 0
        self.runs = 0
        self.lock = threading.Lock()

    def due(self, reserved: Collection[str]) -> tuple[tuple[InstantRun, ...], datetime | None]:
        return tuple(_instant(each) for each in self.rules if each not in reserved), None

    def run(self, item: InstantRun) -> None:
        key = item.scheduled.scheduled.rule.id.value
        with self.lock:
            self.running[key] = self.running.get(key, 0) + 1
            self.most_of_one = max(self.most_of_one, self.running[key])
            self.most_at_once = max(self.most_at_once, sum(self.running.values()))
        time.sleep(self.hold)
        with self.lock:
            self.running[key] -= 1
            self.runs += 1
        if self.failing:
            raise RuntimeError("synthetic run failure")


class Looking:
    """Nothing is due; it counts the looks, and may say when the next request is due."""

    def __init__(
        self,
        next_due: Callable[[], datetime] | None = None,
        failing_looks: int = 0,
    ) -> None:
        self.next_due, self.failing_looks = next_due, failing_looks
        self.looks: list[float] = []

    def due(self, reserved: Collection[str]) -> tuple[tuple[InstantRun, ...], datetime | None]:
        self.looks.append(time.monotonic())
        if len(self.looks) <= self.failing_looks:
            raise RuntimeError("database is locked")
        return (), self.next_due() if self.next_due is not None else None

    def run(self, item: InstantRun) -> None:
        raise AssertionError("nothing is due")


def test_the_dispatcher_never_runs_one_rule_twice_at_once() -> None:
    dispatch = Offering("rule-1")

    asyncio.run(_running(InstantSyncDispatcher(dispatch), lambda: dispatch.runs >= 3))

    assert dispatch.most_of_one == 1


def test_the_dispatcher_runs_no_more_rules_at_once_than_its_concurrency() -> None:
    dispatch = Offering("rule-1", "rule-2", "rule-3", "rule-4", hold=0.05)

    asyncio.run(
        _running(InstantSyncDispatcher(dispatch, concurrency=2), lambda: dispatch.runs >= 4)
    )

    assert dispatch.most_at_once == 2


def test_a_wake_from_another_thread_makes_the_dispatcher_look_at_once() -> None:
    dispatch = Looking()
    # With nothing due it would otherwise sleep its longest, a minute.
    dispatcher = InstantSyncDispatcher(dispatch)

    async def scenario() -> None:
        task = asyncio.create_task(dispatcher.run_forever())
        await _until(lambda: len(dispatch.looks) == 1)
        threading.Thread(target=dispatcher.wake).start()
        await _until(lambda: len(dispatch.looks) == 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())


def test_the_dispatcher_looks_again_when_the_next_request_becomes_due() -> None:
    clock = SystemClock()
    dispatch = Looking(next_due=lambda: clock.now() + timedelta(milliseconds=50))

    asyncio.run(
        _running(InstantSyncDispatcher(dispatch, clock=clock), lambda: len(dispatch.looks) >= 2)
    )

    assert dispatch.looks[1] - dispatch.looks[0] >= 0.03


def test_waking_the_dispatcher_before_it_starts_is_harmless() -> None:
    dispatch = Looking()

    InstantSyncDispatcher(dispatch).wake()

    assert dispatch.looks == []


def test_a_notice_during_a_run_leads_to_its_next_run_without_waiting() -> None:
    class Renotified:
        """One rule whose notice comes again while its first run goes. A reserved rule adds no
        time to wait for, so only the run's end can make the dispatcher look again."""

        def __init__(self) -> None:
            self.pending = True
            self.runs = 0

        def due(self, reserved: Collection[str]) -> tuple[tuple[InstantRun, ...], datetime | None]:
            if "rule-1" in reserved or not self.pending:
                return (), None
            return (_instant("rule-1"),), None

        def run(self, item: InstantRun) -> None:
            self.runs += 1
            # The first run's notice raised the request again; the second consumes it.
            self.pending = self.runs == 1

    dispatch = Renotified()

    # Its longest sleep is a minute, far beyond `_until`'s five seconds.
    asyncio.run(_running(InstantSyncDispatcher(dispatch), lambda: dispatch.runs >= 2))

    assert dispatch.runs == 2


def test_a_failed_look_or_run_never_ends_the_dispatcher(caplog: pytest.LogCaptureFixture) -> None:
    looking = Looking(failing_looks=1)
    failing = Offering("rule-1", failing=True)

    with caplog.at_level("ERROR", logger="calendar_sync.infrastructure.scheduling"):
        asyncio.run(
            _running(
                InstantSyncDispatcher(looking, longest_sleep_seconds=0.01),
                lambda: len(looking.looks) >= 2,
            )
        )
        asyncio.run(_running(InstantSyncDispatcher(failing), lambda: failing.runs >= 2))

    assert "Choosing instant runs failed; looking again shortly" in caplog.text
    assert "Instant run of rule rule-1 failed" in caplog.text


def test_stopping_the_dispatcher_lets_a_running_run_finish_its_acknowledgement() -> None:
    release, finished = threading.Event(), threading.Event()

    class Holding:
        def __init__(self) -> None:
            self.started = threading.Event()

        def due(self, reserved: Collection[str]) -> tuple[tuple[InstantRun, ...], datetime | None]:
            if "rule-1" in reserved or self.started.is_set():
                return (), None
            return (_instant("rule-1"),), None

        def run(self, item: InstantRun) -> None:
            self.started.set()
            release.wait(5)
            finished.set()

    dispatch = Holding()

    async def scenario() -> None:
        task = asyncio.create_task(InstantSyncDispatcher(dispatch).run_forever())
        await _until(dispatch.started.is_set)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        release.set()

    asyncio.run(scenario())

    # The run's thread acknowledges its request; a request never acknowledged stays durable.
    assert finished.wait(5)


class OnePass:
    """A scheduled pass of one rule, with no account to check; it counts its runs."""

    def __init__(self) -> None:
        self.runs = 0

    def begin(self) -> tuple[ScheduledRun, ...]:
        return (_instant("rule-1").scheduled,)

    def run(self, scheduled: ScheduledRun) -> None:
        self.runs += 1

    def checks_due(self) -> tuple[UserId, ...]:
        return ()


class CountingUpkeep:
    def __init__(self) -> None:
        self.cycles = 0

    def run(self) -> None:
        self.cycles += 1


def test_the_loops_never_wait_for_the_threads_web_requests_use() -> None:
    """The event loop's default threads, which `asyncio.to_thread` takes, are as few as five on
    one CPU and serve the Web API's requests. Held there, each loop still runs: it has its own."""
    release = threading.Event()
    scheduled, dispatch, upkeep = OnePass(), Offering("rule-1"), CountingUpkeep()

    async def scenario() -> None:
        loop = asyncio.get_running_loop()
        loop.set_default_executor(ThreadPoolExecutor(1))
        holding = loop.run_in_executor(None, release.wait, 30)
        try:
            await asyncio.wait_for(
                SyncScheduler(cast(ScheduledPass, scheduled)).run_once(), timeout=5
            )
            await _running(InstantSyncDispatcher(dispatch), lambda: dispatch.runs >= 1)
            keeper = asyncio.create_task(WatchKeeper(upkeep).run_forever())
            await _until(lambda: upkeep.cycles >= 1)
            keeper.cancel()
        finally:
            release.set()
            await holding

    asyncio.run(scenario())

    assert (scheduled.runs, dispatch.runs >= 1, upkeep.cycles) == (1, True, 1)


def test_the_watch_keeper_runs_upkeep_each_interval_and_survives_a_failure(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class Upkeep:
        def __init__(self) -> None:
            self.cycles = 0

        def run(self) -> None:
            self.cycles += 1
            if self.cycles == 1:
                raise RuntimeError("synthetic provider outage")

    upkeep = Upkeep()
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise asyncio.CancelledError

    monkeypatch.setattr("calendar_sync.infrastructure.scheduling.asyncio.sleep", sleep)

    with (
        caplog.at_level("ERROR", logger="calendar_sync.infrastructure.scheduling"),
        pytest.raises(asyncio.CancelledError),
    ):
        asyncio.run(WatchKeeper(upkeep, interval_seconds=300).run_forever())

    assert upkeep.cycles == 2
    assert sleeps == [300, 300]
    assert [record.getMessage() for record in caplog.records] == [
        "Watch upkeep failed; trying again at the next interval"
    ]


@pytest.mark.parametrize(
    ("public_url", "with_key", "offered"),
    [
        (ADDRESS, True, True),
        ("http://ghost.example.test", True, False),
        ("", True, False),
        (ADDRESS, False, False),
    ],
    ids=["https", "http", "no address", "no master key"],
)
def test_instant_sync_runs_only_with_a_public_https_address_and_the_master_key(
    tmp_path: Path, public_url: str, with_key: bool, offered: bool
) -> None:
    settings = Settings(
        tmp_path / "test.db",
        master_key=CredentialCipher.generate_key() if with_key else "",
        public_url=public_url,
    )

    container = build_container(settings)

    present = {
        container.instant_dispatcher is not None,
        container.watch_keeper is not None,
        container.watch_inbox is not None,
    }
    assert present == {offered}
    assert container.instant_sync_address == (ADDRESS if offered else None)
    assert container.instant_sync_status.address == container.instant_sync_address


def test_providers_deliver_only_to_an_https_address_at_the_root_of_its_host(
    tmp_path: Path,
) -> None:
    def address(public_url: str) -> str | None:
        return instant_sync_address(Settings(tmp_path / "test.db", public_url=public_url))

    assert address("https://ghost.example.test/") == ADDRESS
    assert address("http://ghost.example.test") is None
    assert address("https://ghost.example.test/calendar") is None
    assert address("") is None


def test_each_user_keeps_their_own_watches_where_accounts_can_be_stored(tmp_path: Path) -> None:
    keyed = build_container(
        Settings(tmp_path / "keyed.db", master_key=CredentialCipher.generate_key())
    )
    unkeyed = build_container(Settings(tmp_path / "unkeyed.db"))

    assert keyed.for_user(USER).watch_upkeep is not None
    assert unkeyed.for_user(USER).watch_upkeep is None


def test_notice_readers_are_found_by_the_slug_in_their_address(tmp_path: Path) -> None:
    settings = Settings(
        tmp_path / "test.db", master_key=CredentialCipher.generate_key(), public_url=ADDRESS
    )

    container = build_container(settings)

    assert container.notice_readers
    for slug, (kind, _reader) in container.notice_readers.items():
        descriptor = container.providers.at(slug)
        assert descriptor is not None
        assert descriptor.kind is kind


class Looping:
    """A loop the service starts in its lifespan and cancels when it stops."""

    def __init__(self) -> None:
        self.started = False
        self.cancelled = False

    async def run_forever(self) -> None:
        self.started = True
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


def test_the_service_starts_and_stops_instant_syncs_loops_beside_the_scheduler(
    tmp_path: Path,
) -> None:
    dispatcher, keeper = Looping(), Looping()
    container = replace(
        build_container(Settings(tmp_path / "test.db")),
        instant_dispatcher=cast(InstantSyncDispatcher, dispatcher),
        watch_keeper=cast(WatchKeeper, keeper),
    )

    with TestClient(create_app(container)) as client:
        client.get("/health")
        started = (dispatcher.started, keeper.started)

    assert started == (True, True)
    assert (dispatcher.cancelled, keeper.cancelled) == (True, True)
