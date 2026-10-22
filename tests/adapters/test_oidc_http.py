"""The real Requests boundary refuses redirects, excess data, and raw provider errors."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
import requests

from calendar_sync.application.identity.provider_sign_in_ports import ProviderSignInRefused
from calendar_sync.infrastructure.oidc_http import (
    MAX_RESPONSE_BYTES,
    RequestsOidcTransport,
    json_response,
    trusted_jwks,
)


class Response:
    def __init__(self, status: int, body: bytes) -> None:
        self.status_code, self.body = status, body
        self.closed = False

    def __enter__(self) -> Response:
        return self

    def __exit__(self, *args: object) -> None:
        self.closed = True

    def iter_content(self, *, chunk_size: int) -> Iterator[bytes]:
        for offset in range(0, len(self.body), chunk_size):
            yield self.body[offset : offset + chunk_size]


@pytest.mark.parametrize(
    ("status", "size", "allowed"),
    [(200, 2, True), (302, 2, False), (500, 2, False), (200, MAX_RESPONSE_BYTES + 1, False)],
)
def test_transport_limits(
    monkeypatch: pytest.MonkeyPatch, status: int, size: int, allowed: bool
) -> None:
    response = Response(status, b"x" * size)
    calls: list[dict[str, Any]] = []

    def request(method: str, url: str, **kwargs: Any) -> Response:
        calls.append(kwargs)
        return response

    monkeypatch.setattr(requests, "request", request)
    transport = RequestsOidcTransport()
    if allowed:
        assert transport.request("GET", "https://provider.example.test/keys") == response.body
    else:
        with pytest.raises(ProviderSignInRefused):
            transport.request("GET", "https://provider.example.test/keys")
    assert len(calls) == 1
    assert calls[0]["timeout"] == 10
    assert calls[0]["allow_redirects"] is False
    assert calls[0]["stream"] is True
    assert response.closed


def test_transport_errors_are_neutral(monkeypatch: pytest.MonkeyPatch) -> None:
    def request(*args: object, **kwargs: object) -> None:
        raise requests.Timeout("private provider response")

    monkeypatch.setattr(requests, "request", request)
    with pytest.raises(
        ProviderSignInRefused, match="Provider sign-in could not be completed"
    ) as error:
        RequestsOidcTransport().request("POST", "https://provider.example.test/token", "secret")
    assert error.value.__suppress_context__


@pytest.mark.parametrize(
    "url",
    [
        "http://provider.example.test/keys",
        "https://evil.test/keys",
        "https://provider.example.test.evil.test/keys",
        "https://user@provider.example.test/keys",
        "https://provider.example.test:444/keys",
        "https://provider.example.test/keys#fragment",
    ],
)
def test_jwks_host_allowlist(url: str) -> None:
    with pytest.raises(ProviderSignInRefused):
        trusted_jwks(url, frozenset({"provider.example.test"}))


@pytest.mark.parametrize("raw", [b"[1]", b"broken", b"x" * (MAX_RESPONSE_BYTES + 1), b"[" * 2000])
def test_json_response_bounds(raw: bytes) -> None:
    with pytest.raises(ProviderSignInRefused):
        json_response(raw)
