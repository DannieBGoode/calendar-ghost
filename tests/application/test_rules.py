from __future__ import annotations

from datetime import UTC, datetime
from threading import Thread

import pytest

from calendar_sync.application.errors import RuleNotFound
from calendar_sync.application.locking import RuleLocks
from calendar_sync.application.ports import RuleRunOutcome, RunKind
from calendar_sync.application.rules import ChangeSyncRulePolicy, GetSyncRuleDetails
from calendar_sync.domain.errors import InvalidStateTransition
from calendar_sync.domain.model import (
    AllDaySyncPolicy,
    PrivacyPolicy,
    SyncRuleId,
    SyncRuleState,
)
from calendar_sync.infrastructure.persistence.memory import InMemoryUnitOfWorkFactory
from tests.application.test_execute_sync_rule import FixedClock
from tests.helpers import rule


def test_changing_an_enabled_rule_pauses_it_and_audits_without_google_writes() -> None:
    unit_of_work = InMemoryUnitOfWorkFactory()
    unit_of_work.state.rules[rule().id] = rule(state=SyncRuleState.ENABLED)

    changed = ChangeSyncRulePolicy(unit_of_work, FixedClock()).execute(
        rule().id, PrivacyPolicy.COPY_DETAILS, AllDaySyncPolicy.INCLUDE
    )

    stored = unit_of_work.state.rules[rule().id]
    assert stored == changed
    assert stored.state is SyncRuleState.PAUSED
    assert stored.reprojection_required is True
    assert unit_of_work.state.audit[-1].action == "policy_changed"
    assert unit_of_work.state.audit[-1].detail == "privacy=copy_details, all_day=include"


def test_saving_the_same_policy_keeps_the_rule_enabled() -> None:
    unit_of_work = InMemoryUnitOfWorkFactory()
    unit_of_work.state.rules[rule().id] = rule(state=SyncRuleState.ENABLED)

    unchanged = ChangeSyncRulePolicy(unit_of_work, FixedClock()).execute(
        rule().id, PrivacyPolicy.BUSY_ONLY, AllDaySyncPolicy.INCLUDE
    )

    assert unchanged.state is SyncRuleState.ENABLED
    assert unit_of_work.state.audit == []


def test_policy_change_is_blocked_for_missing_or_removing_rules() -> None:
    unit_of_work = InMemoryUnitOfWorkFactory()
    unit_of_work.state.rules[rule().id] = rule(state=SyncRuleState.DISABLED)
    use_case = ChangeSyncRulePolicy(unit_of_work, FixedClock())

    with pytest.raises(RuleNotFound):
        use_case.execute(SyncRuleId("missing"), PrivacyPolicy.BUSY_ONLY, AllDaySyncPolicy.INCLUDE)
    with pytest.raises(InvalidStateTransition):
        use_case.execute(rule().id, PrivacyPolicy.COPY_DETAILS, AllDaySyncPolicy.INCLUDE)


def test_details_report_mapping_count_and_latest_outcomes() -> None:
    unit_of_work = InMemoryUnitOfWorkFactory()
    unit_of_work.state.rules[rule().id] = rule()
    synced = RuleRunOutcome(rule().id, RunKind.SYNC, datetime(2026, 9, 1, tzinfo=UTC), True)
    unit_of_work.state.outcomes[(rule().id, RunKind.SYNC)] = synced

    details = GetSyncRuleDetails(unit_of_work).execute(rule().id)

    assert details.rule == rule()
    assert details.mapping_count == 0
    assert details.last_sync == synced
    assert details.last_reconciliation is None
    with pytest.raises(RuleNotFound):
        GetSyncRuleDetails(unit_of_work).execute(SyncRuleId("missing"))


def test_policy_change_waits_for_an_in_flight_provider_write() -> None:
    unit_of_work = InMemoryUnitOfWorkFactory()
    unit_of_work.state.rules[rule().id] = rule(state=SyncRuleState.ENABLED)
    locks = RuleLocks()
    change = ChangeSyncRulePolicy(unit_of_work, FixedClock(), locks)
    writing = locks.for_writes(rule().id)
    writing.acquire()
    worker = Thread(
        target=change.execute,
        args=(rule().id, PrivacyPolicy.COPY_DETAILS, AllDaySyncPolicy.INCLUDE),
    )
    worker.start()
    worker.join(0.1)
    blocked_while_writing = worker.is_alive()
    saved_while_writing = unit_of_work.state.rules[rule().id].state
    writing.release()
    worker.join(2)

    assert blocked_while_writing
    assert saved_while_writing is SyncRuleState.ENABLED
    assert unit_of_work.state.rules[rule().id].state is SyncRuleState.PAUSED
