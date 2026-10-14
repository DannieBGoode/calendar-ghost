"""Sync Cadence: how soon a User's rules run after their sources change (ADR 0036).

Plans decide it (ADR 0028). While Plans are off, every User has the default cadence: Instant Sync,
and Scheduled Sync every five minutes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from calendar_sync.domain.errors import DomainValidationError

SCHEDULED_EVERY = timedelta(minutes=5)
"""How often Scheduled Sync runs every enabled rule."""


@dataclass(frozen=True, slots=True)
class SyncCadence:
    """How soon a User's rules run after their sources change."""

    instant: bool
    """Whether a rule may run soon after its provider reports a change (Instant Sync)."""
    poll_every: timedelta
    """How often Scheduled Sync runs the rule, whether or not it also syncs instantly."""

    def __post_init__(self) -> None:
        if self.poll_every <= timedelta(0):
            raise DomainValidationError("a sync cadence must poll after some time")


DEFAULT_CADENCE = SyncCadence(instant=True, poll_every=SCHEDULED_EVERY)
"""Every User's cadence while Plans are off (ADR 0028)."""
