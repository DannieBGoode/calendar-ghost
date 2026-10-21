"""Sealed provider-flow encoding and short SQLite boundaries."""

import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from calendar_sync.application.identity.provider_sign_in_ports import (
    BoundInvitation,
    FlowContext,
    LinkOwner,
    PendingProviderLink,
    ProviderFlow,
    ProviderSignInRefused,
    ProviderSignInUnavailable,
)
from calendar_sync.domain.access import UserId
from calendar_sync.domain.provider_identity import ProviderClaims, ProviderIdentityKey
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.security import ProviderSignInSecrets


@contextmanager
def flow_transaction(database: Path) -> Iterator[sqlite3.Connection]:
    try:
        with transaction(database, timeout=0.1) as connection:
            yield connection
    except sqlite3.Error:
        raise ProviderSignInUnavailable from None


def proof_valid(value: str) -> bool:
    return re.fullmatch(r"[A-Za-z0-9_-]{43,128}", value) is not None


def context_json(context: FlowContext) -> dict[str, Any]:
    invitation, owner = context.invitation, context.owner
    return {
        "invitation": [invitation.token_hash, invitation.email] if invitation else None,
        "owner": [owner.user_id.value, owner.session_hash, owner.revision] if owner else None,
        "config": context.config_fingerprint,
    }


def read_context(value: dict[str, Any]) -> FlowContext:
    invitation, owner = value["invitation"], value["owner"]
    return FlowContext(
        BoundInvitation(*invitation) if invitation else None,
        LinkOwner(UserId(owner[0]), owner[1], owner[2]) if owner else None,
        value["config"],
    )


def open_flow(row: sqlite3.Row, secrets: ProviderSignInSecrets) -> ProviderFlow | None:
    plaintext = secrets.open(row["sealed_context"], "flow:" + row["state_hash"])
    if plaintext is None:
        return None
    context = read_context(json.loads(plaintext))
    return ProviderFlow(
        row["state_hash"],
        row["provider"],
        row["browser_hash"],
        datetime.fromisoformat(row["expires_at"]),
        context,
    )


def seal_pending(
    flow: ProviderFlow, claims: ProviderClaims, secrets: ProviderSignInSecrets, hashed: str
) -> bytes:
    value = {
        "flow": [
            flow.state_hash,
            flow.provider,
            flow.browser_hash,
            flow.expires_at.isoformat(),
            context_json(flow.context),
        ],
        "claims": [claims.key.issuer, claims.key.subject, claims.email, claims.email_verified],
    }
    return secrets.seal(json.dumps(value), "pending:" + hashed)


def open_pending(row: sqlite3.Row, secrets: ProviderSignInSecrets) -> PendingProviderLink | None:
    plaintext = secrets.open(row["sealed_context"], "pending:" + row["token_hash"])
    if plaintext is None:
        return None
    value = json.loads(plaintext)
    state, provider, browser, expiry, context = value["flow"]
    issuer, subject, email, verified = value["claims"]
    return PendingProviderLink(
        ProviderFlow(
            state, provider, browser, datetime.fromisoformat(expiry), read_context(context)
        ),
        ProviderClaims(ProviderIdentityKey(issuer, subject), email, verified),
    )


def require_capacity(connection: sqlite3.Connection, now: str) -> None:
    total = sum(
        connection.execute(query, (now,)).fetchone()[0]
        for query in (
            "SELECT COUNT(*) FROM provider_flows WHERE expires_at > ?",
            "SELECT COUNT(*) FROM provider_link_flows WHERE expires_at > ?",
            "SELECT COUNT(*) FROM provider_pending_links WHERE expires_at > ?",
        )
    )
    if total >= 1000:
        raise ProviderSignInRefused


def live_owner(connection: sqlite3.Connection, owner: LinkOwner, now: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM users u JOIN user_sessions s ON s.user_id = u.id "
            "WHERE u.id = ? AND u.state = 'active' AND u.credential_revision = ? "
            "AND s.token_hash = ? AND s.expires_at > ?",
            (owner.user_id.value, owner.revision, owner.session_hash, now),
        ).fetchone()
        is not None
    )


def claim_pending(
    connection: sqlite3.Connection, hashed: str, browser_hash: str, now: datetime
) -> bool:
    """Only in the final writer's transaction, after proof and all admission checks.

    A fresh token identifies immutable sealed claims. Rotation, cancellation, expiry, or another
    confirmation makes the claim fail. Rollback restores it together with the writer's changes.
    """
    return (
        connection.execute(
            "DELETE FROM provider_pending_links WHERE token_hash = ? AND browser_hash = ? "
            "AND expires_at > ?",
            (hashed, browser_hash, now.isoformat()),
        ).rowcount
        == 1
    )
