"""Atomic admission and installation-wide identity email readiness."""

import math
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from calendar_sync.application.identity.administration import AdministratorRequired
from calendar_sync.application.identity.identity_email import (
    EmailTest,
    IdentityEmailStorageUnavailable,
    IdentityEmailTestThrottled,
)
from calendar_sync.application.shared.ports import IdGenerator
from calendar_sync.domain.access import UserId
from calendar_sync.infrastructure.persistence.connections import transaction


def _recipient(connection: sqlite3.Connection, actor: UserId) -> str | None:
    row = connection.execute(
        "SELECT email FROM users WHERE id = ? AND role = 'installation_administrator' "
        "AND state = 'active' AND email IS NOT NULL",
        (actor.value,),
    ).fetchone()
    return str(row[0]) if row else None


class SqliteIdentityEmailTests:
    def __init__(self, database: Path, ids: IdGenerator) -> None:
        self._database = database
        self._ids = ids

    def tested_at(self, fingerprint: str) -> datetime | None:
        try:
            with transaction(self._database, timeout=0.1) as connection:
                row = connection.execute(
                    "SELECT fingerprint, tested_at FROM identity_email_readiness "
                    "WHERE singleton = 1",
                ).fetchone()
            if row is None:
                raise IdentityEmailStorageUnavailable
            return datetime.fromisoformat(str(row[1])) if row[0] == fingerprint else None
        except (sqlite3.Error, ValueError):
            raise IdentityEmailStorageUnavailable from None

    def admit(self, actor: UserId, fingerprint: str, at: datetime) -> EmailTest:
        try:
            with transaction(self._database, timeout=0.1) as connection:
                connection.execute("BEGIN IMMEDIATE")
                if _recipient(connection, actor) is None:
                    raise AdministratorRequired
                _require_allowance(connection, actor, at)
                row = connection.execute(
                    "SELECT generation FROM identity_email_readiness WHERE singleton = 1"
                ).fetchone()
                if row is None:
                    raise IdentityEmailStorageUnavailable
                test = EmailTest(self._ids.new(), actor, int(row[0]), fingerprint)
                connection.execute(
                    "INSERT INTO identity_email_test_attempts(id, user_id, admitted_at) "
                    "VALUES (?, ?, ?)",
                    (test.id, actor.value, at.isoformat()),
                )
            return test
        except sqlite3.Error:
            raise IdentityEmailStorageUnavailable from None

    def record_success(self, test: EmailTest, recipient: str, at: datetime) -> bool:
        try:
            with transaction(self._database, timeout=0.1) as connection:
                connection.execute("BEGIN IMMEDIATE")
                if _recipient(connection, test.actor) != recipient:
                    return False
                attempt = connection.execute(
                    "SELECT 1 FROM identity_email_test_attempts WHERE id = ? AND user_id = ?",
                    (test.id, test.actor.value),
                ).fetchone()
                if attempt is None:
                    return False
                result = connection.execute(
                    "UPDATE identity_email_readiness SET fingerprint = ?, tested_at = ? "
                    "WHERE singleton = 1 AND generation = ?",
                    (test.fingerprint, at.isoformat(), test.generation),
                )
                return result.rowcount == 1
        except sqlite3.Error:
            raise IdentityEmailStorageUnavailable from None

    def purge(self, before: datetime, limit: int) -> int:
        if limit <= 0:
            return 0
        try:
            with transaction(self._database, timeout=0.1) as connection:
                result = connection.execute(
                    "DELETE FROM identity_email_test_attempts WHERE id IN "
                    "(SELECT id FROM identity_email_test_attempts "
                    "WHERE julianday(admitted_at) < julianday(?) "
                    "ORDER BY julianday(admitted_at), id LIMIT ?)",
                    (before.isoformat(), limit),
                )
                return result.rowcount
        except sqlite3.Error:
            raise IdentityEmailStorageUnavailable from None


def _require_allowance(connection: sqlite3.Connection, actor: UserId, at: datetime) -> None:
    rows = connection.execute(
        "SELECT admitted_at FROM identity_email_test_attempts "
        "WHERE user_id = ? AND julianday(admitted_at) > julianday(?) "
        "ORDER BY julianday(admitted_at)",
        (actor.value, (at - timedelta(hours=1)).isoformat()),
    ).fetchall()
    if len(rows) >= 3:
        available = datetime.fromisoformat(str(rows[len(rows) - 3][0])) + timedelta(hours=1)
        raise IdentityEmailTestThrottled(max(1, math.ceil((available - at).total_seconds())))
