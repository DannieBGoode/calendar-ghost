"""Keep choices are whole-set, atomic, and immediately apply available places."""

from dataclasses import replace

import pytest

from calendar_sync.application.sync.errors import RuleNotFound
from calendar_sync.application.sync.locking import RuleLocks
from calendar_sync.application.sync.plan_holds import (
    ChooseKeptRules,
    PlanSettlementBusy,
    TooManyKeptRules,
)
from calendar_sync.domain.model import SyncRuleId, SyncRuleState
from tests.application.test_plan_holds import LATER, NEXT, engine, expired
from tests.application.test_plan_limits import _plans_off, _rule, _units
from tests.helpers import rule


def test_full_choice_saved_during_grace_without_holds():
    units = _units(rule(), _rule(NEXT, SyncRuleState.ENABLED))
    holds = engine(units)
    holds.settle()
    grace = units.state.plan_grace
    ChooseKeptRules(holds).execute([NEXT])
    assert units.state.rule_kept == {NEXT}
    assert units.state.plan_grace == grace
    assert all(each.synchronizes for each in units.state.rules.values())
    ChooseKeptRules(holds).execute([])
    assert units.state.rule_kept == set()


@pytest.mark.parametrize("chosen", [[rule().id, NEXT], [SyncRuleId("foreign")], [LATER]])
def test_invalid_choice_is_atomic(chosen):
    units = _units(rule(), _rule(NEXT, SyncRuleState.ENABLED).hold(), _rule(LATER))
    units.state.rule_kept.add(rule().id)
    before = dict(units.state.rules)
    expected = TooManyKeptRules if len(chosen) > 1 else RuleNotFound
    with pytest.raises(expected) as caught:
        ChooseKeptRules(engine(units)).execute(chosen)
    if isinstance(caught.value, TooManyKeptRules):
        assert caught.value.limit == 1
    assert units.state.rule_kept == {rule().id}
    assert units.state.rules == before


def test_keep_releases_into_free_place_and_records_admission():
    units = _units(rule().hold(), _rule(NEXT, SyncRuleState.ENABLED).hold())
    ChooseKeptRules(engine(units)).execute([NEXT])
    assert units.state.rules[NEXT].synchronizes
    assert units.state.rules[rule().id].held_by_plan
    assert units.state.plan_admissions == 1


def test_keep_swaps_worst_counted_without_admission():
    units = _units(rule(), _rule(NEXT, SyncRuleState.ENABLED).hold())
    ChooseKeptRules(engine(units)).execute([NEXT])
    assert units.state.rules[NEXT].synchronizes
    assert units.state.rules[rule().id].held_by_plan
    assert units.state.plan_admissions == 0


def test_keep_never_swaps_reserved_rule():
    units = _units(
        replace(rule(state=SyncRuleState.DRAFT), keeps_place=True),
        _rule(NEXT, SyncRuleState.ENABLED).hold(),
    )
    ChooseKeptRules(engine(units)).execute([NEXT])
    assert units.state.rules[rule().id].keeps_place
    assert units.state.rules[NEXT].held_by_plan


def test_keep_disabled_user_does_not_swap():
    units = _units(rule(), _rule(NEXT, SyncRuleState.ENABLED).hold())
    units.database.disabled.add(engine(units).owner)
    ChooseKeptRules(engine(units)).execute([NEXT])
    assert units.state.rules[rule().id].synchronizes
    assert units.state.rules[NEXT].held_by_plan


def test_keep_without_plans_never_limits_or_holds():
    units = _units(rule(), _rule(NEXT, SyncRuleState.ENABLED).hold())
    ChooseKeptRules(engine(units, _plans_off())).execute([rule().id, NEXT])
    assert all(each.synchronizes for each in units.state.rules.values())


def test_keep_choice_contention_changes_nothing():
    units = _units(rule(), _rule(NEXT, SyncRuleState.ENABLED).hold())
    locks = RuleLocks()
    expired(units)
    before = units.state.plan_grace
    with locks.for_writes(NEXT), pytest.raises(PlanSettlementBusy):
        ChooseKeptRules(engine(units, locks=locks)).execute([NEXT])
    assert units.state.rule_kept == set()
    assert units.state.plan_grace == before
    assert units.state.rules[NEXT].held_by_plan


def test_choice_releases_best_kept_then_swaps_worst_counted():
    from tests.application.test_plan_limits import _plans
    from tests.helpers import NOW
    from tests.plans import FREE

    oldest_held = _rule(NEXT, SyncRuleState.ENABLED).hold()
    newest_held = _rule(LATER, SyncRuleState.ENABLED).hold()
    units = _units(rule(), oldest_held, newest_held)
    plans = _plans()
    plans.change(replace(FREE, limits=replace(FREE.limits, rules=2)), NOW)
    ChooseKeptRules(engine(units, plans)).execute([LATER, NEXT])
    assert units.state.rules[NEXT].synchronizes
    assert units.state.rules[LATER].synchronizes
    assert units.state.rules[rule().id].held_by_plan
    assert units.state.plan_admissions == 1


def test_choice_releases_only_chosen_rules_into_free_places():
    units = _units(rule().hold(), _rule(NEXT, SyncRuleState.ENABLED).hold())
    ChooseKeptRules(engine(units)).execute([])
    assert all(each.held_by_plan for each in units.state.rules.values())
    assert units.state.plan_admissions == 0


def test_foreign_choice_changes_neither_users_rules_nor_kept_marks():
    from tests.users import OTHER_USER

    units = _units(rule())
    other = units.database.state_of(OTHER_USER)
    foreign = _rule(NEXT, SyncRuleState.ENABLED)
    other.rules[NEXT] = foreign
    other.rule_kept.add(NEXT)
    units.state.rule_kept.add(rule().id)
    with pytest.raises(RuleNotFound):
        ChooseKeptRules(engine(units)).execute([NEXT])
    assert units.state.rule_kept == {rule().id}
    assert units.state.rules[rule().id].synchronizes
    assert other.rules[NEXT] == foreign
    assert other.rule_kept == {NEXT}
