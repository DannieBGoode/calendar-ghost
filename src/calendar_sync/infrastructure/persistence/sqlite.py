from __future__ import annotations

import sqlite3
from collections.abc import Collection, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from types import TracebackType
from typing import Self

from calendar_sync.application.shared.ports import Clock
from calendar_sync.application.sync.errors import (
    DuplicateDirectionalRelationship,
    IdentityCollision,
    MissingReference,
)
from calendar_sync.application.sync.ports import (
    AuditRepository,
    CalendarNameRepository,
    ConnectedAccountRecords,
    DiscoveredCalendar,
    EventMappingRepository,
    ExceptionReplayRepository,
    OccurrenceMappingRepository,
    ProviderCallCounts,
    ProviderCallRepository,
    RulePreviewRepository,
    RulePreviewSummary,
    RuleRunOutcomeRepository,
    SourceObservationRepository,
    SyncCursorRepository,
    SyncRuleRepository,
    UnitOfWork,
    UnitOfWorkFactory,
)
from calendar_sync.application.sync.watch_ports import (
    CalendarWatchRepository,
    InstantSyncRequestRepository,
)
from calendar_sync.domain.access import UserId
from calendar_sync.domain.accounts import ConnectedAccountState, ProviderKind
from calendar_sync.domain.audit import AuditAction, AuditEntry, RecordedDecision, RecordedEvent
from calendar_sync.domain.causes import NO_CAUSE, WITHOUT_CAUSE, Cause
from calendar_sync.domain.incidents import IncidentResolution
from calendar_sync.domain.model import (
    AllDayRange,
    AllDaySyncPolicy,
    BirthdayPolicy,
    CalendarEndpoint,
    CalendarId,
    ConnectedAccountId,
    EventId,
    EventMapping,
    EventMappingId,
    EventRef,
    OccurrenceIdentity,
    OccurrenceMapping,
    OccurrenceMappingId,
    OccurrenceStart,
    OccurrenceState,
    ProjectionContent,
    ProjectionFingerprint,
    SyncReason,
    SyncRule,
    SyncRuleId,
    SyncRuleState,
    TentativeEventPolicy,
    TimedInterval,
    TransformationPolicy,
    UnansweredInvitationPolicy,
)
from calendar_sync.domain.providers import ProviderFailureKind
from calendar_sync.domain.runs import RuleRunOutcome, RunKind
from calendar_sync.infrastructure.clock import SystemClock
from calendar_sync.infrastructure.persistence.connections import open_connection
from calendar_sync.infrastructure.persistence.refusals import refusals
from calendar_sync.infrastructure.persistence.source_changes import (
    SqliteSourceObservationRepository,
    change_columns,
)
from calendar_sync.infrastructure.persistence.watches import (
    SqliteCalendarWatchRepository,
    SqliteInstantSyncRequestRepository,
)
from calendar_sync.infrastructure.security import HistoryCipher


class SqliteConnectedAccountRecords:
    def __init__(self, connection: sqlite3.Connection, user_id: UserId) -> None:
        self._connection = connection
        self._user = user_id.value

    def state(self, account_id: ConnectedAccountId) -> ConnectedAccountState | None:
        row = self._connection.execute(
            "SELECT state FROM connected_accounts WHERE id = ? AND user_id = ?",
            (account_id.value, self._user),
        ).fetchone()
        return ConnectedAccountState(str(row["state"])) if row else None

    def lapse(self, account_id: ConnectedAccountId, *, attempted_at: datetime) -> bool:
        # One statement, so a Reauthorization cannot land between the check and the write. A
        # connected account's last update is when it was last authorized. Both times are UTC ISO
        # 8601 text, which orders as the instants do, to the microsecond; julianday would round
        # to the millisecond. The lapse keeps the start of the latest refused request.
        attempted = attempted_at.astimezone(UTC).isoformat()
        cursor = self._connection.execute(
            """
            UPDATE connected_accounts
            SET authorization_lapsed_at = MAX(COALESCE(authorization_lapsed_at, ?), ?)
            WHERE id = ? AND user_id = ? AND state = ? AND updated_at <= ?
            """,
            (
                attempted,
                attempted,
                account_id.value,
                self._user,
                ConnectedAccountState.CONNECTED.value,
                attempted,
            ),
        )
        return cursor.rowcount == 1

    def clear_lapse(self, account_id: ConnectedAccountId, *, requested_before: datetime) -> bool:
        cursor = self._connection.execute(
            """
            UPDATE connected_accounts SET authorization_lapsed_at = NULL
            WHERE id = ? AND user_id = ? AND authorization_lapsed_at <= ?
            """,
            (account_id.value, self._user, requested_before.astimezone(UTC).isoformat()),
        )
        return cursor.rowcount == 1

    def authorized(self, account_id: ConnectedAccountId) -> bool:
        row = self._connection.execute(
            """
            SELECT 1 FROM connected_accounts
            WHERE id = ? AND user_id = ? AND state = ? AND authorization_lapsed_at IS NULL
            """,
            (account_id.value, self._user, ConnectedAccountState.CONNECTED.value),
        ).fetchone()
        return row is not None

    def lapsed(self) -> dict[ConnectedAccountId, ProviderKind]:
        rows = self._connection.execute(
            """
            SELECT id, provider FROM connected_accounts
            WHERE user_id = ? AND state = ? AND authorization_lapsed_at IS NOT NULL
            ORDER BY id
            """,
            (self._user, ConnectedAccountState.CONNECTED.value),
        ).fetchall()
        return {ConnectedAccountId(str(row[0])): ProviderKind(str(row[1])) for row in rows}

    def delete_disconnected(self, account_id: ConnectedAccountId) -> bool:
        # The first write of the transaction takes SQLite's write lock until commit or rollback.
        cursor = self._connection.execute(
            "DELETE FROM connected_accounts WHERE id = ? AND user_id = ? AND state = ?",
            (account_id.value, self._user, ConnectedAccountState.DISCONNECTED.value),
        )
        if cursor.rowcount != 1:
            return False
        # The account's own Incidents, such as its Lapsed Authorization, go with it; its rules
        # take theirs when they are purged.
        self._connection.execute(
            "DELETE FROM incidents WHERE account_id = ? AND rule_id IS NULL AND user_id = ?",
            (account_id.value, self._user),
        )
        return True


class SqliteSyncRuleRepository:
    def __init__(self, connection: sqlite3.Connection, user_id: UserId, clock: Clock) -> None:
        self._connection = connection
        self._user = user_id.value
        self._clock = clock

    def get(self, rule_id: SyncRuleId) -> SyncRule | None:
        row = self._connection.execute(
            "SELECT * FROM sync_rules WHERE id = ? AND user_id = ?", (rule_id.value, self._user)
        ).fetchone()
        return rule_from_row(row) if row else None

    def list(self) -> Sequence[SyncRule]:
        rows = self._connection.execute(
            "SELECT * FROM sync_rules WHERE user_id = ? ORDER BY id", (self._user,)
        ).fetchall()
        return tuple(rule_from_row(row) for row in rows)

    def add(self, rule: SyncRule) -> None:
        with refusals(), _rule_refusals():
            self._connection.execute(
                """
                INSERT INTO sync_rules (
                    id, source_account_id, source_calendar_id,
                    destination_account_id, destination_calendar_id,
                    privacy_policy, all_day_policy, busy_title,
                    tentative_policy, unanswered_policy, birthday_policy,
                    initial_lookback_days, state, reprojection_required,
                    awaiting_reauthorization, user_id, creation_order
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    (SELECT COALESCE(MAX(creation_order), 0) + 1 FROM sync_rules)
                )
                """,
                (*_rule_values(rule), self._user),
            )

    def save(self, rule: SyncRule) -> None:
        with refusals(), _rule_refusals():
            cursor = self._update(rule)
        if cursor.rowcount != 1:
            raise KeyError(f"sync rule {rule.id.value} does not exist")

    def _update(self, rule: SyncRule) -> sqlite3.Cursor:
        return self._connection.execute(
            """
            UPDATE sync_rules SET
                source_account_id = ?, source_calendar_id = ?,
                destination_account_id = ?, destination_calendar_id = ?,
                privacy_policy = ?, all_day_policy = ?, busy_title = ?,
                tentative_policy = ?, unanswered_policy = ?, birthday_policy = ?,
                initial_lookback_days = ?, state = ?, reprojection_required = ?,
                awaiting_reauthorization = ?
            WHERE id = ? AND user_id = ?
            """,
            (*_rule_values(rule)[1:], rule.id.value, self._user),
        )

    def remove(self, rule_id: SyncRuleId) -> None:
        now = self._clock.now().isoformat()
        self._connection.execute(
            """
            UPDATE incidents SET state = 'resolved', updated_at = ?, resolved_at = ?, resolution = ?
            WHERE rule_id = ? AND user_id = ? AND state = 'open'
            """,
            (now, now, IncidentResolution.RULE_REMOVED.value, rule_id.value, self._user),
        )
        self._connection.execute(
            "DELETE FROM sync_rules WHERE id = ? AND user_id = ?", (rule_id.value, self._user)
        )

    def purge(self, rule_id: SyncRuleId) -> None:
        # Neither table references sync_rules, so nothing cascades to them.
        owned = (rule_id.value, self._user)
        self._connection.execute(
            "DELETE FROM audit_entries WHERE rule_id = ? AND user_id = ?", owned
        )
        self._connection.execute("DELETE FROM incidents WHERE rule_id = ? AND user_id = ?", owned)
        self._connection.execute("DELETE FROM sync_rules WHERE id = ? AND user_id = ?", owned)

    def relationship_exists(self, source: CalendarEndpoint, destination: CalendarEndpoint) -> bool:
        row = self._connection.execute(
            """
            SELECT 1 FROM sync_rules
            WHERE source_account_id = ? AND source_calendar_id = ?
              AND destination_account_id = ? AND destination_calendar_id = ? AND user_id = ?
            LIMIT 1
            """,
            (
                source.connected_account_id.value,
                source.calendar_id.value,
                destination.connected_account_id.value,
                destination.calendar_id.value,
                self._user,
            ),
        ).fetchone()
        return row is not None


@contextmanager
def _rule_refusals() -> Iterator[None]:
    """A rule's refusals. Apart from its identifier, only its direction is unique per User, so a
    uniqueness failure naming its source is a second rule for one direction. Its accounts are
    checked when the unit commits, as their references are deferred."""
    try:
        yield
    except sqlite3.IntegrityError as error:
        if "sync_rules.source_account_id" not in str(error):
            raise
        raise DuplicateDirectionalRelationship(
            "a rule already exists for this source and destination"
        ) from error


class SqliteEventMappingRepository:
    def __init__(self, connection: sqlite3.Connection, user_id: UserId) -> None:
        self._connection = connection
        self._user = user_id.value

    def for_source(self, rule_id: SyncRuleId, source: EventRef) -> EventMapping | None:
        row = self._connection.execute(
            """
            SELECT * FROM event_mappings
            WHERE rule_id = ? AND user_id = ? AND source_account_id = ?
              AND source_calendar_id = ? AND source_event_id = ?
            """,
            (
                rule_id.value,
                self._user,
                source.calendar.connected_account_id.value,
                source.calendar.calendar_id.value,
                source.event_id.value,
            ),
        ).fetchone()
        return _mapping_from_row(row) if row else None

    def for_destination(self, rule_id: SyncRuleId, destination: EventRef) -> EventMapping | None:
        row = self._connection.execute(
            """
            SELECT * FROM event_mappings
            WHERE rule_id = ? AND user_id = ? AND destination_account_id = ?
              AND destination_calendar_id = ? AND destination_event_id = ?
            """,
            (
                rule_id.value,
                self._user,
                destination.calendar.connected_account_id.value,
                destination.calendar.calendar_id.value,
                destination.event_id.value,
            ),
        ).fetchone()
        return _mapping_from_row(row) if row else None

    def for_rule(self, rule_id: SyncRuleId) -> Sequence[EventMapping]:
        rows = self._connection.execute(
            "SELECT * FROM event_mappings WHERE rule_id = ? AND user_id = ? ORDER BY id",
            (rule_id.value, self._user),
        ).fetchall()
        return tuple(_mapping_from_row(row) for row in rows)

    def lone_occurrences(self, rule_id: SyncRuleId, series: EventRef) -> Sequence[EventMapping]:
        rows = self._connection.execute(
            """
            SELECT * FROM event_mappings
            WHERE rule_id = ? AND user_id = ? AND occurrence_series_event_id = ?
              AND source_account_id = ? AND source_calendar_id = ?
            ORDER BY id
            """,
            (
                rule_id.value,
                self._user,
                series.event_id.value,
                series.calendar.connected_account_id.value,
                series.calendar.calendar_id.value,
            ),
        ).fetchall()
        return tuple(_mapping_from_row(row) for row in rows)

    def save(self, mapping: EventMapping) -> None:
        # The composite reference refuses a mapping for another User's rule; the update touches
        # only this User's mapping, so another User's identifier is refused rather than changed.
        with refusals():
            cursor = self._insert(mapping)
        if cursor.rowcount != 1:
            raise IdentityCollision(f"event mapping {mapping.id.value} is another User's")

    def _insert(self, mapping: EventMapping) -> sqlite3.Cursor:
        return self._connection.execute(
            """
            INSERT INTO event_mappings (
                id, rule_id, source_account_id, source_calendar_id, source_event_id,
                destination_account_id, destination_calendar_id, destination_event_id,
                source_revision, projection_fingerprint, user_id,
                occurrence_series_event_id, occurrence_original_start
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                source_revision = excluded.source_revision,
                destination_account_id = excluded.destination_account_id,
                destination_calendar_id = excluded.destination_calendar_id,
                destination_event_id = excluded.destination_event_id,
                projection_fingerprint = excluded.projection_fingerprint
            WHERE user_id = excluded.user_id
            """,
            (
                mapping.id.value,
                mapping.rule_id.value,
                mapping.source.calendar.connected_account_id.value,
                mapping.source.calendar.calendar_id.value,
                mapping.source.event_id.value,
                mapping.destination.calendar.connected_account_id.value,
                mapping.destination.calendar.calendar_id.value,
                mapping.destination.event_id.value,
                mapping.source_revision,
                mapping.projection_fingerprint.value,
                self._user,
                mapping.occurrence.series_event_id.value if mapping.occurrence else None,
                _serialize_start(mapping.occurrence.original_start) if mapping.occurrence else None,
            ),
        )

    def delete(self, mapping: EventMapping) -> None:
        self._connection.execute(
            "DELETE FROM event_mappings WHERE id = ? AND user_id = ?",
            (mapping.id.value, self._user),
        )

    def count_for_rule(self, rule_id: SyncRuleId) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) FROM event_mappings WHERE rule_id = ? AND user_id = ?",
            (rule_id.value, self._user),
        ).fetchone()
        return int(row[0])


class SqliteExceptionReplayRepository:
    def __init__(self, connection: sqlite3.Connection, user_id: UserId) -> None:
        self._connection = connection
        self._user = user_id.value

    def pending(self, rule_id: SyncRuleId) -> Sequence[EventMapping]:
        rows = self._connection.execute(
            """
            SELECT event_mappings.* FROM event_mappings
            JOIN pending_exception_replays
              ON pending_exception_replays.series_mapping_id = event_mappings.id
             AND pending_exception_replays.user_id = event_mappings.user_id
            WHERE event_mappings.rule_id = ? AND event_mappings.user_id = ?
            ORDER BY event_mappings.id
            """,
            (rule_id.value, self._user),
        ).fetchall()
        return tuple(_mapping_from_row(row) for row in rows)

    def add(self, series_mapping_id: EventMappingId) -> None:
        # Adding one already pending is a no-op; another User's is refused, not left alone.
        with refusals():
            cursor = self._connection.execute(
                """
                INSERT INTO pending_exception_replays (series_mapping_id, user_id) VALUES (?, ?)
                ON CONFLICT(series_mapping_id) DO UPDATE SET user_id = excluded.user_id
                WHERE pending_exception_replays.user_id = excluded.user_id
                """,
                (series_mapping_id.value, self._user),
            )
        if cursor.rowcount != 1:
            raise MissingReference(f"series mapping {series_mapping_id.value} is not this User's")

    def remove(self, series_mapping_id: EventMappingId) -> None:
        self._connection.execute(
            "DELETE FROM pending_exception_replays WHERE series_mapping_id = ? AND user_id = ?",
            (series_mapping_id.value, self._user),
        )


class SqliteOccurrenceMappingRepository:
    def __init__(self, connection: sqlite3.Connection, user_id: UserId) -> None:
        self._connection = connection
        self._user = user_id.value

    def for_series(self, series_mapping_id: EventMappingId) -> Sequence[OccurrenceMapping]:
        rows = self._connection.execute(
            """
            SELECT * FROM occurrence_mappings WHERE series_mapping_id = ? AND user_id = ?
            ORDER BY original_start
            """,
            (series_mapping_id.value, self._user),
        ).fetchall()
        return tuple(_occurrence_from_row(row) for row in rows)

    def get(
        self, series_mapping_id: EventMappingId, original_start: OccurrenceStart
    ) -> OccurrenceMapping | None:
        row = self._connection.execute(
            """
            SELECT * FROM occurrence_mappings
            WHERE series_mapping_id = ? AND original_start = ? AND user_id = ?
            """,
            (series_mapping_id.value, _serialize_start(original_start), self._user),
        ).fetchone()
        return _occurrence_from_row(row) if row else None

    def save(self, mapping: OccurrenceMapping) -> None:
        with refusals():
            cursor = self._insert(mapping)
        if cursor.rowcount != 1:
            # The occurrence the upsert met is another User's, so its series mapping is too.
            raise MissingReference(f"occurrence mapping {mapping.id.value} is another User's")

    def _insert(self, mapping: OccurrenceMapping) -> sqlite3.Cursor:
        return self._connection.execute(
            """
            INSERT INTO occurrence_mappings (
                id, series_mapping_id, original_start,
                source_account_id, source_calendar_id, source_event_id,
                destination_account_id, destination_calendar_id, destination_event_id,
                state, source_revision, projection_fingerprint, user_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(series_mapping_id, original_start) DO UPDATE SET
                source_account_id = excluded.source_account_id,
                source_calendar_id = excluded.source_calendar_id,
                source_event_id = excluded.source_event_id,
                destination_account_id = excluded.destination_account_id,
                destination_calendar_id = excluded.destination_calendar_id,
                destination_event_id = excluded.destination_event_id,
                state = excluded.state,
                source_revision = excluded.source_revision,
                projection_fingerprint = excluded.projection_fingerprint
            WHERE user_id = excluded.user_id
            """,
            (
                mapping.id.value,
                mapping.series_mapping_id.value,
                _serialize_start(mapping.original_start),
                mapping.source.calendar.connected_account_id.value,
                mapping.source.calendar.calendar_id.value,
                mapping.source.event_id.value,
                mapping.destination.calendar.connected_account_id.value,
                mapping.destination.calendar.calendar_id.value,
                mapping.destination.event_id.value,
                mapping.state.value,
                mapping.source_revision,
                mapping.projection_fingerprint.value if mapping.projection_fingerprint else None,
                self._user,
            ),
        )

    def delete(self, mapping: OccurrenceMapping) -> None:
        self._connection.execute(
            """
            DELETE FROM occurrence_mappings
            WHERE series_mapping_id = ? AND original_start = ? AND user_id = ?
            """,
            (mapping.series_mapping_id.value, _serialize_start(mapping.original_start), self._user),
        )


def _require_own(cursor: sqlite3.Cursor, rule_id: SyncRuleId) -> None:
    """Refuse a write an upsert skipped because the record it met, so its rule, is another
    User's."""
    if cursor.rowcount != 1:
        raise MissingReference(f"a record of rule {rule_id.value} is another User's")


def _serialize_start(value: OccurrenceStart) -> str:
    return value.isoformat()


def _parse_start(value: str) -> OccurrenceStart:
    return date.fromisoformat(value) if len(value) == 10 else datetime.fromisoformat(value)


def _ref(row: sqlite3.Row, prefix: str) -> EventRef:
    return EventRef(
        CalendarEndpoint(
            ConnectedAccountId(str(row[f"{prefix}_account_id"])),
            CalendarId(str(row[f"{prefix}_calendar_id"])),
        ),
        EventId(str(row[f"{prefix}_event_id"])),
    )


def _occurrence_from_row(row: sqlite3.Row) -> OccurrenceMapping:
    fingerprint = row["projection_fingerprint"]
    return OccurrenceMapping(
        id=OccurrenceMappingId(str(row["id"])),
        series_mapping_id=EventMappingId(str(row["series_mapping_id"])),
        original_start=_parse_start(str(row["original_start"])),
        source=_ref(row, "source"),
        destination=_ref(row, "destination"),
        state=OccurrenceState(str(row["state"])),
        source_revision=str(row["source_revision"]),
        projection_fingerprint=ProjectionFingerprint(str(fingerprint)) if fingerprint else None,
    )


class SqliteSyncCursorRepository:
    """A rule's incremental position in one of its calendars, kept in `table`."""

    def __init__(
        self, connection: sqlite3.Connection, user_id: UserId, table: str = "sync_cursors"
    ) -> None:
        self._connection = connection
        self._user = user_id.value
        self._table = table

    def get(self, rule_id: SyncRuleId) -> str | None:
        # Interpolates only one of the two constant table names.
        row = self._connection.execute(
            f"SELECT cursor FROM {self._table} WHERE rule_id = ? AND user_id = ?",  # noqa: S608
            (rule_id.value, self._user),
        ).fetchone()
        return str(row["cursor"]) if row else None

    def save(self, rule_id: SyncRuleId, cursor: str) -> None:
        # Interpolates only one of the two constant table names.
        with refusals():
            written = self._connection.execute(
                f"""
                INSERT INTO {self._table}(rule_id, cursor, user_id) VALUES (?, ?, ?)
                ON CONFLICT(rule_id) DO UPDATE SET cursor = excluded.cursor
                WHERE user_id = excluded.user_id
                """,  # noqa: S608
                (rule_id.value, cursor, self._user),
            )
        _require_own(written, rule_id)


class SqliteAuditRepository:
    LATEST_FOR_SQL = """
        SELECT action, reason, destination_event_id, event_title, event_starts, event_ends,
               event_all_day, event_recurring, event_cancelled
        FROM audit_entries INDEXED BY audit_entries_source_event
        WHERE rule_id = ? AND source_event_id = ? AND user_id = ?
        ORDER BY id DESC LIMIT 1
    """

    def __init__(
        self, connection: sqlite3.Connection, user_id: UserId, history: HistoryCipher | None
    ) -> None:
        self._connection = connection
        self._user = user_id.value
        self._history = history

    def append(self, entry: AuditEntry) -> None:
        event = entry.event
        starts = ends = None
        if event is not None and isinstance(event.time, TimedInterval):
            starts, ends = event.time.starts_at.isoformat(), event.time.ends_at.isoformat()
        elif event is not None and isinstance(event.time, AllDayRange):
            starts, ends = event.time.starts_on.isoformat(), event.time.ends_before.isoformat()
        changed = change_columns(self._history, entry.rule_id, entry.source_event_id, entry.change)
        self._connection.execute(
            """
            INSERT INTO audit_entries (
                occurred_at, rule_id, action, outcome,
                source_event_id, destination_event_id, detail, reason, run_id,
                event_title, event_starts, event_ends,
                event_all_day, event_recurring, event_cancelled,
                change_fields, change_title_before, change_sealed,
                run_reason, found_by, source_comparison, user_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry.occurred_at.isoformat(),
                entry.rule_id.value,
                entry.action,
                entry.outcome,
                entry.source_event_id,
                entry.destination_event_id,
                entry.detail,
                entry.reason,
                entry.run_id,
                event.title if event else None,
                starts,
                ends,
                event is not None and isinstance(event.time, AllDayRange),
                event is not None and event.recurring,
                event is not None and event.cancelled,
                *changed,
                entry.run_reason,
                entry.found_by,
                entry.source_comparison,
                self._user,
            ),
        )

    def latest_for(self, rule_id: SyncRuleId, source_event_id: str) -> RecordedDecision | None:
        row = self._connection.execute(
            self.LATEST_FOR_SQL, (rule_id.value, source_event_id, self._user)
        ).fetchone()
        if row is None:
            return None
        try:
            action = AuditAction(row["action"])
            reason = SyncReason(row["reason"]) if row["reason"] is not None else None
            event = _recorded_event(row)
        except ValueError:
            # A value this release cannot read proves nothing, so the decision is recorded.
            return None
        return RecordedDecision(action, reason, row["destination_event_id"], event)

    def forget_change_values(self, before: datetime) -> None:
        self._connection.execute(
            """
            UPDATE audit_entries SET change_sealed = NULL
            WHERE change_sealed IS NOT NULL AND occurred_at < ? AND user_id = ?
            """,
            (before.isoformat(), self._user),
        )


def _recorded_event(row: sqlite3.Row) -> RecordedEvent | None:
    """The event an entry recorded, as `append` wrote it."""
    if row["event_title"] is None:
        return None
    time: TimedInterval | AllDayRange | None = None
    if row["event_starts"] is not None and row["event_all_day"]:
        time = AllDayRange(
            date.fromisoformat(row["event_starts"]), date.fromisoformat(row["event_ends"])
        )
    elif row["event_starts"] is not None:
        time = TimedInterval(
            datetime.fromisoformat(row["event_starts"]), datetime.fromisoformat(row["event_ends"])
        )
    return RecordedEvent(
        title=row["event_title"],
        time=time,
        recurring=bool(row["event_recurring"]),
        cancelled=bool(row["event_cancelled"]),
    )


class SqliteRuleRunOutcomeRepository:
    def __init__(self, connection: sqlite3.Connection, user_id: UserId) -> None:
        self._connection = connection
        self._user = user_id.value

    def record(self, outcome: RuleRunOutcome) -> None:
        with refusals():
            cursor = self._insert(outcome)
        _require_own(cursor, outcome.rule_id)

    def _insert(self, outcome: RuleRunOutcome) -> sqlite3.Cursor:
        return self._connection.execute(
            """
            INSERT INTO rule_run_outcomes (
                rule_id, kind, completed_at, succeeded, full_run, created, updated,
                deleted, conflicts, checked_mappings, drift, failure_kind, failure_cause,
                failure_provider, last_succeeded_at, last_full_succeeded_at, user_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(rule_id, kind) DO UPDATE SET
                last_succeeded_at = CASE WHEN excluded.succeeded
                    THEN excluded.completed_at ELSE rule_run_outcomes.last_succeeded_at END,
                last_full_succeeded_at = CASE WHEN excluded.succeeded AND excluded.full_run
                    THEN excluded.completed_at ELSE rule_run_outcomes.last_full_succeeded_at END,
                completed_at = excluded.completed_at,
                succeeded = excluded.succeeded,
                full_run = excluded.full_run,
                created = excluded.created,
                updated = excluded.updated,
                deleted = excluded.deleted,
                conflicts = excluded.conflicts,
                checked_mappings = excluded.checked_mappings,
                drift = excluded.drift,
                failure_kind = excluded.failure_kind,
                failure_cause = excluded.failure_cause,
                failure_provider = excluded.failure_provider
            WHERE rule_run_outcomes.user_id = excluded.user_id
            """,
            (
                outcome.rule_id.value,
                outcome.kind.value,
                outcome.completed_at.isoformat(),
                int(outcome.succeeded),
                int(outcome.full_run),
                outcome.created,
                outcome.updated,
                outcome.deleted,
                outcome.conflicts,
                outcome.checked_mappings,
                outcome.drift,
                outcome.failure_kind.value if outcome.failure_kind else None,
                None
                if outcome.succeeded or outcome.failure_kind in WITHOUT_CAUSE
                else outcome.failure_cause.value
                if outcome.failure_cause
                else NO_CAUSE,
                outcome.failure_provider.value
                if outcome.failure_provider and _caused(outcome)
                else None,
                outcome.completed_at.isoformat() if outcome.succeeded else None,
                outcome.completed_at.isoformat()
                if outcome.succeeded and outcome.full_run
                else None,
                self._user,
            ),
        )

    def latest(self, rule_id: SyncRuleId, kind: RunKind) -> RuleRunOutcome | None:
        row = self._connection.execute(
            "SELECT * FROM rule_run_outcomes WHERE rule_id = ? AND kind = ? AND user_id = ?",
            (rule_id.value, kind.value, self._user),
        ).fetchone()
        return outcome_from_row(row) if row is not None else None


def _caused(outcome: RuleRunOutcome) -> bool:
    """Whether a provider's answer explains the outcome: a failure that is not local."""
    return not outcome.succeeded and outcome.failure_kind not in WITHOUT_CAUSE


def outcome_from_row(row: sqlite3.Row) -> RuleRunOutcome:
    return RuleRunOutcome(
        rule_id=SyncRuleId(str(row["rule_id"])),
        kind=RunKind(str(row["kind"])),
        completed_at=datetime.fromisoformat(str(row["completed_at"])),
        succeeded=bool(row["succeeded"]),
        full_run=bool(row["full_run"]),
        created=int(row["created"]),
        updated=int(row["updated"]),
        deleted=int(row["deleted"]),
        conflicts=int(row["conflicts"]),
        checked_mappings=int(row["checked_mappings"]),
        drift=int(row["drift"]),
        failure_kind=None
        if row["failure_kind"] is None
        else ProviderFailureKind(str(row["failure_kind"])),
        failure_cause=None
        if row["succeeded"] or row["failure_kind"] in WITHOUT_CAUSE
        else Cause.recorded(row["failure_cause"]),
        failure_provider=ProviderKind.recorded(row["failure_provider"]),
        last_succeeded_at=optional_time(row["last_succeeded_at"]),
        last_full_succeeded_at=optional_time(row["last_full_succeeded_at"]),
    )


def optional_time(value: object) -> datetime | None:
    return None if value is None else datetime.fromisoformat(str(value))


class SqliteRulePreviewRepository:
    def __init__(self, connection: sqlite3.Connection, user_id: UserId) -> None:
        self._connection = connection
        self._user = user_id.value

    def record(self, summary: RulePreviewSummary) -> None:
        with refusals():
            cursor = self._insert(summary)
        _require_own(cursor, summary.rule_id)

    def _insert(self, summary: RulePreviewSummary) -> sqlite3.Cursor:
        return self._connection.execute(
            """
            INSERT INTO rule_previews (
                rule_id, completed_at, eligible_events, excluded_events, recurring_series,
                occurrence_changes, user_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(rule_id) DO UPDATE SET
                completed_at = excluded.completed_at,
                eligible_events = excluded.eligible_events,
                excluded_events = excluded.excluded_events,
                recurring_series = excluded.recurring_series,
                occurrence_changes = excluded.occurrence_changes
            WHERE user_id = excluded.user_id
            """,
            (
                summary.rule_id.value,
                summary.completed_at.isoformat(),
                summary.eligible_events,
                summary.excluded_events,
                summary.recurring_series,
                summary.occurrence_changes,
                self._user,
            ),
        )

    def latest(self, rule_id: SyncRuleId) -> RulePreviewSummary | None:
        row = self._connection.execute(
            "SELECT * FROM rule_previews WHERE rule_id = ? AND user_id = ?",
            (rule_id.value, self._user),
        ).fetchone()
        return preview_from_row(row) if row is not None else None


def preview_from_row(row: sqlite3.Row) -> RulePreviewSummary:
    return RulePreviewSummary(
        rule_id=SyncRuleId(str(row["rule_id"])),
        completed_at=datetime.fromisoformat(str(row["completed_at"])),
        eligible_events=int(row["eligible_events"]),
        excluded_events=int(row["excluded_events"]),
        recurring_series=int(row["recurring_series"]),
        occurrence_changes=int(row["occurrence_changes"]),
    )


class SqliteProviderCallRepository:
    def __init__(self, connection: sqlite3.Connection, user_id: UserId) -> None:
        self._connection = connection
        self._user = user_id.value

    def add(self, day: date, provider: ProviderKind, counts: ProviderCallCounts) -> None:
        self._connection.execute(
            """
            INSERT INTO provider_calls (user_id, provider, day, calls, rate_limited, failed)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (user_id, provider, day) DO UPDATE SET
                calls = calls + excluded.calls,
                rate_limited = rate_limited + excluded.rate_limited,
                failed = failed + excluded.failed
            """,
            (
                self._user,
                provider.value,
                day.isoformat(),
                counts.calls,
                counts.rate_limited,
                counts.failed,
            ),
        )


class SqliteCalendarNameRepository:
    def __init__(self, connection: sqlite3.Connection, user_id: UserId, clock: Clock) -> None:
        self._connection = connection
        self._user = user_id.value
        self._clock = clock

    def remember(
        self, account_id: ConnectedAccountId, calendars: Sequence[DiscoveredCalendar]
    ) -> None:
        now = self._clock.now().isoformat()
        # Selecting from the account row records nothing for an account deleted meanwhile, or
        # for another User's.
        self._connection.executemany(
            """
            INSERT INTO calendar_names (
                connected_account_id, calendar_id, name, updated_at, user_id
            )
            SELECT id, ?, ?, ?, user_id FROM connected_accounts WHERE id = ? AND user_id = ?
            ON CONFLICT(connected_account_id, calendar_id) DO UPDATE SET
                name = excluded.name,
                updated_at = excluded.updated_at
            WHERE name != excluded.name
            """,
            [
                (calendar.id, calendar.name, now, account_id.value, self._user)
                for calendar in calendars
            ],
        )

    def names(self, endpoints: Collection[CalendarEndpoint]) -> dict[CalendarEndpoint, str]:
        wanted = set(endpoints)
        if not wanted:
            return {}
        rows = self._connection.execute(
            "SELECT connected_account_id, calendar_id, name FROM calendar_names WHERE user_id = ?",
            (self._user,),
        )
        named = (
            (
                CalendarEndpoint(
                    ConnectedAccountId(str(row["connected_account_id"])),
                    CalendarId(str(row["calendar_id"])),
                ),
                str(row["name"]),
            )
            for row in rows
        )
        return {endpoint: name for endpoint, name in named if endpoint in wanted}


class SqliteUnitOfWork:
    """One User's records in one transaction; every repository adds that User (ADR 0029)."""

    accounts: ConnectedAccountRecords
    rules: SyncRuleRepository
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


def _rule_values(rule: SyncRule) -> tuple[object, ...]:
    return (
        rule.id.value,
        rule.source.connected_account_id.value,
        rule.source.calendar_id.value,
        rule.destination.connected_account_id.value,
        rule.destination.calendar_id.value,
        rule.transformation.content.value,
        rule.transformation.all_day.value,
        rule.transformation.busy_title,
        rule.transformation.tentative.value,
        rule.transformation.unanswered.value,
        rule.transformation.birthdays.value,
        rule.initial_lookback_days,
        rule.state.value,
        int(rule.reprojection_required),
        int(rule.awaiting_reauthorization),
    )


def rule_from_row(row: sqlite3.Row) -> SyncRule:
    return SyncRule(
        id=SyncRuleId(str(row["id"])),
        source=CalendarEndpoint(
            ConnectedAccountId(str(row["source_account_id"])),
            CalendarId(str(row["source_calendar_id"])),
        ),
        destination=CalendarEndpoint(
            ConnectedAccountId(str(row["destination_account_id"])),
            CalendarId(str(row["destination_calendar_id"])),
        ),
        transformation=TransformationPolicy(
            content=ProjectionContent(str(row["privacy_policy"])),
            all_day=AllDaySyncPolicy(str(row["all_day_policy"])),
            busy_title=str(row["busy_title"]),
            tentative=TentativeEventPolicy(str(row["tentative_policy"])),
            unanswered=UnansweredInvitationPolicy(str(row["unanswered_policy"])),
            birthdays=BirthdayPolicy(str(row["birthday_policy"])),
        ),
        initial_lookback_days=int(row["initial_lookback_days"]),
        state=SyncRuleState(str(row["state"])),
        reprojection_required=bool(row["reprojection_required"]),
        awaiting_reauthorization=bool(row["awaiting_reauthorization"]),
    )


def _mapping_from_row(row: sqlite3.Row) -> EventMapping:
    return EventMapping(
        id=EventMappingId(str(row["id"])),
        rule_id=SyncRuleId(str(row["rule_id"])),
        source=EventRef(
            CalendarEndpoint(
                ConnectedAccountId(str(row["source_account_id"])),
                CalendarId(str(row["source_calendar_id"])),
            ),
            EventId(str(row["source_event_id"])),
        ),
        destination=EventRef(
            CalendarEndpoint(
                ConnectedAccountId(str(row["destination_account_id"])),
                CalendarId(str(row["destination_calendar_id"])),
            ),
            EventId(str(row["destination_event_id"])),
        ),
        source_revision=str(row["source_revision"]),
        projection_fingerprint=ProjectionFingerprint(str(row["projection_fingerprint"])),
        occurrence=(
            None
            if row["occurrence_series_event_id"] is None
            else OccurrenceIdentity(
                EventId(str(row["occurrence_series_event_id"])),
                _parse_start(str(row["occurrence_original_start"])),
            )
        ),
    )
