from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock

from calendar_sync.domain.model import SyncRuleId


@dataclass(slots=True)
class RuleLocks:
    """Per-rule locks shared by every operation that writes on behalf of one rule.

    ``for_rule`` serializes whole runs: synchronization, reconciliation, and removal. ``for_writes``
    is held only around each provider write and its stop check, so pausing or saving a Material
    Rule Change waits for at most one in-flight write instead of a whole run.
    """

    _locks: dict[SyncRuleId, Lock] = field(default_factory=dict)
    _write_locks: dict[SyncRuleId, Lock] = field(default_factory=dict)
    _guard: Lock = field(default_factory=Lock)

    def for_rule(self, rule_id: SyncRuleId) -> Lock:
        with self._guard:
            return self._locks.setdefault(rule_id, Lock())

    def for_writes(self, rule_id: SyncRuleId) -> Lock:
        with self._guard:
            return self._write_locks.setdefault(rule_id, Lock())
