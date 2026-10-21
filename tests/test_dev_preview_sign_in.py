"""Synthetic identity preview uses real browser flow boundaries without provider network calls."""

from pathlib import Path

from fastapi.testclient import TestClient

from calendar_sync.interfaces.api.app import create_app
from scripts.dev_preview import PREVIEW_EMAIL, PREVIEW_PASSWORD, build_preview_container
from scripts.dev_preview_sign_in import SignInFixture


def test_passwordless_preview_signs_in_locally_and_sets_first_password(tmp_path: Path) -> None:
    origin = "http://127.0.0.1:8001"
    container = build_preview_container(tmp_path / "preview.db", sign_in=SignInFixture.PASSWORDLESS)
    assert container.scheduler is None
    with TestClient(create_app(container), base_url=origin, headers={"Origin": origin}) as client:
        assert client.get("/api/v1/sign-in/providers").json() == {
            "providers": ["google", "microsoft"]
        }
        start = client.post("/api/v1/sign-in/google/start", json={})
        url = start.json()["authorization_url"]
        assert url.startswith(origin + "/api/v1/sign-in/google/callback?")
        assert client.get(url, follow_redirects=False).headers["location"] == "/overview"
        assert client.get("/api/v1/account/sign-in-methods").json()["has_password"] is False
        assert (
            client.post("/api/v1/account/password", json={"password": PREVIEW_PASSWORD}).status_code
            == 204
        )
        assert client.get("/api/v1/account/sign-in-methods").json()["has_password"] is True
        assert client.get("/api/v1/session").json()["user"]["email"] == PREVIEW_EMAIL


def test_microsoft_preview_uses_generic_pending_link_without_external_requests(
    tmp_path: Path,
) -> None:
    origin = "http://127.0.0.1:8001"
    container = build_preview_container(tmp_path / "preview.db", sign_in=SignInFixture.BOTH)
    with TestClient(create_app(container), base_url=origin, headers={"Origin": origin}) as client:
        start = client.post("/api/v1/sign-in/microsoft/start", json={})
        url = start.json()["authorization_url"]
        assert url.startswith(origin + "/api/v1/sign-in/microsoft/callback?")
        assert client.get(url, follow_redirects=False).headers["location"] == "/provider-link"
        assert client.get("/api/v1/sign-in/pending").json() == {"password_required": True}
        answer = client.post(
            "/api/v1/sign-in/confirm", json={"email": PREVIEW_EMAIL, "password": PREVIEW_PASSWORD}
        )
        assert answer.status_code == 200
        assert {
            item["provider"]
            for item in client.get("/api/v1/account/sign-in-methods").json()["identities"]
        } == {"google", "microsoft"}


def test_disabled_preview_keeps_identity_for_recovery(tmp_path: Path) -> None:
    container = build_preview_container(tmp_path / "preview.db", sign_in=SignInFixture.DISABLED)
    with TestClient(create_app(container)) as client:
        client.post("/api/v1/session", json={"email": PREVIEW_EMAIL, "password": PREVIEW_PASSWORD})
        assert client.get("/api/v1/sign-in/providers").json() == {"providers": []}
        assert client.get("/api/v1/account/sign-in-methods").json()["identities"] == [
            {"id": "preview-google", "provider": "google"}
        ]
