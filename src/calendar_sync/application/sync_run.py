from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from calendar_sync.application.errors import RuleNotExecutable
from calendar_sync.application.ports import UnitOfWork
from calendar_sync.domain.model import EventRef, SyncAction, SyncRule, SyncRuleState

OUTCOMES = {SyncAction.IGNORE: "skipped", SyncAction.CONFLICT: "blocked"}


@dataclass(slots=True)
class SyncRunContext:
    """State shared by every decision of one Sync Run."""

    uow: UnitOfWork
    rule: SyncRule
    run_id: str
    counts: dict[SyncAction, int]
    window_start: datetime
    """Unmapped single events that ended before this instant are not projected."""
    reproject: bool = False
    handled: set[EventRef] = field(default_factory=set)
    repaired: set[EventRef] = field(default_factory=set)
    """Source series already repaired this run, so a repair never recurses."""


def require_unchanged(run: SyncRunContext) -> None:
    """Stop before writing if the rule was paused, edited, or removed during this run."""
    current = run.uow.rules.get(run.rule.id)
    if (
        current is None
        or current.state is not SyncRuleState.ENABLED
        or current.material_signature != run.rule.material_signature
    ):
        raise RuleNotExecutable("sync rule changed during synchronization; run stopped")
