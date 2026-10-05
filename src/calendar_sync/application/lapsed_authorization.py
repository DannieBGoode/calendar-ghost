"""Lapsed Authorization: when a provider stops accepting a Connected Account (ADR 0027)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from calendar_sync.application.errors import ProviderFailure
from calendar_sync.application.locking import RuleLocks
from calendar_sync.application.ports import (
    Clock,
    IncidentMessage,
    IncidentNotifications,
    IncidentReport,
    IncidentRepository,
    IncidentResolution,
    UnitOfWorkFactory,
)
from calendar_sync.domain.model import ConnectedAccountId, SyncRuleId, SyncRuleState


def authorization_key(account_id: ConnectedAccountId) -> str:
    """The key of the one Incident an account's Lapsed Authorization opens."""
    return f"authorization:{account_id.value}"


def lapse_incident(account_id: ConnectedAccountId, failure: ProviderFailure) -> IncidentReport:
    """The account's Incident: one for every rule the lapse stops, so one notification."""
    return IncidentReport(
        authorization_key(account_id),
        None,
        failure.kind.value,
        failure.summary,
        account_id=account_id,
        message=IncidentMessage(
            "authorization_lapsed",
            {
                "kind": failure.kind.value,
                "provider": failure.provider.value if failure.provider else None,
            },
        ),
    )


@dataclass(slots=True)
class LapsedAuthorizations:
    """Marks an account the provider refused and resumes what the lapse alone stopped."""

    unit_of_work: UnitOfWorkFactory
    incidents: IncidentRepository
    clock: Clock
    locks: RuleLocks = field(default_factory=RuleLocks)
    notifications: IncidentNotifications | None = None

    def lapsed(
        self, account_id: ConnectedAccountId, failure: ProviderFailure, *, attempted_at: datetime
    ) -> bool:
        """Record that the provider refused a request made at `attempted_at`; whether it lapsed.

        A request begun before the account's latest Reauthorization used credentials that were
        since replaced, so its refusal lapses nothing and opens no Incident.
        """
        now = self.clock.now()
        with self.unit_of_work() as uow:
            lapsed = uow.accounts.lapse(account_id, now, attempted_at=attempted_at)
            uow.commit()
        if not lapsed:
            return False
        incident = lapse_incident(account_id, failure)
        if self.incidents.open(incident, now) and self.notifications is not None:
            self.notifications.incident_opened(incident, now)
        return True

    def restored(self, account_id: ConnectedAccountId) -> int:
        """Clear the account's lapse and resume the rules it alone stopped; how many resumed.

        A rule whose other account still has no valid authorization stays stopped until that
        account is restored too.
        """
        with self.unit_of_work() as uow:
            uow.accounts.clear_lapse(account_id)
            uow.commit()
        with self.unit_of_work() as uow:
            # Every rule of the account, not only those already stopped: a run may stop one
            # until its write lock is released, and `_resume` decides under that lock.
            waiting = tuple(rule.id for rule in uow.rules.list() if rule.uses_account(account_id))
        self.incidents.resolve(
            authorization_key(account_id), self.clock.now(), IncidentResolution.ACCESS_RESTORED
        )
        return sum(self._resume(rule_id) for rule_id in waiting)

    def _resume(self, rule_id: SyncRuleId) -> bool:
        with self.locks.for_writes(rule_id), self.unit_of_work() as uow:
            rule = uow.rules.get(rule_id)
            if (
                rule is None
                or rule.state is not SyncRuleState.DEGRADED
                or not rule.awaiting_reauthorization
                or not uow.accounts.authorized(rule.source.connected_account_id)
                or not uow.accounts.authorized(rule.destination.connected_account_id)
            ):
                return False
            uow.rules.save(rule.resume_after_reauthorization())
            uow.commit()
        return True
