from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from calendar_sync.application.errors import ProviderFailureKind
from calendar_sync.application.ports import IdGenerator, IncidentReport, IncidentResolution
from calendar_sync.domain.model import SyncRuleId
from calendar_sync.infrastructure.identifiers import UuidIdGenerator
from calendar_sync.infrastructure.persistence.activity_queries import open_blocks


class SqliteRuleHealthRecords:
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path

    def record_failure(self, rule_id: SyncRuleId, kind: ProviderFailureKind, at: datetime) -> int:
        with sqlite3.connect(self._database_path) as connection:
            connection.execute(
                """
                INSERT INTO rule_failures(rule_id, consecutive_failures, last_category, updated_at)
                VALUES (?, 1, ?, ?)
                ON CONFLICT(rule_id) DO UPDATE SET
                    consecutive_failures = consecutive_failures + 1,
                    last_category = excluded.last_category,
                    updated_at = excluded.updated_at
                """,
                (rule_id.value, kind.value, at.isoformat()),
            )
            return int(
                connection.execute(
                    "SELECT consecutive_failures FROM rule_failures WHERE rule_id = ?",
                    (rule_id.value,),
                ).fetchone()[0]
            )

    def clear_failures(self, rule_id: SyncRuleId) -> None:
        with sqlite3.connect(self._database_path) as connection:
            connection.execute("DELETE FROM rule_failures WHERE rule_id = ?", (rule_id.value,))

    def audit_floor(self) -> int:
        with sqlite3.connect(self._database_path) as connection:
            return int(
                connection.execute("SELECT COALESCE(MAX(id), 0) FROM audit_entries").fetchone()[0]
            )

    def record_block_check(
        self, rule_id: SyncRuleId, floor: int, run_id: str | None, at: datetime
    ) -> int | None:
        with sqlite3.connect(self._database_path) as connection:
            if not connection.execute(
                "SELECT 1 FROM sync_rules WHERE id = ?", (rule_id.value,)
            ).fetchone():
                return None
            persisting = len(
                open_blocks(
                    connection, rule_id=rule_id.value, after=floor, persisting=True, run_id=run_id
                )
            )
            connection.execute(
                """
                INSERT INTO rule_block_checks (rule_id, audit_floor, checked_at)
                VALUES (?, ?, ?)
                ON CONFLICT(rule_id) DO UPDATE SET
                    audit_floor = excluded.audit_floor, checked_at = excluded.checked_at
                """,
                (rule_id.value, floor, at.isoformat()),
            )
        return persisting


class SqliteIncidentRepository:
    def __init__(self, database_path: Path, ids: IdGenerator | None = None) -> None:
        self._database_path = database_path
        self._ids = ids or UuidIdGenerator()

    def open(self, incident: IncidentReport, at: datetime) -> bool:
        with sqlite3.connect(self._database_path) as connection:
            existing = connection.execute(
                "SELECT state FROM incidents WHERE deduplication_key = ?", (incident.key,)
            ).fetchone()
            connection.execute(
                """
                INSERT INTO incidents (
                    id, deduplication_key, rule_id, account_id, category, state,
                    summary, opened_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'open', ?, ?, ?)
                ON CONFLICT(deduplication_key) DO UPDATE SET
                    account_id = excluded.account_id,
                    category = excluded.category,
                    opened_at = CASE WHEN state = 'open' THEN opened_at ELSE excluded.opened_at END,
                    state = 'open',
                    summary = excluded.summary,
                    updated_at = excluded.updated_at,
                    resolved_at = NULL,
                    resolution = NULL
                """,
                (
                    self._ids.new(),
                    incident.key,
                    incident.rule_id.value,
                    incident.account_id.value if incident.account_id else None,
                    incident.category,
                    incident.summary,
                    at.isoformat(),
                    at.isoformat(),
                ),
            )
        return existing is None or existing[0] != "open"

    def resolve(self, key: str, at: datetime, resolution: IncidentResolution) -> None:
        with sqlite3.connect(self._database_path) as connection:
            connection.execute(
                """
                UPDATE incidents SET
                    state = 'resolved', updated_at = ?, resolved_at = ?, resolution = ?
                WHERE deduplication_key = ? AND state = 'open'
                """,
                (at.isoformat(), at.isoformat(), resolution.value, key),
            )
