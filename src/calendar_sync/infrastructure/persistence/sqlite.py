from __future__ import annotations

import sqlite3
from collections.abc import Collection, Sequence
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from importlib.resources import files
from pathlib import Path
from types import TracebackType
from typing import Self

from calendar_sync.application.causes import NO_CAUSE, WITHOUT_CAUSE, Cause
from calendar_sync.application.errors import DuplicateDirectionalRelationship
from calendar_sync.application.ports import (
    AuditEntry,
    AuditRepository,
    CalendarNameRepository,
    CauseSighting,
    Clock,
    ConnectedAccountRecords,
    ConnectedAccountState,
    DiscoveredCalendar,
    EventMappingRepository,
    ExceptionReplayRepository,
    IncidentResolution,
    InstallationUnitOfWork,
    OccurrenceMappingRepository,
    ProviderCallCounts,
    ProviderCallRepository,
    ProviderCallUse,
    RecordedRule,
    ResourceUse,
    RulePreviewRepository,
    RulePreviewSummary,
    RuleRunOutcome,
    RuleRunOutcomeRepository,
    RunKind,
    ScheduledRule,
    SourceObservationRepository,
    StatusRecords,
    SyncCursorRepository,
    SyncRuleRepository,
    UnitOfWork,
    UnitOfWorkFactory,
)
from calendar_sync.application.providers import ProviderKind
from calendar_sync.domain.access import UserId
from calendar_sync.domain.model import (
    AllDayRange,
    AllDaySyncPolicy,
    CalendarEndpoint,
    CalendarId,
    ConnectedAccountId,
    EventId,
    EventMapping,
    EventMappingId,
    EventRef,
    OccurrenceMapping,
    OccurrenceMappingId,
    OccurrenceStart,
    OccurrenceState,
    ProjectionContent,
    ProjectionFingerprint,
    SyncRule,
    SyncRuleId,
    SyncRuleState,
    TentativeEventPolicy,
    TimedInterval,
    TransformationPolicy,
    UnansweredInvitationPolicy,
)
from calendar_sync.infrastructure.persistence.activity_queries import operations_of
from calendar_sync.infrastructure.persistence.connections import open_connection
from calendar_sync.infrastructure.persistence.source_changes import (
    SqliteSourceObservationRepository,
    change_columns,
)
from calendar_sync.infrastructure.scheduling import SystemClock
from calendar_sync.infrastructure.security import HistoryCipher

_FORWARD_MIGRATIONS = (
    (2, "0002_account_avatar.sql"),
    (3, "0003_audit_reasons.sql"),
    (4, "0004_rule_editing.sql"),
    (5, "0005_occurrence_mappings.sql"),
    (6, "0006_rule_previews.sql"),
    (7, "0007_audit_run_index.sql"),
    (8, "0008_last_full_sync.sql"),
    (9, "0009_audit_event_titles.sql"),
    (10, "0010_pending_exception_replays.sql"),
    (11, "0011_rule_block_checks.sql"),
    (12, "0012_incident_resolutions.sql"),
    (13, "0013_incident_accounts.sql"),
    (14, "0014_source_changes.sql"),
    (15, "0015_invitation_responses.sql"),
    (16, "0016_calendar_names.sql"),
    (17, "0017_provider_kinds.sql"),
    (18, "0018_integration_tokens.sql"),
    (19, "0019_incident_messages.sql"),
    (20, "0020_lapsed_authorization.sql"),
    (21, "0021_users.sql"),
    (22, "0022_registration.sql"),
    (23, "0023_token_scopes.sql"),
    (24, "0024_rule_creation_order.sql"),
    (25, "0025_provider_calls.sql"),
    (26, "0026_failure_causes.sql"),
    (27, "0027_failure_providers.sql"),
    (28, "0028_oauth_state_providers.sql"),
)
_CHECKED_FROM = 21
"""Migrations from here on prove every reference before committing. Earlier ones ran before
references were checked, and a database they left may hold rows no reference reaches."""


class MigrationFailed(RuntimeError):
    """A migration would have left a record referring to one that does not exist."""


def initialize_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    migrations = files("calendar_sync.infrastructure.persistence")
    with closing(open_connection(path)) as connection:
        # Recorded in the database file, so every later connection writes ahead too: a reader then
        # never keeps the scheduler from committing, nor the scheduler a request from reading.
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        applied = {
            int(row[0]) for row in connection.execute("SELECT version FROM schema_migrations")
        }
        if 1 not in applied:
            # Only a new database: later migrations replace tables the initial schema creates.
            connection.executescript(migrations.joinpath("0001_initial.sql").read_text())
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (1, datetime.now(UTC).isoformat()),
            )
            connection.commit()
        # SQLite rebuilds a table only with references unchecked, and changes that setting only
        # outside a transaction; each migration checks its own before it commits.
        connection.execute("PRAGMA foreign_keys = OFF")
        try:
            for version, name in _FORWARD_MIGRATIONS:
                if version not in applied:
                    _migrate(connection, version, migrations.joinpath(name).read_text())
        finally:
            connection.execute("PRAGMA foreign_keys = ON")


def _migrate(connection: sqlite3.Connection, version: int, script: str) -> None:
    """Apply one migration with its version record atomically, so it runs at most once."""
    connection.executescript(f"BEGIN;\n{script}")
    broken = (
        connection.execute("PRAGMA foreign_key_check").fetchall()
        if version >= _CHECKED_FROM
        else []
    )
    if broken:
        connection.rollback()
        tables = ", ".join(sorted({str(row[0]) for row in broken}))
        raise MigrationFailed(
            f"migration {version} would leave records in {tables} that refer to missing records; "
            "nothing was changed"
        )
    connection.execute(
        "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
        (version, datetime.now(UTC).isoformat()),
    )
    connection.commit()


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
        return _rule_from_row(row) if row else None

    def list(self) -> Sequence[SyncRule]:
        rows = self._connection.execute(
            "SELECT * FROM sync_rules WHERE user_id = ? ORDER BY id", (self._user,)
        ).fetchall()
        return tuple(_rule_from_row(row) for row in rows)

    def add(self, rule: SyncRule) -> None:
        try:
            self._connection.execute(
                """
                INSERT INTO sync_rules (
                    id, source_account_id, source_calendar_id,
                    destination_account_id, destination_calendar_id,
                    privacy_policy, all_day_policy, busy_title,
                    tentative_policy, unanswered_policy,
                    initial_lookback_days, state, reprojection_required,
                    awaiting_reauthorization, user_id, creation_order
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    (SELECT COALESCE(MAX(creation_order), 0) + 1 FROM sync_rules)
                )
                """,
                (*_rule_values(rule), self._user),
            )
        except sqlite3.IntegrityError as error:
            raise DuplicateDirectionalRelationship(
                "a rule already exists for this source and destination"
            ) from error

    def save(self, rule: SyncRule) -> None:
        try:
            cursor = self._update(rule)
        except sqlite3.IntegrityError as error:
            raise DuplicateDirectionalRelationship(
                "a rule already exists for this source and destination"
            ) from error
        if cursor.rowcount != 1:
            raise KeyError(f"sync rule {rule.id.value} does not exist")

    def _update(self, rule: SyncRule) -> sqlite3.Cursor:
        return self._connection.execute(
            """
            UPDATE sync_rules SET
                source_account_id = ?, source_calendar_id = ?,
                destination_account_id = ?, destination_calendar_id = ?,
                privacy_policy = ?, all_day_policy = ?, busy_title = ?,
                tentative_policy = ?, unanswered_policy = ?,
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

    def save(self, mapping: EventMapping) -> None:
        # The composite reference refuses a mapping for another User's rule; the update touches
        # only this User's mapping, so another User's identifier is refused rather than changed.
        cursor = self._connection.execute(
            """
            INSERT INTO event_mappings (
                id, rule_id, source_account_id, source_calendar_id, source_event_id,
                destination_account_id, destination_calendar_id, destination_event_id,
                source_revision, projection_fingerprint, user_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )
        if cursor.rowcount != 1:
            raise sqlite3.IntegrityError(f"event mapping {mapping.id.value} is another User's")

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
        cursor = self._connection.execute(
            """
            INSERT INTO pending_exception_replays (series_mapping_id, user_id) VALUES (?, ?)
            ON CONFLICT(series_mapping_id) DO UPDATE SET user_id = excluded.user_id
            WHERE pending_exception_replays.user_id = excluded.user_id
            """,
            (series_mapping_id.value, self._user),
        )
        if cursor.rowcount != 1:
            raise sqlite3.IntegrityError(
                f"series mapping {series_mapping_id.value} is not this User's"
            )

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
        cursor = self._connection.execute(
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
        if cursor.rowcount != 1:
            raise sqlite3.IntegrityError(f"occurrence mapping {mapping.id.value} is another User's")

    def delete(self, mapping: OccurrenceMapping) -> None:
        self._connection.execute(
            """
            DELETE FROM occurrence_mappings
            WHERE series_mapping_id = ? AND original_start = ? AND user_id = ?
            """,
            (mapping.series_mapping_id.value, _serialize_start(mapping.original_start), self._user),
        )


def _require_own(cursor: sqlite3.Cursor, rule_id: SyncRuleId) -> None:
    """Refuse a write an upsert skipped because the record it met is another User's."""
    if cursor.rowcount != 1:
        raise sqlite3.IntegrityError(f"a record of rule {rule_id.value} is another User's")


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
        _require_own(
            self._connection.execute(
                f"""
                INSERT INTO {self._table}(rule_id, cursor, user_id) VALUES (?, ?, ?)
                ON CONFLICT(rule_id) DO UPDATE SET cursor = excluded.cursor
                WHERE user_id = excluded.user_id
                """,  # noqa: S608
                (rule_id.value, cursor, self._user),
            ),
            rule_id,
        )


class SqliteAuditRepository:
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
                change_fields, change_title_before, change_sealed, user_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                self._user,
            ),
        )

    def forget_change_values(self, before: datetime) -> None:
        self._connection.execute(
            """
            UPDATE audit_entries SET change_sealed = NULL
            WHERE change_sealed IS NOT NULL AND occurred_at < ? AND user_id = ?
            """,
            (before.isoformat(), self._user),
        )


class SqliteRuleRunOutcomeRepository:
    def __init__(self, connection: sqlite3.Connection, user_id: UserId) -> None:
        self._connection = connection
        self._user = user_id.value

    def record(self, outcome: RuleRunOutcome) -> None:
        cursor = self._connection.execute(
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
                outcome.failure_kind,
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
        _require_own(cursor, outcome.rule_id)

    def latest(self, rule_id: SyncRuleId, kind: RunKind) -> RuleRunOutcome | None:
        row = self._connection.execute(
            "SELECT * FROM rule_run_outcomes WHERE rule_id = ? AND kind = ? AND user_id = ?",
            (rule_id.value, kind.value, self._user),
        ).fetchone()
        return _outcome_from_row(row) if row is not None else None


def _caused(outcome: RuleRunOutcome) -> bool:
    """Whether a provider's answer explains the outcome: a failure that is not local."""
    return not outcome.succeeded and outcome.failure_kind not in WITHOUT_CAUSE


def _outcome_from_row(row: sqlite3.Row) -> RuleRunOutcome:
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
        failure_kind=None if row["failure_kind"] is None else str(row["failure_kind"]),
        failure_cause=None
        if row["succeeded"] or row["failure_kind"] in WITHOUT_CAUSE
        else Cause.recorded(row["failure_cause"]),
        failure_provider=ProviderKind.recorded(row["failure_provider"]),
        last_succeeded_at=_optional_time(row["last_succeeded_at"]),
        last_full_succeeded_at=_optional_time(row["last_full_succeeded_at"]),
    )


def _cause_sighting(row: sqlite3.Row) -> CauseSighting:
    opened, authorized = _optional_time(row["opened_at"]), _optional_time(row["authorized_at"])
    lived = opened - authorized if row["open"] and opened and authorized else None
    return CauseSighting(
        UserId(str(row["user_id"])),
        Cause.read(row["cause"]),
        datetime.fromisoformat(str(row["at"])),
        bool(row["open"]),
        lived,
        provider=ProviderKind.recorded(row["provider"]),
    )


def _optional_time(value: object) -> datetime | None:
    return None if value is None else datetime.fromisoformat(str(value))


class SqliteRulePreviewRepository:
    def __init__(self, connection: sqlite3.Connection, user_id: UserId) -> None:
        self._connection = connection
        self._user = user_id.value

    def record(self, summary: RulePreviewSummary) -> None:
        cursor = self._connection.execute(
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
        _require_own(cursor, summary.rule_id)

    def latest(self, rule_id: SyncRuleId) -> RulePreviewSummary | None:
        row = self._connection.execute(
            "SELECT * FROM rule_previews WHERE rule_id = ? AND user_id = ?",
            (rule_id.value, self._user),
        ).fetchone()
        return _preview_from_row(row) if row is not None else None


def _preview_from_row(row: sqlite3.Row) -> RulePreviewSummary:
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


class SqliteInstallationUnitOfWork:
    """What the scheduler and the Operator Overview read across Users (ADR 0029)."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._connection: sqlite3.Connection | None = None

    def __enter__(self) -> Self:
        self._connection = open_connection(self._database_path)
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
        self._connection.commit()

    def scheduled_rules(self) -> Sequence[ScheduledRule]:
        assert self._connection is not None
        rows = self._connection.execute(
            """
            SELECT sync_rules.*, outcome.last_full_succeeded_at
            FROM sync_rules
            JOIN users ON users.id = sync_rules.user_id AND users.state = 'active'
            LEFT JOIN rule_run_outcomes outcome
              ON outcome.rule_id = sync_rules.id AND outcome.kind = 'sync'
            WHERE sync_rules.state = ?
            ORDER BY sync_rules.user_id, sync_rules.id
            """,
            (SyncRuleState.ENABLED.value,),
        ).fetchall()
        return tuple(
            ScheduledRule(
                UserId(str(row["user_id"])),
                _rule_from_row(row),
                _optional_time(row["last_full_succeeded_at"]),
            )
            for row in rows
        )

    def forget_change_values(self, before: datetime) -> None:
        assert self._connection is not None
        self._connection.execute(
            """
            UPDATE audit_entries SET change_sealed = NULL
            WHERE change_sealed IS NOT NULL AND occurred_at < ?
            """,
            (before.isoformat(),),
        )

    def resource_use(self, users: Collection[UserId], since: date) -> dict[UserId, ResourceUse]:
        assert self._connection is not None
        use: dict[UserId, ResourceUse] = {}
        ordered = sorted({user.value for user in users})
        for start in range(0, len(ordered), _USERS_PER_QUERY):
            chunk = ordered[start : start + _USERS_PER_QUERY]
            use |= _resource_use(self._connection, chunk, since)
        return use

    def forget_provider_calls(self, before: date) -> None:
        assert self._connection is not None
        self._connection.execute("DELETE FROM provider_calls WHERE day < ?", (before.isoformat(),))

    def failure_causes(self, since: datetime) -> list[CauseSighting]:
        assert self._connection is not None
        # A lapsed account's Incident is joined to the account, whose last authorization time
        # tells how long its grant lived; only that time is read, never who the account is.
        rows = self._connection.execute(
            """
            SELECT user_id, failure_cause AS cause, completed_at AS at, 0 AS open,
                NULL AS opened_at, NULL AS authorized_at, failure_provider AS provider
            FROM rule_run_outcomes
            WHERE succeeded = 0 AND failure_cause IS NOT NULL AND failure_cause != 'none'
                AND completed_at >= ?
                AND failure_kind NOT IN ('infrastructure', 'conflict')
            UNION ALL
            SELECT incident.user_id, incident.cause, incident.updated_at,
                incident.state = 'open', incident.opened_at, account.updated_at,
                incident.provider
            FROM incidents incident
            LEFT JOIN connected_accounts account
                ON incident.rule_id IS NULL
                AND account.id = incident.account_id
                AND account.user_id = incident.user_id
                AND account.state = 'connected'
                AND account.authorization_lapsed_at IS NOT NULL
            WHERE incident.cause IS NOT NULL AND incident.cause != 'none'
                AND incident.category NOT IN ('infrastructure', 'conflict')
                AND (incident.state = 'open' OR incident.updated_at >= ?)
            ORDER BY user_id, at
            """,
            (since.isoformat(), since.isoformat()),
        ).fetchall()
        return [_cause_sighting(row) for row in rows]

    def status_records(self, users: Collection[UserId]) -> dict[UserId, StatusRecords]:
        assert self._connection is not None
        records: dict[UserId, StatusRecords] = {}
        ordered = sorted({user.value for user in users})
        for start in range(0, len(ordered), _USERS_PER_QUERY):
            chunk = ordered[start : start + _USERS_PER_QUERY]
            rules = _recorded_rules(self._connection, chunk)
            for user, operations in operations_of(self._connection, chunk).items():
                records[UserId(user)] = StatusRecords(
                    rules=tuple(rules.get(user, ())),
                    overview=operations.overview,
                    incidents=operations.incidents,
                )
        return records


_USERS_PER_QUERY = 500
"""Users read together, well under SQLite's limit on bound values in one statement."""


def _resource_use(
    connection: sqlite3.Connection, users: Sequence[str], since: date
) -> dict[UserId, ResourceUse]:
    marks = ", ".join("?" * len(users))

    def counted(table: str) -> dict[str, int]:
        # Interpolates only constant table names and `?` placeholders; values stay bound.
        return dict(
            connection.execute(
                f"""
                SELECT user_id, COUNT(*) FROM {table}
                WHERE user_id IN ({marks}) GROUP BY user_id
                """,  # noqa: S608
                users,
            ).fetchall()
        )

    rules, accounts, entries = (
        counted("sync_rules"),
        counted("connected_accounts"),
        counted("audit_entries"),
    )
    calls: dict[str, list[ProviderCallUse]] = {}
    for row in connection.execute(
        f"""
        SELECT user_id, provider, SUM(calls), SUM(rate_limited), SUM(failed)
        FROM provider_calls WHERE user_id IN ({marks}) AND day >= ?
        GROUP BY user_id, provider ORDER BY user_id, provider
        """,  # noqa: S608
        (*users, since.isoformat()),
    ):
        calls.setdefault(str(row[0]), []).append(
            ProviderCallUse(ProviderKind(str(row[1])), int(row[2]), int(row[3]), int(row[4]))
        )
    return {
        UserId(user): ResourceUse(
            rules=rules.get(user, 0),
            connected_accounts=accounts.get(user, 0),
            activity_entries=entries.get(user, 0),
            provider_calls=tuple(calls.get(user, ())),
        )
        for user in users
    }


def _recorded_rules(
    connection: sqlite3.Connection, users: Sequence[str]
) -> dict[str, list[RecordedRule]]:
    """Each of `users`' rules in the order they were created, with what status reads of them."""
    marks = ", ".join("?" * len(users))
    # Interpolates only `?` placeholders; values stay bound.
    outcomes = {
        str(row["rule_id"]): _outcome_from_row(row)
        for row in connection.execute(
            f"SELECT * FROM rule_run_outcomes WHERE kind = 'sync' AND user_id IN ({marks})",  # noqa: S608
            users,
        )
    }
    previews = {
        str(row["rule_id"]): _preview_from_row(row)
        for row in connection.execute(
            f"SELECT * FROM rule_previews WHERE user_id IN ({marks})",  # noqa: S608
            users,
        )
    }
    rules: dict[str, list[RecordedRule]] = {}
    for row in connection.execute(
        f"""
        SELECT * FROM sync_rules WHERE user_id IN ({marks})
        ORDER BY user_id, creation_order, id
        """,  # noqa: S608
        users,
    ):
        rule_id = str(row["id"])
        rules.setdefault(str(row["user_id"]), []).append(
            RecordedRule(_rule_from_row(row), outcomes.get(rule_id), previews.get(rule_id))
        )
    return rules


@dataclass(frozen=True, slots=True)
class SqliteInstallationUnitOfWorkFactory:
    database_path: Path

    def __call__(self) -> InstallationUnitOfWork:
        return SqliteInstallationUnitOfWork(self.database_path)


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
        rule.initial_lookback_days,
        rule.state.value,
        int(rule.reprojection_required),
        int(rule.awaiting_reauthorization),
    )


def _rule_from_row(row: sqlite3.Row) -> SyncRule:
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
    )
