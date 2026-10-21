"""The manual-run limit: Sync Now, Reconcile Now, and Rule Preview, counted together for each
User whose Plan limits anything, so a script pressing them runs no more often than the shortest
sync interval (ADR 0038)."""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

from calendar_sync.application.shared.errors import ApplicationError
from calendar_sync.application.sync.plan_ports import Allowances
from calendar_sync.domain.access import UserId
from calendar_sync.domain.model import SyncRuleId

logger = logging.getLogger(__name__)

MANUAL_RUNS = 12
"""How many manual runs a User whose Plan limits anything may start in any MANUAL_RUN_WINDOW.
Twelve an hour is one run every 5 minutes, the shortest sync interval, so a script pressing Sync
Now polls no faster than the fastest polling Plan. It still lets a User set up 5 rules, preview
each twice, and run Sync Now a few times."""
MANUAL_RUN_WINDOW = timedelta(hours=1)
"""The sliding window MANUAL_RUNS is counted over."""


class RunThrottle(Protocol):
    """Counts each User's manual runs in a sliding window."""

    def admit(self, user: UserId) -> float:
        """Record a run of the User and return 0.0 when the window has room for it; otherwise
        record nothing and return the seconds until a run may start, at most the window. The
        check and the record happen under one lock, so concurrent runs cannot all pass."""
        ...


class ManualRunsThrottled(ApplicationError):
    """The User started many manual runs in a short time; try again later."""

    def __init__(self, retry_after: float) -> None:
        # Rounded up, so a client that waits as told is not refused again.
        self.retry_after = max(1, math.ceil(retry_after))
        super().__init__(
            f"many manual runs in a short time; try again in {self.retry_after} seconds"
        )


@dataclass(slots=True)
class AdmitManualRun:
    """Admits one manual run of the owner, then runs it.

    Only a User whose Plan limits anything is counted (`Allowance.limits_manual_runs`). Fails
    open: when the owner's Allowance cannot be read, the run goes ahead and nothing is counted, so
    a fault in Plans never stops a run.
    """

    allowances: Allowances
    throttle: RunThrottle
    owner: UserId

    def execute[T](self, run: Callable[[SyncRuleId], T], rule_id: SyncRuleId) -> T:
        """Run `run` on the rule once the throttle admits it; raises ManualRunsThrottled, without
        running it, when the owner must wait."""
        if self._counted():
            wait = self.throttle.admit(self.owner)
            if wait > 0:
                raise ManualRunsThrottled(wait)
        return run(rule_id)

    def _counted(self) -> bool:
        try:
            return self.allowances.of(self.owner).limits_manual_runs
        except Exception as error:
            # Only the class: the error's text could name more than the User.
            logger.warning(
                "Could not read the Allowance of User %s; their manual run goes ahead (%s)",
                self.owner.value,
                error.__class__.__name__,
            )
            return False
