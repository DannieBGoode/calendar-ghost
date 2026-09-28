from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import UTC, date, datetime
from importlib.resources import files
from pathlib import Path
from types import TracebackType
from typing import Self

from calendar_sync.application.errors import DuplicateDirectionalRelationship
from calendar_sync.application.ports import (
    AuditEntry,
    AuditRepository,
    EventMappingRepository,
    OccurrenceMappingRepository,
    RuleRunOutcome,
    RuleRunOutcomeRepository,
    RunKind,
    SyncCursorRepository,
    SyncRuleRepository,
    UnitOfWork,
)
from calendar_sync.domain.model import (
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
    PrivacyPolicy,
    ProjectionFingerprint,
    SyncRule,
    SyncRuleId,
    SyncRuleState,
    TransformationPolicy,
)

_FORWARD_MIGRATIONS = (
    (2, "0002_account_avatar.sql"),
    (3, "0003_audit_reasons.sql"),
    (4, "0004_rule_editing.sql"),
    (5, "0005_occurrence_mappings.sql"),
)


def initialize_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    migrations = files("calendar_sync.infrastructure.persistence")
    with sqlite3.connect(path) as connection:
        connection.executescript(migrations.joinpath("0001_initial.sql").read_text())
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            (1, datetime.now(UTC).isoformat()),
        )
        connection.commit()
        applied = {
            int(row[0]) for row in connection.execute("SELECT version FROM schema_migrations")
        }
        for version, name in _FORWARD_MIGRATIONS:
            if version in applied:
                continue
            # Later migrations are not idempotent, so each one commits atomically with its
            # version record and runs at most once.
            connection.executescript(
                "BEGIN;\n"
                f"{migrations.joinpath(name).read_text()}\n"
                "INSERT INTO schema_migrations(version, applied_at) "
                f"VALUES ({version}, '{datetime.now(UTC).isoformat()}');\n"
                "COMMIT;"
            )


class SqliteSyncRuleRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get(self, rule_id: SyncRuleId) -> SyncRule | None:
        row = self._connection.execute(
            "SELECT * FROM sync_rules WHERE id = ?", (rule_id.value,)
        ).fetchone()
        return _rule_from_row(row) if row else None

    def list(self) -> Sequence[SyncRule]:
        rows = self._connection.execute("SELECT * FROM sync_rules ORDER BY id").fetchall()
        return tuple(_rule_from_row(row) for row in rows)

    def add(self, rule: SyncRule) -> None:
        try:
            self._connection.execute(
                """
                INSERT INTO sync_rules (
                    id, source_account_id, source_calendar_id,
                    destination_account_id, destination_calendar_id,
                    privacy_policy, all_day_policy, busy_title,
                    initial_lookback_days, state, reprojection_required
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _rule_values(rule),
            )
        except sqlite3.IntegrityError as error:
            raise DuplicateDirectionalRelationship(
                "a rule already exists for this source and destination"
            ) from error

    def save(self, rule: SyncRule) -> None:
        cursor = self._connection.execute(
            """
            UPDATE sync_rules SET
                source_account_id = ?, source_calendar_id = ?,
                destination_account_id = ?, destination_calendar_id = ?,
                privacy_policy = ?, all_day_policy = ?, busy_title = ?,
                initial_lookback_days = ?, state = ?, reprojection_required = ?
            WHERE id = ?
            """,
            (*_rule_values(rule)[1:], rule.id.value),
        )
        if cursor.rowcount != 1:
            raise KeyError(f"sync rule {rule.id.value} does not exist")

    def remove(self, rule_id: SyncRuleId) -> None:
        now = datetime.now(UTC).isoformat()
        self._connection.execute(
            """
            UPDATE incidents SET state = 'resolved', updated_at = ?, resolved_at = ?
            WHERE rule_id = ? AND state = 'open'
            """,
            (now, now, rule_id.value),
        )
        self._connection.execute("DELETE FROM sync_rules WHERE id = ?", (rule_id.value,))

    def relationship_exists(self, source: CalendarEndpoint, destination: CalendarEndpoint) -> bool:
        row = self._connection.execute(
            """
            SELECT 1 FROM sync_rules
            WHERE source_account_id = ? AND source_calendar_id = ?
              AND destination_account_id = ? AND destination_calendar_id = ?
            LIMIT 1
            """,
            (
                source.connected_account_id.value,
                source.calendar_id.value,
                destination.connected_account_id.value,
                destination.calendar_id.value,
            ),
        ).fetchone()
        return row is not None


class SqliteEventMappingRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def for_source(self, rule_id: SyncRuleId, source: EventRef) -> EventMapping | None:
        row = self._connection.execute(
            """
            SELECT * FROM event_mappings
            WHERE rule_id = ? AND source_account_id = ?
              AND source_calendar_id = ? AND source_event_id = ?
            """,
            (
                rule_id.value,
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
            WHERE rule_id = ? AND destination_account_id = ?
              AND destination_calendar_id = ? AND destination_event_id = ?
            """,
            (
                rule_id.value,
                destination.calendar.connected_account_id.value,
                destination.calendar.calendar_id.value,
                destination.event_id.value,
            ),
        ).fetchone()
        return _mapping_from_row(row) if row else None

    def for_rule(self, rule_id: SyncRuleId) -> Sequence[EventMapping]:
        rows = self._connection.execute(
            "SELECT * FROM event_mappings WHERE rule_id = ? ORDER BY id", (rule_id.value,)
        ).fetchall()
        return tuple(_mapping_from_row(row) for row in rows)

    def save(self, mapping: EventMapping) -> None:
        self._connection.execute(
            """
            INSERT INTO event_mappings (
                id, rule_id, source_account_id, source_calendar_id, source_event_id,
                destination_account_id, destination_calendar_id, destination_event_id,
                source_revision, projection_fingerprint
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                source_revision = excluded.source_revision,
                destination_account_id = excluded.destination_account_id,
                destination_calendar_id = excluded.destination_calendar_id,
                destination_event_id = excluded.destination_event_id,
                projection_fingerprint = excluded.projection_fingerprint
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
            ),
        )

    def delete(self, mapping: EventMapping) -> None:
        self._connection.execute("DELETE FROM event_mappings WHERE id = ?", (mapping.id.value,))

    def count_for_rule(self, rule_id: SyncRuleId) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) FROM event_mappings WHERE rule_id = ?", (rule_id.value,)
        ).fetchone()
        return int(row[0])


class SqliteOccurrenceMappingRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def for_series(self, series_mapping_id: EventMappingId) -> Sequence[OccurrenceMapping]:
        rows = self._connection.execute(
            "SELECT * FROM occurrence_mappings WHERE series_mapping_id = ? ORDER BY original_start",
            (series_mapping_id.value,),
        ).fetchall()
        return tuple(_occurrence_from_row(row) for row in rows)

    def get(
        self, series_mapping_id: EventMappingId, original_start: OccurrenceStart
    ) -> OccurrenceMapping | None:
        row = self._connection.execute(
            "SELECT * FROM occurrence_mappings WHERE series_mapping_id = ? AND original_start = ?",
            (series_mapping_id.value, _serialize_start(original_start)),
        ).fetchone()
        return _occurrence_from_row(row) if row else None

    def save(self, mapping: OccurrenceMapping) -> None:
        self._connection.execute(
            """
            INSERT INTO occurrence_mappings (
                id, series_mapping_id, original_start,
                source_account_id, source_calendar_id, source_event_id,
                destination_account_id, destination_calendar_id, destination_event_id,
                state, source_revision, projection_fingerprint
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )

    def delete(self, mapping: OccurrenceMapping) -> None:
        self._connection.execute(
            "DELETE FROM occurrence_mappings WHERE series_mapping_id = ? AND original_start = ?",
            (mapping.series_mapping_id.value, _serialize_start(mapping.original_start)),
        )


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
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get(self, rule_id: SyncRuleId) -> str | None:
        row = self._connection.execute(
            "SELECT cursor FROM sync_cursors WHERE rule_id = ?", (rule_id.value,)
        ).fetchone()
        return str(row["cursor"]) if row else None

    def save(self, rule_id: SyncRuleId, cursor: str) -> None:
        self._connection.execute(
            """
            INSERT INTO sync_cursors(rule_id, cursor) VALUES (?, ?)
            ON CONFLICT(rule_id) DO UPDATE SET cursor = excluded.cursor
            """,
            (rule_id.value, cursor),
        )


class SqliteDestinationSyncCursorRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get(self, rule_id: SyncRuleId) -> str | None:
        row = self._connection.execute(
            "SELECT cursor FROM destination_sync_cursors WHERE rule_id = ?",
            (rule_id.value,),
        ).fetchone()
        return str(row["cursor"]) if row else None

    def save(self, rule_id: SyncRuleId, cursor: str) -> None:
        self._connection.execute(
            """
            INSERT INTO destination_sync_cursors(rule_id, cursor) VALUES (?, ?)
            ON CONFLICT(rule_id) DO UPDATE SET cursor = excluded.cursor
            """,
            (rule_id.value, cursor),
        )


class SqliteAuditRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def append(self, entry: AuditEntry) -> None:
        self._connection.execute(
            """
            INSERT INTO audit_entries (
                occurred_at, rule_id, action, outcome,
                source_event_id, destination_event_id, detail, reason, run_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )


class SqliteRuleRunOutcomeRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def record(self, outcome: RuleRunOutcome) -> None:
        self._connection.execute(
            """
            INSERT INTO rule_run_outcomes (
                rule_id, kind, completed_at, succeeded, full_run, created, updated,
                deleted, conflicts, checked_mappings, drift, failure_kind
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(rule_id, kind) DO UPDATE SET
                completed_at = excluded.completed_at,
                succeeded = excluded.succeeded,
                full_run = excluded.full_run,
                created = excluded.created,
                updated = excluded.updated,
                deleted = excluded.deleted,
                conflicts = excluded.conflicts,
                checked_mappings = excluded.checked_mappings,
                drift = excluded.drift,
                failure_kind = excluded.failure_kind
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
            ),
        )

    def latest(self, rule_id: SyncRuleId, kind: RunKind) -> RuleRunOutcome | None:
        row = self._connection.execute(
            "SELECT * FROM rule_run_outcomes WHERE rule_id = ? AND kind = ?",
            (rule_id.value, kind.value),
        ).fetchone()
        if row is None:
            return None
        return RuleRunOutcome(
            rule_id=rule_id,
            kind=kind,
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
        )


class SqliteUnitOfWork:
    rules: SyncRuleRepository
    mappings: EventMappingRepository
    occurrences: OccurrenceMappingRepository
    cursors: SyncCursorRepository
    destination_cursors: SyncCursorRepository
    audit: AuditRepository
    run_outcomes: RuleRunOutcomeRepository

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._connection: sqlite3.Connection | None = None

    def __enter__(self) -> Self:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        self._connection = connection
        self.rules = SqliteSyncRuleRepository(connection)
        self.mappings = SqliteEventMappingRepository(connection)
        self.occurrences = SqliteOccurrenceMappingRepository(connection)
        self.cursors = SqliteSyncCursorRepository(connection)
        self.destination_cursors = SqliteDestinationSyncCursorRepository(connection)
        self.audit = SqliteAuditRepository(connection)
        self.run_outcomes = SqliteRuleRunOutcomeRepository(connection)
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


class SqliteUnitOfWorkFactory:
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path

    def __call__(self) -> UnitOfWork:
        return SqliteUnitOfWork(self._database_path)


def _rule_values(rule: SyncRule) -> tuple[object, ...]:
    return (
        rule.id.value,
        rule.source.connected_account_id.value,
        rule.source.calendar_id.value,
        rule.destination.connected_account_id.value,
        rule.destination.calendar_id.value,
        rule.transformation.privacy.value,
        rule.transformation.all_day.value,
        rule.transformation.busy_title,
        rule.initial_lookback_days,
        rule.state.value,
        int(rule.reprojection_required),
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
            privacy=PrivacyPolicy(str(row["privacy_policy"])),
            all_day=AllDaySyncPolicy(str(row["all_day_policy"])),
            busy_title=str(row["busy_title"]),
        ),
        initial_lookback_days=int(row["initial_lookback_days"]),
        state=SyncRuleState(str(row["state"])),
        reprojection_required=bool(row["reprojection_required"]),
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
