from __future__ import annotations

from datetime import UTC, datetime
from threading import Lock, Thread

import pytest

from calendar_sync.application.locking import RuleLocks, RuleWork, RuleWorkKind
from calendar_sync.domain.model import SyncRuleId

STARTED = datetime(2026, 9, 29, 9, 0, tzinfo=UTC)
RULE = SyncRuleId("rule-1")


def test_work_is_visible_only_while_it_runs() -> None:
    locks = RuleLocks()

    with locks.working(RULE, RuleWork(RuleWorkKind.SYNC, STARTED)):
        running = locks.current_work(RULE)
        assert running is not None
        assert (running.kind, running.started_at) == (RuleWorkKind.SYNC, STARTED)
        assert locks.current_work(SyncRuleId("other")) is None

    assert locks.current_work(RULE) is None


def test_overlapping_work_reports_the_newest_and_falls_back_when_it_ends() -> None:
    locks = RuleLocks()

    with locks.working(RULE, RuleWork(RuleWorkKind.SYNC, STARTED)):
        with locks.working(RULE, RuleWork(RuleWorkKind.PREVIEW, STARTED)):
            assert getattr(locks.current_work(RULE), "kind", None) is RuleWorkKind.PREVIEW
        assert getattr(locks.current_work(RULE), "kind", None) is RuleWorkKind.SYNC


def test_work_ends_when_it_fails_and_snapshots_do_not_change_it() -> None:
    locks = RuleLocks()
    work = RuleWork(RuleWorkKind.REMOVAL, STARTED, total=3)

    def fail_after_changing_a_snapshot() -> None:
        with locks.working(RULE, work):
            snapshot = locks.current_work(RULE)
            assert snapshot is not None
            snapshot.done = 2
            assert work.done == 0
            raise RuntimeError("provider failed")

    with pytest.raises(RuntimeError):
        fail_after_changing_a_snapshot()

    assert locks.current_work(RULE) is None


def _held_elsewhere(lock: Lock) -> bool:
    """Whether another thread would have to wait for `lock`."""
    acquired = lock.acquire(timeout=0.05)
    if acquired:
        lock.release()
    return not acquired


# Regression: PR #34 review — a rule created right before VACUUM could run alongside it
def test_holding_every_rule_also_holds_a_rule_first_locked_meanwhile() -> None:
    locks = RuleLocks()
    existing = locks.for_rule(RULE)

    with locks.every_rule(timeout=1.0):
        assert existing.locked()
        # A brand-new rule's first run asks for its lock only now, from another thread.
        newcomer: list[Lock] = []
        thread = Thread(target=lambda: newcomer.append(locks.for_rule(SyncRuleId("new"))))
        thread.start()
        thread.join()
        assert _held_elsewhere(newcomer[0])

    assert not existing.locked()
    assert not newcomer[0].locked()


def test_holding_every_rule_gives_up_after_its_timeout_and_holds_nothing() -> None:
    locks = RuleLocks()
    first = locks.for_rule(SyncRuleId("a-rule"))
    busy = locks.for_rule(SyncRuleId("b-rule"))
    busy.acquire()
    try:
        with pytest.raises(TimeoutError), locks.every_rule(timeout=0.05):
            pytest.fail("entered while a rule was busy")
        assert not first.locked()
        assert busy.locked()
        assert not locks.for_rule(SyncRuleId("asked-for-later")).locked()
    finally:
        busy.release()


def test_only_one_caller_holds_every_rule_at_a_time() -> None:
    locks = RuleLocks()

    with locks.every_rule(timeout=1.0):
        outcome: list[str] = []

        def second_holder() -> None:
            try:
                with locks.every_rule(timeout=0.05):
                    outcome.append("entered")
            except TimeoutError:
                outcome.append("timed out")

        thread = Thread(target=second_holder)
        thread.start()
        thread.join()

    assert outcome == ["timed out"]
    with locks.every_rule(timeout=0.05):
        pass
