"""Provider admission decisions against transaction-current identity records."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from calendar_sync.application.identity.credentials import CredentialSnapshot
from calendar_sync.application.identity.provider_sign_in_ports import (
    AdmissionCommand,
    ProviderSignInRefused,
)
from calendar_sync.domain.access import RegistrationPolicy, UserId
from calendar_sync.domain.provider_identity import (
    LinkDecision,
    ProviderAdmissionFacts,
    decide_provider_link,
    may_admit_provider_user,
)
from calendar_sync.infrastructure.persistence.email_change_records import credential_matches
from calendar_sync.infrastructure.persistence.provider_flow_records import live_owner
from calendar_sync.infrastructure.persistence.registration import _policy
from calendar_sync.infrastructure.persistence.registration_readiness import readiness_status


@dataclass(frozen=True, slots=True)
class AdmissionTarget:
    credential: CredentialSnapshot | None
    identity_owner: UserId | None


def identity_owner(connection: sqlite3.Connection, command: AdmissionCommand) -> UserId | None:
    row = connection.execute(
        "SELECT user_id,provider FROM provider_identities WHERE issuer=? AND subject=?",
        (command.claims.key.issuer, command.claims.key.subject),
    ).fetchone()
    if row is not None and row["provider"] != command.flow.provider:
        raise ProviderSignInRefused
    return UserId(row[0]) if row else None


def load_target(connection: sqlite3.Connection, command: AdmissionCommand) -> AdmissionTarget:
    existing = identity_owner(connection, command)
    owner = command.flow.context.owner
    user_id = existing or (owner.user_id if owner else None)
    if command.expected is not None:
        user_id = command.expected.user_id
    row = None
    if user_id is not None:
        row = connection.execute("SELECT * FROM users WHERE id=?", (user_id.value,)).fetchone()
    elif command.claims.email_verified and command.claims.email:
        row = connection.execute(
            "SELECT * FROM users WHERE email=?", (command.claims.email,)
        ).fetchone()
    credential = (
        CredentialSnapshot(
            UserId(row["id"]), row["credential_revision"], row["password_hash"], row["email"]
        )
        if row
        else None
    )
    return AdmissionTarget(credential, existing)


def require_target(
    connection: sqlite3.Connection,
    command: AdmissionCommand,
    target: AdmissionTarget,
    now: datetime,
) -> LinkDecision:
    if identity_owner(connection, command) != target.identity_owner:
        raise ProviderSignInRefused
    credential, owner = target.credential, command.flow.context.owner
    if credential is not None and not credential_matches(connection, credential):
        raise ProviderSignInRefused
    if owner is not None and not live_owner(connection, owner, now.isoformat()):
        raise ProviderSignInRefused
    if command.expected is not None and (
        command.expected != credential or command.expected.password_hash is None
    ):
        raise ProviderSignInRefused
    proven = owner.user_id if owner else (command.expected.user_id if command.expected else None)
    decision = decide_provider_link(
        target.identity_owner,
        proven,
        credential.user_id if credential else None,
        command.claims.email_verified,
    )
    if decision is LinkDecision.REFUSE and proven is not None:
        raise ProviderSignInRefused
    return decision


def require_admission(
    connection: sqlite3.Connection,
    command: AdmissionCommand,
    now: datetime,
    fingerprint: str | None,
) -> str | None:
    claims, invitation = command.claims, command.flow.context.invitation
    invitation_id = None
    if invitation is not None:
        row = connection.execute(
            "SELECT id FROM invitations WHERE token_hash=? AND accepted_at IS NULL "
            "AND revoked_at IS NULL AND expires_at>?",
            (invitation.token_hash, now.isoformat()),
        ).fetchone()
        if row is None or not claims.email_verified or invitation.email != claims.email:
            raise ProviderSignInRefused
        invitation_id = str(row[0])
    policy = _policy(connection)
    operational = (
        policy is not RegistrationPolicy.OPEN or readiness_status(connection, fingerprint).available
    )
    facts = ProviderAdmissionFacts(
        policy, operational, bool(claims.email_verified and claims.email), invitation_id is not None
    )
    if (
        not may_admit_provider_user(facts)
        or connection.execute("SELECT 1 FROM users LIMIT 1").fetchone() is None
    ):
        raise ProviderSignInRefused
    if connection.execute("SELECT 1 FROM users WHERE email=?", (claims.email,)).fetchone():
        raise ProviderSignInRefused
    return invitation_id
