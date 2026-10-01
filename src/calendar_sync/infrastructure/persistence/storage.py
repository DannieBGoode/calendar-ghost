"""Database usage, and clearing Activity older than an administrator-chosen age (ADR 0019)."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from calendar_sync.application.ports import DatabaseUsage

# Entries clearing never removes. Each is the latest of its rule and source event in one sense:
# overall (open blocks), at or before the rule's last block check (persisting blocks), and among
# those that recorded a title (the name a cancellation without one is shown with).
_PROTECTED = """
    SELECT MAX(id) FROM audit_entries GROUP BY rule_id, source_event_id
    UNION
    SELECT MAX(a.id) FROM audit_entries a
    JOIN rule_block_checks c ON c.rule_id = a.rule_id
    WHERE a.id <= c.audit_floor
    GROUP BY a.rule_id, a.source_event_id
    UNION
    SELECT MAX(id) FROM audit_entries
    WHERE event_title IS NOT NULL AND (event_title <> '' OR NOT event_cancelled)
    GROUP BY rule_id, source_event_id
"""


class SqliteStorage:
    def __init__(self, database_path: Path, batch: int = 5000) -> None:
        self._database_path = database_path
        self._batch = batch

    def usage(self) -> DatabaseUsage:
        with closing(sqlite3.connect(self._database_path)) as connection:
            page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
            pages = int(connection.execute("PRAGMA page_count").fetchone()[0])
            free = int(connection.execute("PRAGMA freelist_count").fetchone()[0])
            count, oldest = connection.execute(
                "SELECT COUNT(*), MIN(occurred_at) FROM audit_entries"
            ).fetchone()
        return DatabaseUsage(
            bytes=pages * page_size,
            reclaimable_bytes=free * page_size,
            activity_entries=int(count),
            oldest_activity_at=datetime.fromisoformat(oldest) if oldest else None,
        )

    def clearable_activity(self, before: datetime) -> int:
        with closing(sqlite3.connect(self._database_path)) as connection:
            # Interpolates only the constant protected-entries query.
            row = connection.execute(
                f"SELECT COUNT(*) FROM audit_entries WHERE occurred_at < ? "  # noqa: S608
                f"AND id NOT IN ({_PROTECTED})",
                (before.isoformat(),),
            ).fetchone()
        return int(row[0])

    def clear_activity(self, before: datetime) -> int:
        removed = 0
        with closing(sqlite3.connect(self._database_path)) as connection:
            # Chosen once, so batches never re-evaluate which entries are protected.
            connection.execute("DROP TABLE IF EXISTS temp.clearable")
            connection.execute(
                f"CREATE TEMP TABLE clearable AS SELECT id FROM audit_entries "  # noqa: S608
                f"WHERE occurred_at < ? AND id NOT IN ({_PROTECTED})",
                (before.isoformat(),),
            )
            connection.commit()
            while True:
                batch = [
                    row[0]
                    for row in connection.execute(
                        "SELECT id FROM temp.clearable ORDER BY id LIMIT ?", (self._batch,)
                    )
                ]
                if not batch:
                    return removed
                marks = ", ".join("?" for _ in batch)
                # One short write transaction per batch (AGENTS.md).
                with connection:
                    removed += connection.execute(
                        f"DELETE FROM audit_entries WHERE id IN ({marks})",  # noqa: S608
                        batch,
                    ).rowcount
                    connection.execute(
                        f"DELETE FROM temp.clearable WHERE id IN ({marks})",  # noqa: S608
                        batch,
                    )

    def compact(self) -> None:
        with closing(sqlite3.connect(self._database_path, isolation_level=None)) as connection:
            connection.execute("VACUUM")
