"""Public joining proves ownership without exposing eligibility or identity inputs."""

import threading
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from calendar_sync.application.identity.registration_ports import PreparedRegistration
from calendar_sync.bootstrap.container import Container, build_container
from calendar_sync.domain.access import RegistrationPolicy, Role, User, UserId
from calendar_sync.infrastructure.identity_email import IdentitySmtp
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.security import hash_password
from calendar_sync.interfaces.api.app import create_app
from calendar_sync.interfaces.api.dependencies import SESSION_COOKIE
from tests.adapters.test_password_reset_api import configured, private
from tests.adapters.test_plans_api import FAMILY_BODY, FREE_BODY, UNLIMITED
from tests.users import ADMIN_EMAIL, ADMIN_PASSWORD, OTHER_USER, add_user, session_for, sign_in

REQUEST = "/api/v1/registrations/request"
CHECK = "/api/v1/registrations/check"
COMPLETE = "/api/v1/registrations"
EMAIL = "new@example.test"


def ready(path: Path) -> tuple[TestClient, Container]:
    container = build_container(configured(path))
    client = TestClient(create_app(container))
    sign_in(client)
    with transaction(path) as connection:
        connection.execute(
            "UPDATE identity_email_readiness SET fingerprint = ?, tested_at = ?",
            (
                container.registrations.check.fingerprint,
                container.registrations.complete.clock.now().isoformat(),
            ),
        )
    opened = client.put("/api/v1/registration", json={"policy": "open"})
    assert opened.status_code == 200, opened.text
    return client, container


def proof(container: Container, email: str = EMAIL, invitation: str | None = None) -> str:
    fingerprint = container.registrations.check.fingerprint
    assert fingerprint
    issued = container.registrations.check.proofs.issue(email, invitation, fingerprint)
    assert issued
    return issued.link.token


def snapshot(path: Path) -> dict[str, list[tuple[object, ...]]]:
    with transaction(path) as connection:
        return {
            table: [tuple(row) for row in connection.execute(f"SELECT * FROM {table}")]
            for table in ("users", "user_sessions", "registration_proofs", "invitations")
        }


@pytest.mark.parametrize("email", [ADMIN_EMAIL, "disabled@example.test", EMAIL])
@pytest.mark.parametrize("queue", ["accepted", "full", "failure"])
def test_generic_requests_match_without_lookup_or_delivery_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, email: str, queue: str
) -> None:
    path = tmp_path / "test.db"
    client, container = ready(path)
    add_user(path, OTHER_USER, email="disabled@example.test", role="user", state="disabled")
    lookup = Mock(side_effect=AssertionError("anonymous account lookup"))
    monkeypatch.setattr(container.identity.users, "by_email", lookup)
    worker = container.identity_mail_worker
    assert worker
    submit = Mock(
        return_value=queue == "accepted",
        side_effect=RuntimeError("private") if queue == "failure" else None,
    )
    monkeypatch.setattr(worker, "submit_registration", submit)
    before = snapshot(path)
    for _ in range(2):
        answer = client.post(REQUEST, json={"email": email, "invitation_token": "unknown"})
        assert (answer.status_code, answer.json()) == (202, {"accepted": True})
        assert "retry-after" not in answer.headers
        private(answer)
    submit.assert_called_once()
    lookup.assert_not_called()
    assert snapshot(path) == before


@pytest.mark.parametrize("blocked", ["lookup", "transport"])
def test_request_does_not_wait_for_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, blocked: str
) -> None:
    _client, container = ready(tmp_path / "test.db")
    started, release = threading.Event(), threading.Event()
    original = container.registrations.check.proofs.issue

    def issue(email: str, invitation: str | None, fingerprint: str) -> PreparedRegistration | None:
        started.set()
        assert release.wait(3)
        return original(email, invitation, fingerprint)

    def send(_self: IdentitySmtp, _recipient: str, _subject: str, _body: str) -> None:
        started.set()
        assert release.wait(3)
        raise RuntimeError("private provider transport failure")

    if blocked == "lookup":
        monkeypatch.setattr(container.registrations.check.proofs, "issue", issue)
    else:
        monkeypatch.setattr(IdentitySmtp, "_send", send)
    container = replace(
        container, scheduler=None, scheduler_watch=None, instant_dispatcher=None, watch_keeper=None
    )
    with TestClient(create_app(container)) as public:
        try:
            answer = public.post(REQUEST, json={"email": EMAIL})
            assert (answer.status_code, answer.json()) == (202, {"accepted": True})
            assert started.wait(3)
            assert public.get("/api/v1/setup").status_code == 200
        finally:
            release.set()


@pytest.mark.parametrize(
    ("target", "payload"),
    [
        (REQUEST, {"email": "not-an-email"}),
        (REQUEST, {"email": "a" * 242 + "@example.test"}),
        (REQUEST, {"email": EMAIL, "invitation_token": "secret" * 22}),
        (CHECK, {"token": "secret" * 22}),
        (CHECK, {"token": "secret-é"}),
        (COMPLETE, {"token": "private-token", "password": "tiny-secret"}),
        (COMPLETE, {"token": "private-token", "password": "p" * 1025}),
        (COMPLETE, {"token": "private-token", "password": ADMIN_PASSWORD, "role": "private-role"}),
        (COMPLETE, {"token": "private-token", "password": ADMIN_PASSWORD, "plan": "private-plan"}),
        (
            COMPLETE,
            {
                "token": "private-token",
                "password": ADMIN_PASSWORD,
                "private-extra-input": "private-value",
            },
        ),
        ("/api/v1/invitations/check", {"token": "secret-é"}),
        (
            "/api/v1/invitations/accept",
            {"token": "secret" * 22, "email": EMAIL, "password": ADMIN_PASSWORD},
        ),
    ],
)
def test_boundaries_before_storage_or_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: str, payload: dict[str, str]
) -> None:
    client, container = ready(tmp_path / "test.db")
    for obj, method in (
        (container.registrations.check.proofs, "check"),
        (container.registrations.request.admission, "admit_front"),
        (container.registrations.complete.passwords, "hash"),
        (container.administration.check_invitation.invitations, "usable"),
    ):
        monkeypatch.setattr(obj, method, Mock(side_effect=AssertionError("before validation")))
    response = client.post(target, json=payload)
    assert response.status_code == 422
    private(response)
    for secret in payload.values():
        assert secret not in response.text
    assert "private-extra-input" not in response.text


@pytest.mark.parametrize(
    "target", [REQUEST, CHECK, COMPLETE, "/api/v1/invitations/check", "/api/v1/invitations/accept"]
)
@pytest.mark.parametrize(
    "body",
    [
        b'{"token":"private-token", "password":"private-password",',
        b'["private-token"]',
        b'"private-password"',
        b" " * 8193,
    ],
)
def test_malformed_and_oversized_inputs_never_echo_secrets(
    tmp_path: Path, target: str, body: bytes
) -> None:
    response = TestClient(create_app(build_container(configured(tmp_path / "test.db")))).post(
        target, content=body, headers={"Content-Type": "application/json", "Content-Length": "1"}
    )
    assert response.status_code == (413 if len(body) > 8192 else 422)
    private(response)
    assert "private-token" not in response.text
    assert "private-password" not in response.text


@pytest.mark.parametrize("page", ["/sign-up", "/verify-email", "/invitation"])
def test_identity_pages_are_private(tmp_path: Path, page: str) -> None:
    client = TestClient(create_app(build_container(configured(tmp_path / "test.db"))))
    private(client.get(page))


def test_check_has_no_mutation_or_sensitive_headers(tmp_path: Path) -> None:
    path = tmp_path / "test.db"
    client, container = ready(path)
    token = proof(container)
    before = snapshot(path)
    for _ in range(2):
        response = client.post(CHECK, json={"token": token})
        assert response.json() == {"usable": True, "email": EMAIL}
        assert "set-cookie" not in response.headers
        private(response)
    assert snapshot(path) == before
    with transaction(path) as connection:
        connection.execute(
            "UPDATE registration_proofs SET expires_at = '2000-01-01T00:00:00+00:00'"
        )
    before = snapshot(path)
    response = client.post(CHECK, json={"token": token})
    assert response.json() == {"usable": False, "email": None}
    assert snapshot(path) == before


@pytest.mark.parametrize("change", ["readiness", "policy", "invitation"])
@pytest.mark.parametrize("during_hash", [False, True])
def test_completion_policy_invitation_and_readiness_races(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str, during_hash: bool
) -> None:
    path = tmp_path / "test.db"
    client, container = ready(path)
    invitation = client.post("/api/v1/invitations").json() if change == "invitation" else None
    token = proof(container, invitation=invitation["token"] if invitation else None)
    assert client.post(CHECK, json={"token": token}).json()["usable"]

    def mutate() -> None:
        if change == "policy":
            assert (
                client.put("/api/v1/registration", json={"policy": "invitation_only"}).status_code
                == 200
            )
        elif change == "invitation":
            assert invitation
            assert client.delete(f"/api/v1/invitations/{invitation['id']}").status_code == 204
        else:
            with transaction(path) as connection:
                connection.execute("UPDATE identity_email_readiness SET fingerprint = 'changed'")

    passwords = container.registrations.complete.passwords
    original_hash = passwords.hash

    def hash_with_race(password: str) -> str:
        mutate()
        return original_hash(password)

    if during_hash:
        monkeypatch.setattr(passwords, "hash", hash_with_race)
    else:
        mutate()
    before = snapshot(path)
    response = client.post(COMPLETE, json={"token": token, "password": ADMIN_PASSWORD})
    expected = (
        (503, "registration_unavailable") if change == "readiness" else (410, "link_unusable")
    )
    assert (response.status_code, response.json()["code"]) == expected
    assert snapshot(path)["users"] == before["users"]
    assert snapshot(path)["user_sessions"] == before["user_sessions"]
    checked = client.post(CHECK, json={"token": token})
    assert checked.status_code == (503 if change == "readiness" else 200)
    if change != "readiness":
        assert checked.json() == {"usable": False, "email": None}
        return
    with transaction(path) as connection:
        connection.execute(
            "UPDATE identity_email_readiness SET fingerprint = ?",
            (container.registrations.check.fingerprint,),
        )
    monkeypatch.setattr(passwords, "hash", original_hash)
    assert client.post(CHECK, json={"token": token}).json() == {"usable": True, "email": EMAIL}
    client.cookies.clear()
    completed = client.post(COMPLETE, json={"token": token, "password": "p" * 1024})
    assert completed.status_code == 200, completed.text
    assert completed.json()["user"]["role"] == "user"
    assert SESSION_COOKIE in completed.cookies
    assert client.get("/api/v1/dashboard").status_code == 200
    assert (
        client.post(COMPLETE, json={"token": token, "password": ADMIN_PASSWORD}).status_code == 410
    )
    assert len(snapshot(path)["user_sessions"]) == len(before["user_sessions"]) + 1


def test_invitation_contract_follows_current_policy_and_preserves_invalid_requests(
    tmp_path: Path,
) -> None:
    path = tmp_path / "test.db"
    client, container = ready(path)
    invitation = client.post("/api/v1/invitations").json()
    assert client.post("/api/v1/invitations/check", json={"token": invitation["token"]}).json() == {
        "usable": True,
        "acceptance": "verified",
    }
    stale = client.post(
        "/api/v1/invitations/accept",
        json={"token": invitation["token"], "email": EMAIL, "password": ADMIN_PASSWORD},
    )
    assert (stale.status_code, stale.json()["code"]) == (409, "invitation_verification_required")
    assert client.post(REQUEST, json={"email": EMAIL, "invitation_token": "invalid"}).json() == {
        "accepted": True
    }
    with transaction(path) as connection:
        connection.execute("UPDATE identity_email_readiness SET fingerprint = 'changed'")
    assert client.post("/api/v1/invitations/check", json={"token": invitation["token"]}).json() == {
        "usable": True,
        "acceptance": "verified",
    }
    with transaction(path) as connection:
        connection.execute(
            "UPDATE identity_email_readiness SET fingerprint = ?",
            (container.registrations.check.fingerprint,),
        )
    token = proof(container, invitation=invitation["token"])
    client.put("/api/v1/registration", json={"policy": "invitation_only"})
    assert client.post("/api/v1/invitations/check", json={"token": invitation["token"]}).json() == {
        "usable": True,
        "acceptance": "direct",
    }
    # A delivered Invitation-bound proof finishes without SMTP after policy changes.
    unavailable = TestClient(create_app(build_container(replace(configured(path), smtp_host=""))))
    assert (
        unavailable.post(COMPLETE, json={"token": token, "password": ADMIN_PASSWORD}).status_code
        == 200
    )
    assert client.post("/api/v1/invitations/check", json={"token": invitation["token"]}).json() == {
        "usable": False,
        "acceptance": None,
    }


def test_cross_purpose_tokens_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "test.db"
    client, container = ready(path)
    token = proof(container)
    invitation = client.post("/api/v1/invitations").json()["token"]
    add_user(path, OTHER_USER, role="user")
    reset = client.post(f"/api/v1/users/{OTHER_USER.value}/password-reset-links").json()["token"]
    client.post(
        "/api/v1/account/email-change",
        json={"email": "next@example.test", "password": ADMIN_PASSWORD},
    )
    pending = client.get("/api/v1/account/email-change").json()["pending"]
    change = container.identity_email.email_changes.show.proofs.prepare(pending["id"])
    assert change
    before = snapshot(path)
    for other in (invitation, reset, change.token):
        assert client.post(CHECK, json={"token": other}).json() == {"usable": False, "email": None}
        assert (
            client.post(COMPLETE, json={"token": other, "password": ADMIN_PASSWORD}).status_code
            == 410
        )
    for target in (
        "/api/v1/password-resets/check",
        "/api/v1/account/email-change/check",
        "/api/v1/invitations/check",
    ):
        assert client.post(target, json={"token": token}).json()["usable"] is False
    for target in (
        "/api/v1/password-resets",
        "/api/v1/account/email-change/confirm",
        "/api/v1/invitations/accept",
    ):
        assert (
            client.post(
                target, json={"token": token, "email": EMAIL, "password": ADMIN_PASSWORD}
            ).status_code
            == 410
        )
    assert snapshot(path) == before


def test_new_user_follows_default_plan(tmp_path: Path) -> None:
    path = tmp_path / "test.db"
    admin, container = ready(path)
    for plan in (FREE_BODY, FAMILY_BODY):
        assert admin.post("/api/v1/plans", json=plan).status_code == 201
    admin.put("/api/v1/plan-settings", json={"enabled": True, "default_plan": "free"})
    member = TestClient(create_app(container))
    joined = member.post(COMPLETE, json={"token": proof(container), "password": ADMIN_PASSWORD})
    assert joined.status_code == 200
    user_id = UserId(joined.json()["user"]["id"])
    user = container.identity.users.get(user_id)
    assert user
    assert user.plan is None
    assert user.role is Role.USER
    assert member.get("/api/v1/account/plan").json()["plan"]["key"] == "free"
    admin.put("/api/v1/plan-settings", json={"enabled": True, "default_plan": "family"})
    assert member.get("/api/v1/account/plan").json()["plan"]["key"] == "family"
    admin.put("/api/v1/plan-settings", json={"enabled": False, "default_plan": "family"})
    unlimited = member.get("/api/v1/account/plan").json()
    assert {key: unlimited[key] for key in UNLIMITED} == UNLIMITED
    assert unlimited["basis"] == "plans_off"


def test_existing_users_keep_access(tmp_path: Path) -> None:
    path = tmp_path / "test.db"
    admin, container = ready(path)
    assert admin.put("/api/v1/registration", json={"policy": "invitation_only"}).status_code == 200
    add_user(path, OTHER_USER, role="user")
    with transaction(path) as connection:
        connection.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(ADMIN_PASSWORD), OTHER_USER.value),
        )
    member = TestClient(create_app(container))
    member.cookies.set(SESSION_COOKIE, session_for(path, OTHER_USER))
    for change in ("open", "readiness", "invitation_only"):
        if change == "open":
            assert admin.put("/api/v1/registration", json={"policy": change}).status_code == 200
        elif change == "readiness":
            with transaction(path) as connection:
                connection.execute("UPDATE identity_email_readiness SET fingerprint = 'changed'")
        elif change == "invitation_only":
            assert admin.put("/api/v1/registration", json={"policy": change}).status_code == 200
        assert member.get("/api/v1/dashboard").status_code == 200
        member.cookies.clear()
        assert (
            member.post(
                "/api/v1/session", json={"email": "user-2@example.test", "password": ADMIN_PASSWORD}
            ).status_code
            == 200
        )


def test_session_race_directs_to_sign_in_without_duplicate_admission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "test.db"
    client, container = ready(path)
    from calendar_sync.application.identity.errors import IncorrectCredentials

    monkeypatch.setattr(
        container.registrations.complete.sessions,
        "start",
        Mock(side_effect=IncorrectCredentials("sign in instead")),
    )
    token = proof(container)
    response = client.post(COMPLETE, json={"token": token, "password": ADMIN_PASSWORD})
    assert (response.status_code, response.json()["code"]) == (401, "incorrect_credentials")
    assert len(snapshot(path)["users"]) == 2
    assert (
        client.post(COMPLETE, json={"token": token, "password": ADMIN_PASSWORD}).status_code == 410
    )


@pytest.mark.parametrize("phase", ["session", "record"])
def test_post_admission_storage_failure_recovers_through_sign_in(
    tmp_path: Path, phase: str
) -> None:
    path = tmp_path / "test.db"
    _, container = ready(path)
    public = TestClient(create_app(container), raise_server_exceptions=False)
    token = proof(container)
    trigger = (
        "BEFORE INSERT ON user_sessions"
        if phase == "session"
        else "BEFORE UPDATE OF last_sign_in_at ON users"
    )
    with transaction(path) as connection:
        connection.execute(
            f"CREATE TRIGGER fail_sign_in {trigger} BEGIN "
            "SELECT RAISE(ABORT, 'synthetic private storage failure'); END"
        )
    response = public.post(COMPLETE, json={"token": token, "password": ADMIN_PASSWORD})
    assert response.status_code == 401
    assert response.json()["code"] == "incorrect_credentials"
    private(response)
    assert "synthetic private storage failure" not in response.text
    assert "set-cookie" not in response.headers
    assert public.get("/api/v1/session").json()["authenticated"] is False
    after = snapshot(path)
    assert len(after["users"]) == 2
    assert len(after["user_sessions"]) == (1 if phase == "session" else 2)
    assert (
        container.registrations.check.proofs.check(token, container.registrations.check.fingerprint)
        is None
    )
    with transaction(path) as connection:
        assert connection.execute("SELECT used_at FROM registration_proofs").fetchone()[0]
    again = public.post(COMPLETE, json={"token": token, "password": ADMIN_PASSWORD})
    assert (again.status_code, again.json()["code"]) == (410, "link_unusable")
    private(again)
    retried = snapshot(path)
    assert retried["users"] == after["users"]
    assert retried["user_sessions"] == after["user_sessions"]
    with transaction(path) as connection:
        connection.execute("DROP TRIGGER fail_sign_in")
    signed_in = public.post("/api/v1/session", json={"email": EMAIL, "password": ADMIN_PASSWORD})
    assert signed_in.status_code == 200
    assert signed_in.json()["user"]["email"] == EMAIL


def test_account_independent_throttles_and_storage_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "test.db"
    client, _ = ready(path)
    for _ in range(20):
        assert client.post(CHECK, json={"token": "invalid"}).status_code == 200
    limited = client.post(CHECK, json={"token": "invalid"})
    assert (limited.status_code, limited.json()["code"]) == (429, "registration_network_throttled")
    assert int(limited.headers["retry-after"]) > 0
    assert (
        client.post("/api/v1/password-resets/check", json={"token": "invalid"}).status_code == 200
    )
    with transaction(path) as connection:
        connection.execute("DROP TABLE registration_request_attempts")
    fresh = TestClient(create_app(build_container(configured(path))), client=("192.0.2.5", 1234))
    for target, payload in (
        (REQUEST, {"email": EMAIL}),
        (CHECK, {"token": "invalid"}),
        (COMPLETE, {"token": "invalid", "password": ADMIN_PASSWORD}),
    ):
        response = fresh.post(target, json=payload)
        assert (response.status_code, response.json()["code"]) == (503, "registration_unavailable")
        private(response)


@pytest.mark.parametrize("failure", ["untested", "changed", "storage"])
def test_administrator_open_readiness_and_public_fail_closed(tmp_path: Path, failure: str) -> None:
    path = tmp_path / "test.db"
    client, _ = ready(path)
    assert client.get("/api/v1/setup").json()["public_registration_available"] is True
    assert client.get("/api/v1/registration").json() == {
        "policy": "open",
        "only_me_available": True,
        "open_available": True,
        "open_unavailable_reason": None,
    }
    with transaction(path) as connection:
        if failure == "storage":
            connection.execute("DROP TABLE identity_email_readiness")
        elif failure == "changed":
            connection.execute("UPDATE identity_email_readiness SET fingerprint = 'changed'")
        else:
            connection.execute(
                "UPDATE identity_email_readiness SET fingerprint = NULL, tested_at = NULL"
            )
    setup = client.get("/api/v1/setup")
    assert setup.status_code == 200
    assert setup.json()["public_registration_available"] is False
    assert setup.json()["administrator_configured"] is True
    refused = client.put("/api/v1/registration", json={"policy": "open"})
    if failure == "storage":
        assert (refused.status_code, refused.json()["code"]) == (503, "registration_unavailable")
        assert client.get("/api/v1/registration").status_code == 503
    else:
        assert (refused.status_code, refused.json()["code"], refused.json()["params"]) == (
            409,
            "open_registration_unavailable",
            {"reason": "identity_email_not_tested"},
        )
        assert (
            client.get("/api/v1/registration").json()["open_unavailable_reason"]
            == "identity_email_not_tested"
        )
    public = client.post(REQUEST, json={"email": EMAIL})
    assert (public.status_code, public.json()["code"], public.json()["params"]) == (
        503,
        "registration_unavailable",
        {},
    )
    private(public)


def test_policy_write_rechecks_administrator_and_only_me_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "test.db"
    client, container = ready(path)
    add_user(path, OTHER_USER, role="user")
    assert client.put("/api/v1/registration", json={"policy": "only_me"}).status_code == 409
    settings = container.administration.set_registration_policy.settings
    original = settings.set_policy

    def demote(policy: RegistrationPolicy, *, actor: UserId, fingerprint: str | None) -> None:
        with transaction(path) as connection:
            connection.execute("UPDATE users SET role = 'user' WHERE id = ?", (actor.value,))
        original(policy, actor=actor, fingerprint=fingerprint)

    monkeypatch.setattr(settings, "set_policy", demote)
    response = client.put("/api/v1/registration", json={"policy": "open"})
    assert (response.status_code, response.json()["code"]) == (403, "administrator_required")
    assert client.put("/api/v1/registration", json={"policy": "open"}).status_code == 403


def test_integration_token_provides_no_registration_authority(tmp_path: Path) -> None:
    client, _ = ready(tmp_path / "test.db")
    token = client.post("/api/v1/integration-tokens", json={"name": "Probe"}).json()["token"]
    client.cookies.clear()
    client.headers["Authorization"] = f"Bearer {token}"
    assert client.post(CHECK, json={"token": token}).json() == {"usable": False, "email": None}
    response = client.post(COMPLETE, json={"token": token, "password": ADMIN_PASSWORD})
    assert (response.status_code, response.json()["code"]) == (410, "link_unusable")
    assert client.get("/api/v1/registration").status_code == 401
    assert client.post(COMPLETE, json={"password": ADMIN_PASSWORD}).status_code == 422


def test_policy_storage_failure_is_safe_for_administrator_and_invitation_checks(
    tmp_path: Path,
) -> None:
    path = tmp_path / "test.db"
    client, _ = ready(path)
    with transaction(path) as connection:
        connection.execute("DROP TABLE installation_settings")
    responses = [
        client.get("/api/v1/registration"),
        client.post("/api/v1/invitations"),
        client.put("/api/v1/registration", json={"policy": "open"}),
        client.post("/api/v1/invitations/check", json={"token": "private-token"}),
        client.post(
            "/api/v1/invitations/accept",
            json={"token": "private-token", "email": EMAIL, "password": ADMIN_PASSWORD},
        ),
    ]
    for response in responses:
        assert (response.status_code, response.json()["code"]) == (503, "registration_unavailable")
        assert "private-token" not in response.text


@pytest.mark.parametrize("phase", ["user", "watches", "availability_user"])
def test_response_tail_storage_failure_recovers_after_committed_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    import sqlite3

    from calendar_sync.infrastructure.persistence.users import SqliteUserDirectory
    from calendar_sync.infrastructure.persistence.watches import SqliteCalendarWatchRepository

    path = tmp_path / "test.db"
    _, container = ready(path)
    token = proof(container)
    public = TestClient(create_app(container), raise_server_exceptions=False)
    original_get = SqliteUserDirectory.get
    calls = 0

    def get(users: SqliteUserDirectory, user: UserId) -> User | None:
        nonlocal calls
        calls += 1
        if calls == (1 if phase == "user" else 2):
            raise sqlite3.OperationalError("synthetic private response read failure")
        return original_get(users, user)

    with monkeypatch.context() as faults:
        if phase == "watches":
            faults.setattr(
                SqliteCalendarWatchRepository,
                "list",
                Mock(side_effect=sqlite3.OperationalError("synthetic watch read failure")),
            )
        else:
            faults.setattr(SqliteUserDirectory, "get", get)
        response = public.post(COMPLETE, json={"token": token, "password": ADMIN_PASSWORD})
    assert (response.status_code, response.json()["code"]) == (401, "incorrect_credentials")
    private(response)
    assert "set-cookie" not in response.headers
    assert "synthetic" not in response.text
    after = snapshot(path)
    assert len(after["users"]) == 2
    assert len(after["user_sessions"]) == 2
    assert (
        container.registrations.check.proofs.check(token, container.registrations.check.fingerprint)
        is None
    )
    with transaction(path) as connection:
        assert connection.execute("SELECT used_at FROM registration_proofs").fetchone()[0]
    replay = public.post(COMPLETE, json={"token": token, "password": ADMIN_PASSWORD})
    assert replay.status_code == 410
    assert snapshot(path)["users"] == after["users"]
    assert snapshot(path)["user_sessions"] == after["user_sessions"]
    signed_in = public.post("/api/v1/session", json={"email": EMAIL, "password": ADMIN_PASSWORD})
    assert signed_in.status_code == 200
    assert signed_in.json()["user"]["email"] == EMAIL
