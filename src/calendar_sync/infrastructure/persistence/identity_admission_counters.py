"""Identical SQLite window queries used by reset and registration counters."""

import math
import sqlite3
from typing import Literal

from calendar_sync.application.identity.reset_admission import ResetBoundary

HOUR = 3600
QUARTER_HOUR = 900
LIMITS: dict[ResetBoundary, int] = {"request": 20, "invalid-token": 20, "completion": 10}
Table = Literal["reset_request_attempts", "registration_request_attempts"]
Query = Literal["global", "email", "pair", "network"]
_ALLOWANCE_QUERIES: dict[Query, str] = {
    "global": "SELECT admitted_at FROM reset_request_attempts WHERE boundary = 'request' "
    "AND admitted_at > ? ORDER BY admitted_at DESC LIMIT 1 OFFSET ?",
    "email": "SELECT admitted_at FROM reset_request_attempts WHERE boundary = 'request' "
    "AND email_digest = ? AND admitted_at > ? ORDER BY admitted_at DESC LIMIT 1 OFFSET ?",
    "pair": "SELECT admitted_at FROM reset_request_attempts WHERE boundary = 'request' "
    "AND pair_digest = ? AND admitted_at > ? ORDER BY admitted_at DESC LIMIT 1 OFFSET ?",
    "network": "SELECT admitted_at FROM reset_request_attempts WHERE boundary = ? "
    "AND network_digest = ? AND admitted_at > ? ORDER BY admitted_at DESC LIMIT 1 OFFSET ?",
}


def allowance_wait(
    connection: sqlite3.Connection,
    table: Table,
    query: Query,
    keys: tuple[str, ...],
    now: float,
    window: int,
    limit: int,
) -> int:
    row = connection.execute(
        _ALLOWANCE_QUERIES[query].replace("reset_request_attempts", table),
        (*keys, now - window, limit - 1),
    ).fetchone()
    return max(1, math.ceil(float(row[0]) + window - now)) if row else 0


def network_wait(
    connection: sqlite3.Connection,
    boundary: ResetBoundary,
    digest: str,
    now: float,
    table: Table = "reset_request_attempts",
) -> int:
    wait = allowance_wait(
        connection,
        table,
        "network",
        (boundary, digest),
        now,
        QUARTER_HOUR,
        LIMITS[boundary],
    )
    return wait


def email_allowed(
    connection: sqlite3.Connection,
    keys: tuple[str, str, str],
    now: float,
    table: Table = "reset_request_attempts",
) -> bool:
    email, _, pair = keys
    return not (
        allowance_wait(connection, table, "email", (email,), now, HOUR, 5)
        or allowance_wait(connection, table, "email", (email,), now, 60, 1)
        or allowance_wait(connection, table, "pair", (pair,), now, HOUR, 2)
    )
