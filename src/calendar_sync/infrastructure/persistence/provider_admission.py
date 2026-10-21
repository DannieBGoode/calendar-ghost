"""One short final transaction for provider admission, ownership and session mutation."""

import secrets
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from calendar_sync.application.identity.credentials import CredentialSnapshot
from calendar_sync.application.identity.ports import Session
from calendar_sync.application.identity.provider_sign_in_ports import (
    AdmissionCommand,
    BrowserProof,
    ProviderSignInRefused,
    ProviderSignInResult,
)
from calendar_sync.application.shared.ports import Clock
from calendar_sync.domain.access import Role, User, UserId, UserState
from calendar_sync.infrastructure.persistence.provider_admission_records import (
    AdmissionTarget,
    load_target,
    require_admission,
    require_target,
)
from calendar_sync.infrastructure.persistence.provider_flow_records import (
    cancel_browser,
    claim_flow,
    claim_pending,
    flow_transaction,
)
from calendar_sync.infrastructure.persistence.provider_flows import SqliteProviderFlows
from calendar_sync.infrastructure.persistence.provider_methods import advance_methods
from calendar_sync.infrastructure.persistence.users import SESSION_LIFETIME, insert_user
from calendar_sync.infrastructure.security import token_hash


@dataclass(frozen=True, slots=True)
class PreparedAdmission:
    target: AdmissionTarget
    email_digest: str | None
    token: str = field(repr=False)
    session_hash: str = field(repr=False)
    user_id: UserId
    identity_id: str


class SqliteProviderAdmission:
    def __init__(
        self,
        database: Path,
        clock: Clock,
        flows: SqliteProviderFlows,
        readiness_fingerprint: str | None,
    ) -> None:
        self._database, self._clock, self._flows = database, clock, flows
        self._readiness = readiness_fingerprint

    def complete(self, command: AdmissionCommand) -> ProviderSignInResult:
        prepared = self._prepare(command)
        result = self._write(command, prepared, None)
        if result is not None:
            return result
        return ProviderSignInResult(None, self._flows.defer(command.flow, command.claims))

    def confirm(
        self, pending: str, browser: BrowserProof, expected: CredentialSnapshot
    ) -> Session | None:
        loaded = self._flows.load_pending(browser, pending)
        if loaded is None:
            return None
        command = AdmissionCommand(loaded.claims, loaded.flow, expected)
        prepared = self._prepare(command)
        try:
            result = self._write(command, prepared, token_hash(pending))
        except ProviderSignInRefused:
            return None
        return result.session if result else None

    def _prepare(self, command: AdmissionCommand) -> PreparedAdmission:
        with flow_transaction(self._database) as connection:
            connection.execute("BEGIN")
            target = load_target(connection, command)
        email = target.credential.email if target.credential else command.claims.email
        token = secrets.token_urlsafe(32)
        return PreparedAdmission(
            target,
            self._flows.email_digest(email),
            token,
            token_hash(token),
            target.credential.user_id if target.credential else UserId(secrets.token_urlsafe(24)),
            secrets.token_urlsafe(24),
        )

    def _write(
        self, command: AdmissionCommand, prepared: PreparedAdmission, pending_hash: str | None
    ) -> ProviderSignInResult | None:
        with flow_transaction(self._database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            now = self._clock.now()
            self._require_provider(connection, command, now)
            require_target(connection, command, prepared.target, now)
            if prepared.target.credential is None and not (
                command.claims.email_verified and command.claims.email
            ):
                return None
            invitation = None
            if prepared.target.credential is None:
                invitation = require_admission(connection, command, now, self._readiness)
            claimed = (
                claim_pending(connection, pending_hash, command.flow.browser_hash, now)
                if pending_hash
                else claim_flow(connection, command.flow, now)
            )
            if not claimed:
                raise ProviderSignInRefused
            self._save_identity(connection, command, prepared, invitation, now)
            return _finish(connection, command, prepared, now)

    def _require_provider(
        self, connection: sqlite3.Connection, command: AdmissionCommand, now: datetime
    ) -> None:
        flow = command.flow
        enabled = connection.execute(
            "SELECT 1 FROM provider_sign_in_settings WHERE provider=? AND enabled=1",
            (flow.provider,),
        ).fetchone()
        if (
            not enabled
            or flow.expires_at <= now
            or flow.context.config_fingerprint != self._flows.fingerprints.get(flow.provider)
        ):
            raise ProviderSignInRefused

    def _save_identity(
        self,
        connection: sqlite3.Connection,
        command: AdmissionCommand,
        prepared: PreparedAdmission,
        invitation: str | None,
        now: datetime,
    ) -> None:
        if prepared.target.credential is None:
            user = User(prepared.user_id, command.claims.email, Role.USER, UserState.ACTIVE, now)
            insert_user(connection, user, None)
        if prepared.target.identity_owner is None:
            connection.execute(
                "INSERT INTO provider_identities VALUES (?,?,?,?,?,?)",
                (
                    prepared.identity_id,
                    prepared.user_id.value,
                    command.flow.provider,
                    command.claims.key.issuer,
                    command.claims.key.subject,
                    now.isoformat(),
                ),
            )
        if invitation is not None:
            connection.execute(
                "UPDATE invitations SET accepted_at=?,accepted_by=? WHERE id=?",
                (now.isoformat(), prepared.user_id.value, invitation),
            )
        email = (
            prepared.target.credential.email if prepared.target.credential else command.claims.email
        )
        connection.execute(
            "UPDATE registration_proofs SET revoked_at=? WHERE email=? AND "
            "used_at IS NULL AND revoked_at IS NULL",
            (now.isoformat(), email),
        )
        connection.execute(
            "DELETE FROM provider_pending_links WHERE email_digest=?", (prepared.email_digest,)
        )


def _finish(
    connection: sqlite3.Connection,
    command: AdmissionCommand,
    prepared: PreparedAdmission,
    now: datetime,
) -> ProviderSignInResult:
    owner = command.flow.context.owner
    if owner is not None:
        advance_methods(connection, owner, now.isoformat())
        cancel_browser(connection, command.flow.browser_hash, owner.session_hash)
        return ProviderSignInResult(None, None)
    cancel_browser(connection, command.flow.browser_hash)
    expiry = now + SESSION_LIFETIME
    connection.execute(
        "INSERT INTO "
        "user_sessions(token_hash,user_id,created_at,expires_at,browser_hash) VALUES (?,?,?,?,?)",
        (
            prepared.session_hash,
            prepared.user_id.value,
            now.isoformat(),
            expiry.isoformat(),
            command.flow.browser_hash,
        ),
    )
    connection.execute(
        "UPDATE users SET last_sign_in_at=? WHERE id=?", (now.isoformat(), prepared.user_id.value)
    )
    return ProviderSignInResult(Session(prepared.token, expiry, prepared.user_id), None)
