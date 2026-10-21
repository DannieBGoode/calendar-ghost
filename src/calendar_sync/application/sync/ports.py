"""The unit of work for one User's synchronization records."""

from __future__ import annotations

from types import TracebackType
from typing import Protocol, Self

from calendar_sync.application.sync.account_ports import (
    CalendarNameRepository,
    ConnectedAccountRecords,
)
from calendar_sync.application.sync.plan_ports import PlanGraceRecord
from calendar_sync.application.sync.record_ports import (
    AuditRepository,
    EventMappingRepository,
    ExceptionReplayRepository,
    OccurrenceMappingRepository,
    ProviderCallRepository,
    RulePreviewRepository,
    RuleRunOutcomeRepository,
    SourceObservationRepository,
    SyncCursorRepository,
    SyncRuleRepository,
)
from calendar_sync.application.sync.watch_ports import (
    CalendarWatchRepository,
    InstantSyncRequestRepository,
)


class UnitOfWork(Protocol):
    """One User's records in one transaction.

    A write that would break what the records keep true raises a `RecordRefused`: a second rule
    for one direction is a `DuplicateDirectionalRelationship`, an identifier or other unique key
    already taken an `IdentityCollision`, and a rule, Event Mapping, or account that is missing
    or another User's a `MissingReference`. A rule's accounts are checked only when the unit
    commits, so an account and the rules that use it can be deleted in either order.
    """

    accounts: ConnectedAccountRecords
    rules: SyncRuleRepository
    plan_grace: PlanGraceRecord
    mappings: EventMappingRepository
    occurrences: OccurrenceMappingRepository
    replays: ExceptionReplayRepository
    cursors: SyncCursorRepository
    destination_cursors: SyncCursorRepository
    audit: AuditRepository
    observations: SourceObservationRepository
    run_outcomes: RuleRunOutcomeRepository
    previews: RulePreviewRepository
    calendar_names: CalendarNameRepository
    provider_calls: ProviderCallRepository
    watches: CalendarWatchRepository
    instant_requests: InstantSyncRequestRepository

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...

    def commit(self) -> None:
        """Keep the unit's writes, and the changes they make to its User's Incidents; raises a
        `MissingReference`, keeping nothing, for a rule whose accounts are not its User's."""

    def user_active(self) -> bool:
        """Whether this unit's User is still active, neither disabled nor deleted, as of now,
        even while the unit is open. A rule of theirs writes nothing otherwise (ADR 0030)."""
        ...


class UnitOfWorkFactory(Protocol):
    """Opens units of work for the one User it was made for (ADR 0029).

    Every repository of its units adds that User to every statement, so a use case given one can
    neither read nor change another User's records.
    """

    def __call__(self) -> UnitOfWork: ...
