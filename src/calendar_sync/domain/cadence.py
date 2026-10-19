"""Sync Cadence: how soon a User's rules run after their sources change (ADR 0036).

Plans decide it (ADR 0028). While Plans are off, every User has the default cadence: Instant Sync,
and Scheduled Sync every five minutes. A Plan's longer interval makes Scheduled Sync run each rule
once per window of that interval instead of at every pass.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta

from calendar_sync.domain.errors import DomainValidationError

SCHEDULED_EVERY = timedelta(minutes=5)
"""How long Scheduled Sync waits between passes, so the shortest poll: a rule polled this often or
more often runs at every pass."""
_SECONDS_PER_DAY = 86_400


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


def scheduled_run_due(
    poll_every: timedelta,
    rule_id: str,
    begins: datetime,
    listed: datetime | None,
    *,
    always_due: bool,
    full_pass_due: bool,
) -> bool:
    """Whether the Scheduled Sync pass that begins at `begins` lists a rule polled every
    `poll_every`; `listed` is when the pass that last listed it began, or None when none did.

    A rule polled every five minutes or less is due at every pass, as is one `always_due`. Any
    other is due once per window of its interval: its windows follow one another from the Unix
    epoch, shifted by the rule's own phase, a hash of its id, so one interval's rules spread over
    its passes instead of all running at one. A rule whose daily full pass is due is also due once
    the pass begins at or after its phase past 00:00 UTC, so restarts and Sync Now cannot keep it
    from its full pass, and the full passes of one interval's rules spread too.
    """
    if always_due or poll_every <= SCHEDULED_EVERY or listed is None:
        return True
    seconds = int(poll_every.total_seconds())
    phase = _phase(rule_id, seconds)
    begun = int(begins.timestamp())
    if _window(int(listed.timestamp()), phase, seconds) < _window(begun, phase, seconds):
        return True
    return full_pass_due and begun % _SECONDS_PER_DAY >= phase


def _phase(rule_id: str, seconds: int) -> int:
    """Where a rule's windows of `seconds` begin, the same in every process and release."""
    digest = hashlib.sha256(rule_id.encode()).digest()
    return int.from_bytes(digest[:8], "big") % seconds


def _window(timestamp: int, phase: int, seconds: int) -> int:
    return (timestamp - phase) // seconds
