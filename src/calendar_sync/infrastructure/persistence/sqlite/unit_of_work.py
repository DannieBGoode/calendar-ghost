from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import Self

from calendar_sync.application.shared.ports import Clock
from calendar_sync.application.sync.account_ports import (
    CalendarNameRepository,
    ConnectedAccountRecords,
)
from calendar_sync.application.sync.plan_ports import PlanGraceRecord
from calendar_sync.application.sync.ports import UnitOfWork, UnitOfWorkFactory
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
from calendar_sync.domain.access import UserId
from calendar_sync.infrastructure.clock import SystemClock
from calendar_sync.infrastructure.persistence.connections import open_connection
from calendar_sync.infrastructure.persistence.plan_grace import SqlitePlanGraceRecord
from calendar_sync.infrastructure.persistence.refusals import refusals
from calendar_sync.infrastructure.persistence.source_changes import (
    SqliteSourceObservationRepository,
)
from calendar_sync.infrastructure.persistence.sqlite.sync.accounts import (
    SqliteCalendarNameRepository,
    SqliteConnectedAccountRecords,
)
from calendar_sync.infrastructure.persistence.sqlite.sync.mappings import (
    SqliteEventMappingRepository,
    SqliteExceptionReplayRepository,
    SqliteOccurrenceMappingRepository,
)
from calendar_sync.infrastructure.persistence.sqlite.sync.records import (
    SqliteAuditRepository,
    SqliteProviderCallRepository,
    SqliteRuleRunOutcomeRepository,
    SqliteSyncCursorRepository,
)
from calendar_sync.infrastructure.persistence.sqlite.sync.rules import (
    SqliteRulePreviewRepository,
    SqliteSyncRuleRepository,
)
from calendar_sync.infrastructure.persistence.watches import (
    SqliteCalendarWatchRepository,
    SqliteInstantSyncRequestRepository,
)
from calendar_sync.infrastructure.security import HistoryCipher


class SqliteUnitOfWork:
    """One User's records in one transaction; every repository adds that User (ADR 0029)."""

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

    def __init__(
        self,
        database_path: Path,
        user_id: UserId,
        clock: Clock,
        history: HistoryCipher | None = None,
    ) -> None:
        self._database_path = database_path
        self._user = user_id
        self._clock = clock
        self._history = history
        self._connection: sqlite3.Connection | None = None

    def __enter__(self) -> Self:
        connection = open_connection(self._database_path)
        self._connection = connection
        user = self._user
        self.accounts = SqliteConnectedAccountRecords(connection, user)
        self.rules = SqliteSyncRuleRepository(connection, user, self._clock)
        self.plan_grace = SqlitePlanGraceRecord(connection, user)
        self.mappings = SqliteEventMappingRepository(connection, user)
        self.occurrences = SqliteOccurrenceMappingRepository(connection, user)
        self.replays = SqliteExceptionReplayRepository(connection, user)
        self.cursors = SqliteSyncCursorRepository(connection, user)
        self.destination_cursors = SqliteSyncCursorRepository(
            connection, user, "destination_sync_cursors"
        )
        self.audit = SqliteAuditRepository(connection, user, self._history)
        self.observations = SqliteSourceObservationRepository(connection, user, self._history)
        self.run_outcomes = SqliteRuleRunOutcomeRepository(connection, user)
        self.previews = SqliteRulePreviewRepository(connection, user)
        self.calendar_names = SqliteCalendarNameRepository(connection, user, self._clock)
        self.provider_calls = SqliteProviderCallRepository(connection, user)
        self.watches = SqliteCalendarWatchRepository(connection, user)
        self.instant_requests = SqliteInstantSyncRequestRepository(connection, user)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        assert self._connection is not None
        if exc_type is not None:
            self._connection.rollback()
        self._connection.close()
        self._connection = None
        return None

    def commit(self) -> None:
        assert self._connection is not None
        # A rule's references to its accounts are deferred, so a rule naming an account that is
        # not its User's, or no longer exists, is refused here.
        with refusals():
            self._connection.commit()

    def user_active(self) -> bool:
        assert self._connection is not None
        row = self._connection.execute(
            "SELECT 1 FROM users WHERE id = ? AND state = 'active'", (self._user.value,)
        ).fetchone()
        return row is not None


@dataclass(frozen=True, slots=True)
class SqliteUnitOfWorkFactory:
    """Units of work over one database, each for the one User `for_user` names (ADR 0029).

    Without a History Cipher, no Source Change has values.
    """

    database_path: Path
    clock: Clock = field(default_factory=SystemClock)
    history: HistoryCipher | None = None

    def for_user(self, user_id: UserId) -> UnitOfWorkFactory:
        return _UserUnitsOfWork(self, user_id)


@dataclass(frozen=True, slots=True)
class _UserUnitsOfWork:
    database: SqliteUnitOfWorkFactory
    user_id: UserId

    def __call__(self) -> UnitOfWork:
        database = self.database
        return SqliteUnitOfWork(
            database.database_path, self.user_id, database.clock, database.history
        )
