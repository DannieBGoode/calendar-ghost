"""Enablement diagnostics belong only to Installation Administrators."""

from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from calendar_sync.bootstrap.container import build_container
from calendar_sync.interfaces.api.app import create_app
from calendar_sync.interfaces.api.dependencies import SESSION_COOKIE
from tests.adapters.test_password_reset_api import configured
from tests.adapters.test_provider_sign_in_api import ORIGIN, ready
from tests.users import OTHER_USER, add_user, session_for, sign_in

ROOT = "/api/v1/settings/sign-in-providers"


def test_enablement_guards_and_public_availability(tmp_path: Path) -> None:
    path = tmp_path / "test.db"
    client, _, _ = ready(path)
    assert client.get(ROOT).status_code == 401
    assert (
        client.put(
            ROOT + "/google",
            json={"enabled": True},
            headers={"Authorization": "Bearer synthetic-token"},
        ).status_code
        == 401
    )
    assert client.get("/api/v1/sign-in/providers").json() == {
        "providers": ["google"],
        "capabilities": {"google": {"can_verify_email": True}},
    }
    add_user(path, OTHER_USER, role="user")
    client.cookies.set(SESSION_COOKIE, session_for(path, OTHER_USER))
    assert client.get(ROOT).status_code == 403
    assert client.put(ROOT + "/google", json={"enabled": False}).status_code == 403
    sign_in(client)
    assert client.get(ROOT).status_code == 200
    assert (
        client.put(
            ROOT + "/google", json={"enabled": False}, headers={"Origin": "https://evil.test"}
        ).status_code
        == 403
    )
    assert client.put(ROOT + "/google", json={"enabled": False}).status_code == 204
    assert client.get("/api/v1/sign-in/providers").json() == {"providers": [], "capabilities": {}}


@pytest.mark.parametrize("slug", ["google", "microsoft"])
def test_descriptors_reuse_clients_with_separate_sign_in_consent(tmp_path: Path, slug: str) -> None:
    settings = configured(
        tmp_path / "test.db",
        google_client_id="synthetic-client",
        google_client_secret="synthetic-secret",
        microsoft_client_id="synthetic-client",
        microsoft_client_secret="synthetic-secret",
    )
    client = TestClient(
        create_app(build_container(settings)), base_url=ORIGIN, headers={"Origin": ORIGIN}
    )
    sign_in(client)
    assert client.put(ROOT + "/" + slug, json={"enabled": True}).status_code == 204
    client.cookies.clear()
    answer = client.post("/api/v1/sign-in/" + slug + "/start", json={})
    assert answer.status_code == 200
    values = parse_qs(urlsplit(answer.json()["authorization_url"]).query)
    assert values["scope"] == ["openid email profile"]
    assert values["client_id"] == ["synthetic-client"]
    assert values["redirect_uri"] == [ORIGIN + "/api/v1/sign-in/" + slug + "/callback"]
    assert values["code_challenge_method"] == ["S256"]
    assert "synthetic-secret" not in answer.text


def test_callback_uri_uses_configured_origin_not_request_host(tmp_path: Path) -> None:
    settings = configured(tmp_path / "test.db")
    client = TestClient(create_app(build_container(settings)), base_url="http://testserver")
    sign_in(client)
    answer = client.get(ROOT)
    assert answer.status_code == 200
    for item in answer.json():
        assert item["callback_uri"] == f"{ORIGIN}/api/v1/sign-in/{item['provider']}/callback"


def test_callback_uri_absent_without_configured_origin(tmp_path: Path) -> None:
    settings = configured(tmp_path / "test.db", public_url="")
    client = TestClient(create_app(build_container(settings)))
    sign_in(client)
    answer = client.get(ROOT)
    assert answer.status_code == 200
    assert all(item["callback_uri"] is None for item in answer.json())


@pytest.mark.parametrize("slug", ["google", "microsoft"])
@pytest.mark.parametrize("origin", ["http://127.0.0.2:8000", "http://[0:0:0:0:0:0:0:1]:8000"])
def test_disabled_sign_in_composes_with_literal_loopback(
    tmp_path: Path, slug: str, origin: str
) -> None:
    settings = configured(
        tmp_path / "test.db",
        public_url=origin,
        **{
            f"{slug}_client_id": "synthetic-client",
            f"{slug}_client_secret": "synthetic-secret",
        },
    )
    service = build_container(settings).provider_sign_in
    item = next(item for item in service.settings.list() if item.provider == slug)
    assert item.available
    assert not item.enabled
    assert service.runtime is not None
    assert slug in service.runtime.begin.providers


@pytest.mark.parametrize("slug", ["google", "microsoft"])
def test_nonloopback_http_keeps_sign_in_unavailable(tmp_path: Path, slug: str) -> None:
    settings = configured(
        tmp_path / "test.db",
        public_url="http://192.168.1.2:8000",
        **{
            f"{slug}_client_id": "synthetic-client",
            f"{slug}_client_secret": "synthetic-secret",
        },
    )
    service = build_container(settings).provider_sign_in
    assert not next(item for item in service.settings.list() if item.provider == slug).available


@pytest.mark.parametrize(("slug", "allowed"), [("google", True), ("microsoft", False)])
def test_invitation_start_requires_provider_email_capability(
    tmp_path: Path, slug: str, allowed: bool
) -> None:
    path = tmp_path / "test.db"
    settings = configured(
        path,
        **{
            f"{slug}_client_id": "synthetic-client",
            f"{slug}_client_secret": "synthetic-secret",
        },
    )
    client = TestClient(
        create_app(build_container(settings)), base_url=ORIGIN, headers={"Origin": ORIGIN}
    )
    sign_in(client)
    assert client.put(ROOT + "/" + slug, json={"enabled": True}).status_code == 204
    client.cookies.clear()
    availability = client.get("/api/v1/sign-in/providers").json()
    assert availability["capabilities"][slug]["can_verify_email"] is allowed
    answer = client.post(
        f"/api/v1/sign-in/{slug}/start",
        json={"invitation_token": "synthetic-invitation", "email": "new@example.test"},
    )
    assert answer.status_code == (200 if allowed else 401)
    from calendar_sync.infrastructure.persistence.connections import transaction

    with transaction(path) as connection:
        assert connection.execute("SELECT count(*) FROM provider_flows").fetchone()[0] == int(
            allowed
        )
    if not allowed:
        assert "authorization_url" not in answer.json()
        assert "set-cookie" not in answer.headers


@pytest.mark.parametrize("state", ["live", "expired", "revoked", "consumed"])
def test_only_me_administrator_can_manage_only_live_invitations(tmp_path: Path, state: str) -> None:
    from calendar_sync.infrastructure.persistence.connections import transaction

    path = tmp_path / "test.db"
    client, _, _ = ready(path)
    sign_in(client)
    assert client.put("/api/v1/registration", json={"policy": "invitation_only"}).status_code == 200
    invitation = client.post("/api/v1/invitations").json()
    assert client.put("/api/v1/registration", json={"policy": "only_me"}).status_code == 200
    with transaction(path) as connection:
        if state == "expired":
            connection.execute("UPDATE invitations SET expires_at='2000-01-01T00:00:00+00:00'")
        elif state == "revoked":
            connection.execute("UPDATE invitations SET revoked_at='2000-01-01T00:00:00+00:00'")
        elif state == "consumed":
            connection.execute("UPDATE invitations SET accepted_at='2000-01-01T00:00:00+00:00'")
    pending = client.get("/api/v1/invitations")
    assert pending.status_code == 200
    assert [item["id"] for item in pending.json()] == (
        [invitation["id"]] if state == "live" else []
    )
    assert client.post("/api/v1/invitations").status_code == 409
    if state == "live":
        assert client.delete("/api/v1/invitations/" + invitation["id"]).status_code == 204
        assert client.get("/api/v1/invitations").json() == []
    client.cookies.clear()
    assert client.get("/api/v1/invitations").status_code == 401
