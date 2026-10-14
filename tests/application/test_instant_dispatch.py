"""Instant dispatch: which Instant Sync Requests run now, in what order, and how each run
acknowledges its request (ADR 0036)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Self, cast

import pytest

from calendar_sync.application.operations.instant_sync import (
    MAX_WAIT,
    MIN_GAP,
    QUIET,
    InstantDispatch,
    InstantRun,
    due_at,
)
from calendar_sync.application.operations.ports import (
    InstallationUnitOfWorkFactory,
    InstantSyncOwner,
    PendingInstantRun,
)
from calendar_sync.application.operations.scheduled_pass import (
    ScheduledPass,
    ScheduledServices,
    SyncRuns,
)
from calendar_sync.application.sync.errors import ProviderFailure
from calendar_sync.application.sync.health import RunHealth
from calendar_sync.application.sync.ports import ScheduledRule, UnitOfWorkFactory
from calendar_sync.application.sync.synchronization import SyncRunResult
from calendar_sync.application.sync.watch_ports import PendingRequest
from calendar_sync.domain.access import UserId
from calendar_sync.domain.cadence import SCHEDULED_EVERY, SyncCadence
from calendar_sync.domain.model import SyncRule, SyncRuleId, SyncRuleState
from calendar_sync.domain.providers import ProviderFailureKind
from tests.helpers import NOW, rule
from tests.scheduled_fakes import RecordingHealth
from tests.users import OTHER_USER, USER


class Clock:
    def __init__(self) -> None:
        self.moment = NOW

    def now(self) -> datetime:
        return self.moment


@dataclass
class Requests:
    """Every User's Instant Sync Requests, as the inbox raises them and runs acknowledge them."""

    clock: Clock
    pending: dict[tuple[UserId, SyncRuleId], PendingRequest] = field(default_factory=dict)
    acknowledging_fails: bool = False

    def notice(self, owner: UserId, rule_id: SyncRuleId, at: datetime | None = None) -> None:
        moment = at or self.clock.now()
        known = self.pending.get((owner, rule_id))
        if known is None:
            self.pending[owner, rule_id] = PendingRequest(rule_id, 1, 0, moment, moment, None)
            return
        waiting = known.requested_seq > known.handled_seq
        self.pending[owner, rule_id] = replace(
            known,
            requested_seq=known.requested_seq + 1,
            first_requested_at=known.first_requested_at if waiting else moment,
            last_requested_at=moment,
        )

    def acknowledge(self, owner: UserId, rule_id: SyncRuleId, seq: int, ran_at: datetime) -> None:
        if self.acknowledging_fails:
            raise RuntimeError("database is locked")
        known = self.pending[owner, rule_id]
        self.pending[owner, rule_id] = replace(
            known, handled_seq=max(known.handled_seq, seq), last_run_at=ran_at
        )

    def waiting(self, owner: UserId, rule_id: SyncRuleId) -> bool:
        known = self.pending[owner, rule_id]
        return known.requested_seq > known.handled_seq


class OwnersRequests:
    def __init__(self, requests: Requests, owner: UserId) -> None:
        self.requests, self.owner = requests, owner

    def acknowledge(self, rule_id: SyncRuleId, seq: int, ran_at: datetime) -> None:
        self.requests.acknowledge(self.owner, rule_id, seq, ran_at)


class OwnersUnit:
    """One User's unit of work, as far as acknowledging their requests uses it."""

    def __init__(self, requests: Requests, owner: UserId) -> None:
        self.instant_requests = OwnersRequests(requests, owner)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def commit(self) -> None:
        return None


@dataclass
class Installation:
    """Every User's records, as far as dispatch reads them across Users."""

    requests: Requests
    rules: dict[SyncRuleId, tuple[UserId, SyncRule]]
    owners: dict[UserId, InstantSyncOwner]
    failing: set[SyncRuleId] = field(default_factory=set)

    def __call__(self) -> Self:
        return self

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def commit(self) -> None:
        return None

    def instant_sync_owners(self) -> tuple[InstantSyncOwner, ...]:
        return tuple(self.owners.values())

    def pending_instant_runs(self) -> tuple[PendingInstantRun, ...]:
        """As the stores list them: enabled rules of Users who are not disabled."""
        return tuple(
            PendingInstantRun(
                ScheduledRule(owner, self.rules[rule_id][1], None),
                request,
                rule_id in self.failing,
            )
            for (owner, rule_id), request in self.requests.pending.items()
            if request.requested_seq > request.handled_seq
            and self.rules[rule_id][1].state is SyncRuleState.ENABLED
            and not self.owners[owner].disabled
        )


class Runs:
    """A User's Sync Runs: each records its rule, and may do something while it runs."""

    def __init__(self) -> None:
        self.ran: list[tuple[str, bool]] = []
        self.during: Callable[[], None] = lambda: None
        self.failure: Exception | None = None

    def execute(self, rule_id: SyncRuleId, *, full: bool = False) -> SyncRunResult:
        self.ran.append((rule_id.value, full))
        self.during()
        if self.failure is not None:
            raise self.failure
        return SyncRunResult(rule_id)


class Cadences:
    def __init__(self) -> None:
        self.scheduled_only: set[UserId] = set()

    def cadence(self, user: UserId) -> SyncCadence:
        return SyncCadence(instant=user not in self.scheduled_only, poll_every=SCHEDULED_EVERY)


class World:
    """An installation whose rules' Instant Sync Requests one dispatch runs."""

    def __init__(self, *owned: tuple[UserId, SyncRule]) -> None:
        self.clock = Clock()
        self.requests = Requests(self.clock)
        self.installation = Installation(
            self.requests,
            {each.id: (owner, each) for owner, each in owned},
            {
                owner: InstantSyncOwner(user=owner, wanted=True, disabled=False, next_due=None)
                for owner, _ in owned
            },
        )
        self.runs = Runs()
        self.cadences = Cadences()
        services = ScheduledServices(cast(SyncRuns, self.runs), cast(RunHealth, RecordingHealth()))
        installation = cast(InstallationUnitOfWorkFactory, self.installation)
        self.dispatch = InstantDispatch(
            installation,
            ScheduledPass(installation, lambda _owner: services, self.clock),
            self._units,
            self.cadences,
            self.clock,
        )

    def _units(self, owner: UserId) -> UnitOfWorkFactory:
        return cast(UnitOfWorkFactory, lambda: OwnersUnit(self.requests, owner))

    def owner(self, user: UserId, *, wanted: bool = True, disabled: bool = False) -> None:
        self.installation.owners[user] = replace(
            self.installation.owners[user], wanted=wanted, disabled=disabled
        )


def _rule(rule_id: str) -> SyncRule:
    return replace(rule(), id=SyncRuleId(rule_id))


def _ids(runs: tuple[InstantRun, ...]) -> list[str]:
    return [run.scheduled.scheduled.rule.id.value for run in runs]


def test_the_timing_is_the_one_the_design_settles() -> None:
    assert timedelta(seconds=10) == QUIET
    assert timedelta(seconds=30) == MAX_WAIT
    assert timedelta(seconds=30) == MIN_GAP
    assert due_at(PendingRequest(rule().id, 1, 0, NOW, NOW, None)) == NOW + QUIET


@pytest.mark.parametrize(
    ("first", "last", "ran", "due_now", "wake"),
    [
        (-10, -10, None, True, None),
        (-5, -5, None, False, 5),
        (-30, -1, None, True, None),
        (-25, -1, None, False, 5),
        (-20, -20, -10, False, 20),
        (-20, -20, -30, True, None),
    ],
    ids=[
        "quiet for its window",
        "still within its quiet window",
        "notices kept coming for the longest wait",
        "notices keep coming within the longest wait",
        "ran within the gap",
        "ran before the gap",
    ],
)
def test_a_request_is_due_after_its_quiet_window_its_longest_wait_and_the_rules_gap(
    first: int, last: int, ran: int | None, due_now: bool, wake: int | None
) -> None:
    world = World((USER, rule()))
    world.requests.pending[USER, rule().id] = PendingRequest(
        rule().id,
        1,
        0,
        NOW + timedelta(seconds=first),
        NOW + timedelta(seconds=last),
        None if ran is None else NOW + timedelta(seconds=ran),
    )

    runs, next_due = world.dispatch.due(frozenset())

    assert _ids(runs) == (["rule-1"] if due_now else [])
    assert next_due == (None if wake is None else NOW + timedelta(seconds=wake))
    assert world.requests.waiting(USER, rule().id)


def test_due_runs_take_turns_between_users_and_never_list_in_full() -> None:
    owned = [
        *((USER, _rule(f"rule-{number}")) for number in (1, 2, 3)),
        (OTHER_USER, _rule("rule-4")),
    ]
    world = World(*owned)
    for owner, each in owned:
        world.requests.notice(owner, each.id, NOW - QUIET)

    runs, next_due = world.dispatch.due(frozenset())

    assert _ids(runs) == ["rule-1", "rule-4", "rule-2", "rule-3"]
    assert {run.scheduled.full for run in runs} == {False}
    assert [run.seq for run in runs] == [1, 1, 1, 1]
    assert next_due is None


def test_a_reserved_rule_is_left_alone() -> None:
    world = World((USER, rule()))
    world.requests.notice(USER, rule().id, NOW - QUIET)

    runs, next_due = world.dispatch.due(frozenset({"rule-1"}))

    assert (runs, next_due) == ((), None)
    assert world.requests.waiting(USER, rule().id)


INELIGIBLE: dict[str, Callable[[World], None]] = {
    "turned off": lambda world: world.owner(USER, wanted=False),
    "not in plan": lambda world: world.cadences.scheduled_only.add(USER),
    "last run failed": lambda world: world.installation.failing.add(rule().id),
}


def _pause(world: World) -> None:
    world.installation.rules[rule().id] = (USER, rule(state=SyncRuleState.PAUSED))


def _resume(world: World) -> None:
    world.installation.rules[rule().id] = (USER, rule())


INACTIVE: dict[str, tuple[Callable[[World], None], Callable[[World], None]]] = {
    "paused rule": (_pause, _resume),
    "disabled user": (
        lambda world: world.owner(USER, disabled=True),
        lambda world: world.owner(USER),
    ),
}


@pytest.mark.parametrize("change", list(INELIGIBLE.values()), ids=list(INELIGIBLE))
def test_a_request_whose_rule_may_not_run_instantly_is_dropped(
    change: Callable[[World], None],
) -> None:
    world = World((USER, rule()))
    world.requests.notice(USER, rule().id, NOW - QUIET)
    change(world)

    runs, next_due = world.dispatch.due(frozenset())

    assert (runs, next_due) == ((), None)
    assert not world.requests.waiting(USER, rule().id)
    assert world.runs.ran == []


@pytest.mark.parametrize(("stop", "resume"), list(INACTIVE.values()), ids=list(INACTIVE))
def test_a_request_waits_while_its_rule_or_user_is_inactive_then_runs(
    stop: Callable[[World], None], resume: Callable[[World], None]
) -> None:
    world = World((USER, rule()))
    world.requests.notice(USER, rule().id, NOW - QUIET)
    stop(world)

    waiting = world.dispatch.due(frozenset())
    resume(world)
    runs, _ = world.dispatch.due(frozenset())

    assert waiting == ((), None)
    assert _ids(runs) == ["rule-1"]


@pytest.mark.parametrize(("stop", "resume"), list(INACTIVE.values()), ids=list(INACTIVE))
def test_a_waiting_request_is_dropped_once_active_if_its_user_turned_instant_sync_off(
    stop: Callable[[World], None], resume: Callable[[World], None]
) -> None:
    world = World((USER, rule()))
    world.requests.notice(USER, rule().id, NOW - QUIET)
    stop(world)
    world.dispatch.due(frozenset())
    resume(world)
    world.owner(USER, wanted=False)

    runs, next_due = world.dispatch.due(frozenset())

    assert (runs, next_due) == ((), None)
    assert not world.requests.waiting(USER, rule().id)


def test_a_queued_run_whose_user_turned_instant_sync_off_does_not_run() -> None:
    world = World((USER, rule()))
    world.requests.notice(USER, rule().id, NOW - QUIET)
    (item,), _ = world.dispatch.due(frozenset())
    world.owner(USER, wanted=False)

    world.dispatch.run(item)

    assert world.runs.ran == []
    assert not world.requests.waiting(USER, rule().id)


def test_a_queued_run_whose_rule_was_paused_waits_without_running() -> None:
    world = World((USER, rule()))
    world.requests.notice(USER, rule().id, NOW - QUIET)
    (item,), _ = world.dispatch.due(frozenset())
    _pause(world)

    world.dispatch.run(item)

    assert world.runs.ran == []
    assert world.requests.waiting(USER, rule().id)


@pytest.mark.parametrize(
    "failure",
    [None, ProviderFailure(ProviderFailureKind.PERMANENT, "synthetic refusal")],
    ids=["succeeded", "failed"],
)
def test_a_run_acknowledges_its_request_whether_it_succeeded_or_failed(
    failure: ProviderFailure | None,
) -> None:
    world = World((USER, rule()))
    world.runs.failure = failure
    world.requests.notice(USER, rule().id, NOW - QUIET)
    (item,), _ = world.dispatch.due(frozenset())
    world.clock.moment = NOW + timedelta(seconds=3)

    world.dispatch.run(item)

    assert world.runs.ran == [("rule-1", False)]
    assert not world.requests.waiting(USER, rule().id)
    assert world.requests.pending[USER, rule().id].last_run_at == NOW + timedelta(seconds=3)


def test_a_notice_during_a_run_keeps_its_request_for_another_run() -> None:
    world = World((USER, rule()))
    world.requests.notice(USER, rule().id, NOW - QUIET)
    world.runs.during = lambda: world.requests.notice(USER, rule().id)
    (item,), _ = world.dispatch.due(frozenset())

    world.dispatch.run(item)
    runs, next_due = world.dispatch.due(frozenset())

    assert world.requests.waiting(USER, rule().id)
    # It runs again, once the rule's gap since this run has passed.
    assert (runs, next_due) == ((), NOW + MIN_GAP)


def test_a_crash_before_the_acknowledgement_runs_the_rule_again(
    caplog: pytest.LogCaptureFixture,
) -> None:
    world = World((USER, rule()))
    world.requests.notice(USER, rule().id, NOW - QUIET)
    (item,), _ = world.dispatch.due(frozenset())
    world.requests.acknowledging_fails = True

    with caplog.at_level("ERROR", logger="calendar_sync.application.operations.instant_sync"):
        world.dispatch.run(item)
    world.requests.acknowledging_fails = False
    # The process restarts: a new dispatch finds the request still pending.
    restarted = replace(world.dispatch)
    again, _ = restarted.due(frozenset())

    assert world.requests.waiting(USER, rule().id)
    assert _ids(again) == ["rule-1"]
    assert "Could not acknowledge the instant run of rule rule-1" in caplog.text


def test_a_rule_whose_acknowledgement_failed_waits_the_gap_before_it_runs_again() -> None:
    world = World((USER, rule()))
    world.requests.notice(USER, rule().id, NOW - QUIET)
    world.requests.acknowledging_fails = True
    ran_at = NOW + timedelta(seconds=3)

    def run_once_more() -> tuple[tuple[InstantRun, ...], datetime | None]:
        (item,), _ = world.dispatch.due(frozenset())
        world.clock.moment = ran_at
        world.dispatch.run(item)
        return world.dispatch.due(frozenset())

    # Storage that keeps refusing the acknowledgement must not run the rule back to back.
    held = run_once_more()
    world.clock.moment = ran_at + MIN_GAP
    again, _ = world.dispatch.due(frozenset())
    world.requests.acknowledging_fails = False
    world.dispatch.run(again[0])
    after_success, _ = world.dispatch.due(frozenset())

    assert held == ((), ran_at + MIN_GAP)
    assert _ids(again) == ["rule-1"]
    assert world.runs.ran == [("rule-1", False), ("rule-1", False)]
    assert after_success == ()


def test_an_unexpected_failure_still_acknowledges_the_request() -> None:
    world = World((USER, rule()))
    world.requests.notice(USER, rule().id, NOW - QUIET)
    (item,), _ = world.dispatch.due(frozenset())

    def broken(_owner: UserId) -> ScheduledServices:
        raise RuntimeError("synthetic composition failure")

    world.dispatch.scheduled_pass = ScheduledPass(
        cast(InstallationUnitOfWorkFactory, world.installation), broken, world.clock
    )

    with pytest.raises(RuntimeError):
        world.dispatch.run(item)

    assert not world.requests.waiting(USER, rule().id)
