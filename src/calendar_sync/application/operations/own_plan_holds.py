"""Read-only grace information for Your plan, derived from the current Allowance."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from calendar_sync.domain.plan_hold import PlanGrace, RulePlace, RuleStanding


@dataclass(frozen=True, slots=True)
class OwnPlanGrace:
    holds_at: datetime
    rule_limit: int
    held: int
    """Counted rules predicted to become held, excluding already held rules."""
    reserved: int
    """Rule Replacement drafts predicted to give up their reserved places."""


def grace_view(
    grace: PlanGrace | None,
    standings: Sequence[RuleStanding],
    limit: int | None,
    admissions: int,
) -> OwnPlanGrace | None:
    """Show a meaningful stored deadline without settling or inventing a new one.

    Further lowering or a new admission requires settlement to record a fresh grace. A raise
    retains the stored deadline and recalculates losses under the current limit, as settlement
    does. An expired eligible grace remains visible until the next settlement finishes it.
    """
    if grace is None or limit is None or limit < grace.rule_limit or admissions > grace.admissions:
        return None
    counted = sorted(
        (each for each in standings if each.place is not RulePlace.HELD),
        key=lambda each: each.rank,
    )
    if len(counted) <= limit:
        return None
    losers = counted[limit:]
    return OwnPlanGrace(
        grace.holds_at,
        limit,
        sum(each.place is RulePlace.COUNTED for each in losers),
        sum(each.place is RulePlace.RESERVED for each in losers),
    )
