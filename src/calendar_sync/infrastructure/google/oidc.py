"""Google ID-token issuer policy, kept separate from calendar consent."""

from calendar_sync.application.identity.provider_sign_in_ports import ProviderSignInRefused
from calendar_sync.application.shared.ports import Clock
from calendar_sync.domain.provider_identity import ProviderClaims, ProviderIdentityKey
from calendar_sync.infrastructure.oidc import OidcAuthorization, OidcClientConfig, OidcEndpoints
from calendar_sync.infrastructure.oidc_claims import text_claim
from calendar_sync.infrastructure.oidc_http import OidcTransport

ISSUER = "https://accounts.google.com"


class _GooglePolicy:
    endpoints = OidcEndpoints(
        f"{ISSUER}/.well-known/openid-configuration",
        f"{ISSUER}/o/oauth2/v2/auth",
        "https://oauth2.googleapis.com/token",
        frozenset({"www.googleapis.com"}),
    )

    def translate(
        self, claims: dict[str, object], _key: dict[str, object], issuer: str
    ) -> ProviderClaims:
        if issuer != ISSUER or claims.get("iss") not in {ISSUER, "accounts.google.com"}:
            raise ProviderSignInRefused
        email = claims.get("email")
        return ProviderClaims(
            ProviderIdentityKey(ISSUER, text_claim(claims, "sub")),
            email if isinstance(email, str) else None,
            isinstance(email, str) and claims.get("email_verified") is True,
        )


class GoogleAuthorization(OidcAuthorization):
    def __init__(self, client: OidcClientConfig, clock: Clock, http: OidcTransport) -> None:
        super().__init__(client, _GooglePolicy(), clock, http)
