"""Atomic owned provider method writes; all slow credential work precedes this boundary."""

import sqlite3
from pathlib import Path

from calendar_sync.application.identity.credentials import CredentialSnapshot
from calendar_sync.application.identity.provider_sign_in_ports import (
    LinkedProviderIdentity,
    LinkOwner,
    ProviderAvailability,
    SignInMethods,
)
from calendar_sync.application.shared.ports import Clock
from calendar_sync.domain.access import UserId
from calendar_sync.domain.provider_identity import may_remove_sign_in_method
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.persistence.credentials import revoke_resets
from calendar_sync.infrastructure.persistence.email_change_records import (
    credential_matches,
    revoke_email_changes,
)


def enabled_providers(
    connection: sqlite3.Connection, availability: tuple[ProviderAvailability, ...]
) -> frozenset[str]:
    """Combine current administrator enablement with immutable environment availability."""
    available = {item.provider for item in availability if item.available}
    return frozenset(
        str(row[0])
        for row in connection.execute(
            "SELECT provider FROM provider_sign_in_settings WHERE enabled = 1"
        )
        if row[0] in available
    )


def _live_owner(connection: sqlite3.Connection, owner: LinkOwner, now: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM users u JOIN user_sessions s ON s.user_id = u.id "
            "WHERE u.id = ? AND u.state = 'active' AND u.credential_revision = ? "
            "AND s.token_hash = ? AND s.expires_at > ?",
            (owner.user_id.value, owner.revision, owner.session_hash, now),
        ).fetchone()
        is not None
    )


def _advance(connection: sqlite3.Connection, owner: LinkOwner, now: str) -> None:
    connection.execute(
        "UPDATE users SET credential_revision = credential_revision + 1 WHERE id = ?",
        (owner.user_id.value,),
    )
    revoke_resets(connection, owner.user_id, now)
    revoke_email_changes(connection, owner.user_id, now)
    connection.execute(
        "DELETE FROM user_sessions WHERE user_id = ? AND token_hash IS NOT ?",
        (owner.user_id.value, owner.session_hash),
    )


def _methods(connection: sqlite3.Connection, user_id: UserId) -> SignInMethods:
    row = connection.execute(
        "SELECT password_hash FROM users WHERE id = ?", (user_id.value,)
    ).fetchone()
    identities = connection.execute(
        "SELECT id, provider FROM provider_identities WHERE user_id = ? ORDER BY created_at, id",
        (user_id.value,),
    ).fetchall()
    return SignInMethods(
        row is not None and row[0] is not None,
        tuple(LinkedProviderIdentity(str(row[0]), str(row[1])) for row in identities),
    )


class SqliteProviderMethods:
    def __init__(
        self, database_path: Path, clock: Clock, availability: tuple[ProviderAvailability, ...]
    ) -> None:
        self._database_path = database_path
        self._clock = clock
        self._availability = availability

    def show(self, user_id: UserId) -> SignInMethods:
        with transaction(self._database_path) as connection:
            return _methods(connection, user_id)

    def unlink(self, owner: LinkOwner, identity_id: str) -> bool:
        with transaction(self._database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            now = self._clock.now().isoformat()
            if not _live_owner(connection, owner, now):
                return False
            methods = _methods(connection, owner.user_id)
            if not any(identity.id == identity_id for identity in methods.identities):
                return False
            enabled = enabled_providers(connection, self._availability)
            remaining = sum(
                identity.id != identity_id and identity.provider in enabled
                for identity in methods.identities
            )
            if not may_remove_sign_in_method(methods.has_password, remaining):
                return False
            connection.execute(
                "DELETE FROM provider_identities WHERE id = ? AND user_id = ?",
                (identity_id, owner.user_id.value),
            )
            _advance(connection, owner, now)
        return True

    def set_password(self, owner: LinkOwner, expected: CredentialSnapshot, hashed: str) -> bool:
        if expected.password_hash is not None or expected.user_id != owner.user_id:
            return False
        with transaction(self._database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            now = self._clock.now().isoformat()
            if not _live_owner(connection, owner, now) or not credential_matches(
                connection, expected
            ):
                return False
            connection.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?", (hashed, owner.user_id.value)
            )
            _advance(connection, owner, now)
        return True
