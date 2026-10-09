from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import Iterator, MutableMapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from calendar_sync.application.ports import IntegrationTokenScope
from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import build_adapters, compose
from calendar_sync.domain.access import UserId
from calendar_sync.interfaces.api.app import create_app
from calendar_sync.interfaces.mcp.server import McpEndpoint, McpServices
from tests.helpers import rule
from tests.users import USER, administrator, sign_in

PASSWORD = {"password": "correct horse battery staple"}
PROTOCOL = "2025-06-18"
JSON_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
    "MCP-Protocol-Version": PROTOCOL,
}


@pytest.fixture
def mcp(tmp_path: Path) -> Iterator[tuple[TestClient, str]]:
    """A signed-in client on a LAN host name, with one rule and one Integration Token."""
    database = tmp_path / "test.db"
    settings = Settings(database)
    adapters = build_adapters(settings)
    container = replace(compose(settings, adapters), scheduler=None)
    user = administrator(adapters.administrator)
    with sqlite3.connect(database) as connection:
        connection.executemany(
            """
            INSERT INTO connected_accounts (
                id, provider, display_name, email, encrypted_credentials,
                state, created_at, updated_at, user_id
            ) VALUES (?, 'google', ?, ?, x'00', 'connected', '2026-09-01', '2026-09-01',
                (SELECT id FROM users ORDER BY rowid LIMIT 1))
            """,
            [
                (account, account, f"{account}@example.test")
                for account in ("personal-account", "work-account")
            ],
        )
    with adapters.unit_of_work(user)() as uow:
        uow.rules.add(rule())
        uow.commit()
    with TestClient(create_app(container), base_url="http://ghost.lan:8000") as client:
        sign_in(client)
        token: str = client.post("/api/v1/integration-tokens", json={"name": "Agent"}).json()[
            "token"
        ]
        yield client, token


def _rpc(
    client: TestClient, token: str | None, method: str, params: dict[str, Any] | None = None
) -> Any:
    headers = dict(JSON_HEADERS)
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    body: dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        body["params"] = params
    return client.post("/mcp", headers=headers, json=body)


def test_tools_are_listed_and_read_only(mcp: Any) -> None:
    client, token = mcp
    client.cookies.clear()
    response = _rpc(client, token, "tools/list")
    tools = {tool["name"]: tool for tool in response.json()["result"]["tools"]}
    assert set(tools) == {"get_status", "get_rule"}
    assert all(tool["annotations"]["readOnlyHint"] is True for tool in tools.values())


def test_initialize_names_the_server_and_explains_the_statuses(mcp: Any) -> None:
    client, token = mcp
    result = _rpc(
        client,
        token,
        "initialize",
        {
            "protocolVersion": PROTOCOL,
            "capabilities": {},
            "clientInfo": {"name": "t", "version": "1"},
        },
    ).json()["result"]
    assert result["serverInfo"]["name"] == "calendar-ghost"
    assert "needs_attention" in result["instructions"]
    assert "read-only" in result["instructions"]


def test_get_status_matches_the_status_api(mcp: Any) -> None:
    client, token = mcp
    called = _rpc(client, token, "tools/call", {"name": "get_status", "arguments": {}}).json()
    api = client.get("/api/v1/status", headers={"Authorization": f"Bearer {token}"}).json()
    structured = called["result"]["structuredContent"]
    assert structured["status"] == api["status"]
    assert structured["rules"] == api["rules"]


@pytest.mark.parametrize("reference", ["rule-1", "Unnamed calendar → Unnamed calendar"])
def test_get_rule_finds_a_rule_by_id_or_name(mcp: Any, reference: str) -> None:
    client, token = mcp
    called = _rpc(
        client, token, "tools/call", {"name": "get_rule", "arguments": {"rule": reference}}
    ).json()
    structured = called["result"]["structuredContent"]
    assert structured["rule"]["id"] == "rule-1"
    assert "last_sync" in structured


def test_get_rule_reports_an_unknown_rule_without_listing_names(mcp: Any) -> None:
    client, token = mcp
    called = _rpc(
        client, token, "tools/call", {"name": "get_rule", "arguments": {"rule": "Nope"}}
    ).json()
    assert called["result"]["isError"] is True
    text = called["result"]["content"][0]["text"]
    assert "get_status" in text
    assert "Unnamed calendar" not in text


def test_mcp_refuses_missing_revoked_and_cookie_only_credentials(mcp: Any) -> None:
    client, token = mcp
    assert _rpc(client, None, "tools/list").status_code == 401
    assert _rpc(client, "cgs_" + "A" * 43, "tools/list").status_code == 401
    unauthorized = _rpc(client, None, "tools/list")
    assert unauthorized.headers["www-authenticate"] == "Bearer"
    assert unauthorized.json() == {
        "detail": "valid credentials required",
        "code": "credentials_required",
        "params": {},
    }
    token_id = client.get("/api/v1/integration-tokens").json()[0]["id"]
    client.delete(f"/api/v1/integration-tokens/{token_id}")
    assert _rpc(client, token, "tools/list").status_code == 401


@pytest.mark.parametrize("method", ["GET", "DELETE", "PUT"])
def test_only_post_is_served_so_no_stream_stays_open(mcp: Any, method: str) -> None:
    client, token = mcp
    response = client.request(method, "/mcp", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 405
    assert response.headers["allow"] == "POST"
    assert response.json()["code"] == "method_not_allowed"


def test_paths_below_mcp_are_not_found_and_the_web_ui_is_unaffected(mcp: Any) -> None:
    client, token = mcp
    below = client.post("/mcp/", headers={"Authorization": f"Bearer {token}"}, json={})
    assert below.status_code == 404
    assert below.json() == {"detail": "not found", "code": "not_found", "params": {}}
    assert client.post("/mcp/extra", json={}).status_code == 404
    # The compiled Web UI is committed, so its client-side routes still serve the application.
    web_ui = client.get("/rules")
    assert web_ui.status_code == 200
    assert web_ui.headers["content-type"].startswith("text/html")
    assert "mcp" not in client.get("/api/openapi.json").text


def test_the_first_authorization_header_decides_as_on_the_status_api(mcp: Any) -> None:
    client, token = mcp
    client.cookies.clear()
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    good_first = [("Authorization", f"Bearer {token}"), ("Authorization", "Bearer nope")]
    bad_first = list(reversed(good_first))

    def codes(headers: list[tuple[str, str]]) -> tuple[int, int]:
        mcp_code = client.post("/mcp", headers=[*JSON_HEADERS.items(), *headers], json=body)
        api_code = client.get("/api/v1/status", headers=headers)
        return mcp_code.status_code, api_code.status_code

    assert codes(good_first) == (200, 200)
    assert codes(bad_first) == (401, 401)


@dataclass(frozen=True)
class _Summary:
    scope: object
    owner: UserId = USER


@dataclass(frozen=True)
class _Tokens:
    scope: object

    def authenticate(self, token: str) -> _Summary:
        return _Summary(self.scope)


@dataclass(frozen=True)
class _Services:
    token_authentication: _Tokens
    administrator: None = None


def _call_gate(scope: object) -> tuple[int, dict[str, object]]:
    """POST /mcp with a bearer token straight to the gate of an MCP endpoint that is not running."""
    endpoint = McpEndpoint(cast(McpServices, _Services(_Tokens(scope))))
    sent: list[MutableMapping[str, Any]] = []

    async def receive() -> MutableMapping[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: MutableMapping[str, Any]) -> None:
        sent.append(message)

    request = {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "headers": [(b"authorization", b"Bearer cgs_token")],
    }
    asyncio.run(endpoint.app(request, receive, send))
    return sent[0]["status"], json.loads(sent[1]["body"])


def test_a_token_without_the_status_scope_is_forbidden() -> None:
    assert _call_gate("rules:write") == (
        403,
        {"detail": "token lacks the required scope", "code": "insufficient_scope", "params": {}},
    )


def test_a_valid_token_before_the_server_starts_gets_service_unavailable() -> None:
    assert _call_gate(IntegrationTokenScope.STATUS_READ) == (
        503,
        {
            "detail": "the MCP server is starting or stopping",
            "code": "mcp_not_running",
            "params": {},
        },
    )


@pytest.mark.parametrize(
    "path",
    [
        "/.well-known/oauth-protected-resource",
        "/.well-known/oauth-protected-resource/mcp",
        "/.well-known/oauth-authorization-server",
        "/.well-known/openid-configuration/mcp",
    ],
)
def test_oauth_discovery_is_not_answered_by_the_web_ui(mcp: Any, path: str) -> None:
    # MCP clients look for OAuth metadata before using a bearer token; an HTML page with 200
    # would read as metadata. Calendar Ghost has none, so it says so in JSON.
    client, _ = mcp
    response = client.get(path)
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"
