"""Scheduled rules, Sync Run identifiers, and provider call measurement ports."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from calendar_sync.domain.access import UserId
from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.model import SyncRule


@dataclass(frozen=True, slots=True)
class ScheduledRule:
    """An enabled rule of a User who may sign in, with what the scheduler needs to run it."""

    owner: UserId
    rule: SyncRule
    last_full_succeeded_at: datetime | None
    """When the rule's last successful full run completed, so its daily pass is due per rule."""
    last_run_at: datetime | None = None
    """When the rule's last sync completed, from any origin, failed or not; None if it never
    ran."""
    failing: bool = False
    """Whether its last sync failed, or a store that keeps failure streaks has one recorded for
    it."""
    previewed_at: datetime | None = None
    """When its latest Preview completed; None if it has none."""

    @property
    def always_due(self) -> bool:
        """Whether every scheduled pass lists it, whatever its interval: it never ran, it is
        failing, it was previewed after its last run, or it awaits reprojection."""
        return (
            self.last_run_at is None
            or self.failing
            or (self.previewed_at is not None and self.previewed_at > self.last_run_at)
            or self.rule.reprojection_required
        )


class RunIdGenerator(Protocol):
    """Identifies one Sync Run's Audit Entries.

    Run identifiers are persisted and shown in Activity, so they stay 32 lowercase hex characters.
    """

    def new_run_id(self) -> str: ...


@dataclass(slots=True)
class ProviderCallCounts:
    """How many calls went to one provider, and how many of them did not get what they asked."""

    calls: int = 0
    rate_limited: int = 0
    """Calls the provider refused for its rate limit or quota."""
    failed: int = 0
    """Calls with no answer, or answered with an error other than a rate limit or not found."""


@dataclass(slots=True)
class ProviderCallTally:
    """The provider calls one run made so far; the adapter adds each call as it returns."""

    calls: int = 0
    seconds: float = 0.0
    slowest_seconds: float = 0.0
    rate_limited: int = 0
    """Calls the provider refused for its rate limit or quota."""
    server_errors: int = 0
    """Calls the provider answered with a server error."""
    token_refreshes: int = 0
    """Access tokens renewed during the run."""
    providers: dict[ProviderKind, ProviderCallCounts] = field(default_factory=dict)
    """The same calls by provider, as each User's resource use counts them."""


class ProviderCallStats(Protocol):
    def measure(self) -> AbstractContextManager[ProviderCallTally]:
        """Tally the provider calls made in this context, by this thread, until it exits."""
        ...
