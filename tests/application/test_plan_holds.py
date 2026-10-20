"""A User's Plan settlement commits holds, releases, and grace together."""

from dataclasses import replace
from datetime import timedelta
from threading import Event, Thread

import pytest

from calendar_sync.application.sync.locking import RuleLocks
from calendar_sync.application.sync.plan_holds import PlanHolds, PlanSettlementBusy, SettleLocks
from calendar_sync.application.sync.ports import Allowances
from calendar_sync.domain.access import Role
from calendar_sync.domain.model import SyncRuleId, SyncRuleState
from calendar_sync.domain.plan_hold import GRACE, PlanGrace, PlanNoticeKind
from calendar_sync.infrastructure.persistence.memory import InMemoryUserUnitOfWorkFactory
from tests.application.test_plan_limits import _plans, _plans_off, _rule, _units
from tests.fake_calendar import FixedClock
from tests.helpers import NOW, rule
from tests.users import USER

NEXT = SyncRuleId("next")
LATER = SyncRuleId("later")


def engine(
    units: InMemoryUserUnitOfWorkFactory,
    plans: Allowances | None = None,
    locks: RuleLocks | None = None,
) -> PlanHolds:
    return PlanHolds(
        units, USER, plans or _plans(), locks or RuleLocks(), SettleLocks(), FixedClock()
    )


def expired(units: InMemoryUserUnitOfWorkFactory, limit: int = 1) -> None:
    units.state.plan_grace = PlanGrace(NOW - timedelta(seconds=1), limit, 0)


def test_grace_then_atomic_holds_and_give_up_without_activity() -> None:
    units = _units(
        rule(), _rule(NEXT, SyncRuleState.ENABLED), replace(_rule(LATER), keeps_place=True)
    )
    holds = engine(units)
    notice = holds.settle()
    assert notice is not None
    assert notice.kind is PlanNoticeKind.GRACE_STARTED
    assert notice.holds_at == NOW + GRACE
    assert (notice.count, notice.held, notice.reserved) == (3, 1, 1)
    expired(units)
    notice = holds.settle()
    assert notice is not None
    assert (notice.kind, notice.held) == (PlanNoticeKind.RULES_HELD, 1)
    assert units.state.rules[NEXT].held_by_plan
    assert not units.state.rules[LATER].keeps_place
    assert units.state.plan_grace is None
    assert units.state.audit == []
    assert units.database.incidents_of(USER) == {}


def test_give_up_alone_sends_no_held_notice() -> None:
    units = _units(rule(), replace(_rule(NEXT), keeps_place=True))
    expired(units)
    assert engine(units).settle() is None
    assert not units.state.rules[NEXT].keeps_place
    assert units.state.plan_grace is None


@pytest.mark.parametrize("authorized", [True, False])
def test_release_uses_fresh_account_authorization(authorized: bool) -> None:
    units = _units(rule().hold())
    if not authorized:
        units.state.lapsed[rule().source.connected_account_id] = NOW
    assert engine(units).settle() is None
    current = units.state.rules[rule().id]
    assert current.synchronizes is authorized
    assert current.awaiting_reauthorization is not authorized
    assert current.counts_toward_plan


@pytest.mark.parametrize("plans", [_plans_off(), _plans(Role.INSTALLATION_ADMINISTRATOR)])
def test_no_limit_releases_all_holds(plans: Allowances | None) -> None:
    units = _units(rule().hold(), _rule(NEXT, SyncRuleState.ENABLED).hold())
    expired(units)
    engine(units, plans).settle()
    assert all(each.synchronizes for each in units.state.rules.values())
    assert units.state.plan_grace is None


def test_disabled_user_clears_grace_and_retains_holds() -> None:
    units = _units(rule(), _rule(NEXT, SyncRuleState.ENABLED).hold())
    units.database.disabled.add(USER)
    expired(units)
    engine(units).settle()
    assert units.state.rules[NEXT].held_by_plan
    assert units.state.plan_grace is None


def test_scheduled_settlement_never_swaps() -> None:
    units = _units(rule(), _rule(NEXT, SyncRuleState.ENABLED).hold())
    units.state.rule_kept.add(NEXT)
    engine(units).settle()
    assert units.state.rules[rule().id].synchronizes
    assert units.state.rules[NEXT].held_by_plan


def test_notify_false_only_suppresses_notice() -> None:
    units = _units(rule(), _rule(NEXT, SyncRuleState.ENABLED))
    assert engine(units).settle(notify=False) is None
    assert units.state.plan_grace is not None
    assert units.state.plan_grace.holds_at == NOW + GRACE
    expired(units)
    assert engine(units).settle(notify=False) is None
    assert units.state.rules[NEXT].held_by_plan


def test_busy_rule_skips_user_without_delaying_listing() -> None:
    units = _units(rule(), _rule(NEXT, SyncRuleState.ENABLED))
    locks = RuleLocks()
    completed = Event()
    outcomes: list[BaseException] = []

    def settle() -> None:
        try:
            engine(units, locks=locks).settle()
        except BaseException as error:
            outcomes.append(error)
        finally:
            completed.set()

    # 'next' sorts before 'rule-1': contention releases an earlier acquired lock too.
    with locks.for_writes(rule().id):
        worker = Thread(target=settle)
        worker.start()
        try:
            assert completed.wait(2)
            assert locks.for_writes(NEXT).acquire(blocking=False)
            locks.for_writes(NEXT).release()
        finally:
            worker.join(2)
    assert not worker.is_alive()
    assert len(outcomes) == 1
    assert isinstance(outcomes[0], PlanSettlementBusy)
    assert units.state.plan_grace is None


def test_allowance_failure_changes_nothing() -> None:
    from tests.identity_fakes import BrokenAllowances

    units = _units(rule(), _rule(NEXT, SyncRuleState.ENABLED))
    expired(units)
    before = units.state.plan_grace
    with pytest.raises(RuntimeError):
        engine(units, BrokenAllowances()).settle()
    assert units.state.rules[NEXT].synchronizes
    assert units.state.plan_grace == before


def test_explicit_unlimited_plan_releases_all_holds() -> None:
    from tests.plans import FREE

    plans = _plans()
    plans.change(replace(FREE, limits=replace(FREE.limits, rules=None)), NOW)
    units = _units(rule().hold(), _rule(NEXT, SyncRuleState.ENABLED).hold())
    expired(units)
    assert engine(units, plans).settle() is None
    assert all(each.synchronizes for each in units.state.rules.values())
    assert units.state.plan_grace is None


def test_settle_locks_are_shared_per_user_but_independent_between_users() -> None:
    from tests.users import OTHER_USER

    locks = SettleLocks()
    assert locks.for_user(USER) is locks.for_user(USER)
    assert locks.for_user(USER) is not locks.for_user(OTHER_USER)
