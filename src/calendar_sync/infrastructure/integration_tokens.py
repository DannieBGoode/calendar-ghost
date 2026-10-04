from __future__ import annotations

import logging
import secrets
import sqlite3
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

from calendar_sync.application.integration_tokens import TOKEN_PREFIX, is_well_formed, token_name
from calendar_sync.application.ports import (
    Clock,
    IdGenerator,
    IntegrationTokenScope,
    IntegrationTokenSummary,
    IssuedIntegrationToken,
)
from calendar_sync.infrastructure.security import token_hash

logger = logging.getLogger(__name__)

USAGE_GRANULARITY = timedelta(minutes=5)
"""A monitor polling every 20 seconds must not write to SQLite on every request."""

_COLUMNS = "id, name, scope, created_at, last_used_at, revoked_at"


class SqliteIntegrationTokens:
    def __init__(self, database_path: Path, clock: Clock, ids: IdGenerator) -> None:
        self._database_path = database_path
        self._clock = clock
        self._ids = ids

    def issue(self, name: str) -> IssuedIntegrationToken:
        cleaned = token_name(name)
        token = TOKEN_PREFIX + secrets.token_urlsafe(32)
        summary = IntegrationTokenSummary(
            self._ids.new(),
            cleaned,
            IntegrationTokenScope.STATUS_READ,
            self._clock.now(),
            None,
            None,
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO integration_tokens (id, name, token_hash, scope, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    summary.id,
                    summary.name,
                    token_hash(token),
                    summary.scope.value,
                    summary.created_at.isoformat(),
                ),
            )
        return IssuedIntegrationToken(summary, token)

    def list(self) -> Sequence[IntegrationTokenSummary]:
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT {_COLUMNS} FROM integration_tokens
                ORDER BY revoked_at IS NOT NULL, created_at DESC
                """  # noqa: S608
            ).fetchall()
        return [_summary(row) for row in rows]

    def revoke(self, token_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE integration_tokens SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
                (self._clock.now().isoformat(), token_id),
            )
        return cursor.rowcount == 1

    def authenticate(self, token: str) -> IntegrationTokenSummary | None:
        if not is_well_formed(token):
            return None
        now = self._clock.now()
        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT {_COLUMNS} FROM integration_tokens
                WHERE token_hash = ? AND revoked_at IS NULL
                """,  # noqa: S608
                (token_hash(token),),
            ).fetchone()
            if row is None:
                return None
            summary = _summary(row)
            if summary.last_used_at is None or now - summary.last_used_at >= USAGE_GRANULARITY:
                summary = _record_use(connection, summary, now)
        return summary

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection]:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        except BaseException:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            connection.close()


def _record_use(
    connection: sqlite3.Connection, summary: IntegrationTokenSummary, now: datetime
) -> IntegrationTokenSummary:
    """The summary with this use recorded, or unchanged when the database is busy.

    Recording use is best effort: a valid token must not fail its request because another
    operation, such as a scheduled pass, holds the write lock.
    """
    try:
        connection.execute(
            "UPDATE integration_tokens SET last_used_at = ? WHERE id = ?",
            (now.isoformat(), summary.id),
        )
    except sqlite3.OperationalError:
        logger.warning("Could not record the use of integration token %s", summary.id)
        connection.rollback()
        return summary
    return replace(summary, last_used_at=now)


def _summary(row: sqlite3.Row) -> IntegrationTokenSummary:
    return IntegrationTokenSummary(
        id=str(row["id"]),
        name=str(row["name"]),
        scope=IntegrationTokenScope(str(row["scope"])),
        created_at=datetime.fromisoformat(str(row["created_at"])),
        last_used_at=_time(row["last_used_at"]),
        revoked_at=_time(row["revoked_at"]),
    )


def _time(value: object) -> datetime | None:
    return datetime.fromisoformat(str(value)) if value is not None else None
