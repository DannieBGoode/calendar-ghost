"""Rule health: when a failed run stops its rule, and when rule trouble becomes an Incident.

These are product rules (CONTEXT.md: Degraded Rule, Provider Incident, Lapsed Authorization).
The application applies them through its ports, locks, and notifications."""

from __future__ import annotations

from dataclasses import dataclass

from calendar_sync.domain.incidents import IncidentCategory, IncidentMessage, IncidentReport
from calendar_sync.domain.model import ConnectedAccountId, SyncRuleId
from calendar_sync.domain.providers import (
    AUTHORIZATION_FAILURES,
    ProviderFailureFacts,
    ProviderFailureKind,
)

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


def _failure_message(code: str, failure: ProviderFailureFacts) -> IncidentMessage:
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
    def summary(failure: ProviderFailureFacts) -> str:
        """What failed, naming the provider when the failure says which one (ADR 0022)."""
        return failure.summary

    @staticmethod
    def provider_key(rule_id: SyncRuleId) -> str:
        return f"provider:{rule_id.value}"

    @staticmethod
    def blocked_key(rule_id: SyncRuleId) -> str:
        return f"blocked:{rule_id.value}"

    def after_failure(
        self, rule_id: SyncRuleId, failure: ProviderFailureFacts, consecutive_failures: int
    ) -> FailureResponse:
        if failure.kind in AUTHORIZATION_FAILURES and failure.account_id is not None:
            return FailureResponse(degrade=True, incident=None, lapsed=failure.account_id)
        degrade = failure.kind in INTERVENTION_FAILURES
        if not degrade and consecutive_failures < self.threshold:
            return FailureResponse(degrade=False, incident=None)
        return FailureResponse(degrade, self.provider_incident(rule_id, failure))

    def provider_incident(
        self, rule_id: SyncRuleId, failure: ProviderFailureFacts
    ) -> IncidentReport:
        """The rule's one provider Incident, naming the account whose request failed."""
        return IncidentReport(
            self.provider_key(rule_id),
            rule_id,
            failure.kind.incident_category,
            self.summary(failure),
            account_id=failure.account_id,
            message=_failure_message("provider_failure", failure),
            cause=failure.provider_cause,
            provider=failure.provider,
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
            IncidentCategory.CONFLICT,
            f"{events} could not be synced and {verb} still blocked at the daily check.",
            message=IncidentMessage("events_still_blocked", {"count": persisting}),
        )

    def removal_blocked(self, rule_id: SyncRuleId, failure: ProviderFailureFacts) -> IncidentReport:
        return IncidentReport(
            f"removal:{rule_id.value}",
            rule_id,
            failure.kind.incident_category,
            f"Rule Removal stopped: {self.summary(failure)}",
            account_id=failure.account_id,
            message=_failure_message("removal_stopped", failure),
            cause=failure.provider_cause,
            provider=failure.provider,
        )
