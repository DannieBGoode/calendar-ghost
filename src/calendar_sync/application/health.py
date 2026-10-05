"""Rule health: when a failed run degrades its rule and when rule trouble becomes an Incident."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from calendar_sync.application.errors import (
    AUTHORIZATION_FAILURES,
    ProviderFailure,
    ProviderFailureKind,
)
from calendar_sync.application.lapsed_authorization import LapsedAuthorizations
from calendar_sync.application.locking import RuleLocks
from calendar_sync.application.ports import (
    Clock,
    IncidentMessage,
    IncidentNotifications,
    IncidentReport,
    IncidentRepository,
    IncidentResolution,
    RuleHealthRecords,
    UnitOfWorkFactory,
)
from calendar_sync.domain.model import ConnectedAccountId, SyncRule, SyncRuleId, SyncRuleState

PROVIDER_INCIDENT_THRESHOLD = 3
"""Consecutive failed runs after which a temporary or rate-limited condition opens an Incident."""

# Retrying cannot resolve these, so the rule stops until the administrator acts.
INTERVENTION_FAILURES = AUTHORIZATION_FAILURES | {
    ProviderFailureKind.PERMANENT,
    ProviderFailureKind.INFRASTRUCTURE,
}


@dataclass(frozen=True, slots=True)
class FailureResponse:
    degrade: bool
    incident: IncidentReport | None
    lapsed: ConnectedAccountId | None = None
    """The account whose authorization lapsed; its own Incident replaces the rule's."""


def _failure_message(code: str, failure: ProviderFailure) -> IncidentMessage:
    return IncidentMessage(
        code,
        {
            "kind": failure.kind.value,
            "provider": failure.provider.value if failure.provider else None,
        },
    )


@dataclass(frozen=True, slots=True)
class RuleHealthPolicy:
    """Pure decisions about a rule's failed runs, persisting blocks, and interrupted removals."""

    threshold: int = PROVIDER_INCIDENT_THRESHOLD

    @staticmethod
    def summary(failure: ProviderFailure) -> str:
        """What failed, naming the provider when the failure says which one (ADR 0022)."""
        return failure.summary

    @staticmethod
    def provider_key(rule_id: SyncRuleId) -> str:
        return f"provider:{rule_id.value}"

    @staticmethod
    def blocked_key(rule_id: SyncRuleId) -> str:
        return f"blocked:{rule_id.value}"

    def after_failure(
        self, rule_id: SyncRuleId, failure: ProviderFailure, consecutive_failures: int
    ) -> FailureResponse:
        if failure.requires_authorization and failure.account_id is not None:
            return FailureResponse(degrade=True, incident=None, lapsed=failure.account_id)
        degrade = failure.kind in INTERVENTION_FAILURES
        if not degrade and consecutive_failures < self.threshold:
            return FailureResponse(degrade=False, incident=None)
        return FailureResponse(degrade, self.provider_incident(rule_id, failure))

    def provider_incident(self, rule_id: SyncRuleId, failure: ProviderFailure) -> IncidentReport:
        """The rule's one provider Incident, naming the account whose request failed."""
        return IncidentReport(
            self.provider_key(rule_id),
            rule_id,
            failure.kind.value,
            self.summary(failure),
            account_id=failure.account_id,
            message=_failure_message("provider_failure", failure),
        )

    def after_full_pass(self, rule_id: SyncRuleId, persisting: int) -> IncidentReport | None:
        """The Incident for blocks a daily pass found again; none resolves an open one."""
        if not persisting:
            return None
        events = "1 event" if persisting == 1 else f"{persisting} events"
        verb = "was" if persisting == 1 else "were"
        return IncidentReport(
            self.blocked_key(rule_id),
            rule_id,
            "conflict",
            f"{events} could not be synced and {verb} still blocked at the daily check.",
            message=IncidentMessage("events_still_blocked", {"count": persisting}),
        )

    def removal_blocked(self, rule_id: SyncRuleId, failure: ProviderFailure) -> IncidentReport:
        return IncidentReport(
            f"removal:{rule_id.value}",
            rule_id,
            failure.kind.value,
            f"Rule Removal stopped: {self.summary(failure)}",
            account_id=failure.account_id,
            message=_failure_message("removal_stopped", failure),
        )


class RunHealth(Protocol):
    """What the scheduler reports after each Sync Run."""

    def audit_floor(self) -> int: ...

    def record_success(
        self,
        rule: SyncRule,
        *,
        full_pass_floor: int | None = None,
        full_pass_run: str | None = None,
    ) -> None: ...

    def record_failure(
        self, rule: SyncRule, failure: ProviderFailure, *, attempted_at: datetime | None = None
    ) -> None: ...


@dataclass(slots=True)
class RuleHealth:
    """Applies RuleHealthPolicy to recorded runs, opening, resolving, and notifying Incidents."""

    unit_of_work: UnitOfWorkFactory
    records: RuleHealthRecords
    incidents: IncidentRepository
    clock: Clock
    locks: RuleLocks = field(default_factory=RuleLocks)
    notifications: IncidentNotifications | None = None
    policy: RuleHealthPolicy = field(default_factory=RuleHealthPolicy)
    lapses: LapsedAuthorizations = field(init=False)

    def __post_init__(self) -> None:
        self.lapses = LapsedAuthorizations(
            self.unit_of_work, self.incidents, self.clock, self.locks, self.notifications
        )

    def audit_floor(self) -> int:
        return self.records.audit_floor()

    def record_success(
        self,
        rule: SyncRule,
        *,
        full_pass_floor: int | None = None,
        full_pass_run: str | None = None,
    ) -> None:
        """Record a successful run; a daily pass also names the audit entry it began after."""
        self.records.clear_failures(rule.id)
        self.incidents.resolve(
            self.policy.provider_key(rule.id),
            self.clock.now(),
            IncidentResolution.SYNC_SUCCEEDED,
        )
        if full_pass_floor is not None:
            self.record_full_pass(rule.id, full_pass_floor, full_pass_run)

    def record_full_pass(self, rule_id: SyncRuleId, floor: int, run_id: str | None = None) -> None:
        """A full pass that began after audit entry `floor` decided every blocked event again.

        Blocks it repeated are persisting and open one Incident; blocks it did not repeat are no
        longer open. Scheduled daily passes and Reconcile Now both report here.
        """
        # Rule Removal holds this lock throughout, so a rule removed after its pass finished is
        # never given an incident no run could resolve. Notifying waits until the lock is
        # released, so a slow webhook never holds up the rule's other commands.
        with self.locks.for_rule(rule_id):
            opened = self._record_full_pass(rule_id, floor, run_id)
        if opened is not None:
            self._notify(*opened)

    def _record_full_pass(
        self, rule_id: SyncRuleId, floor: int, run_id: str | None
    ) -> tuple[IncidentReport, datetime] | None:
        now = self.clock.now()
        persisting = self.records.record_block_check(rule_id, floor, run_id, now)
        if persisting is None:
            return None
        incident = self.policy.after_full_pass(rule_id, persisting)
        if incident is None:
            self.incidents.resolve(
                self.policy.blocked_key(rule_id), now, IncidentResolution.BLOCKS_CLEARED
            )
            return None
        return (incident, now) if self.incidents.open(incident, now) else None

    def record_failure(
        self, rule: SyncRule, failure: ProviderFailure, *, attempted_at: datetime | None = None
    ) -> None:
        """Record a failed run that began at `attempted_at`, or just now when not given."""
        now = self.clock.now()
        consecutive = self.records.record_failure(rule.id, failure.kind, now)
        response = self.policy.after_failure(rule.id, failure, consecutive)
        if response.lapsed is not None and not self.lapses.lapsed(
            response.lapsed, failure, attempted_at=attempted_at or now
        ):
            # Reauthorized while the run was in flight; its refusal stops nothing.
            return
        if response.degrade:
            self._degrade(rule, awaiting_reauthorization=response.lapsed is not None)
        if response.incident is not None and self.incidents.open(response.incident, now):
            self._notify(response.incident, now)

    def removal_blocked(
        self, rule_id: SyncRuleId, failure: ProviderFailure, *, attempted_at: datetime
    ) -> None:
        """Open or refresh the one Incident for a removal stopped by lost authorization."""
        now = self.clock.now()
        incident = self.policy.removal_blocked(rule_id, failure)
        if self.incidents.open(incident, now):
            self._notify(incident, now)
        if failure.account_id is not None:
            self.lapses.lapsed(failure.account_id, failure, attempted_at=attempted_at)

    def recovery_blocked(
        self, rule_id: SyncRuleId, failure: ProviderFailure, *, attempted_at: datetime
    ) -> None:
        """Record the lost authorization a preview met.

        A rule whose calendars belong to two accounts can stop on the first and meet the second
        only while recovering, so the second account's authorization lapses too. Without the
        account, the rule's own Incident names the failure instead.
        """
        if failure.account_id is not None:
            self.lapses.lapsed(failure.account_id, failure, attempted_at=attempted_at)
            return
        now = self.clock.now()
        incident = self.policy.provider_incident(rule_id, failure)
        if self.incidents.open(incident, now):
            self._notify(incident, now)

    def _degrade(self, rule: SyncRule, *, awaiting_reauthorization: bool) -> None:
        if rule.state is not SyncRuleState.ENABLED:
            return
        with self.locks.for_writes(rule.id), self.unit_of_work() as uow:
            current = uow.rules.get(rule.id)
            if current is not None and current.state is SyncRuleState.ENABLED:
                uow.rules.save(current.degrade(awaiting_reauthorization=awaiting_reauthorization))
                uow.commit()

    def _notify(self, incident: IncidentReport, at: datetime) -> None:
        if self.notifications is not None:
            self.notifications.incident_opened(incident, at)
