from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import date, datetime

from calendar_sync.application.sync.errors import IdentityCollision, MissingReference
from calendar_sync.domain.access import UserId
from calendar_sync.domain.model import (
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
    ProjectionFingerprint,
    SyncRuleId,
)
from calendar_sync.infrastructure.persistence.refusals import refusals


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
