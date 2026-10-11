"""The Microsoft package as bootstrap composes it: one descriptor (ADR 0022, ADR 0032)."""

from __future__ import annotations

import httpx

from calendar_sync.application.ports import Clock
from calendar_sync.application.provider_descriptors import ProviderConnection, ProviderDescriptor
from calendar_sync.infrastructure.microsoft.guide import MICROSOFT
from calendar_sync.infrastructure.microsoft.oauth import MicrosoftClient, MicrosoftOAuthService
from calendar_sync.infrastructure.persistence.accounts import SqliteConnectedAccountStore
from calendar_sync.infrastructure.persistence.authorization_states import (
    SqliteAuthorizationStates,
)


def microsoft_provider(
    client: MicrosoftClient,
    accounts: SqliteConnectedAccountStore | None,
    states: SqliteAuthorizationStates,
    master_key: str,
    clock: Clock,
    http: httpx.Client | None = None,
) -> ProviderDescriptor:
    """Microsoft's descriptor. It offers nothing until the installation registers its Entra
    application, and no account can be stored without the installation master key."""
    configured = client.oauth.complete
    if accounts is None or not configured:
        return ProviderDescriptor(MICROSOFT, configured=configured)
    oauth = MicrosoftOAuthService(
        client, accounts, states, master_key, http or httpx.Client(), clock
    )
    return ProviderDescriptor(
        MICROSOFT,
        configured=True,
        connection=ProviderConnection(oauth, client.oauth.redirect_uri),
        calendars=oauth,
    )
