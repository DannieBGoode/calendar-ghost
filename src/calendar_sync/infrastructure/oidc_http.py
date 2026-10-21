"""Bounded OIDC transport, with no redirects or provider diagnostics escaping."""

import json
from typing import Protocol
from urllib.parse import urlsplit

import requests

from calendar_sync.application.identity.provider_sign_in_ports import ProviderSignInRefused

MAX_RESPONSE_BYTES = 1024 * 1024
TIMEOUT_SECONDS = 10


class OidcTransport(Protocol):
    def request(self, method: str, url: str, body: str | None = None) -> bytes: ...


class RequestsOidcTransport:
    def request(self, method: str, url: str, body: str | None = None) -> bytes:
        try:
            with requests.request(
                method,
                url,
                data=body,
                timeout=TIMEOUT_SECONDS,
                allow_redirects=False,
                stream=True,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            ) as response:
                if response.status_code != 200:
                    raise ProviderSignInRefused
                chunks = bytearray()
                for chunk in response.iter_content(chunk_size=8192):
                    chunks.extend(chunk)
                    if len(chunks) > MAX_RESPONSE_BYTES:
                        raise ProviderSignInRefused
                return bytes(chunks)
        except requests.RequestException:
            raise ProviderSignInRefused from None


def json_response(raw: bytes) -> dict[str, object]:
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ProviderSignInRefused
    try:
        value = json.loads(raw)
    except (ValueError, RecursionError):
        raise ProviderSignInRefused from None
    if not isinstance(value, dict):
        raise ProviderSignInRefused
    return value


def trusted_jwks(value: object, hosts: frozenset[str]) -> str:
    if not isinstance(value, str) or len(value) > 2048:
        raise ProviderSignInRefused
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in hosts
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or parsed.fragment
        or not parsed.path
    ):
        raise ProviderSignInRefused
    return value
