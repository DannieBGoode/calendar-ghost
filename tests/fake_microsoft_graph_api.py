"""A fake of Microsoft's identity platform and Graph v1.0, served through httpx, with synthetic
data.

It answers the requests the Outlook adapter makes, in the shapes Microsoft documents (ADR 0032):
the OAuth 2.0 token endpoint with PKCE and rotating refresh tokens, `/me`, and calendars. Tests
place mailboxes in it, consent as their owner would, and refuse requests the way Microsoft does.
No request leaves the process.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

GRAPH = "https://graph.microsoft.com/v1.0"
LOGIN = "https://login.microsoftonline.com"
CLIENT_ID = "synthetic-client"
CLIENT_SECRET = "synthetic-secret"

Json = dict[str, Any]


@dataclass
class FakeCalendar:
    id: str
    name: str | None
    can_edit: bool = True
    default: bool = False


@dataclass
class FakeMailbox:
    """One Microsoft account's mailbox, as Graph shows it to that account."""

    address: str
    display_name: str = "Synthetic Person"
    mail: str | None = None
    """`/me` `mail`; personal accounts often have none."""
    calendars: list[FakeCalendar] = field(default_factory=list)


@dataclass
class Grant:
    mailbox: FakeMailbox
    scope: str


@dataclass(frozen=True)
class Refusal:
    """How Microsoft refuses a request: an HTTP status and its documented error body."""

    status: int
    body: Json
    headers: Mapping[str, str] = field(default_factory=dict)


def token_error(error: str, *codes: int, status: int = 400) -> Refusal:
    """A token endpoint refusal (RFC 6749 5.2), with AADSTS numbers for diagnostics only."""
    return Refusal(
        status,
        {
            "error": error,
            "error_description": f"AADSTS{codes[0] if codes else 0}: private-marker said no",
            "error_codes": list(codes),
        },
    )


def graph_error(status: int, code: str, inner: str | None = None, **headers: str) -> Refusal:
    """A Graph refusal, whose message quotes something private that must never be kept."""
    body: Json = {"error": {"code": code, "message": "private-marker-calendar said no"}}
    if inner is not None:
        body["error"]["innerError"] = {"code": inner}
    return Refusal(status, body, headers)


class FakeMicrosoftGraph:
    """Microsoft's identity platform and Graph, for the mailboxes a test places in it."""

    def __init__(self) -> None:
        self.client_id = CLIENT_ID
        self.client_secret = CLIENT_SECRET
        self.mailboxes: dict[str, FakeMailbox] = {}
        self.granted_scope = "openid email offline_access User.Read Calendars.ReadWrite"
        self._codes: dict[str, tuple[Grant, str, str]] = {}
        self._access: dict[str, Grant] = {}
        self._refresh: dict[str, Grant] = {}
        self.token_requests: list[Mapping[str, str]] = []
        self.requests: list[httpx.Request] = []
        self.refusals: list[tuple[Callable[[httpx.Request], bool], Refusal]] = []
        """Refusals answered, in order, to the first request each one matches; each answers
        once."""

    # Test helpers -------------------------------------------------------------------------

    def mailbox(self, address: str, **details: Any) -> FakeMailbox:
        box = FakeMailbox(address, **details)
        if not box.calendars:
            box.calendars = [FakeCalendar("calendar-default", "Calendar", default=True)]
        self.mailboxes[address] = box
        return box

    def consent(self, authorization_url: str, address: str, scope: str | None = None) -> str:
        """Approve a consent page as the mailbox's owner; the code the redirect would carry."""
        query = {
            key: values[0] for key, values in parse_qs(urlparse(authorization_url).query).items()
        }
        assert query["client_id"] == self.client_id
        assert query["code_challenge_method"] == "S256"
        code = secrets.token_urlsafe(16)
        grant = Grant(self.mailboxes[address], scope if scope is not None else self.granted_scope)
        self._codes[code] = (grant, query["code_challenge"], query["redirect_uri"])
        return code

    def issue(self, address: str, *, expires_in: int = 3600) -> Json:
        """Tokens for a mailbox, as an earlier consent left them."""
        return self._tokens(Grant(self.mailboxes[address], self.granted_scope), expires_in)

    def refuse(
        self, refusal: Refusal, when: Callable[[httpx.Request], bool] = lambda _: True
    ) -> None:
        self.refusals.append((when, refusal))

    def revoke(self, address: str) -> None:
        """The owner removes the application's access: every token of the mailbox stops."""
        for tokens in (self._access, self._refresh):
            for token in [
                token for token, grant in tokens.items() if grant.mailbox.address == address
            ]:
                del tokens[token]

    def client(self) -> httpx.Client:
        # Through a lambda, so a test may replace `handle` after the client was made.
        return httpx.Client(transport=httpx.MockTransport(lambda request: self.handle(request)))

    # Serving ------------------------------------------------------------------------------

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        for index, (matches, refusal) in enumerate(self.refusals):
            if matches(request):
                del self.refusals[index]
                return httpx.Response(
                    refusal.status, json=refusal.body, headers=dict(refusal.headers)
                )
        url = str(request.url)
        if url.startswith(LOGIN):
            return self._token_endpoint(request)
        if url.startswith(GRAPH):
            grant = self._access.get(
                request.headers.get("Authorization", "").removeprefix("Bearer ")
            )
            if grant is None:
                return _graph_error(401, "InvalidAuthenticationToken")
            return self.graph(request, grant.mailbox)
        return httpx.Response(404)

    def graph(self, request: httpx.Request, mailbox: FakeMailbox) -> httpx.Response:
        path = request.url.path.removeprefix("/v1.0")
        if request.method == "GET" and path == "/me":
            return httpx.Response(
                200,
                json={
                    "displayName": mailbox.display_name,
                    "mail": mailbox.mail,
                    "userPrincipalName": mailbox.address,
                },
            )
        if request.method == "GET" and path == "/me/calendars":
            return self._calendars(request, mailbox)
        calendar = next(
            (c for c in mailbox.calendars if path.startswith(f"/me/calendars/{c.id}/")), None
        )
        if request.method == "GET" and calendar is not None and path.endswith("/events"):
            return httpx.Response(200, json={"value": []})
        return _graph_error(404, "ErrorItemNotFound")

    def _calendars(self, request: httpx.Request, mailbox: FakeMailbox) -> httpx.Response:
        page = int(request.url.params.get("page", "0"))
        size = 2
        calendars = mailbox.calendars[page * size : (page + 1) * size]
        body: Json = {
            "value": [
                {
                    "id": calendar.id,
                    "name": calendar.name,
                    "canEdit": calendar.can_edit,
                    "isDefaultCalendar": calendar.default,
                }
                for calendar in calendars
            ]
        }
        if (page + 1) * size < len(mailbox.calendars):
            body["@odata.nextLink"] = f"{GRAPH}/me/calendars?page={page + 1}"
        return httpx.Response(200, json=body)

    def _token_endpoint(self, request: httpx.Request) -> httpx.Response:
        form = {key: values[0] for key, values in parse_qs(request.content.decode()).items()}
        self.token_requests.append(form)
        if (form.get("client_id"), form.get("client_secret")) != (
            self.client_id,
            self.client_secret,
        ):
            return _token_error(401, "invalid_client", 7000215)
        if form.get("grant_type") == "authorization_code":
            return self._exchange(form)
        if form.get("grant_type") == "refresh_token":
            grant = self._refresh.pop(form.get("refresh_token", ""), None)
            if grant is None:
                return _token_error(400, "invalid_grant", 70008)
            return httpx.Response(200, json=self._tokens(grant, 3600))
        return _token_error(400, "unsupported_grant_type", 70003)

    def _exchange(self, form: Mapping[str, str]) -> httpx.Response:
        found = self._codes.pop(form.get("code", ""), None)
        if found is None:
            return _token_error(400, "invalid_grant", 70000)
        grant, challenge, redirect_uri = found
        digest = hashlib.sha256(form.get("code_verifier", "").encode()).digest()
        if base64.urlsafe_b64encode(digest).rstrip(b"=").decode() != challenge:
            return _token_error(400, "invalid_grant", 501481)
        if form.get("redirect_uri") != redirect_uri:
            return _token_error(400, "invalid_grant", 50011)
        return httpx.Response(200, json=self._tokens(grant, 3600))

    def _tokens(self, grant: Grant, expires_in: int) -> Json:
        access, refresh = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
        self._access[access] = grant
        self._refresh[refresh] = grant
        claims = {"email": grant.mailbox.address, "preferred_username": grant.mailbox.address}
        payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
        return {
            "token_type": "Bearer",
            "access_token": access,
            "refresh_token": refresh,
            "expires_in": expires_in,
            "scope": " ".join(
                f"https://graph.microsoft.com/{scope}" if scope[0].isupper() else scope
                for scope in grant.scope.split()
            ),
            "id_token": f"e30.{payload}.signature",
        }


def _token_error(status: int, error: str, code: int) -> httpx.Response:
    refusal = token_error(error, code, status=status)
    return httpx.Response(refusal.status, json=refusal.body)


def _graph_error(status: int, code: str) -> httpx.Response:
    return httpx.Response(status, json={"error": {"code": code, "message": "private-marker"}})
