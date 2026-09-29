from __future__ import annotations

from datetime import UTC, datetime

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
