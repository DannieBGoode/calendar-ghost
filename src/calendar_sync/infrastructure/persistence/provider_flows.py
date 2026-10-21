"""Single-use browser-bound provider flows, and anonymous pending password proofs."""

import json
import secrets
from collections.abc import Mapping
from contextlib import suppress
from datetime import datetime, timedelta
from pathlib import Path

from calendar_sync.application.identity.provider_sign_in_ports import (
    BeginIntent,
    BoundInvitation,
    BrowserProof,
    FlowContext,
    InvitationIntent,
    PendingLink,
    PendingProviderLink,
    ProviderCallback,
    ProviderFlow,
    ProviderSignInRefused,
)
from calendar_sync.application.shared.ports import Clock
from calendar_sync.domain.access import email_address
from calendar_sync.domain.provider_identity import ProviderClaims
from calendar_sync.infrastructure.persistence.provider_flow_records import (
    context_json,
    flow_transaction,
    live_owner,
    open_flow,
    open_pending,
    proof_valid,
    require_capacity,
    seal_pending,
)
from calendar_sync.infrastructure.security import ProviderSignInSecrets, token_hash

LIFETIME = timedelta(minutes=10)


class SqliteProviderFlows:
    def __init__(
        self, database: Path, master_key: str, clock: Clock, fingerprints: Mapping[str, str]
    ) -> None:
        self._database, self._clock = database, clock
        self._secrets = ProviderSignInSecrets(master_key)
        self.fingerprints = dict(fingerprints)

    def begin(self, intent: BeginIntent, state: str) -> ProviderFlow:
        if not proof_valid(state) or not proof_valid(intent.browser.value):
            raise ProviderSignInRefused
        fingerprint = self.fingerprints.get(intent.provider)
        if fingerprint is None or (intent.owner is not None and intent.invitation is not None):
            raise ProviderSignInRefused
        invitation = _invitation(intent.invitation)
        context = FlowContext(invitation, intent.owner, fingerprint)
        now = self._clock.now()
        flow = ProviderFlow(
            token_hash(state),
            intent.provider,
            token_hash(intent.browser.value),
            now + LIFETIME,
            context,
        )
        sealed = self._secrets.seal(json.dumps(context_json(context)), "flow:" + flow.state_hash)
        values = (
            flow.state_hash,
            flow.provider,
            flow.browser_hash,
            flow.expires_at.isoformat(),
            sealed,
        )
        with flow_transaction(self._database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            require_capacity(connection, now.isoformat())
            if intent.owner is None:
                connection.execute("INSERT INTO provider_flows VALUES (?, ?, ?, ?, ?)", values)
            else:
                if not live_owner(connection, intent.owner, now.isoformat()):
                    raise ProviderSignInRefused
                connection.execute(
                    "INSERT INTO provider_link_flows(state_hash, provider, "
                    "browser_hash, expires_at, sealed_context, user_id, session_hash, revision) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        *values,
                        intent.owner.user_id.value,
                        intent.owner.session_hash,
                        intent.owner.revision,
                    ),
                )
        self._maintain()
        return flow

    def consume(self, callback: ProviderCallback) -> ProviderFlow | None:
        if not proof_valid(callback.state) or not proof_valid(callback.browser.value):
            return None
        hashed, browser = token_hash(callback.state), token_hash(callback.browser.value)
        with flow_transaction(self._database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "DELETE FROM provider_flows WHERE state_hash = ? RETURNING *", (hashed,)
            ).fetchone()
            owned = connection.execute(
                "DELETE FROM provider_link_flows WHERE state_hash = ? RETURNING *", (hashed,)
            ).fetchone()
            if owned is not None:
                row = owned
                if callback.owner is None or not live_owner(
                    connection, callback.owner, self._clock.now().isoformat()
                ):
                    row = None
        if row is None:
            return None
        flow = open_flow(row, self._secrets)
        if flow is None or flow.expires_at <= self._clock.now():
            return None
        if (
            flow.provider != callback.provider
            or flow.browser_hash != browser
            or flow.context.owner != callback.owner
            or flow.context.config_fingerprint != self.fingerprints.get(flow.provider)
        ):
            return None
        return flow

    def defer(self, flow: ProviderFlow, claims: ProviderClaims) -> PendingLink:
        if flow.context.owner is not None or flow.expires_at <= self._clock.now():
            raise ProviderSignInRefused
        token = secrets.token_urlsafe(32)
        hashed = token_hash(token)
        sealed = seal_pending(flow, claims, self._secrets, hashed)
        with flow_transaction(self._database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM provider_pending_links WHERE browser_hash = ?", (flow.browser_hash,)
            )
            require_capacity(connection, self._clock.now().isoformat())
            connection.execute(
                "INSERT INTO provider_pending_links VALUES (?, ?, ?, ?)",
                (hashed, flow.browser_hash, flow.expires_at.isoformat(), sealed),
            )
        self._maintain()
        return PendingLink(token, flow.expires_at)

    def pending(self, browser: BrowserProof, token: str) -> PendingLink | None:
        loaded = self.load_pending(browser, token)
        return PendingLink(token, loaded.flow.expires_at) if loaded is not None else None

    def load_pending(self, browser: BrowserProof, token: str) -> PendingProviderLink | None:
        """Read/decrypt outside the final writer lock; claim_pending guards its later commit."""
        if not proof_valid(browser.value) or not proof_valid(token):
            return None
        values = (token_hash(token), token_hash(browser.value), self._clock.now().isoformat())
        with flow_transaction(self._database) as connection:
            row = connection.execute(
                "SELECT * FROM provider_pending_links WHERE token_hash = ? "
                "AND browser_hash = ? AND expires_at > ?",
                values,
            ).fetchone()
        if row is None:
            return None
        pending = open_pending(row, self._secrets)
        if pending is None or pending.flow.context.config_fingerprint != self.fingerprints.get(
            pending.flow.provider
        ):
            return None
        return pending

    def cancel(self, browser: BrowserProof) -> None:
        if not proof_valid(browser.value):
            return
        hashed = token_hash(browser.value)
        with flow_transaction(self._database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM provider_flows WHERE browser_hash = ?", (hashed,))
            connection.execute("DELETE FROM provider_link_flows WHERE browser_hash = ?", (hashed,))
            connection.execute(
                "DELETE FROM provider_pending_links WHERE browser_hash = ?", (hashed,)
            )

    def purge(self, before: datetime, limit: int) -> int:
        remaining = min(max(0, limit), 250)
        removed = 0
        cutoff = min(before, self._clock.now()).isoformat()
        with flow_transaction(self._database) as connection:
            for query in (
                "DELETE FROM provider_flows WHERE state_hash IN (SELECT state_hash "
                "FROM provider_flows WHERE expires_at <= ? "
                "ORDER BY expires_at LIMIT ?)",
                "DELETE FROM provider_link_flows WHERE state_hash IN (SELECT "
                "state_hash FROM provider_link_flows WHERE expires_at <= ? "
                "ORDER BY expires_at LIMIT ?)",
                "DELETE FROM provider_pending_links WHERE token_hash IN (SELECT "
                "token_hash FROM provider_pending_links WHERE expires_at <= ? "
                "ORDER BY expires_at LIMIT ?)",
            ):
                count = connection.execute(query, (cutoff, remaining)).rowcount
                removed += count
                remaining -= count
        return removed

    def _maintain(self) -> None:
        with suppress(Exception):
            self.purge(self._clock.now(), 250)


def _invitation(intent: InvitationIntent | None) -> BoundInvitation | None:
    if intent is None:
        return None
    if (
        not intent.token
        or len(intent.token) > 128
        or not intent.token.isascii()
        or len(intent.email) > 254
    ):
        raise ProviderSignInRefused
    return BoundInvitation(token_hash(intent.token), email_address(intent.email))
