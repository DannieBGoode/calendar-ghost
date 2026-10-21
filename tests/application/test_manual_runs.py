"""Manual runs: whom the throttle counts, and what a refused run says (ADR 0038)."""

import logging
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field

import pytest

from calendar_sync.application.sync.manual_runs import AdmitManualRun, ManualRunsThrottled
from calendar_sync.application.sync.plan_ports import Allowances
from calendar_sync.domain.access import UserId
from calendar_sync.domain.model import SyncRuleId
from calendar_sync.domain.plans import UNLIMITED, Allowance, AllowanceBasis
from tests.identity_fakes import BrokenAllowances
from tests.plans import FREE
from tests.users import USER

RULE = SyncRuleId("rule-1")
LIMITED = Allowance(AllowanceBasis.PLAN, plan=FREE, on_default=True)
"""A User the Default Plan limits."""


@dataclass
class Everyone:
    """Allowances that give every User the same Allowance."""

    allowance: Allowance

    def of(self, user: UserId) -> Allowance:
        return self.allowance

    def of_users(self, users: Collection[UserId]) -> Mapping[UserId, Allowance]:
        return dict.fromkeys(users, self.allowance)


@dataclass
class RecordingThrottle:
    """Answers every run with `wait`, recording whose runs it was asked to admit."""

    wait: float = 0.0
    asked: list[UserId] = field(default_factory=list)

    def admit(self, user: UserId) -> float:
        self.asked.append(user)
        return self.wait


@dataclass
class RecordingRun:
    """A manual run that records the rules it ran and answers with a result of its own."""

    ran: list[SyncRuleId] = field(default_factory=list)

    def __call__(self, rule_id: SyncRuleId) -> str:
        self.ran.append(rule_id)
        return f"ran {rule_id.value}"


def _admit(allowances: Allowances, throttle: RecordingThrottle, run: RecordingRun) -> str:
    return AdmitManualRun(allowances, throttle, USER).execute(run, RULE)


@pytest.mark.parametrize(
    "allowance",
    [
        pytest.param(UNLIMITED, id="plans off"),
        pytest.param(Allowance(AllowanceBasis.ADMINISTRATOR, assigned=FREE), id="administrator"),
    ],
)
def test_plans_off_and_administrators_run_without_the_throttle(allowance: Allowance) -> None:
    # A throttle that would refuse every run shows that nobody asked it.
    throttle, run = RecordingThrottle(wait=60.0), RecordingRun()

    assert _admit(Everyone(allowance), throttle, run) == "ran rule-1"
    assert throttle.asked == []
    assert run.ran == [RULE]


def test_a_limited_user_runs_while_the_throttle_admits() -> None:
    throttle, run = RecordingThrottle(), RecordingRun()

    assert _admit(Everyone(LIMITED), throttle, run) == "ran rule-1"
    assert throttle.asked == [USER]
    assert run.ran == [RULE]


def test_a_refused_run_raises_with_the_wait_and_never_runs() -> None:
    throttle, run = RecordingThrottle(wait=89.2), RecordingRun()

    with pytest.raises(ManualRunsThrottled) as refused:
        _admit(Everyone(LIMITED), throttle, run)

    # Rounded up, so a client that waits as told is not refused again.
    assert refused.value.retry_after == 90
    assert "90 seconds" in str(refused.value)
    assert throttle.asked == [USER]
    assert run.ran == []


def test_a_failed_plans_read_runs_without_the_throttle_and_logs_only_the_class(
    caplog: pytest.LogCaptureFixture,
) -> None:
    throttle, run = RecordingThrottle(wait=60.0), RecordingRun()

    with caplog.at_level(logging.WARNING):
        result = _admit(BrokenAllowances(), throttle, run)

    # Fails open: a fault in Plans never stops a run, and records nothing.
    assert result == "ran rule-1"
    assert throttle.asked == []
    assert run.ran == [RULE]
    assert "RuntimeError" in caplog.text
    assert USER.value in caplog.text
    assert "database is locked" not in caplog.text
