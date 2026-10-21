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
    assert client.get("/api/v1/sign-in/providers").json() == {"providers": ["google"]}
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
    assert client.get("/api/v1/sign-in/providers").json() == {"providers": []}


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
