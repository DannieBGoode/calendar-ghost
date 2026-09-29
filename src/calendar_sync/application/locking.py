from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from threading import Lock

from calendar_sync.domain.model import ProjectionHandling, SyncRuleId


class RuleWorkKind(StrEnum):
    PREVIEW = "preview"
    SYNC = "sync"
    RECONCILIATION = "reconciliation"
    REMOVAL = "removal"


@dataclass(slots=True, eq=False)
class RuleWork:
    """Work running for one rule in this process, so a reloaded page can show it again.

    Removal fills ``total`` once it knows its mappings and counts each one it handles in ``done``.
    """

    kind: RuleWorkKind
    started_at: datetime
    handling: ProjectionHandling | None = None
    total: int | None = None
    done: int = 0


@dataclass(slots=True)
class RuleLocks:
    """Per-rule locks shared by every operation that writes on behalf of one rule.

    ``for_rule`` serializes whole runs: synchronization, reconciliation, and removal. ``for_writes``
    is short: it spans each provider write with its stop check, and every read-modify-write of the
    rule itself, so lifecycle changes never overwrite each other and wait for at most one
    in-flight write instead of a whole run. Acquire ``for_rule`` before ``for_writes``, never the
    reverse.

    ``working`` records what runs for a rule while it runs. It is in memory only: the shipped
    deployment is one process, and work never outlives the process that started it.
    """

    _locks: dict[SyncRuleId, Lock] = field(default_factory=dict)
    _write_locks: dict[SyncRuleId, Lock] = field(default_factory=dict)
    _work: dict[SyncRuleId, list[RuleWork]] = field(default_factory=dict)
    _guard: Lock = field(default_factory=Lock)

    def for_rule(self, rule_id: SyncRuleId) -> Lock:
        with self._guard:
            return self._locks.setdefault(rule_id, Lock())

    def for_writes(self, rule_id: SyncRuleId) -> Lock:
        with self._guard:
            return self._write_locks.setdefault(rule_id, Lock())

    def working(self, rule_id: SyncRuleId, work: RuleWork) -> AbstractContextManager[RuleWork]:
        return _Working(self, rule_id, work)

    def _start(self, rule_id: SyncRuleId, work: RuleWork) -> None:
        with self._guard:
            self._work.setdefault(rule_id, []).append(work)

    def _finish(self, rule_id: SyncRuleId, work: RuleWork) -> None:
        with self._guard:
            running = self._work[rule_id]
            running.remove(work)
            if not running:
                del self._work[rule_id]

    def current_work(self, rule_id: SyncRuleId) -> RuleWork | None:
        """A snapshot of the newest work running for the rule, if any."""
        with self._guard:
            running = self._work.get(rule_id)
            return replace(running[-1]) if running else None


@dataclass(frozen=True, slots=True)
class _Working(AbstractContextManager[RuleWork]):
    # Not @contextmanager: its exit assigns __traceback__ on the exception, which frozen
    # slotted dataclass errors such as RemovalInterrupted reject.
    locks: RuleLocks
    rule_id: SyncRuleId
    work: RuleWork

    def __enter__(self) -> RuleWork:
        self.locks._start(self.rule_id, self.work)
        return self.work

    def __exit__(self, *_: object) -> None:
        self.locks._finish(self.rule_id, self.work)
