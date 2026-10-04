from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import build_adapters, compose
from calendar_sync.interfaces.api.app import create_app
from tests.helpers import rule

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
    with sqlite3.connect(database) as connection:
        connection.executemany(
            """
            INSERT INTO connected_accounts (
                id, provider, display_name, email, encrypted_credentials,
                state, created_at, updated_at
            ) VALUES (?, 'google', ?, ?, x'00', 'connected', '2026-09-01', '2026-09-01')
            """,
            [
                (account, account, f"{account}@example.test")
                for account in ("personal-account", "work-account")
            ],
        )
    with adapters.unit_of_work() as uow:
        uow.rules.add(rule())
        uow.commit()
    with TestClient(create_app(container), base_url="http://ghost.lan:8000") as client:
        client.post("/api/v1/setup/admin", json=PASSWORD)
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
    token_id = client.get("/api/v1/integration-tokens").json()[0]["id"]
    client.delete(f"/api/v1/integration-tokens/{token_id}")
    assert _rpc(client, token, "tools/list").status_code == 401


@pytest.mark.parametrize("method", ["GET", "DELETE", "PUT"])
def test_only_post_is_served_so_no_stream_stays_open(mcp: Any, method: str) -> None:
    client, token = mcp
    response = client.request(method, "/mcp", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 405
    assert response.headers["allow"] == "POST"


def test_paths_below_mcp_are_not_found_and_the_web_ui_is_unaffected(mcp: Any) -> None:
    client, token = mcp
    below = client.post("/mcp/", headers={"Authorization": f"Bearer {token}"}, json={})
    assert below.status_code == 404
    assert client.post("/mcp/extra", json={}).status_code == 404
    # The compiled Web UI is committed, so its client-side routes still serve the application.
    web_ui = client.get("/rules")
    assert web_ui.status_code == 200
    assert web_ui.headers["content-type"].startswith("text/html")
    assert "mcp" not in client.get("/api/openapi.json").text
