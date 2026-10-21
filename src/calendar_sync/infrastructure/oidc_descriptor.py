"""Shared environment checks for provider-owned sign-in descriptors."""

from calendar_sync.infrastructure.oauth import OAuthClientConfig
from calendar_sync.infrastructure.oidc import OidcClientConfig


def sign_in_client(
    client: OAuthClientConfig, origin: str | None, slug: str
) -> OidcClientConfig | None:
    if origin is None or not client.client_id or not client.client_secret:
        return None
    return OidcClientConfig(
        client.client_id, client.client_secret, f"{origin}/api/v1/sign-in/{slug}/callback"
    )
