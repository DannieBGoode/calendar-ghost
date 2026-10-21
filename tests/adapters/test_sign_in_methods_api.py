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
    assert answer.headers["location"].endswith("unavailable")
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
