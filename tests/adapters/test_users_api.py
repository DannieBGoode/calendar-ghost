"""Registration, Invitations, Password Reset Links, roles, and User Deletion over the Web API."""

from pathlib import Path

from fastapi.testclient import TestClient

from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import build_container
from calendar_sync.interfaces.api.app import create_app

ADMIN = {"email": "admin@example.test", "password": "correct horse battery staple"}
MEMBER = {"email": "member@example.test", "password": "another long password"}


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(build_container(Settings(tmp_path / "test.db"))))


def _invite(admin: TestClient) -> str:
    response = admin.post("/api/v1/invitations")
    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "no-store"
    token: str = response.json()["token"]
    return token


def _set_up_with_member(admin: TestClient, member: TestClient) -> str:
    admin.post("/api/v1/setup/admin", json=ADMIN)
    admin.put("/api/v1/registration", json={"policy": "invitation_only"})
    accepted = member.post("/api/v1/invitations/accept", json={"token": _invite(admin), **MEMBER})
    assert accepted.status_code == 200, accepted.text
    member_id: str = accepted.json()["user"]["id"]
    return member_id


def test_only_me_lets_nobody_join_until_the_administrator_invites(tmp_path: Path) -> None:
    with _client(tmp_path) as admin:
        admin.post("/api/v1/setup/admin", json=ADMIN)
        initial = admin.get("/api/v1/registration").json()
        closed = admin.post("/api/v1/invitations")
        opened = admin.put("/api/v1/registration", json={"policy": "invitation_only"}).json()
        token = _invite(admin)
        pending = admin.get("/api/v1/invitations").json()

    assert initial == {"policy": "only_me", "only_me_available": True}
    assert (closed.status_code, closed.json()["code"]) == (409, "registration_closed")
    assert opened["policy"] == "invitation_only"
    assert len(token) >= 40
    assert [set(item) for item in pending] == [{"id", "created_at", "expires_at"}]


def test_an_invited_person_joins_with_their_own_email_and_password(tmp_path: Path) -> None:
    with _client(tmp_path) as admin, _client(tmp_path) as member:
        admin.post("/api/v1/setup/admin", json=ADMIN)
        admin.put("/api/v1/registration", json={"policy": "invitation_only"})
        token = _invite(admin)
        checked = member.post("/api/v1/invitations/check", json={"token": token}).json()
        joined = member.post("/api/v1/invitations/accept", json={"token": token, **MEMBER})
        dashboard = member.get("/api/v1/dashboard").json()
        reused = member.post("/api/v1/invitations/accept", json={"token": token, **MEMBER})
        rechecked = member.post("/api/v1/invitations/check", json={"token": token}).json()
        listed = admin.get("/api/v1/users").json()
        back_to_only_me = admin.put("/api/v1/registration", json={"policy": "only_me"})

    assert checked == {"usable": True}
    assert joined.json()["user"]["role"] == "user"
    assert dashboard["sync_rules"] == 0
    assert (reused.status_code, reused.json()["code"]) == (410, "link_unusable")
    assert rechecked == {"usable": False}
    assert [(user["email"], user["role"], user["state"]) for user in listed] == [
        ("admin@example.test", "installation_administrator", "active"),
        ("member@example.test", "user", "active"),
    ]
    assert (back_to_only_me.status_code, back_to_only_me.json()["code"]) == (
        409,
        "only_me_needs_one_user",
    )


def test_a_member_is_refused_every_administrator_route(tmp_path: Path) -> None:
    with _client(tmp_path) as admin, _client(tmp_path) as member:
        member_id = _set_up_with_member(admin, member)
        refused = [
            member.get("/api/v1/users"),
            member.get("/api/v1/registration"),
            member.post("/api/v1/invitations"),
            member.put(
                f"/api/v1/users/{member_id}/role", json={"role": "installation_administrator"}
            ),
            member.get("/api/v1/storage"),
        ]

    assert {(response.status_code, response.json()["code"]) for response in refused} == {
        (403, "administrator_required")
    }


def test_a_reset_link_lets_a_user_choose_a_new_password_and_signs_them_out(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as admin, _client(tmp_path) as member:
        member_id = _set_up_with_member(admin, member)
        issued = admin.post(f"/api/v1/users/{member_id}/password-reset-links")
        token = issued.json()["token"]
        valid = member.post("/api/v1/password-resets/check", json={"token": token}).json()
        reset = member.post(
            "/api/v1/password-resets", json={"token": token, "password": "a third long password"}
        )
        signed_out = member.get("/api/v1/dashboard").status_code
        old = member.post("/api/v1/session", json=MEMBER).status_code
        new = member.post(
            "/api/v1/session", json={**MEMBER, "password": "a third long password"}
        ).status_code
        again = member.post(
            "/api/v1/password-resets", json={"token": token, "password": "a fourth long password"}
        )

    assert issued.status_code == 201
    assert issued.headers["cache-control"] == "no-store"
    assert valid == {"usable": True}
    assert reset.status_code == 204
    assert signed_out == 401
    assert (old, new) == (401, 200)
    assert again.status_code == 410


def test_roles_and_disabling_keep_one_administrator_and_sign_disabled_users_out(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as admin, _client(tmp_path) as member:
        member_id = _set_up_with_member(admin, member)
        admin_id = admin.get("/api/v1/session").json()["user"]["id"]
        last = admin.put(f"/api/v1/users/{admin_id}/role", json={"role": "user"})
        yourself = admin.put(f"/api/v1/users/{admin_id}/state", json={"state": "disabled"})
        disabled = admin.put(f"/api/v1/users/{member_id}/state", json={"state": "disabled"})
        signed_out = member.get("/api/v1/dashboard").status_code
        refused = member.post("/api/v1/session", json=MEMBER)
        admin.put(f"/api/v1/users/{member_id}/state", json={"state": "active"})
        enabled = member.post("/api/v1/session", json=MEMBER).status_code
        granted = admin.put(
            f"/api/v1/users/{member_id}/role", json={"role": "installation_administrator"}
        )
        missing = admin.put("/api/v1/users/missing/state", json={"state": "disabled"})

    assert (last.status_code, last.json()["code"]) == (409, "last_administrator")
    assert (yourself.status_code, yourself.json()["code"]) == (409, "your_own_state")
    assert disabled.json()["state"] == "disabled"
    assert signed_out == 401
    assert (refused.status_code, refused.json()["code"]) == (403, "user_disabled")
    assert enabled == 200
    assert granted.json()["role"] == "installation_administrator"
    assert missing.status_code == 404


def test_users_are_deleted_by_an_administrator_or_by_themselves(tmp_path: Path) -> None:
    with _client(tmp_path) as admin, _client(tmp_path) as member:
        member_id = _set_up_with_member(admin, member)
        deleted = admin.delete(f"/api/v1/users/{member_id}")
        gone = member.get("/api/v1/dashboard").status_code
        rejoined_id = _set_up_with_member(admin, member)
        wrong = member.request(
            "DELETE",
            "/api/v1/account",
            json={"password": "wrong password!", "projections": "delete"},
        )
        own = member.request(
            "DELETE",
            "/api/v1/account",
            json={"password": MEMBER["password"], "projections": "detach"},
        )
        listed = admin.get("/api/v1/users").json()

    assert deleted.json() == {"rules": 0, "deleted": 0, "detached": 0, "left": 0}
    assert gone == 401
    assert rejoined_id != member_id
    assert (wrong.status_code, wrong.json()["code"]) == (403, "incorrect_password")
    assert own.status_code == 200
    assert [user["email"] for user in listed] == ["admin@example.test"]


def test_the_last_administrator_leaves_only_when_nobody_else_remains(tmp_path: Path) -> None:
    with _client(tmp_path) as admin, _client(tmp_path) as member:
        member_id = _set_up_with_member(admin, member)
        pending = _invite(admin)
        while_shared = admin.get("/api/v1/account/deletion").json()
        member_view = member.get("/api/v1/account/deletion").json()
        admin.delete(f"/api/v1/users/{member_id}")
        alone = admin.get("/api/v1/account/deletion").json()
        left = admin.request(
            "DELETE",
            "/api/v1/account",
            json={"password": ADMIN["password"], "projections": "delete"},
        )
        setup = member.get("/api/v1/setup").json()
        joined = member.post("/api/v1/invitations/accept", json={"token": pending, **MEMBER})
        again = admin.post("/api/v1/setup/admin", json=ADMIN)
        policy = admin.get("/api/v1/registration").json()["policy"]

    assert while_shared == {"needs_another_administrator": True, "last_user": False}
    assert member_view == {"needs_another_administrator": False, "last_user": False}
    assert alone == {"needs_another_administrator": False, "last_user": True}
    assert left.status_code == 200
    assert setup["administrator_configured"] is False
    assert (joined.status_code, joined.json()["code"]) == (410, "link_unusable")
    assert again.status_code in (200, 201)
    assert policy == "only_me"
