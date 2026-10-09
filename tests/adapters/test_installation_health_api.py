"""Installation Health over the status API and MCP, for Installation Administrators only."""

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import build_container
from calendar_sync.interfaces.api.app import create_app
from tests.adapters.test_mcp import JSON_HEADERS
from tests.users import ADMIN_EMAIL, ADMIN_PASSWORD

MEMBER = {"email": "member@example.test", "password": "another long password"}
BOTH = ["status:read", "installation:read"]


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(build_container(Settings(tmp_path / "test.db"))))


def _issue(client: TestClient, scopes: list[str] | None = None) -> Any:
    body: dict[str, Any] = {"name": "Monitor"}
    if scopes is not None:
        body["scopes"] = scopes
    return client.post("/api/v1/integration-tokens", json=body)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _join(admin: TestClient, member: TestClient) -> None:
    admin.post("/api/v1/setup/admin", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    admin.put("/api/v1/registration", json={"policy": "invitation_only"})
    token = admin.post("/api/v1/invitations").json()["token"]
    member.post("/api/v1/invitations/accept", json={"token": token, **MEMBER})


def test_an_administrator_reads_installation_health_without_any_user_named(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as admin, _client(tmp_path) as member:
        _join(admin, member)
        by_session = admin.get("/api/v1/installation/health")
        issued = _issue(admin, BOTH).json()
        admin.cookies.clear()
        by_token = admin.get("/api/v1/installation/health", headers=_bearer(issued["token"]))
        status = admin.get("/api/v1/status", headers=_bearer(issued["token"]))

    body = by_session.json()
    assert by_session.headers["cache-control"] == "no-store"
    assert set(body) == {
        "status",
        "needs_attention",
        "incidents",
        "users",
        "disabled_users",
        "checked_at",
    }
    # Without a master key there is no scheduler; nobody has a rule, so both Users read setup.
    assert (body["status"], body["incidents"], body["users"]) == ("setup", [], {"setup": 2})
    assert "member@example.test" not in by_session.text
    assert issued["scopes"] == sorted(BOTH)
    assert by_token.json()["users"] == {"setup": 2}
    assert status.status_code == 200


def test_only_installation_read_tokens_and_administrators_read_installation_health(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as admin, _client(tmp_path) as member:
        _join(admin, member)
        status_only = _issue(admin).json()["token"]
        health_only = _issue(admin, ["installation:read"]).json()["token"]
        refused_scope = admin.get("/api/v1/installation/health", headers=_bearer(status_only))
        refused_status = admin.get("/api/v1/status", headers=_bearer(health_only))
        member_session = member.get("/api/v1/installation/health")
        member_issue = _issue(member, BOTH)

    assert (refused_scope.status_code, refused_scope.json()["code"]) == (403, "insufficient_scope")
    assert (refused_status.status_code, refused_status.json()["code"]) == (
        403,
        "insufficient_scope",
    )
    assert (member_session.status_code, member_session.json()["code"]) == (
        403,
        "administrator_required",
    )
    assert (member_issue.status_code, member_issue.json()["code"]) == (
        403,
        "administrator_required",
    )


def test_a_token_stops_reading_installation_health_when_its_user_stops_administering(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as admin, _client(tmp_path) as member:
        _join(admin, member)
        admin_id = admin.get("/api/v1/session").json()["user"]["id"]
        member_id = member.get("/api/v1/session").json()["user"]["id"]
        token = _issue(admin, BOTH).json()["token"]
        admin.put(f"/api/v1/users/{member_id}/role", json={"role": "installation_administrator"})
        member.put(f"/api/v1/users/{admin_id}/role", json={"role": "user"})
        refused = admin.get("/api/v1/installation/health", headers=_bearer(token))
        still_status = admin.get("/api/v1/status", headers=_bearer(token))

    assert (refused.status_code, refused.json()["code"]) == (403, "administrator_required")
    assert still_status.status_code == 200


def test_mcp_offers_installation_health_to_installation_read_tokens_only(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        client.post("/api/v1/setup/admin", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        both = _issue(client, BOTH).json()["token"]
        status_only = _issue(client).json()["token"]
        client.cookies.clear()

        def call(token: str, tool: str) -> Any:
            body = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": tool, "arguments": {}},
            }
            return client.post("/mcp", headers={**JSON_HEADERS, **_bearer(token)}, json=body).json()

        health = call(both, "get_installation_health")["result"]
        refused = call(status_only, "get_installation_health")["result"]

    assert health["structuredContent"]["users"] == {"setup": 1}
    assert refused["isError"] is True
    assert "installation:read" in refused["content"][0]["text"]
