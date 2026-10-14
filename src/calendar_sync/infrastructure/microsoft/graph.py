"""Requests to Microsoft Graph v1.0 and the identity platform, and how they are refused.

Every Graph request names an operation, carries the account's access token, asks for UTC times
and text bodies, and is tallied for the run that made it. A refusal keeps only what may be
recorded: its HTTP status, Microsoft's error codes, its Retry-After hint, and whether it says a
subscription's notification URL failed validation. It never keeps the message, which can quote
the request (ADR 0031, ADR 0034, ADR 0036).
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx

from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.infrastructure.provider_calls import record_call

GRAPH = "https://graph.microsoft.com/v1.0"
LOGIN = "https://login.microsoftonline.com"
# Every read asks for UTC times and plain-text bodies (ADR 0034).
READ_PREFERENCES = 'outlook.timezone="UTC", outlook.body-content-type="text"'
# How long one request may take before it counts as not answered.
TIMEOUT_SECONDS = 30.0
# Graph refuses a subscription whose notification URL failed its validation request with a 400
# that says so only in its message, such as "Subscription validation request failed.
# Notification endpoint must respond with 200 OK to validation request." The message is matched
# here and never kept (ADR 0036).
UNVALIDATED_ENDPOINT = re.compile(
    r"validation request (?:failed|timed out)|notification endpoint", re.IGNORECASE
)

Json = dict[str, Any]


# Not frozen: raising an error sets its __traceback__, which a frozen dataclass refuses.
@dataclass(eq=False)
class GraphRefusal(Exception):
    """Graph answered a request with an error."""

    status: int | None
    """None when no answer arrived at all."""
    codes: tuple[str, ...] = ()
    """`error.code` and each nested `innerError.code`, outermost first."""
    retry_after: str | None = None
    endpoint_refused: bool = False
    """Graph would not create a subscription because its notification URL did not answer the
    validation request: the installation's address is unreachable, not the account refused."""

    def __str__(self) -> str:
        return f"Graph answered {self.status or 'nothing'} {' '.join(self.codes)}".strip()


# Not frozen: raising an error sets its __traceback__, which a frozen dataclass refuses.
@dataclass(eq=False)
class TokenRefusal(Exception):
    """The identity platform's token endpoint refused, or could not be reached."""

    status: int | None
    error: str | None = None
    """The RFC 6749 `error` field, which clients react to."""
    codes: tuple[int, ...] = field(default=())
    """`error_codes`: AADSTS numbers, for diagnostics only."""
    retry_after: str | None = None
    """How long a throttled request should wait, as Microsoft's `Retry-After` header says."""

    def __str__(self) -> str:
        return f"Microsoft refused the token request: {self.error or self.status or 'no answer'}"


def graph_refusal(response: httpx.Response) -> GraphRefusal:
    body = _json(response)
    return GraphRefusal(
        response.status_code,
        _graph_codes(body),
        response.headers.get("retry-after"),
        endpoint_refused=response.status_code == 400 and _says_endpoint_unvalidated(body),
    )


def _says_endpoint_unvalidated(body: Mapping[str, Any]) -> bool:
    """Whether Graph's message says the notification URL failed validation; only this answer
    is kept, never the message."""
    error = body.get("error")
    message = error.get("message") if isinstance(error, Mapping) else None
    return isinstance(message, str) and UNVALIDATED_ENDPOINT.search(message) is not None


def token_refusal(response: httpx.Response) -> TokenRefusal:
    body = _json(response)
    error = body.get("error") if isinstance(body.get("error"), str) else None
    codes = body.get("error_codes")
    return TokenRefusal(
        response.status_code,
        error,
        tuple(code for code in codes if isinstance(code, int)) if isinstance(codes, list) else (),
        response.headers.get("retry-after"),
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
        if status == 204:
            return {}
        try:
            answer = response.json()
        except ValueError as error:
            # A success without the JSON Graph documents is no answer, so it is tried again.
            raise GraphRefusal(None) from error
        if not isinstance(answer, dict):
            raise GraphRefusal(None)
        return answer

    def pages(
        self, operation: str, url: str, token: str, *, params: Mapping[str, str] | None = None
    ) -> Iterator[Json]:
        """Every page of a listing, following `@odata.nextLink`."""
        page = self.request(operation, "GET", url, token, params=params)
        yield page
        while isinstance(link := page.get("@odata.nextLink"), str):
            page = self.request(operation, "GET", link, token)
            yield page


def items_of(page: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
    """A listing page's items. A page without a list in `value` is no answer, never an empty
    one, so it fails for now and proves nothing absent."""
    values = page.get("value")
    if not isinstance(values, list):
        raise GraphRefusal(None)
    return [item for item in values if isinstance(item, Mapping)]
