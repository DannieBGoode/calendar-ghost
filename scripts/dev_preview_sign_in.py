"""Synthetic provider identity flows for the development preview, never production routes."""

from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlencode

from calendar_sync.application.identity.provider_sign_in_ports import ProviderAuthorization
from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import Adapters, Container
from calendar_sync.bootstrap.provider_sign_in import compose_provider_sign_in
from calendar_sync.domain.access import UserId
from calendar_sync.domain.provider_identity import ProviderClaims, ProviderIdentityKey
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.security import CredentialCipher


class SignInFixture(StrEnum):
    BOTH = "both"
    PASSWORDLESS = "passwordless"
    DISABLED = "disabled"


@dataclass(frozen=True)
class _PreviewAuthorization:
    provider: str
    origin: str
    fingerprint: str
    email: str
    verified: bool

    def begin(self, state: str, _nonce: str, _verifier: str) -> str:
        # Exercise the genuine callback boundary on this loopback server only.
        query = urlencode({"state": state, "code": "synthetic-preview-code"})
        return f"{self.origin}/api/v1/sign-in/{self.provider}/callback?{query}"

    def exchange(self, _code: str, _nonce: str, _verifier: str) -> ProviderClaims:
        return ProviderClaims(
            ProviderIdentityKey(f"https://{self.provider}.preview.test", "preview-person"),
            self.email,
            self.verified,
        )


def sign_in_fixture(
    container: Container,
    adapters: Adapters,
    user: UserId,
    fixture: SignInFixture,
    origin: str,
    path: Path,
) -> Container:
    """Real SQLite and browser proofs; provider exchange is entirely synthetic and local."""
    settings = Settings(
        path,
        public_url=origin,
        master_key=CredentialCipher.generate_key(),
        google_client_id="preview-google-client",
        google_client_secret="preview-google-secret",  # noqa: S106
        microsoft_client_id="preview-microsoft-client",
        microsoft_client_secret="preview-microsoft-secret",  # noqa: S106
    )
    service = compose_provider_sign_in(settings, adapters)
    assert service.runtime is not None
    with transaction(settings.database_path) as connection:
        email = str(
            connection.execute("SELECT email FROM users WHERE id=?", (user.value,)).fetchone()[0]
        )
        connection.execute(
            "INSERT INTO provider_identities VALUES (?,?,?,?,?,?)",
            (
                "preview-google",
                user.value,
                "google",
                "https://google.preview.test",
                "preview-person",
                adapters.clock.now().isoformat(),
            ),
        )
        if fixture is SignInFixture.PASSWORDLESS:
            connection.execute("UPDATE users SET password_hash=NULL WHERE id=?", (user.value,))
        connection.executemany(
            "INSERT INTO provider_sign_in_settings(provider,enabled) VALUES (?,?) "
            "ON CONFLICT(provider) DO UPDATE SET enabled=excluded.enabled",
            [
                (provider, fixture is not SignInFixture.DISABLED)
                for provider in ("google", "microsoft")
            ],
        )
    providers: dict[str, ProviderAuthorization] = {
        slug: _PreviewAuthorization(slug, origin, provider.fingerprint, email, slug == "google")
        for slug, provider in service.runtime.begin.providers.items()
    }
    runtime = replace(
        service.runtime,
        begin=replace(service.runtime.begin, providers=providers),
        complete=replace(service.runtime.complete, providers=providers),
    )
    return replace(container, provider_sign_in=replace(service, runtime=runtime))
