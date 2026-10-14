"""Instant Sync across Users (ADR 0036): watch upkeep and the dispatch of Instant Sync Requests.

Both run beside the scheduler and, like it, read every User through the installation-wide unit
of work (ADR 0029). Each User's own work still runs with that User's units: their watch upkeep,
each rule's run through the scheduled pass, and each acknowledgement.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from calendar_sync.application.operations.ports import (
    InstallationUnitOfWorkFactory,
    InstantSyncOwner,
)
from calendar_sync.application.shared.ports import Clock
from calendar_sync.application.sync.instant_sync import CallBudget, UpkeepWatches
from calendar_sync.application.sync.watch_ports import SyncCadencePolicy
from calendar_sync.domain.access import UserId

logger = logging.getLogger(__name__)

QUIET = timedelta(seconds=10)
"""How long a rule's notices must stay quiet before its instant run, so a burst runs it once."""
MAX_WAIT = timedelta(seconds=30)
"""The longest that notices which keep coming hold a rule's instant run back."""
MIN_GAP = timedelta(seconds=30)
"""The shortest time between two instant runs of one rule."""
UPKEEP_BUDGET = 200
"""Provider calls one upkeep cycle may make across every User; the rest waits a cycle."""


@dataclass(slots=True)
class WatchUpkeep:
    """Keeps every User's Calendar Watches as their rules, preference, and Plan want them.

    Each cycle visits Users with nothing planned yet first, then the others in order of their
    earliest due work, so what waited longest goes first. Disabled Users are visited too: nothing
    is wanted for them, so their watches stop.
    """

    installation: InstallationUnitOfWorkFactory
    upkeep_for: Callable[[UserId], UpkeepWatches | None]
    """A User's own upkeep; None where no provider can watch, as without the master key."""
    cadence: SyncCadencePolicy
    address: str | None
    """The installation's public https address; None when it has none."""
    clock: Clock
    _carried: tuple[UserId, ...] = ()
    """The Users the last cycle never reached, then the User it stopped on; they go first."""

    def run(self, budget: int = UPKEEP_BUDGET) -> None:
        calls = CallBudget(budget)
        with self.installation() as installation:
            owners = self._in_turn(installation.instant_sync_owners())
        self._carried = ()
        for position, owner in enumerate(owners):
            self._keep(owner, calls)
            if calls.exhausted:
                # The Users it never reached go first next cycle, then this one, whose upkeep
                # the budget may have cut short. So a User with a large backlog never stays
                # first forever, and two such Users take turns.
                unreached = owners[position + 1 :]
                self._carried = (*(each.user for each in unreached), owner.user)
                logger.info("Watch upkeep spent its provider call budget; the rest waits a cycle")
                return

    def _in_turn(self, owners: Sequence[InstantSyncOwner]) -> list[InstantSyncOwner]:
        """The Users the last cycle never reached, then the User it stopped on, then those with
        nothing planned yet, whose coverage is missing, then the rest by earliest due work."""
        now = self.clock.now()
        carried = {user: turn for turn, user in enumerate(self._carried)}

        def turn(owner: InstantSyncOwner) -> tuple[int, int, datetime, str]:
            if owner.user in carried:
                return 0, carried[owner.user], now, owner.user.value
            if owner.next_due is None:
                return 1, 0, now, owner.user.value
            return 2, 0, owner.next_due, owner.user.value

        return sorted(owners, key=turn)

    def _keep(self, owner: InstantSyncOwner, calls: CallBudget) -> None:
        """One User's upkeep; a failure waits for the next cycle and holds up nobody else."""
        try:
            upkeep = self.upkeep_for(owner.user)
            if upkeep is not None:
                upkeep.execute(allowed=self._allowed(owner), address=self.address, budget=calls)
        except Exception:
            logger.exception("Upkeep of a User's watches failed; trying again next cycle")

    def _allowed(self, owner: InstantSyncOwner) -> bool:
        """Whether the User may have watches: the installation can be reached, the User is
        active and wants Instant Sync, and their Plan includes it."""
        return (
            self.address is not None
            and not owner.disabled
            and owner.wanted
            and self.cadence.cadence(owner.user).instant
        )
