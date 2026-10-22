"""Session-only method changes preserve the owning session and the last usable method."""

from pathlib import Path

import pytest

from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.interfaces.api.dependencies import SESSION_COOKIE
from tests.adapters.test_provider_sign_in_api import begin, finish, ready
from tests.users import ADMIN_EMAIL, ADMIN_PASSWORD, OTHER_USER, add_user, session_for, sign_in

ROOT = "/api/v1/account/sign-in-methods"


@pytest.mark.parametrize("authorization", [None, "Bearer synthetic-integration-token"])
def test_methods_require_session(tmp_path: Path, authorization: str | None) -> None:
    client, _, _ = ready(tmp_path / "test.db")
    headers = {"Authorization": authorization} if authorization else {}
    for method, path, body in [
        ("GET", ROOT, None),
        ("POST", ROOT + "/google/start", {}),
        ("DELETE", ROOT + "/unknown", None),
        ("POST", "/api/v1/account/password", {"password": ADMIN_PASSWORD}),
    ]:
        answer = client.request(method, path, json=body, headers=headers)
        assert answer.status_code == 401


def test_owned_link_retains_session_and_cannot_unlink_another_users_identity(
    tmp_path: Path,
) -> None:
    path = tmp_path / "test.db"
    client, _, _ = ready(path)
    sign_in(client)
    token = client.cookies.get(SESSION_COOKIE)
    answer = finish(client, begin(client, ROOT + "/google/start"))
    assert answer.headers["location"] == "/settings/account"
    assert client.cookies.get(SESSION_COOKIE) == token
    methods = client.get(ROOT).json()
    identity = methods["identities"][0]
    assert set(identity) == {"id", "provider"}
    add_user(path, OTHER_USER, role="user")
    client.cookies.clear()
    client.cookies.set(SESSION_COOKIE, session_for(path, OTHER_USER))
    assert client.delete(ROOT + "/" + identity["id"]).status_code == 404


def test_owned_link_rechecks_session_after_start(tmp_path: Path) -> None:
    client, container, provider = ready(tmp_path / "test.db")
    sign_in(client)
    state = begin(client, ROOT + "/google/start")
    container.identity.sessions.end(client.cookies.get(SESSION_COOKIE))
    answer = finish(client, state)
    assert answer.headers["location"] == "/sign-in?provider_result=unavailable"
    assert provider.calls == 0


def test_first_password_only_and_last_method_guard(tmp_path: Path) -> None:
    path = tmp_path / "test.db"
    client, _, _ = ready(path)
    finish(client, begin(client))
    identity = client.get(ROOT).json()["identities"][0]["id"]
    with transaction(path) as connection:
        connection.execute("UPDATE users SET password_hash=NULL WHERE email=?", (ADMIN_EMAIL,))
    assert client.delete(ROOT + "/" + identity).status_code == 409
    assert (
        client.post("/api/v1/account/password", json={"password": ADMIN_PASSWORD}).status_code
        == 204
    )
    assert client.get(ROOT).json()["has_password"] is True
    assert (
        client.post("/api/v1/account/password", json={"password": ADMIN_PASSWORD}).status_code
        == 409
    )
    assert client.delete(ROOT + "/" + identity).status_code == 204
    assert client.get(ROOT).json()["identities"] == []


@pytest.mark.parametrize("owned", [False, True])
def test_callback_denial_returns_to_the_current_session_context(
    tmp_path: Path, owned: bool
) -> None:
    client, _, provider = ready(tmp_path / "test.db")
    if owned:
        sign_in(client)
    state = begin(client, ROOT + "/google/start" if owned else "/api/v1/sign-in/google/start")
    answer = finish(client, state, error="private-denial", return_url="https://evil.test")
    expected = "/settings/account" if owned else "/sign-in"
    assert answer.headers["location"] == expected + "?provider_result=unavailable"
    assert "set-cookie" not in answer.headers
    assert provider.calls == 0


def test_owned_link_collision_returns_to_account_without_changing_identity_owner(
    tmp_path: Path,
) -> None:
    path = tmp_path / "test.db"
    client, _, _ = ready(path)
    assert finish(client, begin(client)).headers["location"] == "/overview"
    identity = client.get(ROOT).json()["identities"][0]["id"]
    add_user(path, OTHER_USER, role="user")
    client.cookies.clear()
    client.cookies.set(SESSION_COOKIE, session_for(path, OTHER_USER))
    answer = finish(client, begin(client, ROOT + "/google/start"))
    assert answer.headers["location"] == "/settings/account?provider_result=unavailable"
    assert client.get(ROOT).json()["identities"] == []
    assert client.delete(ROOT + "/" + identity).status_code == 404
