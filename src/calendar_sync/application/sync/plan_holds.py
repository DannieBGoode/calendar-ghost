"""Transactional Plan settlement and whole-set keep choices for one User."""

from collections.abc import Collection, Iterator, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field, replace
from threading import Lock
from typing import Protocol

from calendar_sync.application.shared.errors import ApplicationError
from calendar_sync.application.shared.ports import Clock
from calendar_sync.application.sync.errors import RuleNotFound
from calendar_sync.application.sync.locking import RuleLocks
from calendar_sync.application.sync.plan_ports import Allowances
from calendar_sync.application.sync.ports import UnitOfWork, UnitOfWorkFactory
from calendar_sync.domain.access import UserId
from calendar_sync.domain.model import SyncRuleId
from calendar_sync.domain.plan_hold import (
    PlanNotice,
    PlanNoticeKind,
    RulePlace,
    RuleStanding,
    Settlement,
    settle,
)


class PlanSettlementBusy(ApplicationError):
    """A rule is being written; retry this User without waiting for provider work."""


class TooManyKeptRules(ApplicationError):
    def __init__(self, limit: int) -> None:
        super().__init__(f"choose at most {limit} rules to keep")
        self.limit = limit


class PlanNotices(Protocol):
    def plan_changed(self, notice: PlanNotice) -> None: ...


@dataclass(slots=True)
class SettleLocks:
    """One shared instance per process serializes settlement and choices for each User."""

    _locks: dict[UserId, Lock] = field(default_factory=dict)
    _guard: Lock = field(default_factory=Lock)

    def for_user(self, owner: UserId) -> Lock:
        with self._guard:
            return self._locks.setdefault(owner, Lock())


@dataclass(slots=True)
class PlanHolds:
    unit_of_work: UnitOfWorkFactory
    owner: UserId
    allowances: Allowances
    locks: RuleLocks
    settle_locks: SettleLocks
    clock: Clock

    def settle(self, notify: bool = True) -> PlanNotice | None:
        with _locked_transaction(self) as (uow, locked):
            limit = self.allowances.of(self.owner).limits.rules
            decision = settle(
                uow.rules.standings(),
                limit,
                uow.plan_grace.get(),
                uow.plan_grace.admissions(),
                self.clock.now(),
                active=uow.user_active(),
            )
            held = _apply(uow, decision, locked)
            grace = decision.grace
            if grace is not None and _count(uow.rules.standings()) <= grace.rule_limit:
                grace = None
            uow.plan_grace.save(grace)
            uow.commit()
        return _notice(decision.notice, held) if notify else None


@contextmanager
def _locked_transaction(holds: PlanHolds) -> Iterator[tuple[UnitOfWork, frozenset[SyncRuleId]]]:
    with holds.settle_locks.for_user(holds.owner), ExitStack() as stack:
        with holds.unit_of_work() as discovery:
            locked = frozenset(each.rule_id for each in discovery.rules.standings())
        for rule_id in sorted(locked, key=lambda each: each.value):
            lock = holds.locks.for_writes(rule_id)
            if not lock.acquire(blocking=False):
                raise PlanSettlementBusy("a rule is being written; retry the Plan settlement")
            stack.callback(lock.release)
        with holds.unit_of_work() as uow:
            # First statement: no stale read snapshot, and no writer-before-rule-lock inversion.
            uow.plan_grace.acquire()
            yield uow, locked


def _count(standings: Sequence[RuleStanding]) -> int:
    return sum(each.place is not RulePlace.HELD for each in standings)


def _apply(uow: UnitOfWork, decision: Settlement, locked: frozenset[SyncRuleId]) -> int:
    held = 0
    for rule_id in decision.hold:
        if rule_id in locked:
            rule = uow.rules.get(rule_id)
            if rule is not None:
                uow.rules.save(rule.hold())
                held += 1
    for rule_id in decision.give_up:
        if rule_id in locked:
            rule = uow.rules.get(rule_id)
            if rule is not None:
                uow.rules.save(rule.give_up_place())
    for rule_id in decision.release:
        if rule_id in locked:
            _release(uow, rule_id)
    return held


def _release(uow: UnitOfWork, rule_id: SyncRuleId) -> None:
    rule = uow.rules.get(rule_id)
    if rule is None:
        raise RuleNotFound(rule_id.value)
    authorized = all(
        uow.accounts.authorized(endpoint.connected_account_id)
        for endpoint in (rule.source, rule.destination)
    )
    uow.rules.save(rule.release_hold(authorized))


def _notice(notice: PlanNotice | None, held: int) -> PlanNotice | None:
    if notice is not None and notice.kind is PlanNoticeKind.RULES_HELD:
        return replace(notice, held=held) if held else None
    return notice


@dataclass(slots=True)
class ChooseKeptRules:
    holds: PlanHolds

    def execute(self, chosen: Collection[SyncRuleId]) -> None:
        chosen = frozenset(chosen)
        with _locked_transaction(self.holds) as (uow, locked):
            limit = self.holds.allowances.of(self.holds.owner).limits.rules
            standings = uow.rules.standings()
            _validate_choice(standings, chosen, limit, locked)
            uow.rules.keep(chosen)
            if uow.user_active():
                _apply_choice(uow, uow.rules.standings(), limit, locked)
            uow.commit()


def _validate_choice(
    standings: Sequence[RuleStanding],
    chosen: frozenset[SyncRuleId],
    limit: int | None,
    locked: frozenset[SyncRuleId],
) -> None:
    if not chosen.issubset(each.rule_id for each in standings):
        raise RuleNotFound("a chosen rule is not eligible to keep")
    if limit is not None and len(chosen) > limit:
        raise TooManyKeptRules(limit)
    if any(
        each.rule_id not in locked and each.kept != (each.rule_id in chosen) for each in standings
    ):
        raise PlanSettlementBusy("eligible rules changed; retry the whole keep choice")


def _apply_choice(
    uow: UnitOfWork,
    standings: Sequence[RuleStanding],
    limit: int | None,
    locked: frozenset[SyncRuleId],
) -> None:
    held = sorted(
        (
            each
            for each in standings
            if each.place is RulePlace.HELD
            and each.rule_id in locked
            and (each.kept or limit is None)
        ),
        key=lambda each: each.rank,
    )
    free = len(held) if limit is None else max(0, limit - _count(standings))
    for each in held[:free]:
        _release(uow, each.rule_id)
        uow.plan_grace.admit()
    worst = sorted(
        (
            each
            for each in standings
            if each.place is RulePlace.COUNTED and not each.kept and each.rule_id in locked
        ),
        key=lambda each: each.rank,
        reverse=True,
    )
    for releasing, holding in zip(held[free:], worst, strict=False):
        rule = uow.rules.get(holding.rule_id)
        if rule is None:
            raise RuleNotFound(holding.rule_id.value)
        uow.rules.save(rule.hold())
        _release(uow, releasing.rule_id)
