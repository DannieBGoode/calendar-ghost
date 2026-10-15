from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from threading import Thread

import pytest

from calendar_sync.application.sync.errors import (
    ConnectedAccountRequired,
    DuplicateDirectionalRelationship,
    RuleNotFound,
)
from calendar_sync.application.sync.locking import RuleLocks, RuleWork, RuleWorkKind
from calendar_sync.application.sync.rules import (
    ChangeSyncRulePolicy,
    CreateDraftSyncRule,
    CreateSyncRule,
    EnableSyncRule,
    GetSyncRuleDetails,
    ListSyncRules,
    PauseSyncRule,
)
from calendar_sync.domain.accounts import ConnectedAccountState
from calendar_sync.domain.errors import InvalidStateTransition
from calendar_sync.domain.model import (
    AllDaySyncPolicy,
    BirthdayPolicy,
    ProjectionContent,
    SyncRule,
    SyncRuleId,
    SyncRuleState,
    TentativeEventPolicy,
    TransformationPolicy,
    UnansweredInvitationPolicy,
)
from calendar_sync.domain.runs import RuleRunOutcome, RunKind
from tests.application.test_execute_sync_rule import FixedClock
from tests.helpers import rule
from tests.identity_fakes import MemoryPlans
from tests.users import USER, memory_units

MARK = TentativeEventPolicy.MARK
AS_TENTATIVE = UnansweredInvitationPolicy.AS_TENTATIVE
EXCLUDE = BirthdayPolicy.EXCLUDE


def test_changing_an_enabled_rule_pauses_it_and_audits_without_google_writes() -> None:
    unit_of_work = memory_units()
    unit_of_work.state.rules[rule().id] = rule(state=SyncRuleState.ENABLED)

    changed = ChangeSyncRulePolicy(unit_of_work, FixedClock(), locks=RuleLocks()).execute(
        rule().id,
        ProjectionContent.DETAILS,
        AllDaySyncPolicy.INCLUDE,
        tentative=TentativeEventPolicy.SKIP,
        unanswered=UnansweredInvitationPolicy.WAIT,
        birthdays=BirthdayPolicy.INCLUDE,
    )

    stored = unit_of_work.state.rules[rule().id]
    assert stored == changed
    assert stored.state is SyncRuleState.PAUSED
    assert stored.reprojection_required is True
    assert unit_of_work.state.audit[-1].action == "policy_changed"
    assert stored.transformation.tentative is TentativeEventPolicy.SKIP
    assert stored.transformation.unanswered is UnansweredInvitationPolicy.WAIT
    assert stored.transformation.birthdays is BirthdayPolicy.INCLUDE
    assert unit_of_work.state.audit[-1].detail == (
        "privacy=copy_details, all_day=include, tentative=skip, unanswered=wait, birthdays=include"
    )


def test_saving_the_same_policy_keeps_the_rule_enabled() -> None:
    unit_of_work = memory_units()
    unit_of_work.state.rules[rule().id] = rule(state=SyncRuleState.ENABLED)

    unchanged = ChangeSyncRulePolicy(unit_of_work, FixedClock(), locks=RuleLocks()).execute(
        rule().id,
        ProjectionContent.BUSY_ONLY,
        AllDaySyncPolicy.INCLUDE,
        tentative=MARK,
        unanswered=AS_TENTATIVE,
        birthdays=EXCLUDE,
    )

    assert unchanged.state is SyncRuleState.ENABLED
    assert unit_of_work.state.audit == []


def test_policy_change_is_blocked_for_missing_or_removing_rules() -> None:
    unit_of_work = memory_units()
    unit_of_work.state.rules[rule().id] = rule(state=SyncRuleState.REMOVING)
    use_case = ChangeSyncRulePolicy(unit_of_work, FixedClock(), locks=RuleLocks())

    with pytest.raises(RuleNotFound):
        use_case.execute(
            SyncRuleId("missing"),
            ProjectionContent.BUSY_ONLY,
            AllDaySyncPolicy.INCLUDE,
            tentative=MARK,
            unanswered=AS_TENTATIVE,
            birthdays=EXCLUDE,
        )
    with pytest.raises(InvalidStateTransition):
        use_case.execute(
            rule().id,
            ProjectionContent.DETAILS,
            AllDaySyncPolicy.INCLUDE,
            tentative=MARK,
            unanswered=AS_TENTATIVE,
            birthdays=EXCLUDE,
        )


def test_details_report_mapping_count_and_latest_outcomes() -> None:
    unit_of_work = memory_units()
    unit_of_work.state.rules[rule().id] = rule()
    synced = RuleRunOutcome(rule().id, RunKind.SYNC, datetime(2026, 9, 1, tzinfo=UTC), True)
    unit_of_work.state.outcomes[(rule().id, RunKind.SYNC)] = synced

    get_details = GetSyncRuleDetails(unit_of_work, RuleLocks(), MemoryPlans(), USER)

    details = get_details.execute(rule().id)

    assert details.rule == rule()
    assert details.mapping_count == 0
    assert details.last_sync == synced
    assert details.last_reconciliation is None
    # Plans are off, so nothing limits a Start.
    assert (details.can_start, details.rule_limit) == (True, None)
    with pytest.raises(RuleNotFound):
        get_details.execute(SyncRuleId("missing"))


def test_policy_change_waits_for_an_in_flight_provider_write() -> None:
    unit_of_work = memory_units()
    unit_of_work.state.rules[rule().id] = rule(state=SyncRuleState.ENABLED)
    locks = RuleLocks()
    change = ChangeSyncRulePolicy(unit_of_work, FixedClock(), locks)
    writing = locks.for_writes(rule().id)
    writing.acquire()
    worker = Thread(
        target=change.execute,
        args=(rule().id, ProjectionContent.DETAILS, AllDaySyncPolicy.INCLUDE),
        kwargs={"tentative": MARK, "unanswered": AS_TENTATIVE, "birthdays": EXCLUDE},
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


def test_enabling_a_previewed_rule_saves_it_enabled() -> None:
    unit_of_work = memory_units()
    unit_of_work.state.rules[rule().id] = rule(state=SyncRuleState.PREVIEWED)

    enabled = EnableSyncRule(unit_of_work, RuleLocks(), MemoryPlans(), USER).execute(rule().id)

    assert enabled.state is SyncRuleState.ENABLED
    assert unit_of_work.state.rules[rule().id] == enabled


def test_enabling_is_blocked_for_missing_or_unpreviewed_rules() -> None:
    unit_of_work = memory_units()
    unit_of_work.state.rules[rule().id] = rule(state=SyncRuleState.DRAFT)
    enable = EnableSyncRule(unit_of_work, RuleLocks(), MemoryPlans(), USER)

    with pytest.raises(RuleNotFound):
        enable.execute(SyncRuleId("missing"))
    with pytest.raises(InvalidStateTransition):
        enable.execute(rule().id)
    assert unit_of_work.state.rules[rule().id].state is SyncRuleState.DRAFT


def test_pausing_keeps_the_rule_and_is_blocked_unless_enabled() -> None:
    unit_of_work = memory_units()
    unit_of_work.state.rules[rule().id] = rule(state=SyncRuleState.ENABLED)
    pause = PauseSyncRule(unit_of_work, RuleLocks())

    paused = pause.execute(rule().id)

    assert paused.state is SyncRuleState.PAUSED
    assert unit_of_work.state.rules[rule().id] == paused
    with pytest.raises(InvalidStateTransition):
        pause.execute(rule().id)
    with pytest.raises(RuleNotFound):
        pause.execute(SyncRuleId("missing"))


@pytest.mark.parametrize("change", ["enable", "pause"])
def test_lifecycle_changes_wait_for_an_in_flight_provider_write(change: str) -> None:
    unit_of_work = memory_units()
    starting = SyncRuleState.PREVIEWED if change == "enable" else SyncRuleState.ENABLED
    unit_of_work.state.rules[rule().id] = rule(state=starting)
    locks = RuleLocks()
    execute: Callable[[SyncRuleId], SyncRule] = (
        EnableSyncRule(unit_of_work, locks, MemoryPlans(), USER).execute
        if change == "enable"
        else PauseSyncRule(unit_of_work, locks).execute
    )
    writing = locks.for_writes(rule().id)
    writing.acquire()
    worker = Thread(target=execute, args=(rule().id,))
    worker.start()
    worker.join(0.1)
    blocked_while_writing = worker.is_alive()
    writing.release()
    worker.join(2)

    assert blocked_while_writing
    assert unit_of_work.state.rules[rule().id].state is not starting


def test_new_rules_are_drafts_under_a_generated_identity() -> None:
    unit_of_work = memory_units()
    for endpoint_ in (rule().source, rule().destination):
        unit_of_work.state.accounts[endpoint_.connected_account_id] = (
            ConnectedAccountState.CONNECTED
        )
    details = TransformationPolicy(content=ProjectionContent.DETAILS)

    created = CreateDraftSyncRule(CreateSyncRule(unit_of_work), GeneratedIds("new-rule")).execute(
        rule().source, rule().destination, details
    )

    assert created.id == SyncRuleId("new-rule")
    assert created.state is SyncRuleState.DRAFT
    assert created.transformation == details
    assert unit_of_work.state.rules[created.id] == created


def test_listing_reports_each_rule_with_its_latest_outcomes_and_running_work() -> None:
    unit_of_work = memory_units()
    unit_of_work.state.rules[rule().id] = rule()
    synced = RuleRunOutcome(rule().id, RunKind.SYNC, datetime(2026, 9, 1, tzinfo=UTC), True)
    unit_of_work.state.outcomes[(rule().id, RunKind.SYNC)] = synced
    locks = RuleLocks()
    work = RuleWork(RuleWorkKind.SYNC, datetime(2026, 9, 1, tzinfo=UTC))

    with locks.working(rule().id, work):
        (running,) = ListSyncRules(unit_of_work, locks).execute()
        details = GetSyncRuleDetails(unit_of_work, locks, MemoryPlans(), USER).execute(rule().id)
    (idle,) = ListSyncRules(unit_of_work, locks).execute()

    assert running.rule == rule()
    assert running.last_sync == synced
    assert running.latest_preview is None
    assert running.running is not None
    assert running.running.kind is RuleWorkKind.SYNC
    assert details.running is not None
    assert idle.running is None


class GeneratedIds:
    def __init__(self, value: str) -> None:
        self.value = value

    def new(self) -> str:
        return self.value


@pytest.mark.parametrize("missing", ["source", "destination"])
def test_new_rules_require_both_connected_accounts_to_exist(missing: str) -> None:
    unit_of_work = memory_units(accounts=())
    present = rule().destination if missing == "source" else rule().source
    unit_of_work.state.accounts[present.connected_account_id] = ConnectedAccountState.CONNECTED

    with pytest.raises(ConnectedAccountRequired):
        CreateSyncRule(unit_of_work).execute(rule(state=SyncRuleState.DRAFT))

    assert unit_of_work.state.rules == {}


def test_new_rules_refuse_a_relationship_another_rule_has() -> None:
    unit_of_work = memory_units()
    unit_of_work.state.rules[rule().id] = rule()
    twin = SyncRule(SyncRuleId("twin"), rule().source, rule().destination)

    with pytest.raises(DuplicateDirectionalRelationship):
        CreateSyncRule(unit_of_work).execute(twin)

    assert unit_of_work.state.rules == {rule().id: rule()}
