"""Recording stand-ins for the services a scheduled pass runs one User's rules with."""

from __future__ import annotations

from datetime import datetime

from calendar_sync.application.sync.errors import ProviderFailure
from calendar_sync.application.sync.synchronization import SyncRunResult
from calendar_sync.domain.model import SyncRuleId


class RecordingExecuteRule:
    def __init__(self, outcomes: list[Exception | None]) -> None:
        self.outcomes = outcomes
        self.calls = 0

    def execute(self, rule_id: SyncRuleId, *, full: bool = False) -> SyncRunResult:
        outcome = self.outcomes[self.calls]
        self.calls += 1
        if outcome is not None:
            raise outcome
        return SyncRunResult(rule_id)


class RecordingHealth:
    def __init__(self) -> None:
        self.successes = 0
        self.full_successes = 0
        self.failures: list[ProviderFailure] = []

    def record_success(
        self,
        _rule: object,
        *,
        full_pass_floor: int | None = None,
        full_pass_run: str | None = None,
    ) -> None:
        self.successes += 1
        self.full_successes += full_pass_floor is not None
        self.full_pass_run = full_pass_run

    def audit_floor(self) -> int:
        return 0

    def record_failure(
        self, _rule: object, failure: ProviderFailure, *, attempted_at: datetime | None = None
    ) -> None:
        self.failures.append(failure)

    def finish_interrupted_lapses(self) -> int:
        return 0
