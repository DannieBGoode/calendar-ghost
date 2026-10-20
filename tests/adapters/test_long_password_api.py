"""Every current-credential boundary accepts passwords installed through reset."""

from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import Container, build_container
from calendar_sync.interfaces.api.app import create_app
from tests.adapters.test_password_reset_api import COMPLETE, issued
from tests.users import ADMIN_PASSWORD, OTHER_USER, sign_in


def reset_and_sign_in(container: Container, client: TestClient, path: Path, length: int) -> str:
    sign_in(client)
    token = issued(container, path)
    password = "p" * length
    response = client.post(COMPLETE, json={"token": token, "password": password})
    assert response.status_code == 204
    client.delete("/api/v1/session")
    signed_in = client.post(
        "/api/v1/session",
        json={"email": f"{OTHER_USER.value}@example.test", "password": password},
    )
    assert signed_in.status_code == 200
    assert signed_in.json()["user"]["id"] == OTHER_USER.value
    return password


@pytest.mark.parametrize("length", [257, 1024])
def test_password_reset_can_always_be_followed_by_sign_in(tmp_path: Path, length: int) -> None:
    path = tmp_path / "test.db"
    container = build_container(Settings(path))
    client = TestClient(create_app(container))
    reset_and_sign_in(container, client, path, length)


@pytest.mark.parametrize("action", ["email", "password", "deletion"])
def test_long_reset_credential_confirms_account_management(tmp_path: Path, action: str) -> None:
    path = tmp_path / "test.db"
    container = build_container(Settings(path))
    client = TestClient(create_app(container))
    password = reset_and_sign_in(container, client, path, 1024)
    if action == "email":
        response = client.put(
            "/api/v1/account/email", json={"email": "changed@example.test", "password": password}
        )
        assert response.status_code == 200
        assert response.json()["email"] == "changed@example.test"
    elif action == "password":
        response = client.put(
            "/api/v1/account/password",
            json={"current_password": password, "new_password": ADMIN_PASSWORD},
        )
        assert response.status_code == 204
    else:
        response = client.request(
            "DELETE", "/api/v1/account", json={"password": password, "projections": "detach"}
        )
        assert response.status_code == 200
        assert container.identity.users.get(OTHER_USER) is None


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("POST", "/api/v1/session", {"password": "p" * 1025}),
        ("PUT", "/api/v1/account/email", {"email": "changed@example.test", "password": "p" * 1025}),
        (
            "PUT",
            "/api/v1/account/password",
            {"current_password": "p" * 1025, "new_password": ADMIN_PASSWORD},
        ),
        ("DELETE", "/api/v1/account", {"password": "p" * 1025, "projections": "detach"}),
    ],
)
def test_overlong_current_credentials_are_rejected_before_password_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
    payload: dict[str, str],
) -> None:
    container = build_container(Settings(tmp_path / "test.db"))
    client = TestClient(create_app(container))
    sign_in(client)
    passwords = container.identity.sign_in.passwords
    monkeypatch.setattr(passwords, "verify", Mock(side_effect=AssertionError("verification")))
    monkeypatch.setattr(passwords, "hash", Mock(side_effect=AssertionError("hashing")))
    assert client.request(method, path, json=payload).status_code == 422


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/v1/setup/admin", {"email": "new@example.test", "password": "p" * 257}),
        (
            "/api/v1/invitations/accept",
            {"token": "synthetic", "email": "new@example.test", "password": "p" * 257},
        ),
    ],
)
def test_other_password_creation_bounds_remain_unchanged(
    tmp_path: Path, path: str, payload: dict[str, str]
) -> None:
    client = TestClient(create_app(build_container(Settings(tmp_path / "test.db"))))
    assert client.post(path, json=payload).status_code == 422


def test_own_password_change_creation_bound_remains_unchanged(tmp_path: Path) -> None:
    container = build_container(Settings(tmp_path / "test.db"))
    client = TestClient(create_app(container))
    sign_in(client)
    response = client.put(
        "/api/v1/account/password",
        json={"current_password": ADMIN_PASSWORD, "new_password": "p" * 257},
    )
    assert response.status_code == 422
