"""Lapsed Authorization: when a provider stops accepting a Connected Account (ADR 0027)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from calendar_sync.application.shared.ports import Clock
from calendar_sync.application.sync.errors import ProviderFailure
from calendar_sync.application.sync.locking import RuleLocks
from calendar_sync.application.sync.ports import (
    IncidentNotifications,
    IncidentRepository,
    UnitOfWork,
    UnitOfWorkFactory,
)
from calendar_sync.domain.incidents import IncidentMessage, IncidentReport, IncidentResolution
from calendar_sync.domain.model import ConnectedAccountId, SyncRule, SyncRuleId, SyncRuleState


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
        cause=failure.provider_cause,
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
        self._resolve(account_id)
        return sum(self._resume(rule_id) for rule_id in waiting)

    def resume_restored(self) -> int:
        """Finish restorations an interruption left; how many rules resumed.

        Reauthorizing clears a lapse with the new credentials, and `restored` then commits each
        step on its own, so a stop or failure between them leaves rules the lapse alone stopped
        while their accounts are authorized again. Each scheduler pass calls this, so they resume
        and their accounts' Incidents resolve without another Reauthorization (ADR 0027).
        """
        with self.unit_of_work() as uow:
            waiting = tuple(
                rule
                for rule in uow.rules.list()
                if rule.state is SyncRuleState.DEGRADED and rule.awaiting_reauthorization
            )
            accounts = {
                account
                for rule in waiting
                for account in (
                    rule.source.connected_account_id,
                    rule.destination.connected_account_id,
                )
            }
            authorized = {account for account in accounts if uow.accounts.authorized(account)}
        for account_id in sorted(authorized, key=lambda account: account.value):
            self._resolve(account_id)
        return sum(self._resume(rule.id) for rule in waiting)

    def _resolve(self, account_id: ConnectedAccountId) -> None:
        # A newer lapse recorded since keeps its reopened Incident open.
        self.incidents.resolve(
            authorization_key(account_id),
            self.clock.now(),
            IncidentResolution.ACCESS_RESTORED,
            while_authorized=account_id,
        )

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
                or not _both_authorized(uow, rule)
            ):
                return False
            uow.rules.save(rule.resume_after_reauthorization())
            # Recording a lapse takes no rule lock, so check again inside the write the save
            # began, which holds off other writers: a lapse committed before this check keeps
            # the rule stopped, and one committed after it finds the rule enabled and stops it.
            if not _both_authorized(uow, rule):
                return False
            uow.commit()
        return True


def _both_authorized(uow: UnitOfWork, rule: SyncRule) -> bool:
    return uow.accounts.authorized(rule.source.connected_account_id) and uow.accounts.authorized(
        rule.destination.connected_account_id
    )
