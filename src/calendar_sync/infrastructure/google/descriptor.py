"""The Google package as bootstrap composes it: one descriptor (ADR 0022, ADR 0036)."""

from __future__ import annotations

from calendar_sync.application.shared.ports import Clock
from calendar_sync.application.sync.provider_descriptors import (
    ProviderConnection,
    ProviderDescriptor,
)
from calendar_sync.infrastructure.google.guide import GOOGLE
from calendar_sync.infrastructure.google.oauth import GoogleOAuthService
from calendar_sync.infrastructure.google.provider import GoogleCalendarProvider
from calendar_sync.infrastructure.google.watches import GoogleCalendarWatcher, GoogleNoticeReader
from calendar_sync.infrastructure.oauth import OAuthClientConfig
from calendar_sync.infrastructure.persistence.accounts import SqliteConnectedAccountStore
from calendar_sync.infrastructure.persistence.authorization_states import (
    SqliteAuthorizationStates,
)


def google_provider(
    client: OAuthClientConfig,
    accounts: SqliteConnectedAccountStore | None,
    states: SqliteAuthorizationStates,
    master_key: str,
    clock: Clock,
) -> ProviderDescriptor:
    """Google's descriptor. Without the installation master key no account can be stored, so it
    offers no adapters; without its OAuth client, no User can connect an account."""
    if accounts is None:
        return ProviderDescriptor(GOOGLE)
    oauth = GoogleOAuthService(client, accounts, states, verifier_key=master_key)
    return ProviderDescriptor(
        GOOGLE,
        configured=bool(client.client_id and client.client_secret),
        connection=ProviderConnection(oauth, client.redirect_uri),
        calendars=oauth,
        provider=GoogleCalendarProvider(oauth.service_for, clock),
        watcher=GoogleCalendarWatcher(oauth.service_for, clock),
        notice_reader=GoogleNoticeReader(),
    )
