"""The latest outcome of each kind of run a rule had: counts, never content."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.causes import Cause
from calendar_sync.domain.model import SyncRuleId
from calendar_sync.domain.providers import ProviderFailureKind


class RunKind(StrEnum):
    SYNC = "sync"
    RECONCILIATION = "reconciliation"


@dataclass(frozen=True, slots=True)
class RuleRunOutcome:
    """The latest result of one kind of run: counts and a failure category, never content."""

    rule_id: SyncRuleId
    kind: RunKind
    completed_at: datetime
    succeeded: bool
    full_run: bool = False
    created: int = 0
    updated: int = 0
    deleted: int = 0
    conflicts: int = 0
    checked_mappings: int = 0
    drift: int = 0
    failure_kind: ProviderFailureKind | None = None
    failure_cause: Cause | None = None
    """Why a failed run failed (ADR 0031); None for a success. A failure recorded without one
    reads as unknown."""
    failure_provider: ProviderKind | None = None
    """The provider whose answer gave the Cause, so hints can name it; None without a Cause."""
    # When the most recent successful run of this kind completed. The repository keeps it across
    # later failures, so a failed run never erases evidence that calendars were once current.
    last_succeeded_at: datetime | None = None
    # When the most recent successful full run completed, kept across later incremental runs so
    # the daily full pass is due per rule and survives restarts.
    last_full_succeeded_at: datetime | None = None
