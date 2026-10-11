"""Requests to Microsoft Graph v1.0 and the identity platform, and how they are refused.

Every Graph request names an operation, carries the account's access token, asks for UTC times
and text bodies, and is tallied for the run that made it. A refusal keeps only what may be
recorded: its HTTP status, Microsoft's error codes, and its Retry-After hint, never its message,
which can quote the request (ADR 0031, ADR 0032).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx

from calendar_sync.application.providers import ProviderKind
from calendar_sync.infrastructure.provider_calls import record_call

GRAPH = "https://graph.microsoft.com/v1.0"
LOGIN = "https://login.microsoftonline.com"
# Every read asks for UTC times and plain-text bodies (ADR 0032).
READ_PREFERENCES = 'outlook.timezone="UTC", outlook.body-content-type="text"'
# How long one request may take before it counts as not answered.
TIMEOUT_SECONDS = 30.0

Json = dict[str, Any]


@dataclass(frozen=True, slots=True)
class GraphRefusal(Exception):
    """Graph answered a request with an error."""

    status: int | None
    """None when no answer arrived at all."""
    codes: tuple[str, ...] = ()
    """`error.code` and each nested `innerError.code`, outermost first."""
    retry_after: str | None = None

    def __str__(self) -> str:
        return f"Graph answered {self.status or 'nothing'} {' '.join(self.codes)}".strip()


@dataclass(frozen=True, slots=True)
class TokenRefusal(Exception):
    """The identity platform's token endpoint refused, or could not be reached."""

    status: int | None
    error: str | None = None
    """The RFC 6749 `error` field, which clients react to."""
    codes: tuple[int, ...] = field(default=())
    """`error_codes`: AADSTS numbers, for diagnostics only."""

    def __str__(self) -> str:
        return f"Microsoft refused the token request: {self.error or self.status or 'no answer'}"


def graph_refusal(response: httpx.Response) -> GraphRefusal:
    return GraphRefusal(
        response.status_code,
        _graph_codes(_json(response)),
        response.headers.get("retry-after"),
    )


def token_refusal(response: httpx.Response) -> TokenRefusal:
    body = _json(response)
    error = body.get("error") if isinstance(body.get("error"), str) else None
    codes = body.get("error_codes")
    return TokenRefusal(
        response.status_code,
        error,
        tuple(code for code in codes if isinstance(code, int)) if isinstance(codes, list) else (),
    )


def _graph_codes(body: Mapping[str, Any]) -> tuple[str, ...]:
    codes: list[str] = []
    level: object = body.get("error")
    while isinstance(level, Mapping):
        code = level.get("code")
        if isinstance(code, str) and code:
            codes.append(code)
        # Graph names the nested error innerError, and older answers innererror.
        level = level.get("innerError", level.get("innererror"))
    return tuple(codes)


def _json(response: httpx.Response) -> Json:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


@dataclass(slots=True)
class GraphHttp:
    """Sends Graph requests for an account, tallying each one by its operation name alone."""

    http: httpx.Client
    timer: Callable[[], float] = time.monotonic

    def request(
        self,
        operation: str,
        method: str,
        url: str,
        token: str,
        *,
        params: Mapping[str, str] | None = None,
        body: Json | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Json:
        """One Graph request; its JSON answer, empty for 204, or a GraphRefusal."""
        started = self.timer()
        status: int | None = None
        try:
            response = self.http.request(
                method,
                url if url.startswith("https://") else f"{GRAPH}{url}",
                params=params,
                json=body,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Prefer": READ_PREFERENCES,
                    **(headers or {}),
                },
                timeout=TIMEOUT_SECONDS,
            )
            status = response.status_code
        except httpx.HTTPError as error:
            raise GraphRefusal(None) from error
        finally:
            record_call(
                ProviderKind.OUTLOOK,
                operation,
                status,
                self.timer() - started,
                rate_limited=status == 429,
            )
        if status >= 400:
            raise graph_refusal(response)
        return _json(response) if status != 204 else {}

    def pages(
        self, operation: str, url: str, token: str, *, params: Mapping[str, str] | None = None
    ) -> Iterator[Json]:
        """Every page of a listing, following `@odata.nextLink`."""
        page = self.request(operation, "GET", url, token, params=params)
        yield page
        while isinstance(link := page.get("@odata.nextLink"), str):
            page = self.request(operation, "GET", link, token)
            yield page
