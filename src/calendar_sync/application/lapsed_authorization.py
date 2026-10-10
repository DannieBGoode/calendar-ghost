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
        cause=failure.cause,
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

        A lapse stops every enabled rule of the account, however it was found: a sync run, a
        preview, a removal, or an access check. A request begun before the account's latest
        Reauthorization used credentials that were since replaced, so its refusal lapses
        nothing, stops nothing, and opens no Incident.
        """
        now = self.clock.now()
        with self.unit_of_work() as uow:
            lapsed = uow.accounts.lapse(account_id, attempted_at=attempted_at)
            enabled = tuple(
                rule.id
                for rule in uow.rules.list()
                if rule.state is SyncRuleState.ENABLED and rule.uses_account(account_id)
            )
            uow.commit()
        if not lapsed:
            return False
        for rule_id in enabled:
            self._stop(rule_id, account_id)
        incident = lapse_incident(account_id, failure)
        if self.incidents.open(incident, now) and self.notifications is not None:
            self.notifications.incident_opened(incident, now)
        return True

    def restored(self, account_id: ConnectedAccountId, *, accepted_at: datetime) -> int:
        """The provider accepted a request begun at `accepted_at`: clear a lapse from requests
        begun before it, and resume the rules it alone stopped; how many resumed.

        A refusal of a request begun later stands, and nothing resumes. A rule whose other
        account still has no valid authorization stays stopped until that account is restored
        too.
        """
        with self.unit_of_work() as uow:
            uow.accounts.clear_lapse(account_id, requested_before=accepted_at)
            authorized = uow.accounts.authorized(account_id)
            uow.commit()
        if not authorized:
            return 0
        with self.unit_of_work() as uow:
            # Every rule of the account, not only those already stopped: a run may stop one
            # until its write lock is released, and `_resume` decides under that lock.
            waiting = tuple(rule.id for rule in uow.rules.list() if rule.uses_account(account_id))
        # A newer lapse recorded since keeps its reopened Incident open.
        self.incidents.resolve(
            authorization_key(account_id),
            self.clock.now(),
            IncidentResolution.ACCESS_RESTORED,
            while_authorized=account_id,
        )
        return sum(self._resume(rule_id) for rule_id in waiting)

    def _stop(self, rule_id: SyncRuleId, account_id: ConnectedAccountId) -> None:
        """Stop an enabled rule until the account is authorized again; waits for any write."""
        with self.locks.for_writes(rule_id), self.unit_of_work() as uow:
            rule = uow.rules.get(rule_id)
            if rule is None or rule.state is not SyncRuleState.ENABLED:
                return
            # Restoring decides for each rule under this same write lock, after clearing the lapse.
            # If it cleared the lapse before this check, the rule keeps running; if after, it
            # waits for this lock and then finds the rule awaiting and resumes it.
            if uow.accounts.authorized(account_id):
                return
            uow.rules.save(rule.degrade(awaiting_reauthorization=True))
            uow.commit()

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
