from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock

from calendar_sync.domain.model import SyncRuleId


@dataclass(slots=True)
class RuleLocks:
    """Per-rule locks shared by every operation that writes on behalf of one rule.

    ``for_rule`` serializes whole runs: synchronization, reconciliation, and removal. ``for_writes``
    is short: it spans each provider write with its stop check, and every read-modify-write of the
    rule itself, so lifecycle changes never overwrite each other and wait for at most one
    in-flight write instead of a whole run. Acquire ``for_rule`` before ``for_writes``, never the
    reverse.
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
