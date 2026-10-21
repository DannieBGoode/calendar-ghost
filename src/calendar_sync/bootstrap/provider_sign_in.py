"""Compose sign-in through identity descriptors, independently of calendar consent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from calendar_sync.application.identity.provider_links import ConfirmProviderLink
from calendar_sync.application.identity.provider_sign_in import (
    BeginProviderSignIn,
    CompleteProviderSignIn,
)
from calendar_sync.application.identity.provider_sign_in_ports import (
    ProviderFlowMaintenance,
    ProviderFlows,
    ProviderMethods,
    ProviderSignInLimits,
    ProviderSignInSettings,
)
from calendar_sync.application.identity.sign_in_methods import (
    ResolveProviderOwner,
    SetOwnPassword,
    UnlinkProviderIdentity,
)
from calendar_sync.bootstrap.config import Settings
from calendar_sync.infrastructure.google.descriptor import google_sign_in
from calendar_sync.infrastructure.identity_email import identity_origin
from calendar_sync.infrastructure.microsoft.descriptor import microsoft_sign_in
from calendar_sync.infrastructure.microsoft.oauth import MicrosoftClient
from calendar_sync.infrastructure.oauth import OAuthClientConfig
from calendar_sync.infrastructure.persistence.credentials import SqliteCredentialChanges
from calendar_sync.infrastructure.persistence.provider_admission import SqliteProviderAdmission
from calendar_sync.infrastructure.persistence.provider_flows import SqliteProviderFlows
from calendar_sync.infrastructure.persistence.provider_methods import SqliteProviderMethods
from calendar_sync.infrastructure.persistence.provider_sign_in_limits import (
    SqliteProviderSignInLimits,
)
from calendar_sync.infrastructure.persistence.provider_sign_in_settings import (
    SqliteProviderSignInSettings,
)
from calendar_sync.infrastructure.persistence.users import SqliteSessions, SqliteUserDirectory
from calendar_sync.infrastructure.security import ProviderSignInSecrets, token_hash

if TYPE_CHECKING:
    from calendar_sync.bootstrap.container import Adapters


@dataclass(frozen=True, slots=True)
class ProviderFlowServices:
    begin: BeginProviderSignIn
    complete: CompleteProviderSignIn
    confirm: ConfirmProviderLink
    flows: ProviderFlows
    limits: ProviderSignInLimits


@dataclass(frozen=True, slots=True)
class SignInMethodServices:
    methods: ProviderMethods
    owner: ResolveProviderOwner
    unlink: UnlinkProviderIdentity
    set_password: SetOwnPassword


@dataclass(frozen=True, slots=True)
class ProviderSignInServices:
    origin: str | None
    secure: bool
    settings: ProviderSignInSettings
    methods: SignInMethodServices
    runtime: ProviderFlowServices | None
    maintenance: tuple[ProviderFlowMaintenance, ...]


def compose_provider_sign_in(settings: Settings, adapters: Adapters) -> ProviderSignInServices:
    origin = identity_origin(settings.public_url)
    trusted = origin if settings.master_key else None
    clock, database = adapters.clock, settings.database_path
    descriptors = (
        google_sign_in(
            OAuthClientConfig(
                settings.google_client_id,
                settings.google_client_secret,
                settings.google_redirect_uri,
            ),
            trusted,
            clock,
        ),
        microsoft_sign_in(
            MicrosoftClient(
                OAuthClientConfig(
                    settings.microsoft_client_id,
                    settings.microsoft_client_secret,
                    settings.microsoft_redirect_uri,
                ),
                settings.microsoft_tenant,
            ),
            trusted,
            clock,
        ),
    )
    availability = tuple(item.availability for item in descriptors)
    providers = {
        item.availability.provider: item.authorization
        for item in descriptors
        if item.authorization is not None
    }
    configuration = SqliteProviderSignInSettings(database, availability)
    methods = SqliteProviderMethods(database, clock, availability)
    credentials = SqliteCredentialChanges(database, clock, read_timeout=0.1)
    owned = SignInMethodServices(
        methods,
        ResolveProviderOwner(
            SqliteSessions(database, clock, sign_in_timeout=0.1), credentials, token_hash
        ),
        UnlinkProviderIdentity(methods),
        SetOwnPassword(credentials, adapters.passwords, methods, token_hash),
    )
    runtime = None
    maintenance: tuple[ProviderFlowMaintenance, ...] = ()
    if settings.master_key:
        flows = SqliteProviderFlows(
            database,
            settings.master_key,
            clock,
            {slug: provider.fingerprint for slug, provider in providers.items()},
        )
        limits = SqliteProviderSignInLimits(database, settings.master_key, clock)
        admission = SqliteProviderAdmission(
            database, clock, flows, adapters.identity_email.setup.fingerprint
        )
        secrets = ProviderSignInSecrets(settings.master_key)
        runtime = ProviderFlowServices(
            BeginProviderSignIn(providers, flows, secrets, configuration),
            CompleteProviderSignIn(providers, flows, secrets, configuration, admission),
            ConfirmProviderLink(
                SqliteUserDirectory(database, sign_in_timeout=0.1, read_timeout=0.1),
                adapters.passwords,
                adapters.sign_in_throttle,
                flows,
                admission,
            ),
            flows,
            limits,
        )
        maintenance = (flows, limits)
    return ProviderSignInServices(
        origin,
        bool(origin and origin.startswith("https://")),
        configuration,
        owned,
        runtime,
        maintenance,
    )
