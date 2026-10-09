"""Who may join the installation, and the single-use links that let them (ADR 0030)."""

from __future__ import annotations

import secrets
import sqlite3
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from calendar_sync.application.ports import IdGenerator, IssuedLink, PendingInvitation
from calendar_sync.domain.access import (
    RegistrationPolicy,
    User,
    UserId,
    link_expiry,
    require_registration_change,
)
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.persistence.users import insert_user
from calendar_sync.infrastructure.security import token_hash

# A link is usable while it is neither used nor revoked, and its expiry is still ahead.
_USABLE = "used_at IS NULL AND revoked_at IS NULL AND expires_at > ?"
_INVITATION_USABLE = "accepted_at IS NULL AND revoked_at IS NULL AND expires_at > ?"


class SqliteRegistrationSettings:
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path

    def policy(self) -> RegistrationPolicy:
        with transaction(self._database_path) as connection:
            return _policy(connection)

    def set_policy(self, policy: RegistrationPolicy) -> None:
        with transaction(self._database_path) as connection:
            # Held from the count to the change, so an invitation accepted meanwhile is counted.
            connection.execute("BEGIN IMMEDIATE")
            users = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            require_registration_change(policy, int(users))
            # Migration 22 creates the one row.
            connection.execute(
                "UPDATE installation_settings SET registration_policy = ? WHERE singleton = 1",
                (policy.value,),
            )


def _policy(connection: sqlite3.Connection) -> RegistrationPolicy:
    row = connection.execute(
        "SELECT registration_policy FROM installation_settings WHERE singleton = 1"
    ).fetchone()
    return RegistrationPolicy(str(row[0])) if row else RegistrationPolicy.default()


class SqliteInvitations:
    def __init__(self, database_path: Path, ids: IdGenerator) -> None:
        self._database_path = database_path
        self._ids = ids

    def issue(self, created_by: UserId, at: datetime) -> IssuedLink:
        link = IssuedLink(self._ids.new(), secrets.token_urlsafe(32), link_expiry(at))
        with transaction(self._database_path) as connection:
            connection.execute(
                """
                INSERT INTO invitations (id, token_hash, created_by, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    link.id,
                    token_hash(link.token),
                    created_by.value,
                    at.isoformat(),
                    link.expires_at.isoformat(),
                ),
            )
        return link

    def pending(self, at: datetime) -> Sequence[PendingInvitation]:
        with transaction(self._database_path) as connection:
            rows = connection.execute(
                "SELECT id, created_at, expires_at FROM invitations "  # noqa: S608
                f"WHERE {_INVITATION_USABLE} ORDER BY created_at, id",
                (at.isoformat(),),
            ).fetchall()
        return tuple(
            PendingInvitation(
                str(row["id"]),
                datetime.fromisoformat(str(row["created_at"])),
                datetime.fromisoformat(str(row["expires_at"])),
            )
            for row in rows
        )

    def revoke(self, invitation_id: str, at: datetime) -> bool:
        with transaction(self._database_path) as connection:
            cursor = connection.execute(
                f"UPDATE invitations SET revoked_at = ? WHERE id = ? AND {_INVITATION_USABLE}",  # noqa: S608
                (at.isoformat(), invitation_id, at.isoformat()),
            )
        return cursor.rowcount == 1

    def revoke_all(self, at: datetime) -> None:
        with transaction(self._database_path) as connection:
            connection.execute(
                f"UPDATE invitations SET revoked_at = ? WHERE {_INVITATION_USABLE}",  # noqa: S608
                (at.isoformat(), at.isoformat()),
            )

    def usable(self, token: str, at: datetime) -> bool:
        with transaction(self._database_path) as connection:
            row = connection.execute(
                f"SELECT 1 FROM invitations WHERE token_hash = ? AND {_INVITATION_USABLE}",  # noqa: S608
                (token_hash(token), at.isoformat()),
            ).fetchone()
        return row is not None

    def accept(self, token: str, user: User, password_hash: str, at: datetime) -> bool:
        with transaction(self._database_path) as connection:
            # Held from the check to the use, so two people cannot both use the link. An
            # unusable link is refused before the email is looked at, so it reveals nothing.
            connection.execute("BEGIN IMMEDIATE")
            usable = connection.execute(
                f"SELECT 1 FROM invitations WHERE token_hash = ? AND {_INVITATION_USABLE}",  # noqa: S608
                (token_hash(token), at.isoformat()),
            ).fetchone()
            if usable is None:
                return False
            # Read under the same lock as Only Me is chosen, so a person cannot join after it,
            # nor after the last User left and the installation returned to setup.
            anyone = connection.execute("SELECT 1 FROM users LIMIT 1").fetchone()
            if not _policy(connection).lets_people_join or anyone is None:
                return False
            # EmailTaken rolls the transaction back, so the invitation stays usable.
            insert_user(connection, user, password_hash)
            connection.execute(
                "UPDATE invitations SET accepted_at = ?, accepted_by = ? WHERE token_hash = ?",
                (at.isoformat(), user.id.value, token_hash(token)),
            )
        return True


class SqlitePasswordResetLinks:
    def __init__(self, database_path: Path, ids: IdGenerator) -> None:
        self._database_path = database_path
        self._ids = ids

    def issue(self, user_id: UserId, created_by: UserId, at: datetime) -> IssuedLink:
        link = IssuedLink(self._ids.new(), secrets.token_urlsafe(32), link_expiry(at))
        with transaction(self._database_path) as connection:
            # Only the newest link of a User works, so a link handed to the wrong person is
            # stopped by issuing another.
            connection.execute(
                f"UPDATE password_reset_links SET revoked_at = ? WHERE user_id = ? AND {_USABLE}",  # noqa: S608
                (at.isoformat(), user_id.value, at.isoformat()),
            )
            connection.execute(
                """
                INSERT INTO password_reset_links (
                    id, token_hash, user_id, created_by, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    link.id,
                    token_hash(link.token),
                    user_id.value,
                    created_by.value,
                    at.isoformat(),
                    link.expires_at.isoformat(),
                ),
            )
        return link

    def owner(self, token: str, at: datetime) -> UserId | None:
        with transaction(self._database_path) as connection:
            return _owner(connection, token, at)

    def reset(self, token: str, password_hash: str, at: datetime) -> UserId | None:
        with transaction(self._database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            owner = _owner(connection, token, at)
            if owner is None:
                return None
            connection.execute(
                "UPDATE password_reset_links SET used_at = ? WHERE token_hash = ?",
                (at.isoformat(), token_hash(token)),
            )
            connection.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, owner.value)
            )
        return owner


def _owner(connection: sqlite3.Connection, token: str, at: datetime) -> UserId | None:
    row = connection.execute(
        f"SELECT user_id FROM password_reset_links WHERE token_hash = ? AND {_USABLE}",  # noqa: S608
        (token_hash(token), at.isoformat()),
    ).fetchone()
    return UserId(str(row[0])) if row is not None else None
