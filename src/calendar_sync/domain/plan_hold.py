"""Pure settlement of a User's counted, reserved, and held rule places."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from calendar_sync.domain.model import SyncRuleId

GRACE = timedelta(days=7)


class RulePlace(StrEnum):
    COUNTED = "counted"
    RESERVED = "reserved"
    HELD = "held"


@dataclass(frozen=True, slots=True)
class PlanGrace:
    holds_at: datetime
    rule_limit: int
    admissions: int


@dataclass(frozen=True, slots=True)
class RuleStanding:
    rule_id: SyncRuleId
    place: RulePlace
    order: int
    kept: bool

    @property
    def rank(self) -> tuple[bool, int, str]:
        """Lower is better: kept first, then the oldest, with the ID breaking ties."""
        return (not self.kept, self.order, self.rule_id.value)


class PlanNoticeKind(StrEnum):
    GRACE_STARTED = "grace_started"
    RULES_HELD = "rules_held"


@dataclass(frozen=True, slots=True)
class PlanNotice:
    """Counts only, so delivery needs no rule, account, or event identifiers."""

    kind: PlanNoticeKind
    count: int
    limit: int
    held: int
    holds_at: datetime
    reserved: int = 0


@dataclass(frozen=True, slots=True)
class Settlement:
    hold: tuple[SyncRuleId, ...]
    give_up: tuple[SyncRuleId, ...]
    release: tuple[SyncRuleId, ...]
    grace: PlanGrace | None
    notice: PlanNotice | None


def settle(
    standings: Sequence[RuleStanding],
    limit: int | None,
    grace: PlanGrace | None,
    admissions: int,
    now: datetime,
    *,
    active: bool,
) -> Settlement:
    """Decide transitions without touching persistence or changing the standings."""
    if not active:
        return Settlement((), (), (), None, None)
    held = sorted(
        (rule for rule in standings if rule.place is RulePlace.HELD), key=lambda r: r.rank
    )
    if limit is None:
        return Settlement((), (), tuple(rule.rule_id for rule in held), None, None)
    counted = tuple(rule for rule in standings if rule.place is not RulePlace.HELD)
    if len(counted) > limit:
        return _settle_excess(counted, limit, grace, admissions, now)
    release = tuple(rule.rule_id for rule in held[: limit - len(counted)])
    return Settlement((), (), release, None, None)


def _settle_excess(
    counted: Sequence[RuleStanding],
    limit: int,
    grace: PlanGrace | None,
    admissions: int,
    now: datetime,
) -> Settlement:
    restart = grace is None or limit < grace.rule_limit or admissions > grace.admissions
    holds_at = now + GRACE if restart or grace is None else grace.holds_at
    settled_grace = PlanGrace(holds_at, limit, admissions)
    losers = sorted(counted, key=lambda rule: rule.rank, reverse=True)[: len(counted) - limit]
    hold = tuple(rule.rule_id for rule in losers if rule.place is RulePlace.COUNTED)
    give_up = tuple(rule.rule_id for rule in losers if rule.place is RulePlace.RESERVED)
    if restart:
        grace_notice = PlanNotice(
            PlanNoticeKind.GRACE_STARTED, len(counted), limit, len(hold), holds_at, len(give_up)
        )
        return Settlement((), (), (), settled_grace, grace_notice)
    if now < holds_at:
        return Settlement((), (), (), settled_grace, None)
    notice = (
        PlanNotice(PlanNoticeKind.RULES_HELD, len(counted), limit, len(hold), holds_at)
        if hold
        else None
    )
    # Keep an expired grace until a later read proves all excess has gone. A caller can commit
    # only the subset it locked, and must finish any remaining excess without a fresh grace.
    return Settlement(hold, give_up, (), settled_grace, notice)
