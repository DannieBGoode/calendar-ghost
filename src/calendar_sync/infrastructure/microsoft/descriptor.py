"""The Microsoft package as bootstrap composes it: one descriptor (ADR 0022, ADR 0034, ADR 0036)."""

from __future__ import annotations

from datetime import date

import httpx

from calendar_sync.application.identity.provider_sign_in_ports import (
    ProviderAvailability,
    ProviderSignInDescriptor,
    ProviderSignInRefused,
)
from calendar_sync.application.shared.ports import Clock
from calendar_sync.application.sync.provider_descriptors import (
    ProviderConnection,
    ProviderDescriptor,
)
from calendar_sync.infrastructure.microsoft.guide import MICROSOFT
from calendar_sync.infrastructure.microsoft.oauth import MicrosoftClient, MicrosoftOAuthService
from calendar_sync.infrastructure.microsoft.oidc import MicrosoftAuthorization
from calendar_sync.infrastructure.microsoft.provider import OutlookCalendarProvider
from calendar_sync.infrastructure.microsoft.watches import (
    OutlookCalendarWatcher,
    OutlookNoticeReader,
)
from calendar_sync.infrastructure.oidc_descriptor import sign_in_client
from calendar_sync.infrastructure.oidc_http import RequestsOidcTransport
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
    secret_expires: date | None = None,
) -> ProviderDescriptor:
    """Microsoft's descriptor. It offers nothing until the installation registers its Entra
    application, and no account can be stored without the installation master key."""
    configured = client.oauth.complete
    if accounts is None or not configured:
        return ProviderDescriptor(MICROSOFT, configured=configured, secret_expires=secret_expires)
    oauth = MicrosoftOAuthService(
        client, accounts, states, master_key, http or httpx.Client(), clock
    )
    return ProviderDescriptor(
        MICROSOFT,
        configured=True,
        connection=ProviderConnection(oauth, client.oauth.redirect_uri),
        calendars=oauth,
        provider=OutlookCalendarProvider(oauth, oauth.graph, clock),
        secret_expires=secret_expires,
        watcher=OutlookCalendarWatcher(oauth, oauth.graph, clock),
        notice_reader=OutlookNoticeReader(),
    )


def microsoft_sign_in(
    client: MicrosoftClient, origin: str | None, clock: Clock
) -> ProviderSignInDescriptor:
    configured = sign_in_client(client.oauth, origin, "microsoft")
    try:
        authorization = (
            MicrosoftAuthorization(configured, client.tenant, clock, RequestsOidcTransport())
            if configured
            else None
        )
    except (ValueError, ProviderSignInRefused):
        authorization = None
    return ProviderSignInDescriptor(
        ProviderAvailability(
            "microsoft",
            authorization is not None,
            None if authorization else "configuration_required",
        ),
        authorization,
    )
