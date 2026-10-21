"""Hash-only registration proofs and atomic verified admission (ADR 0040)."""

import secrets
import sqlite3
from datetime import datetime
from pathlib import Path

from calendar_sync.application.identity.errors import EmailTaken
from calendar_sync.application.identity.ports import IssuedLink
from calendar_sync.application.identity.registration_ports import (
    PendingRegistration,
    PreparedRegistration,
    RegistrationUnavailable,
)
from calendar_sync.application.shared.ports import Clock, IdGenerator
from calendar_sync.domain.access import (
    RegistrationPolicy,
    Role,
    User,
    UserId,
    UserState,
    email_address,
)
from calendar_sync.domain.registration import (
    RegistrationProof,
    may_finish_registration,
    may_request_registration,
    registration_expiry,
)
from calendar_sync.infrastructure.persistence.registration import _policy, _registration_transaction
from calendar_sync.infrastructure.persistence.registration_readiness import readiness_status
from calendar_sync.infrastructure.persistence.users import insert_user
from calendar_sync.infrastructure.security import token_hash


def _invitation(connection: sqlite3.Connection, token: str, at: datetime) -> sqlite3.Row | None:
    row = connection.execute(
        "SELECT id, expires_at FROM invitations WHERE token_hash = ? "
        "AND accepted_at IS NULL AND revoked_at IS NULL AND julianday(expires_at) > julianday(?)",
        (token_hash(token), at.isoformat()),
    ).fetchone()
    return row if isinstance(row, sqlite3.Row) else None


def _admissible(connection: sqlite3.Connection, bound: bool, fingerprint: str | None) -> bool:
    policy = _policy(connection)
    # Closed policy is unusable; readiness loss alone keeps a live, allowed proof pending.
    if not may_finish_registration(policy, bound, True):
        return False
    if connection.execute("SELECT 1 FROM users LIMIT 1").fetchone() is None:
        return False
    operational = (
        policy is not RegistrationPolicy.OPEN or readiness_status(connection, fingerprint).available
    )
    if not may_finish_registration(policy, bound, operational):
        raise RegistrationUnavailable("Open registration is temporarily unavailable")
    return True


def _live_proof(
    connection: sqlite3.Connection, token: str, at: datetime
) -> RegistrationProof | None:
    row = connection.execute(
        "SELECT * FROM registration_proofs WHERE token_hash = ?", (token_hash(token),)
    ).fetchone()
    if row is None:
        return None
    proof = RegistrationProof(
        str(row["token_hash"]),
        str(row["email"]),
        datetime.fromisoformat(str(row["expires_at"])),
        row["invitation_id"],
        datetime.fromisoformat(row["used_at"]) if row["used_at"] else None,
        datetime.fromisoformat(row["revoked_at"]) if row["revoked_at"] else None,
    )
    if not proof.usable(at):
        return None
    if proof.invitation_id is not None:
        parent = connection.execute(
            "SELECT 1 FROM invitations WHERE id = ? AND accepted_at IS NULL "
            "AND revoked_at IS NULL AND julianday(expires_at) > julianday(?)",
            (proof.invitation_id, at.isoformat()),
        ).fetchone()
        if parent is None:
            return None
    return proof


class SqliteRegistrationProofs:
    def __init__(self, database: Path, ids: IdGenerator, clock: Clock) -> None:
        self._database, self._ids, self._clock = database, ids, clock

    def issue(
        self, email: str, invitation_token: str | None, fingerprint: str
    ) -> PreparedRegistration | None:
        normalized = email_address(email)
        with _registration_transaction(self._database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            now = self._clock.now()
            if not may_request_registration(
                _policy(connection), readiness_status(connection, fingerprint).available
            ):
                return None
            invitation = (
                _invitation(connection, invitation_token, now) if invitation_token else None
            )
            if invitation_token is not None and invitation is None:
                return None
            if connection.execute("SELECT 1 FROM users LIMIT 1").fetchone() is None:
                return None
            if connection.execute("SELECT 1 FROM users WHERE email = ?", (normalized,)).fetchone():
                return None
            expiry = registration_expiry(
                now, datetime.fromisoformat(invitation["expires_at"]) if invitation else None
            )
            link = IssuedLink(self._ids.new(), secrets.token_urlsafe(32), expiry)
            connection.execute(
                "INSERT INTO registration_proofs "
                "(token_hash, email, invitation_id, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
                (
                    token_hash(link.token),
                    normalized,
                    invitation["id"] if invitation else None,
                    now.isoformat(),
                    expiry.isoformat(),
                ),
            )
        return PreparedRegistration(normalized, link)

    def check(self, token: str, fingerprint: str | None) -> PendingRegistration | None:
        with _registration_transaction(self._database) as connection:
            connection.execute("BEGIN")
            proof = _live_proof(connection, token, self._clock.now())
            if proof is None:
                return None
            if connection.execute("SELECT 1 FROM users WHERE email = ?", (proof.email,)).fetchone():
                return None
            if not _admissible(connection, proof.invitation_id is not None, fingerprint):
                return None
            return PendingRegistration(proof.email)

    def complete(self, token: str, password_hash: str, fingerprint: str | None) -> User | None:
        try:
            with _registration_transaction(self._database) as connection:
                connection.execute("BEGIN IMMEDIATE")
                now = self._clock.now()
                proof = _live_proof(connection, token, now)
                if proof is None:
                    return None
                if connection.execute(
                    "SELECT 1 FROM users WHERE email = ?", (proof.email,)
                ).fetchone():
                    return None
                if not _admissible(connection, proof.invitation_id is not None, fingerprint):
                    return None
                user = User(UserId(self._ids.new()), proof.email, Role.USER, UserState.ACTIVE, now)
                insert_user(connection, user, password_hash)
                connection.execute(
                    "UPDATE registration_proofs SET used_at = ? WHERE email = ? "
                    "AND used_at IS NULL AND revoked_at IS NULL",
                    (now.isoformat(), proof.email),
                )
                if proof.invitation_id is not None:
                    connection.execute(
                        "UPDATE invitations SET accepted_at = ?, accepted_by = ? WHERE id = ?",
                        (now.isoformat(), user.id.value, proof.invitation_id),
                    )
            return user
        except EmailTaken:
            return None

    def purge(self, before: datetime, limit: int) -> int:
        if limit <= 0:
            return 0
        with _registration_transaction(self._database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            cutoff = min(before, self._clock.now()).isoformat()
            return connection.execute(
                "DELETE FROM registration_proofs WHERE token_hash IN ("
                "SELECT token_hash FROM registration_proofs "
                "WHERE julianday(expires_at) <= julianday(?) "
                "OR julianday(used_at) <= julianday(?) OR julianday(revoked_at) <= julianday(?) "
                "ORDER BY created_at, token_hash LIMIT ?)",
                (cutoff, cutoff, cutoff, min(limit, 500)),
            ).rowcount
