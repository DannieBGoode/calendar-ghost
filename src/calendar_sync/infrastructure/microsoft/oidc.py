"""Microsoft tenant and signing-key issuer validation for provider sign-in."""

import re
from uuid import UUID

from calendar_sync.application.identity.provider_sign_in_ports import ProviderSignInRefused
from calendar_sync.application.shared.ports import Clock
from calendar_sync.domain.provider_identity import ProviderClaims, ProviderIdentityKey
from calendar_sync.infrastructure.oidc import OidcAuthorization, OidcClientConfig, OidcEndpoints
from calendar_sync.infrastructure.oidc_claims import text_claim
from calendar_sync.infrastructure.oidc_http import OidcTransport

LOGIN = "https://login.microsoftonline.com"
PERSONAL_TENANT = "9188040d-6c67-4c5b-b112-36a304b66dad"


def _guid(value: str) -> str:
    if str(UUID(value)) != value:
        raise ProviderSignInRefused
    return value


class _MicrosoftPolicy:
    def __init__(self, tenant: str) -> None:
        self.tenant = tenant
        self._alias = _tenant_alias(tenant)
        self.endpoints = OidcEndpoints(
            f"{LOGIN}/{tenant}/v2.0/.well-known/openid-configuration",
            f"{LOGIN}/{tenant}/oauth2/v2.0/authorize",
            f"{LOGIN}/{tenant}/oauth2/v2.0/token",
            frozenset({"login.microsoftonline.com"}),
        )

    def translate(
        self, claims: dict[str, object], key: dict[str, object], issuer: str
    ) -> ProviderClaims:
        tenant = _guid(text_claim(claims, "tid", 36))
        expected = f"{LOGIN}/{tenant}/v2.0"
        if claims.get("iss") != expected or issuer.replace("{tenantid}", tenant) != expected:
            raise ProviderSignInRefused
        key_issuer = text_claim(key, "issuer")
        if key_issuer.replace("{tenantid}", tenant) != expected:
            raise ProviderSignInRefused
        self._require_tenant(tenant, issuer)
        email = claims.get("email")
        return ProviderClaims(
            ProviderIdentityKey(expected, text_claim(claims, "sub")),
            email if isinstance(email, str) else None,
            False,
        )

    def _require_tenant(self, tenant: str, issuer: str) -> None:
        if self._alias:
            if issuer != f"{LOGIN}/{tenant}/v2.0":
                raise ProviderSignInRefused
            return
        if self.tenant == "common":
            return
        if self.tenant == "organizations" and tenant != PERSONAL_TENANT:
            return
        if self.tenant == "consumers" and tenant == PERSONAL_TENANT:
            return
        if self.tenant == tenant:
            return
        raise ProviderSignInRefused


class MicrosoftAuthorization(OidcAuthorization):
    def __init__(
        self, client: OidcClientConfig, tenant: str, clock: Clock, http: OidcTransport
    ) -> None:
        super().__init__(client, _MicrosoftPolicy(tenant), clock, http)


def _tenant_alias(value: str) -> bool:
    if value in {"common", "organizations", "consumers"}:
        return False
    if "." not in value:
        _guid(value)
        return False
    label = r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    if len(value) > 253 or re.fullmatch(rf"{label}(?:\.{label})+", value) is None:
        raise ProviderSignInRefused
    return True
