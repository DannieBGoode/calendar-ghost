"""Database usage, and clearing Activity older than an administrator-chosen age (ADR 0019)."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from calendar_sync.application.errors import STORAGE_BUSY_MESSAGE, StorageBusy
from calendar_sync.application.ports import DatabaseUsage
from calendar_sync.infrastructure.persistence.activity_queries import _BLOCK, _TITLE_OBSERVED
from calendar_sync.infrastructure.persistence.connections import open_connection

# Entries clearing never removes, besides every entry newer than the cutoff (the caller's own
# `occurred_at < :cutoff` condition). Activity compares an entry with the earlier entries of its
# rule and source event by id: `_repeated_repairs` reads the previous entry, `_previous_names` the
# previous one that recorded a title, and a persisting block check the latest at or before its
# floor. So, by id rather than by time, which a clock stepping back would reorder, it keeps:
# - each event's latest entry, which keeps open blocks and the dashboard's blocked-entry links;
# - the previous entry of every entry newer than the cutoff, and of each event's latest when that
#   one is a block, which a block check compares with even when the clock made it look old;
# - the previous titled entry of every entry newer than the cutoff, and of each event's latest
#   when that one recorded no title, which Activity then names from it.
# With ids in time order these are the latest entry older than the cutoff and the latest titled
# one; entries newer than the cutoff then render exactly as before clearing.
# Interpolates only the constant `_TITLE_OBSERVED` and `_BLOCK` predicates.
_LATEST = "SELECT MAX(id) AS id FROM audit_entries GROUP BY rule_id, source_event_id"
_PREVIOUS = """
    SELECT MAX(p.id) FROM audit_entries p
    WHERE p.rule_id = k.rule_id AND p.source_event_id = k.source_event_id AND p.id < k.id
"""
_PROTECTED = f"""
    SELECT id FROM (
        {_LATEST}
        UNION
        SELECT ({_PREVIOUS}) FROM audit_entries k
        WHERE k.occurred_at >= :cutoff OR (k.id IN ({_LATEST}) AND {_BLOCK.format(t="k")})
        UNION
        SELECT ({_PREVIOUS} AND {_TITLE_OBSERVED}) FROM audit_entries k
        WHERE k.occurred_at >= :cutoff OR (k.id IN ({_LATEST}) AND NOT ({_TITLE_OBSERVED}))
    )
    WHERE id IS NOT NULL
"""  # noqa: S608


class SqliteStorage:
    def __init__(self, database_path: Path, batch: int = 5000, busy_timeout: float = 30.0) -> None:
        self._database_path = database_path
        self._batch = batch
        self._busy_timeout = busy_timeout

    def usage(self) -> DatabaseUsage:
        with closing(open_connection(self._database_path)) as connection:
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
        with closing(open_connection(self._database_path)) as connection:
            # Interpolates only the constant protected-entries query.
            row = connection.execute(
                f"SELECT COUNT(*) FROM audit_entries WHERE occurred_at < :cutoff "  # noqa: S608
                f"AND id NOT IN ({_PROTECTED})",
                {"cutoff": cutoff},
            ).fetchone()
        return int(row[0])

    def clear_activity(self, before: datetime) -> int:
        cutoff = before.astimezone(UTC).isoformat()
        removed = 0
        with closing(open_connection(self._database_path)) as connection:
            # Chosen once, so batches never re-evaluate which entries are protected. A fresh
            # connection never carries a temp table over from an earlier call.
            # Keyed by id, so each batch reads and deletes its candidates without a full scan.
            connection.execute("CREATE TEMP TABLE clearable (id INTEGER PRIMARY KEY)")
            connection.execute(
                f"INSERT INTO temp.clearable SELECT id FROM audit_entries "  # noqa: S608
                f"WHERE occurred_at < :cutoff AND id NOT IN ({_PROTECTED})",
                {"cutoff": cutoff},
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
                open_connection(
                    self._database_path, isolation_level=None, timeout=self._busy_timeout
                )
            ) as connection:
                connection.execute("VACUUM")
                # Under write-ahead logging the compacted pages land in the log first; copying them
                # back and emptying the log is what returns the space to the filesystem.
                connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.OperationalError as error:
            detail = str(error).lower()
            if "locked" in detail or "busy" in detail:
                raise StorageBusy(STORAGE_BUSY_MESSAGE) from error
            raise
