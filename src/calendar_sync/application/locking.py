from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock

from calendar_sync.domain.model import SyncRuleId


@dataclass(slots=True)
class RuleLocks:
    """Serializes every operation that writes on behalf of one Directional Sync Rule."""

    _locks: dict[SyncRuleId, Lock] = field(default_factory=dict)
    _guard: Lock = field(default_factory=Lock)

    def for_rule(self, rule_id: SyncRuleId) -> Lock:
        with self._guard:
            return self._locks.setdefault(rule_id, Lock())
