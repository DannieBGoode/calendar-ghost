from __future__ import annotations

import logging
import secrets
import sqlite3
from collections.abc import Sequence
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
from calendar_sync.domain.access import UserId
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.security import token_hash

logger = logging.getLogger(__name__)

USAGE_GRANULARITY = timedelta(minutes=5)
"""A monitor polling every 20 seconds must not write to SQLite on every request."""

_COLUMNS = "id, user_id, name, scope, created_at, last_used_at, revoked_at"


class SqliteIntegrationTokens:
    """Integration Tokens: each User manages their own through `for_user`; authenticating a
    presented token finds it whoever owns it, and says whose it is."""

    def __init__(self, database_path: Path, clock: Clock, ids: IdGenerator) -> None:
        self._database_path = database_path
        self._clock = clock
        self._ids = ids

    def for_user(self, user_id: UserId) -> SqliteUserIntegrationTokens:
        return SqliteUserIntegrationTokens(self._database_path, user_id, self._clock, self._ids)

    def authenticate(self, token: str) -> IntegrationTokenSummary | None:
        if not is_well_formed(token):
            return None
        now = self._clock.now()
        with transaction(self._database_path) as connection:
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


class SqliteUserIntegrationTokens:
    """One User's Integration Tokens; another User's are neither listed nor revoked."""

    def __init__(
        self, database_path: Path, user_id: UserId, clock: Clock, ids: IdGenerator
    ) -> None:
        self._database_path = database_path
        self._user = user_id
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
            owner=self._user,
        )
        with transaction(self._database_path) as connection:
            connection.execute(
                """
                INSERT INTO integration_tokens (id, user_id, name, token_hash, scope, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    summary.id,
                    self._user.value,
                    summary.name,
                    token_hash(token),
                    summary.scope.value,
                    summary.created_at.isoformat(),
                ),
            )
        return IssuedIntegrationToken(summary, token)

    def list(self) -> Sequence[IntegrationTokenSummary]:
        with transaction(self._database_path) as connection:
            rows = connection.execute(
                f"""
                SELECT {_COLUMNS} FROM integration_tokens WHERE user_id = ?
                ORDER BY revoked_at IS NOT NULL, created_at DESC, id
                """,  # noqa: S608
                (self._user.value,),
            ).fetchall()
        return [_summary(row) for row in rows]

    def revoke(self, token_id: str) -> bool:
        with transaction(self._database_path) as connection:
            cursor = connection.execute(
                """
                UPDATE integration_tokens SET revoked_at = ?
                WHERE id = ? AND user_id = ? AND revoked_at IS NULL
                """,
                (self._clock.now().isoformat(), token_id, self._user.value),
            )
        return cursor.rowcount == 1


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
        owner=UserId(str(row["user_id"])),
    )


def _time(value: object) -> datetime | None:
    return datetime.fromisoformat(str(value)) if value is not None else None
