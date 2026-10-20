"""Atomic compare-and-change for a User's credentials and browser sessions."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from calendar_sync.application.identity.credentials import CredentialSnapshot
from calendar_sync.application.shared.ports import Clock
from calendar_sync.domain.access import UserId
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.persistence.users import _taken_or
from calendar_sync.infrastructure.security import token_hash


def revoke_resets(connection: sqlite3.Connection, user_id: UserId, at: str) -> None:
    """Invalidate every unused proof inside the credential writer's transaction."""
    connection.execute(
        "UPDATE password_reset_links SET revoked_at = ? "
        "WHERE user_id = ? AND used_at IS NULL AND revoked_at IS NULL",
        (at, user_id.value),
    )


class SqliteCredentialChanges:
    def __init__(self, database_path: Path, clock: Clock) -> None:
        self._database_path = database_path
        self._clock = clock

    def current(self, user_id: UserId) -> CredentialSnapshot | None:
        with transaction(self._database_path) as connection:
            row = connection.execute(
                "SELECT credential_revision, password_hash FROM users "
                "WHERE id = ? AND state = 'active'",
                (user_id.value,),
            ).fetchone()
        return CredentialSnapshot(user_id, int(row[0]), str(row[1])) if row is not None else None

    def change_password(self, expected: CredentialSnapshot, hashed: str, keep: str | None) -> bool:
        with transaction(self._database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            now = self._clock.now().isoformat()
            if (
                keep is not None
                and connection.execute(
                    "SELECT 1 FROM user_sessions "
                    "WHERE token_hash = ? AND user_id = ? AND expires_at > ?",
                    (token_hash(keep), expected.user_id.value, now),
                ).fetchone()
                is None
            ):
                return False
            changed = connection.execute(
                "UPDATE users SET password_hash = ?, credential_revision = credential_revision + 1 "
                "WHERE id = ? AND credential_revision = ? "
                "AND password_hash = ? AND state = 'active'",
                (hashed, *_expected(expected)),
            ).rowcount
            if changed != 1:
                return False
            revoke_resets(connection, expected.user_id, now)
            connection.execute(
                "DELETE FROM user_sessions WHERE user_id = ? AND token_hash IS NOT ?",
                (expected.user_id.value, token_hash(keep) if keep is not None else None),
            )
        return True

    def change_email(self, expected: CredentialSnapshot, email: str) -> bool:
        try:
            with transaction(self._database_path) as connection:
                connection.execute("BEGIN IMMEDIATE")
                changed = connection.execute(
                    "UPDATE users SET email = ?, credential_revision = credential_revision + 1 "
                    "WHERE id = ? AND credential_revision = ? "
                    "AND password_hash = ? AND state = 'active'",
                    (email, *_expected(expected)),
                ).rowcount
                if changed != 1:
                    return False
                revoke_resets(connection, expected.user_id, self._clock.now().isoformat())
        except sqlite3.IntegrityError as error:
            raise _taken_or(error) from error
        return True


def _expected(expected: CredentialSnapshot) -> tuple[str, int, str]:
    return expected.user_id.value, expected.revision, expected.password_hash
