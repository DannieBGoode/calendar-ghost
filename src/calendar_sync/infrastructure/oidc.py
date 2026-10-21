"""Provider-neutral authorization-code mechanics. Provider packages own issuer policy."""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol, cast
from urllib.parse import urlsplit

from authlib.oauth2 import OAuth2Client  # type: ignore[import-untyped]
from authlib.oauth2.rfc6749.parameters import prepare_token_request  # type: ignore[import-untyped]
from joserfc import jws, jwt
from joserfc.errors import JoseError
from joserfc.jwk import RSAKey

from calendar_sync.application.identity.provider_sign_in_ports import ProviderSignInRefused
from calendar_sync.application.shared.ports import Clock
from calendar_sync.domain.provider_identity import ProviderClaims
from calendar_sync.infrastructure.identity_email import identity_loopback
from calendar_sync.infrastructure.oidc_claims import text_claim, validate_claims
from calendar_sync.infrastructure.oidc_http import OidcTransport, json_response, trusted_jwks

MAX_TOKEN_BYTES = 16_384
CACHE_LIFETIME = timedelta(hours=1)


@dataclass(frozen=True, slots=True)
class OidcClientConfig:
    client_id: str
    client_secret: str = field(repr=False)
    redirect_uri: str

    def __post_init__(self) -> None:
        parsed = urlsplit(self.redirect_uri)
        secure = parsed.scheme == "https" or (
            parsed.scheme == "http" and identity_loopback(parsed.hostname or "")
        )
        if (
            not secure
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("provider sign-in requires a trusted callback address")
        if not self.client_id or not self.client_secret:
            raise ValueError("provider sign-in requires client credentials")


@dataclass(frozen=True, slots=True)
class OidcEndpoints:
    discovery: str
    authorization: str
    token: str
    jwks_hosts: frozenset[str]


class OidcPolicy(Protocol):
    endpoints: OidcEndpoints

    def translate(
        self, claims: dict[str, object], key: dict[str, object], issuer: str, /
    ) -> ProviderClaims: ...


@dataclass(frozen=True, slots=True)
class _KeyCache:
    expires_at: datetime
    issuer: str
    uri: str
    keys: tuple[dict[str, object], ...]


class OidcAuthorization:
    def __init__(
        self, client: OidcClientConfig, policy: OidcPolicy, clock: Clock, http: OidcTransport
    ) -> None:
        self._client, self._policy, self._clock, self._http = client, policy, clock, http
        self._cache: _KeyCache | None = None

    @property
    def fingerprint(self) -> str:
        # The secret is included only in this irreversible digest, never persisted as context.
        value = (
            self._client.client_id,
            self._client.client_secret,
            self._client.redirect_uri,
            self._policy.endpoints.discovery,
        )
        return hashlib.sha256(json.dumps(value).encode()).hexdigest()

    def begin(self, state: str, nonce: str, verifier: str) -> str:
        for value in (state, nonce, verifier):
            _bounded_ascii(value, 128)
        client = OAuth2Client(
            session=None,
            client_id=self._client.client_id,
            client_secret=self._client.client_secret,
            scope="openid email profile",
            redirect_uri=self._client.redirect_uri,
            code_challenge_method="S256",
        )
        url, _ = client.create_authorization_url(
            self._policy.endpoints.authorization,
            state=state,
            nonce=nonce,
            code_verifier=verifier,
            prompt="select_account",
        )
        return str(url)

    def exchange(self, code: str, nonce: str, verifier: str) -> ProviderClaims:
        _bounded_ascii(code, 4096)
        _bounded_ascii(nonce, 128)
        _bounded_ascii(verifier, 128)
        body = prepare_token_request(
            "authorization_code",
            code=code,
            redirect_uri=self._client.redirect_uri,
            code_verifier=verifier,
            client_id=self._client.client_id,
            client_secret=self._client.client_secret,
        )
        try:
            tokens = json_response(self._http.request("POST", self._policy.endpoints.token, body))
            value = tokens.get("id_token")
            _bounded_ascii(value, MAX_TOKEN_BYTES)
            assert isinstance(value, str)
            header = jws.extract_compact(value.encode()).protected
            kid = _valid_header(header)
            cache = self._keys()
            key = _select_key(cache, kid)
            if key is None:
                cache = self._keys(refresh=True)
                key = _select_key(cache, kid)
            if key is None:
                raise ProviderSignInRefused
            decoded = jwt.decode(
                value,
                RSAKey.import_key(cast("dict[str, str | list[str]]", key)),
                algorithms=["RS256"],
            )
            if not isinstance(decoded.claims, dict):
                raise ProviderSignInRefused
            validate_claims(
                decoded.claims, self._client.client_id, nonce, int(self._clock.now().timestamp())
            )
            return self._policy.translate(decoded.claims, key, cache.issuer)
        except (JoseError, ValueError, TypeError, KeyError, RecursionError):
            raise ProviderSignInRefused from None

    def _keys(self, *, refresh: bool = False) -> _KeyCache:
        cached = self._cache
        now = self._clock.now()
        if cached is not None and cached.expires_at > now and not refresh:
            return cached
        if cached is None or cached.expires_at <= now:
            metadata = json_response(self._http.request("GET", self._policy.endpoints.discovery))
            issuer = text_claim(metadata, "issuer")
            uri = trusted_jwks(metadata.get("jwks_uri"), self._policy.endpoints.jwks_hosts)
        else:
            issuer, uri = cached.issuer, cached.uri
        document = json_response(self._http.request("GET", uri))
        keys = document.get("keys")
        if (
            not isinstance(keys, list)
            or not 1 <= len(keys) <= 100
            or any(not isinstance(key, dict) for key in keys)
        ):
            raise ProviderSignInRefused
        expiry = (
            cached.expires_at
            if cached is not None and cached.expires_at > now
            else now + CACHE_LIFETIME
        )
        result = _KeyCache(expiry, issuer, uri, tuple(keys))
        self._cache = result
        return result


def _select_key(cache: _KeyCache, kid: str) -> dict[str, object] | None:
    keys = [key for key in cache.keys if key.get("kid") == kid]
    if not keys:
        return None
    if len(keys) != 1:
        raise ProviderSignInRefused
    key = keys[0]
    if (
        key.get("kty") != "RSA"
        or key.get("use", "sig") != "sig"
        or key.get("alg", "RS256") != "RS256"
    ):
        raise ProviderSignInRefused
    text_claim(key, "n", 1024)
    text_claim(key, "e", 16)
    if "key_ops" in key and key["key_ops"] != ["verify"]:
        raise ProviderSignInRefused
    return key


def _valid_header(header: dict[str, object]) -> str:
    if not isinstance(header, dict):
        raise ProviderSignInRefused
    if header.get("alg") != "RS256" or any(
        name in header for name in ("jku", "x5u", "jwk", "crit")
    ):
        raise ProviderSignInRefused
    return text_claim(header, "kid", 128)


def _bounded_ascii(value: object, limit: int) -> None:
    if not isinstance(value, str) or not value or len(value) > limit or not value.isascii():
        raise ProviderSignInRefused
