"""Rule health records and Incident reporting ports of Synchronization."""

from __future__ import annotations

from collections.abc import Collection
from datetime import datetime
from typing import Protocol

from calendar_sync.application.sync.errors import ProviderFailure
from calendar_sync.domain.causes import Cause
from calendar_sync.domain.incidents import IncidentReport, IncidentResolution
from calendar_sync.domain.model import ConnectedAccountId, SyncRuleId
from calendar_sync.domain.providers import ProviderFailureKind


class IncidentRepository(Protocol):
    def open(self, incident: IncidentReport, at: datetime, *, refresh: bool = True) -> bool:
        """Open or refresh the Incident under its key; whether it was newly opened.

        Reopening a resolved Incident starts a new episode, so its opening time is `at`. One
        about an account alone opens only while that account's authorization has lapsed. With
        `refresh=False`, an Incident already open keeps what it says.
        """
        ...

    def resolve(
        self,
        key: str,
        at: datetime,
        resolution: IncidentResolution,
        *,
        while_authorized: ConnectedAccountId | None = None,
    ) -> None:
        """Resolve the Incident under this key, if it is open, recording why.

        With `while_authorized`, only if that account is authorized when it resolves, checked
        atomically, so a lapse recorded just before keeps its Incident open.
        """
        ...

    def accounts_with_open_incidents(self) -> frozenset[ConnectedAccountId]:
        """Every account whose own Incident, the one its Lapsed Authorization opens, is open."""
        ...

    def accounts_lapsed_by(self, causes: Collection[Cause]) -> frozenset[ConnectedAccountId]:
        """Every account whose own Incident is open with one of `causes`, as it last recorded."""
        ...


class IncidentNotifications(Protocol):
    def incident_opened(self, incident: IncidentReport, at: datetime) -> None:
        """Deliver an Incident Notification; best-effort, so it never raises."""
        ...


class RuleHealthRecords(Protocol):
    """What rule health remembers between runs: failure streaks and daily block checks."""

    def record_failure(self, rule_id: SyncRuleId, kind: ProviderFailureKind, at: datetime) -> int:
        """Count one more consecutive failure; how many there are now."""
        ...

    def clear_failures(self, rule_id: SyncRuleId) -> None: ...

    def audit_floor(self) -> int:
        """The newest audit entry now, taken before a full pass so its decisions lie above it."""
        ...

    def record_block_check(
        self, rule_id: SyncRuleId, floor: int, run_id: str | None, at: datetime
    ) -> int | None:
        """Record a full pass that began after entry `floor`; how many blocks it found persisting.

        A block persists when it was its event's latest decision before the pass began and the
        pass decided it again. `None` when the rule no longer exists.
        """
        ...


class RemovalIncidents(Protocol):
    def removal_blocked(
        self, rule_id: SyncRuleId, failure: ProviderFailure, *, attempted_at: datetime
    ) -> None:
        """Open or refresh the one Incident for a removal stopped by lost authorization."""
        ...


class RecoveryIncidents(Protocol):
    def recovery_blocked(
        self, rule_id: SyncRuleId, failure: ProviderFailure, *, attempted_at: datetime
    ) -> None:
        """Record the lost authorization a preview met, lapsing the account it names."""
        ...


class FullPassRecords(Protocol):
    """Bookkeeping that lets a successful full pass stand in for a rule's daily one."""

    def audit_floor(self) -> int:
        """The newest audit entry now, taken before a full pass so its decisions lie above it."""
        ...

    def record_full_pass(self, rule_id: SyncRuleId, floor: int, run_id: str | None = None) -> None:
        """A full pass that began after audit entry `floor` decided every blocked event again."""
        ...
