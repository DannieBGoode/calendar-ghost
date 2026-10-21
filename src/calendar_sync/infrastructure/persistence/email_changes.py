"""SQLite-only, session-owned email proofs; mail and passwords never enter the lock."""

import secrets
import sqlite3
from contextlib import suppress
from datetime import datetime, timedelta
from pathlib import Path

from calendar_sync.application.identity.credentials import CredentialSnapshot
from calendar_sync.application.identity.email_change_admission import EmailChangeStorageUnavailable
from calendar_sync.application.identity.email_changes import (
    EmailChangeCompletion,
    EmailChangeUnavailable,
    PendingEmailChange,
    PreparedEmailChange,
)
from calendar_sync.application.shared.ports import Clock, IdGenerator
from calendar_sync.domain.access import UserId, email_address
from calendar_sync.domain.email_changes import CredentialRevision
from calendar_sync.infrastructure.persistence.credentials import revoke_resets
from calendar_sync.infrastructure.persistence.email_change_admission import admit_issuance
from calendar_sync.infrastructure.persistence.email_change_records import (
    credential_matches,
    current_request,
    email_change_transaction,
    proof_row,
    revoke_email_changes,
    session_matches,
    usable_proof,
)
from calendar_sync.infrastructure.security import EmailChangeAdmissionDigests, token_hash


class SqliteEmailChangeProofs:
    def __init__(
        self, database_path: Path, ids: IdGenerator, clock: Clock, *, master_key: str = ""
    ) -> None:
        self._database = database_path
        self._ids = ids
        self._clock = clock
        self._digests = EmailChangeAdmissionDigests(master_key) if master_key else None

    def pending(self, user_id: UserId) -> PendingEmailChange | None:
        with email_change_transaction(self._database) as connection:
            row = current_request(connection, user_id, self._clock.now())
            return _pending(row) if row else None

    def request(self, expected: CredentialSnapshot, email: str, session: str) -> PendingEmailChange:
        if self._digests is None:
            raise EmailChangeStorageUnavailable
        normalized = email_address(email)
        digest = self._digests.digest("target", normalized)
        with email_change_transaction(self._database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            now = self._clock.now()
            if not credential_matches(connection, expected) or not session_matches(
                connection, expected.user_id, session, now
            ):
                raise EmailChangeUnavailable
            admit_issuance(connection, expected.user_id, digest, now)
            revoke_email_changes(connection, expected.user_id, now.isoformat())
            pending = PendingEmailChange(self._ids.new(), normalized, now + timedelta(hours=24))
            connection.execute(
                "INSERT INTO email_change_proofs(id, user_id, proposed_email, "
                "credential_revision, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    pending.id,
                    expected.user_id.value,
                    normalized,
                    expected.revision,
                    now.isoformat(),
                    pending.expires_at.isoformat(),
                ),
            )
        self._cleanup()
        return pending

    def cancel(self, user_id: UserId, request_id: str) -> None:
        with email_change_transaction(self._database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE email_change_proofs SET revoked_at = ? WHERE id = ? AND "
                "user_id = ? AND used_at IS NULL AND revoked_at IS NULL",
                (self._clock.now().isoformat(), request_id, user_id.value),
            )

    def prepare(self, request_id: str) -> PreparedEmailChange | None:
        with email_change_transaction(self._database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            now = self._clock.now()
            row = connection.execute(
                "SELECT p.* FROM email_change_proofs p JOIN users u ON u.id = p.user_id "
                "AND u.state = 'active' AND u.credential_revision = p.credential_revision "
                "WHERE p.id = ? AND p.token_hash IS NULL AND p.used_at IS NULL "
                "AND p.revoked_at IS NULL AND p.expires_at > ?",
                (request_id, now.isoformat()),
            ).fetchone()
            if row is None:
                return None
            token = secrets.token_urlsafe(32)
            connection.execute(
                "UPDATE email_change_proofs SET token_hash = ? WHERE id = ? AND user_id = ?",
                (token_hash(token), request_id, row["user_id"]),
            )
            return PreparedEmailChange(str(row["proposed_email"]), token)

    def check(self, user_id: UserId, token: str) -> bool:
        with email_change_transaction(self._database) as connection:
            row = proof_row(connection, user_id, token)
            return row is not None and usable_proof(row, user_id, self._clock.now())

    def confirm(
        self, expected: CredentialSnapshot, token: str, session: str
    ) -> EmailChangeCompletion | None:
        with email_change_transaction(self._database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            now = self._clock.now()
            row = proof_row(connection, expected.user_id, token)
            if (
                row is None
                or not usable_proof(row, expected.user_id, now)
                or not credential_matches(connection, expected)
                or not session_matches(connection, expected.user_id, session, now)
            ):
                return None
            if expected.email is None:
                return None
            try:
                connection.execute(
                    "UPDATE users SET email = ?, credential_revision = ? WHERE id = ?",
                    (
                        row["proposed_email"],
                        CredentialRevision(expected.revision).next().value,
                        expected.user_id.value,
                    ),
                )
            except sqlite3.IntegrityError as error:
                # Uniqueness loses without proof/session mutation or identity disclosure.
                if "UNIQUE" in str(error) and "users.email" in str(error):
                    raise EmailChangeUnavailable from None
                raise
            connection.execute(
                "UPDATE email_change_proofs SET used_at = ? WHERE id = ? AND user_id = ?",
                (now.isoformat(), row["id"], expected.user_id.value),
            )
            revoke_resets(connection, expected.user_id, now.isoformat())
            revoke_email_changes(connection, expected.user_id, now.isoformat())
            connection.execute(
                "DELETE FROM user_sessions WHERE user_id = ? AND token_hash != ?",
                (expected.user_id.value, token_hash(session)),
            )
            completed = EmailChangeCompletion(expected.email)
        self._cleanup()
        return completed

    def _cleanup(self) -> None:
        # Cleanup is maintenance, never part of an already committed admission or change.
        with suppress(EmailChangeStorageUnavailable):
            self.purge(self._clock.now(), 500)

    def purge(self, before: datetime, limit: int) -> int:
        if limit <= 0:
            return 0
        with email_change_transaction(self._database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            cutoff = min(before, self._clock.now()).isoformat()
            return connection.execute(
                "DELETE FROM email_change_proofs WHERE id IN (SELECT id FROM email_change_proofs "
                "WHERE expires_at <= ? OR used_at <= ? OR revoked_at <= ? ORDER "
                "BY created_at LIMIT ?)",
                (cutoff, cutoff, cutoff, min(limit, 500)),
            ).rowcount


def _pending(row: sqlite3.Row) -> PendingEmailChange:
    return PendingEmailChange(
        str(row["id"]), str(row["proposed_email"]), datetime.fromisoformat(row["expires_at"])
    )
