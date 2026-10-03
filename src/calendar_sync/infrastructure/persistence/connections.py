"""The one place that opens SQLite connections, so every adapter gets the same settings.

Foreign keys are enforced, rows are read by column name, and a writer waits up to the busy
timeout for another's lock.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Literal

BUSY_TIMEOUT_SECONDS = 5.0


def open_connection(
    database_path: Path,
    *,
    timeout: float = BUSY_TIMEOUT_SECONDS,
    isolation_level: Literal["DEFERRED", "IMMEDIATE", "EXCLUSIVE"] | None = "DEFERRED",
) -> sqlite3.Connection:
    """A connection with the installation's settings; the caller closes it."""
    connection = sqlite3.connect(database_path, timeout=timeout, isolation_level=isolation_level)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
    except BaseException:
        connection.close()
        raise
    return connection


@contextmanager
def transaction(database_path: Path) -> Iterator[sqlite3.Connection]:
    """One short transaction: committed when the block succeeds, rolled back if it raises.

    The connection is closed either way, so no handle or lock outlives the block.
    """
    with closing(open_connection(database_path)) as connection, connection:
        yield connection
