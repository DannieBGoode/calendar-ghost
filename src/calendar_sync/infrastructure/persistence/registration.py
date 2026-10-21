"""Who may join the installation, and the single-use links that let them (ADR 0030)."""

from __future__ import annotations

import secrets
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from calendar_sync.application.identity.administration import AdministratorRequired
from calendar_sync.application.identity.errors import ResetStorageUnavailable, UserDisabled
from calendar_sync.application.identity.password_reset import PreparedPasswordReset
from calendar_sync.application.identity.ports import IssuedLink, PendingInvitation
from calendar_sync.application.identity.registration_ports import (
    InvitationVerificationRequired,
    OpenRegistrationUnavailable,
    RegistrationStorageUnavailable,
)
from calendar_sync.application.shared.ports import Clock, IdGenerator
from calendar_sync.domain.access import (
    RegistrationPolicy,
    Role,
    User,
    UserId,
    UserState,
    email_address,
    link_expiry,
    require_registration_change,
)
from calendar_sync.domain.registration import may_accept_invitation_directly, may_issue_invitation
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.persistence.credentials import revoke_resets
from calendar_sync.infrastructure.persistence.email_change_records import revoke_email_changes
from calendar_sync.infrastructure.persistence.registration_readiness import readiness_status
from calendar_sync.infrastructure.persistence.users import insert_user
from calendar_sync.infrastructure.security import token_hash

_INVITATION_USABLE = "accepted_at IS NULL AND revoked_at IS NULL AND expires_at > ?"


@contextmanager
def _registration_transaction(database: Path) -> Iterator[sqlite3.Connection]:
    try:
        with transaction(database, timeout=0.1) as connection:
            yield connection
    except sqlite3.Error:
        raise RegistrationStorageUnavailable from None


class SqliteRegistrationSettings:
    def __init__(self, database_path: Path, clock: Clock) -> None:
        self._database_path = database_path
        self._clock = clock

    def policy(self) -> RegistrationPolicy:
        with _registration_transaction(self._database_path) as connection:
            return _policy(connection)

    def set_policy(
        self, policy: RegistrationPolicy, *, actor: UserId, fingerprint: str | None
    ) -> None:
        try:
            with transaction(self._database_path, timeout=0.1) as connection:
                connection.execute("BEGIN IMMEDIATE")
                administrator = connection.execute(
                    "SELECT 1 FROM users WHERE id = ? AND role = 'installation_administrator' "
                    "AND state = 'active'",
                    (actor.value,),
                ).fetchone()
                if administrator is None:
                    raise AdministratorRequired("an active Installation Administrator is required")
                users = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
                require_registration_change(policy, int(users))
                if policy is RegistrationPolicy.OPEN:
                    status = readiness_status(connection, fingerprint)
                    if status.reason is not None:
                        raise OpenRegistrationUnavailable(status.reason)
                connection.execute(
                    "UPDATE installation_settings SET registration_policy = ? WHERE singleton = 1",
                    (policy.value,),
                )
                _revoke_registration(connection, policy, self._clock.now())
        except sqlite3.Error:
            raise RegistrationStorageUnavailable from None

    def return_to_setup(self, at: datetime) -> None:
        with transaction(self._database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            at = self._clock.now()
            users = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            require_registration_change(RegistrationPolicy.ONLY_ME, int(users))
            _revoke_registration(connection, RegistrationPolicy.ONLY_ME, at)
            connection.execute(
                "UPDATE identity_email_readiness SET fingerprint = NULL, tested_at = NULL, "
                "generation = generation + 1 WHERE singleton = 1"
            )
            # Plans turn off and keep their definitions, so a new first User inherits no limit.
            connection.execute(
                """
                UPDATE installation_settings SET registration_policy = ?, plans_enabled = 0
                WHERE singleton = 1
                """,
                (RegistrationPolicy.ONLY_ME.value,),
            )
            connection.execute(
                f"UPDATE invitations SET revoked_at = ? WHERE {_INVITATION_USABLE}",  # noqa: S608
                (at.isoformat(), at.isoformat()),
            )


def _revoke_registration(
    connection: sqlite3.Connection, policy: RegistrationPolicy, at: datetime
) -> None:
    if policy is RegistrationPolicy.OPEN:
        return
    connection.execute(
        "UPDATE registration_proofs SET revoked_at = ? WHERE used_at IS NULL "
        "AND revoked_at IS NULL AND (? = 'only_me' OR invitation_id IS NULL)",
        (at.isoformat(), policy.value),
    )


def _policy(connection: sqlite3.Connection) -> RegistrationPolicy:
    row = connection.execute(
        "SELECT registration_policy FROM installation_settings WHERE singleton = 1"
    ).fetchone()
    return RegistrationPolicy(str(row[0])) if row else RegistrationPolicy.default()


class SqliteInvitations:
    def __init__(self, database_path: Path, ids: IdGenerator, clock: Clock) -> None:
        self._database_path = database_path
        self._ids = ids
        self._clock = clock

    def issue(self, created_by: UserId, at: datetime) -> IssuedLink | None:
        link = IssuedLink(self._ids.new(), secrets.token_urlsafe(32), link_expiry(at))
        with transaction(self._database_path) as connection:
            # Held from the checks to the insert, so an invitation issued while the last User
            # leaves is either revoked with the others or never issued.
            connection.execute("BEGIN IMMEDIATE")
            administrator = connection.execute(
                """
                SELECT 1 FROM users
                WHERE id = ? AND role = 'installation_administrator' AND state = 'active'
                """,
                (created_by.value,),
            ).fetchone()
            if administrator is None or not may_issue_invitation(_policy(connection)):
                return None
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
            if cursor.rowcount:
                connection.execute(
                    "UPDATE registration_proofs SET revoked_at = ? WHERE invitation_id = ? "
                    "AND used_at IS NULL AND revoked_at IS NULL",
                    (at.isoformat(), invitation_id),
                )
        return cursor.rowcount == 1

    def usable(self, token: str, at: datetime) -> bool:
        with _registration_transaction(self._database_path) as connection:
            row = connection.execute(
                f"SELECT 1 FROM invitations WHERE token_hash = ? AND {_INVITATION_USABLE}",  # noqa: S608
                (token_hash(token), at.isoformat()),
            ).fetchone()
        return row is not None

    def accept(self, token: str, email: str, password_hash: str) -> User | None:
        with _registration_transaction(self._database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            at = self._clock.now()
            usable = connection.execute(
                f"SELECT 1 FROM invitations WHERE token_hash = ? AND {_INVITATION_USABLE}",  # noqa: S608
                (token_hash(token), at.isoformat()),
            ).fetchone()
            if usable is None:
                return None
            policy = _policy(connection)
            if not may_accept_invitation_directly(policy):
                if may_issue_invitation(policy):
                    raise InvitationVerificationRequired(
                        "verify your email before joining under Open"
                    )
                return None
            if connection.execute("SELECT 1 FROM users LIMIT 1").fetchone() is None:
                return None
            user = User(
                UserId(self._ids.new()), email_address(email), Role.USER, UserState.ACTIVE, at
            )
            insert_user(connection, user, password_hash)
            connection.execute(
                "UPDATE invitations SET accepted_at = ?, accepted_by = ? WHERE token_hash = ?",
                (at.isoformat(), user.id.value, token_hash(token)),
            )
        return user


@contextmanager
def _reset_transaction(database: Path) -> Iterator[sqlite3.Connection]:
    try:
        with transaction(database, timeout=0.1) as connection:
            yield connection
    except sqlite3.Error:
        raise ResetStorageUnavailable from None


class SqlitePasswordResetLinks:
    def __init__(self, database_path: Path, ids: IdGenerator, clock: Clock) -> None:
        self._database_path = database_path
        self._ids = ids
        self._clock = clock

    def issue(self, user_id: UserId, created_by: UserId, at: datetime) -> IssuedLink:
        with _reset_transaction(self._database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            administrator = connection.execute(
                "SELECT 1 FROM users WHERE id = ? AND state = 'active' "
                "AND role = 'installation_administrator'",
                (created_by.value,),
            ).fetchone()
            if administrator is None:
                raise AdministratorRequired("an active Installation Administrator is required")
            row = connection.execute(
                "SELECT credential_revision FROM users WHERE id = ? AND state = 'active'",
                (user_id.value,),
            ).fetchone()
            if row is None:
                raise UserDisabled("the User is no longer active")
            revoke_resets(connection, user_id, at.isoformat())
            return self._insert(connection, user_id, int(row[0]), created_by, at, link_expiry(at))

    def issue_for_email(self, email: str) -> PreparedPasswordReset | None:
        with _reset_transaction(self._database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            now = self._clock.now()
            row = connection.execute(
                "SELECT id, email, credential_revision FROM users "
                "WHERE email = ? AND state = 'active'",
                (email,),
            ).fetchone()
            if row is None:
                return None
            link = self._insert(
                connection,
                UserId(str(row["id"])),
                int(row["credential_revision"]),
                None,
                now,
                now + timedelta(hours=1),
            )
            return PreparedPasswordReset(str(row["email"]), link)

    def _insert(
        self,
        connection: sqlite3.Connection,
        user_id: UserId,
        revision: int,
        creator: UserId | None,
        at: datetime,
        expires: datetime,
    ) -> IssuedLink:
        link = IssuedLink(self._ids.new(), secrets.token_urlsafe(32), expires)
        connection.execute(
            """
            INSERT INTO password_reset_links (
                id, token_hash, user_id, credential_revision, created_by, created_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                link.id,
                token_hash(link.token),
                user_id.value,
                revision,
                creator.value if creator else None,
                at.isoformat(),
                expires.isoformat(),
            ),
        )
        return link

    def owner(self, token: str, at: datetime) -> UserId | None:
        with _reset_transaction(self._database_path) as connection:
            return _owner(connection, token, at)

    def reset(self, token: str, password_hash: str) -> UserId | None:
        with _reset_transaction(self._database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            now = self._clock.now()
            owner = _owner(connection, token, now)
            if owner is None:
                return None
            connection.execute(
                "UPDATE password_reset_links SET used_at = ? WHERE token_hash = ?",
                (now.isoformat(), token_hash(token)),
            )
            connection.execute(
                "UPDATE users SET password_hash = ?, credential_revision = credential_revision + 1 "
                "WHERE id = ?",
                (password_hash, owner.value),
            )
            revoke_resets(connection, owner, now.isoformat())
            revoke_email_changes(connection, owner, now.isoformat())
            connection.execute("DELETE FROM user_sessions WHERE user_id = ?", (owner.value,))
        return owner


def _owner(connection: sqlite3.Connection, token: str, at: datetime) -> UserId | None:
    row = connection.execute(
        """
        SELECT links.user_id FROM password_reset_links AS links
        JOIN users ON users.id = links.user_id AND users.state = 'active'
            AND users.credential_revision = links.credential_revision
        WHERE links.token_hash = ? AND links.used_at IS NULL AND links.revoked_at IS NULL
            AND links.expires_at > ?
        """,
        (token_hash(token), at.isoformat()),
    ).fetchone()
    return UserId(str(row[0])) if row is not None else None
