"""Fair, bounded Plan settlement before a scheduled pass lists rules."""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from calendar_sync.application.operations.ports import UserPlanStanding
from calendar_sync.application.shared.ports import Clock
from calendar_sync.application.sync.plan_holds import PlanHolds
from calendar_sync.application.sync.plan_ports import Allowances
from calendar_sync.domain.access import UserId
from calendar_sync.domain.plan_hold import PlanNotice, settle

logger = logging.getLogger(__name__)
MAX_SETTLEMENTS = 100


@dataclass(slots=True)
class ScheduledPlanHolds:
    allowances: Allowances
    holds_for: Callable[[UserId], PlanHolds]
    clock: Clock
    _after: str = field(default="", init=False)

    def settle(
        self, standings: Sequence[UserPlanStanding]
    ) -> tuple[tuple[UserId, PlanNotice], ...]:
        try:
            allowances = self.allowances.of_users({each.owner for each in standings})
        except Exception as error:
            logger.error(
                "Reading Plan allowances failed; settling nobody (%s)", type(error).__name__
            )
            return ()
        ordered = sorted(standings, key=lambda each: each.owner.value)
        ordered = [each for each in ordered if each.owner.value > self._after] + [
            each for each in ordered if each.owner.value <= self._after
        ]
        notices = []
        attempts = 0
        now = self.clock.now()
        for each in ordered:
            if not _changed(each, allowances[each.owner].limits.rules, now):
                continue
            self._after = each.owner.value
            attempts += 1
            try:
                notice = self.holds_for(each.owner).settle()
                if notice is not None:
                    notices.append((each.owner, notice))
            except Exception as error:
                logger.error(
                    "Plan settlement failed for User %s; trying again later (%s)",
                    each.owner.value,
                    type(error).__name__,
                )
            if attempts == MAX_SETTLEMENTS:
                break
        return tuple(notices)


def _changed(each: UserPlanStanding, limit: int | None, now: datetime) -> bool:
    try:
        decision = settle(
            each.standings, limit, each.grace, each.admissions, now, active=each.active
        )
        return bool(
            decision.hold or decision.give_up or decision.release or decision.grace != each.grace
        )
    except Exception as error:
        logger.error(
            "Reading Plan standing failed for User %s; skipping holds (%s)",
            each.owner.value,
            type(error).__name__,
        )
        return False
