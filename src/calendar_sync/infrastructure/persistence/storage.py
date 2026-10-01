"""Database usage, and clearing Activity older than an administrator-chosen age (ADR 0019)."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from calendar_sync.application.errors import STORAGE_BUSY_MESSAGE, StorageBusy
from calendar_sync.application.ports import DatabaseUsage
from calendar_sync.infrastructure.persistence.activity_queries import _TITLE_OBSERVED

# Entries clearing never removes, per rule and source event: the latest entry older than the
# cutoff, and the latest older than it that recorded a title. Every reader that compares an entry
# with an earlier one for the same rule and source event -- `_previous_names`, `_repeated_repairs`,
# and a persisting block check at any floor at or after the cutoff -- looks back at most one entry
# past the cutoff, and these two clauses are that entry. When every entry of an event is older than
# the cutoff, its latest is still kept by the first clause, which keeps its open blocks and the
# dashboard's blocked-entry links too. Every entry newer than the cutoff is kept regardless, by the
# caller's own `occurred_at < ?` condition.
# Protection selects by `occurred_at` while those readers find an entry's predecessor by id, so it
# assumes ids follow `occurred_at` within a rule and source event. That holds because entries are
# appended with the clock's current time; a clock stepping back only changes how an entry inside
# the window compares with its predecessor, and never which blocks are open.
# Interpolates only the constant `_TITLE_OBSERVED` predicate.
_PROTECTED = f"""
    SELECT MAX(id) FROM audit_entries WHERE occurred_at < ? GROUP BY rule_id, source_event_id
    UNION
    SELECT MAX(id) FROM audit_entries WHERE occurred_at < ? AND {_TITLE_OBSERVED}
    GROUP BY rule_id, source_event_id
"""  # noqa: S608


class SqliteStorage:
    def __init__(self, database_path: Path, batch: int = 5000, busy_timeout: float = 30.0) -> None:
        self._database_path = database_path
        self._batch = batch
        self._busy_timeout = busy_timeout

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
        cutoff = before.astimezone(UTC).isoformat()
        with closing(sqlite3.connect(self._database_path)) as connection:
            # Interpolates only the constant protected-entries query.
            row = connection.execute(
                f"SELECT COUNT(*) FROM audit_entries WHERE occurred_at < ? "  # noqa: S608
                f"AND id NOT IN ({_PROTECTED})",
                (cutoff, cutoff, cutoff),
            ).fetchone()
        return int(row[0])

    def clear_activity(self, before: datetime) -> int:
        cutoff = before.astimezone(UTC).isoformat()
        removed = 0
        with closing(sqlite3.connect(self._database_path)) as connection:
            # Chosen once, so batches never re-evaluate which entries are protected. A fresh
            # connection never carries a temp table over from an earlier call.
            # Keyed by id, so each batch reads and deletes its candidates without a full scan.
            connection.execute("CREATE TEMP TABLE clearable (id INTEGER PRIMARY KEY)")
            connection.execute(
                f"INSERT INTO temp.clearable SELECT id FROM audit_entries "  # noqa: S608
                f"WHERE occurred_at < ? AND id NOT IN ({_PROTECTED})",
                (cutoff, cutoff, cutoff),
            )
            # The insert opened a read transaction on the database; ending it lets a writer that
            # started meanwhile commit, and each batch then waits for its own write lock.
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
        try:
            with closing(
                sqlite3.connect(
                    self._database_path, isolation_level=None, timeout=self._busy_timeout
                )
            ) as connection:
                connection.execute("VACUUM")
        except sqlite3.OperationalError as error:
            detail = str(error).lower()
            if "locked" in detail or "busy" in detail:
                raise StorageBusy(STORAGE_BUSY_MESSAGE) from error
            raise
