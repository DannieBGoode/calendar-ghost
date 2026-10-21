"""Email-change row decisions shared by credential writers, inside their transaction."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from calendar_sync.application.identity.credentials import CredentialSnapshot
from calendar_sync.application.identity.email_change_admission import EmailChangeStorageUnavailable
from calendar_sync.domain.access import UserId
from calendar_sync.domain.email_changes import CredentialRevision, EmailChangeProof
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.security import token_hash


@contextmanager
def email_change_transaction(path: Path) -> Iterator[sqlite3.Connection]:
    try:
        with transaction(path, timeout=0.1) as connection:
            yield connection
    except sqlite3.Error:
        raise EmailChangeStorageUnavailable from None


def revoke_email_changes(connection: sqlite3.Connection, user_id: UserId, at: str) -> None:
    connection.execute(
        "UPDATE email_change_proofs SET revoked_at = ? "
        "WHERE user_id = ? AND used_at IS NULL AND revoked_at IS NULL",
        (at, user_id.value),
    )


def current_request(
    connection: sqlite3.Connection, user_id: UserId, at: datetime
) -> sqlite3.Row | None:
    row: sqlite3.Row | None = connection.execute(
        "SELECT p.* FROM email_change_proofs p JOIN users u ON u.id = p.user_id "
        "AND u.credential_revision = p.credential_revision AND u.state = 'active' "
        "WHERE p.user_id = ? AND p.used_at IS NULL AND p.revoked_at IS NULL "
        "AND p.expires_at > ? ORDER BY p.created_at DESC LIMIT 1",
        (user_id.value, at.isoformat()),
    ).fetchone()
    return row


def credential_matches(connection: sqlite3.Connection, expected: CredentialSnapshot) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM users WHERE id = ? AND credential_revision = ? "
            "AND password_hash IS ? AND email IS ? AND state = 'active'",
            (expected.user_id.value, expected.revision, expected.password_hash, expected.email),
        ).fetchone()
        is not None
    )


def session_matches(
    connection: sqlite3.Connection, user_id: UserId, session: str, now: datetime
) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM user_sessions WHERE user_id = ? AND token_hash = ? AND expires_at > ?",
            (user_id.value, token_hash(session), now.isoformat()),
        ).fetchone()
        is not None
    )


def usable_proof(row: sqlite3.Row, user_id: UserId, at: datetime) -> bool:
    proof = EmailChangeProof(
        UserId(str(row["user_id"])),
        CredentialRevision(int(row["credential_revision"])),
        str(row["token_hash"]),
        datetime.fromisoformat(row["expires_at"]),
        datetime.fromisoformat(row["used_at"]) if row["used_at"] else None,
        datetime.fromisoformat(row["revoked_at"]) if row["revoked_at"] else None,
    )
    return proof.usable_by(
        user_id, CredentialRevision(int(row["live_revision"])), row["state"] == "active", at
    )


def proof_row(connection: sqlite3.Connection, user_id: UserId, token: str) -> sqlite3.Row | None:
    row: sqlite3.Row | None = connection.execute(
        "SELECT p.*, u.credential_revision live_revision, u.state FROM email_change_proofs p "
        "JOIN users u ON u.id = p.user_id WHERE p.user_id = ? AND p.token_hash = ?",
        (user_id.value, token_hash(token)),
    ).fetchone()

    return row
