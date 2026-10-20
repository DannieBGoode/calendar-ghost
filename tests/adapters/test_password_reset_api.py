"""Public recovery is bounded before parsing, storage, and password hashing."""

import asyncio
import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from starlette.types import Message, Scope

from calendar_sync.application.identity.ports import IssuedLink
from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import Container, build_container
from calendar_sync.domain.access import Role, UserId, UserState
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.security import CredentialCipher
from calendar_sync.interfaces.api.app import create_app
from tests.users import ADMIN_EMAIL, ADMIN_PASSWORD, OTHER_USER, add_user, session_for, sign_in

REQUEST = "/api/v1/password-resets/request"
CHECK = "/api/v1/password-resets/check"
COMPLETE = "/api/v1/password-resets"
KEY = CredentialCipher.generate_key()


def configured(path: Path, **changes: object) -> Settings:
    values: dict[str, Any] = {
        "master_key": KEY,
        "smtp_host": "smtp.example.test",
        "smtp_sender": "ghost@example.test",
        "public_url": "https://calendar.example.test",
    }
    values.update(changes)
    return Settings(path, **values)


class HasHeaders(Protocol):
    @property
    def headers(self) -> Mapping[str, str]: ...


def private(response: HasHeaders) -> None:
    headers = response.headers
    assert headers["cache-control"] == "no-store"
    assert headers["referrer-policy"] == "no-referrer"


def issued(container: Container, path: Path) -> str:
    add_user(path, OTHER_USER, role="user")
    actor = next(user.id for user in container.identity.users.list() if user.email == ADMIN_EMAIL)
    return container.administration.issue_password_reset.execute(actor, OTHER_USER).token


@pytest.mark.parametrize(
    "email", ["active@example.test", "disabled@example.test", "unknown@example.test", ADMIN_EMAIL]
)
@pytest.mark.parametrize("queue", ["accepted", "full", "stopped", "failure"])
def test_requests_are_generic_and_never_read_users_or_send_mail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, email: str, queue: str
) -> None:
    path = tmp_path / "test.db"
    container = build_container(configured(path))
    add_user(path, email=ADMIN_EMAIL)
    add_user(path, UserId("active"), email="active@example.test", role="user")
    add_user(path, UserId("disabled"), email="disabled@example.test", role="user", state="disabled")
    lookup = Mock(side_effect=AssertionError("anonymous account lookup"))
    monkeypatch.setattr(container.identity.users, "by_email", lookup)
    worker = container.identity_mail_worker
    assert worker is not None
    submit = Mock(
        return_value=queue == "accepted",
        side_effect=RuntimeError("private") if queue == "failure" else None,
    )
    monkeypatch.setattr(worker, "submit_reset", submit)
    client = TestClient(create_app(container))
    response = client.post(REQUEST, json={"email": email})
    suppressed = client.post(REQUEST, json={"email": email})
    for answer in (response, suppressed):
        assert (answer.status_code, answer.json()) == (202, {"accepted": True})
        assert "retry-after" not in answer.headers
        private(answer)
    assert submit.call_count == 1
    lookup.assert_not_called()
    with transaction(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM password_reset_links").fetchone()[0] == 0


@pytest.mark.parametrize(
    ("changes", "available"),
    [
        ({}, True),
        ({"smtp_host": ""}, False),
        ({"smtp_sender": ""}, False),
        ({"master_key": ""}, False),
        ({"public_url": ""}, False),
        ({"public_url": "http://192.0.2.1"}, False),
        ({"public_url": "http://localhost:8000"}, True),
        ({"public_url": "https://host.test/path"}, False),
        ({"smtp_starttls": False}, False),
    ],
)
def test_availability_is_configuration_only(
    tmp_path: Path, changes: dict[str, object], available: bool
) -> None:
    container = build_container(configured(tmp_path / "test.db", **changes))
    client = TestClient(create_app(container))
    assert client.get("/api/v1/setup").json()["password_reset_available"] is available
    response = client.post(REQUEST, json={"email": "unknown@example.test"})
    assert response.status_code == (202 if available else 503)
    private(response)


@pytest.mark.parametrize("settings_kind", ["lan", "keyless", "removed-smtp"])
def test_administrator_links_complete_without_email_origin_or_master_key(
    tmp_path: Path, settings_kind: str
) -> None:
    path = tmp_path / "test.db"
    container = build_container(configured(path))
    client = TestClient(create_app(container))
    sign_in(client)
    token = issued(container, path)
    changes: dict[str, object] = (
        {"public_url": "http://192.0.2.1"}
        if settings_kind == "lan"
        else {"master_key": ""}
        if settings_kind == "keyless"
        else {"smtp_host": ""}
    )
    client = TestClient(create_app(build_container(configured(path, **changes))))
    checked = client.post(CHECK, json={"token": token})
    assert checked.json() == {"usable": True}
    completed = client.post(COMPLETE, json={"token": token, "password": "a new long password"})
    assert completed.status_code == 204
    private(checked)
    private(completed)
    assert client.get("/api/v1/session").json()["authenticated"] is False


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        (REQUEST, {"email": "not-an-email"}),
        (REQUEST, {"email": "a" * 242 + "@example.test"}),
        (CHECK, {"token": "secret" * 22}),
        (CHECK, {"token": "secret-é"}),
        (COMPLETE, {"token": "private-token", "password": "tiny-secret"}),
        (COMPLETE, {"token": "private-token", "password": "p" * 1025}),
    ],
)
def test_validation_is_private_and_precedes_storage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path: str, payload: dict[str, str]
) -> None:
    container = build_container(configured(tmp_path / "test.db"))
    monkeypatch.setattr(
        container.administration.check_password_reset.links,
        "owner",
        Mock(side_effect=AssertionError("storage before validation")),
    )
    response = TestClient(create_app(container)).post(path, json=payload)
    assert response.status_code == 422
    private(response)
    for secret in payload.values():
        assert secret not in response.text


@pytest.mark.parametrize("length", [8192, 8193])
@pytest.mark.parametrize(
    ("target", "payload", "accepted"),
    [
        (REQUEST, {"email": "unknown@example.test"}, 202),
        (CHECK, {"token": "forged"}, 200),
        (COMPLETE, {"token": "forged", "password": "a new long password"}, 410),
    ],
)
@pytest.mark.parametrize("content_length", [None, "1", "99999"])
def test_streamed_body_limit_precedes_parser(
    tmp_path: Path,
    length: int,
    content_length: str | None,
    target: str,
    payload: dict[str, str],
    accepted: int,
) -> None:
    app = create_app(build_container(configured(tmp_path / "test.db")))
    data = json.dumps(payload).encode().ljust(length)
    headers = [(b"content-type", b"application/json")]
    if content_length:
        headers.append((b"content-length", content_length.encode()))
    messages: list[Message] = []
    pieces = [data[:100], data[100:8000], data[8000:]]

    async def receive() -> Message:
        chunk = pieces.pop(0)
        return {"type": "http.request", "body": chunk, "more_body": bool(pieces)}

    async def send(message: Message) -> None:
        messages.append(message)

    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": target,
        "raw_path": target.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("192.0.2.1", 1234),
        "server": ("test", 80),
    }
    asyncio.run(app(scope, receive, send))
    assert messages[0]["status"] == (accepted if length == 8192 else 413)
    response_headers = dict(messages[0]["headers"])
    assert response_headers[b"cache-control"] == b"no-store"
    assert response_headers[b"referrer-policy"] == b"no-referrer"


@pytest.mark.parametrize("master_key", ["", KEY])
def test_valid_completion_budget_is_checked_before_lookup_and_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, master_key: str
) -> None:
    path = tmp_path / "test.db"
    container = build_container(Settings(path, master_key=master_key))
    client = TestClient(create_app(container))
    sign_in(client)
    token = issued(container, path)
    reset = container.administration.reset_password
    # Keep one valid proof for all ten admitted attempts, representing a race lost at commit.
    monkeypatch.setattr(reset.links, "reset", Mock(return_value=None))
    hashed = Mock(return_value="synthetic-hash")
    monkeypatch.setattr(reset.passwords, "hash", hashed)
    for _ in range(10):
        assert (
            client.post(
                COMPLETE, json={"token": token, "password": "a new long password"}
            ).status_code
            == 410
        )
    monkeypatch.setattr(
        reset.links, "owner", Mock(side_effect=AssertionError("lookup after throttle"))
    )
    refused = client.post(COMPLETE, json={"token": token, "password": "a new long password"})
    assert refused.status_code == 429
    assert refused.json()["code"] == "reset_network_throttled"
    assert hashed.call_count == 10
    assert int(refused.headers["retry-after"]) > 0
    private(refused)


@pytest.mark.parametrize("failure", ["read", "write", "admission"])
def test_storage_failures_are_safe_and_completion_is_atomic(tmp_path: Path, failure: str) -> None:
    path = tmp_path / "test.db"
    container = build_container(Settings(path))
    client = TestClient(create_app(container), raise_server_exceptions=False)
    sign_in(client)
    token = issued(container, path)
    original_hash = container.identity.users.password_hash(OTHER_USER)
    session = session_for(path, OTHER_USER)
    with transaction(path) as connection:
        if failure == "read":
            connection.execute("ALTER TABLE password_reset_links RENAME TO hidden_reset_links")
        elif failure == "write":
            connection.execute(
                "CREATE TRIGGER refuse_session_delete BEFORE DELETE ON user_sessions "
                "BEGIN SELECT RAISE(ABORT, 'private-sqlite-fault'); END"
            )
        else:
            # Master Key enables durable admission even when SMTP is absent.
            container = build_container(Settings(path, master_key=KEY))
            client = TestClient(create_app(container), raise_server_exceptions=False)
            connection.execute("DROP TABLE reset_request_attempts")
    response = client.post(COMPLETE, json={"token": token, "password": "private-reset-password"})
    assert (response.status_code, response.json()["code"]) == (503, "reset_storage_unavailable")
    assert "private" not in response.text
    private(response)
    assert container.identity.users.password_hash(OTHER_USER) == original_hash
    assert container.identity.sessions.user_of(session) == OTHER_USER


@pytest.mark.parametrize("path", ["/forgot-password", "/password-reset"])
def test_reset_pages_are_private_and_read_only(tmp_path: Path, path: str) -> None:
    client = TestClient(create_app(build_container(Settings(tmp_path / "test.db"))))
    response = client.get(path)
    assert response.status_code == 200
    private(response)


@pytest.mark.parametrize("master_key", ["", KEY])
def test_reset_throttles_are_independent_of_sign_in_and_forwarded_headers(
    tmp_path: Path, master_key: str
) -> None:
    path = tmp_path / "test.db"
    container = build_container(Settings(path, master_key=master_key))
    client = TestClient(create_app(container))
    sign_in(client)
    token = issued(container, path)
    client.delete("/api/v1/session")
    for _ in range(5):
        assert (
            client.post(
                "/api/v1/session", json={"email": ADMIN_EMAIL, "password": "wrong"}
            ).status_code
            == 401
        )
    assert client.post(CHECK, json={"token": token}).json() == {"usable": True}
    for _ in range(20):
        assert client.post(CHECK, json={"token": "forged"}).json() == {"usable": False}
    refused = client.post(
        CHECK,
        json={"token": token},
        headers={"X-Forwarded-For": "192.0.2.47", "Forwarded": "for=192.0.2.47"},
    )
    assert refused.status_code == 429
    private(refused)
    # The ordinary sign-in budget is still its own, including its stable response code.
    blocked_signin = client.post(
        "/api/v1/session", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    assert (blocked_signin.status_code, blocked_signin.json()["code"]) == (429, "sign_in_throttled")


def test_ipv6_token_rotation_shares_one_network_allowance(tmp_path: Path) -> None:
    container = build_container(Settings(tmp_path / "test.db", master_key=KEY))
    app = create_app(container)
    for index in range(20):
        client = TestClient(app, client=(f"2001:db8:1234:abcd::{index:x}", 1234))
        assert client.post(CHECK, json={"token": "forged"}).status_code == 200
    same = TestClient(app, client=("2001:db8:1234:abcd::ffff", 1234))
    other = TestClient(app, client=("2001:db8:1234:abce::1", 1234))
    assert same.post(CHECK, json={"token": "forged"}).status_code == 429
    assert other.post(CHECK, json={"token": "forged"}).status_code == 200


@pytest.mark.parametrize(("length", "status"), [(254, 202), (255, 422)])
def test_normalized_email_bound_retains_existing_normalization(
    tmp_path: Path, length: int, status: int
) -> None:
    container = build_container(configured(tmp_path / "test.db"))
    client = TestClient(create_app(container))
    email = "A" * (length - len("@example.test")) + "@Example.test"
    assert client.post(REQUEST, json={"email": f"  {email}  "}).status_code == status


@pytest.mark.parametrize(("length", "status"), [(128, 200), (129, 422)])
def test_token_size_is_reset_only(tmp_path: Path, length: int, status: int) -> None:
    client = TestClient(create_app(build_container(Settings(tmp_path / "test.db"))))
    assert client.post(CHECK, json={"token": "t" * length}).status_code == status
    assert client.post("/api/v1/invitations/check", json={"token": "t" * length}).status_code == 200


@pytest.mark.parametrize(("length", "status"), [(11, 422), (12, 204), (1024, 204), (1025, 422)])
def test_new_password_size_precedes_hashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, length: int, status: int
) -> None:
    path = tmp_path / "test.db"
    container = build_container(Settings(path))
    client = TestClient(create_app(container))
    sign_in(client)
    token = issued(container, path)
    hashed = Mock(return_value="new-hash")
    monkeypatch.setattr(container.administration.reset_password.passwords, "hash", hashed)
    response = client.post(COMPLETE, json={"token": token, "password": "p" * length})
    assert response.status_code == status
    assert hashed.call_count == (1 if status == 204 else 0)


def test_disabled_target_issuance_has_stable_conflict_and_no_proof(tmp_path: Path) -> None:
    path = tmp_path / "test.db"
    container = build_container(Settings(path))
    client = TestClient(create_app(container))
    sign_in(client)
    add_user(path, OTHER_USER, role="user", state="disabled")
    response = client.post(f"/api/v1/users/{OTHER_USER.value}/password-reset-links")
    assert (response.status_code, response.json()["code"]) == (409, "user_disabled")
    private(response)
    with transaction(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM password_reset_links").fetchone()[0] == 0


@pytest.mark.parametrize("change", ["demote", "disable"])
def test_issuer_permission_race_is_private_and_preserves_existing_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    path = tmp_path / "test.db"
    container = build_container(Settings(path))
    client = TestClient(create_app(container), raise_server_exceptions=False)
    sign_in(client)
    token = issued(container, path)
    add_user(path, UserId("second-administrator"))
    links = container.administration.issue_password_reset.links
    issue = links.issue
    with transaction(path) as connection:
        before = [tuple(row) for row in connection.execute("SELECT * FROM password_reset_links")]

    def changed_before_lock(user: UserId, actor: UserId, at: datetime) -> IssuedLink:
        if change == "demote":
            container.identity.users.set_role(actor, Role.USER)
        else:
            container.identity.users.set_state(actor, UserState.DISABLED)
        return issue(user, actor, at)

    monkeypatch.setattr(links, "issue", changed_before_lock)
    response = client.post(f"/api/v1/users/{OTHER_USER.value}/password-reset-links")
    assert response.status_code == 403
    assert response.json()["code"] == "administrator_required"
    private(response)
    with transaction(path) as connection:
        assert [
            tuple(row) for row in connection.execute("SELECT * FROM password_reset_links")
        ] == before
    assert client.post(CHECK, json={"token": token}).json() == {"usable": True}


@pytest.mark.parametrize("boundary", ["request", "completion"])
def test_committed_admission_proceeds_when_only_cleanup_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    path = tmp_path / "test.db"
    container = build_container(configured(path))
    client = TestClient(create_app(container), raise_server_exceptions=False)
    sign_in(client)
    token = issued(container, path)
    attempts = container.reset_admission.attempts
    assert attempts is not None
    purge = attempts.purge
    purged = Mock()

    def locked_purge(before: datetime, limit: int) -> int:
        with transaction(path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM reset_request_attempts WHERE boundary = ?", (boundary,)
                ).fetchone()[0]
                == 1
            )
            purged()
            # Only this separate cleanup transaction fails; the allowance is durable already.
            return purge(before, limit)

    monkeypatch.setattr(attempts, "purge", locked_purge)
    worker = container.identity_mail_worker
    assert worker is not None
    submit = Mock(return_value=True)
    monkeypatch.setattr(worker, "submit_reset", submit)
    reset = container.administration.reset_password
    original_hash = reset.passwords.hash

    def hash_after_cleanup(password: str) -> str:
        purged.assert_called_once_with()
        return original_hash(password)

    hashed = Mock(side_effect=hash_after_cleanup)
    monkeypatch.setattr(reset.passwords, "hash", hashed)
    if boundary == "request":
        response = client.post(REQUEST, json={"email": "unknown@example.test"})
        assert (response.status_code, response.json()) == (202, {"accepted": True})
        suppressed = client.post(REQUEST, json={"email": "unknown@example.test"})
        assert (suppressed.status_code, suppressed.json()) == (202, {"accepted": True})
        private(suppressed)
        submit.assert_called_once()
        hashed.assert_not_called()
    else:
        response = client.post(COMPLETE, json={"token": token, "password": "a new long password"})
        assert response.status_code == 204
        hashed.assert_called_once_with("a new long password")
        assert client.post(CHECK, json={"token": token}).json() == {"usable": False}
        submit.assert_not_called()
    private(response)
    purged.assert_called_once_with()
    with transaction(path) as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM reset_request_attempts WHERE boundary = ?", (boundary,)
            ).fetchone()[0]
            == 1
        )
        assert connection.execute("SELECT COUNT(*) FROM password_reset_links").fetchone()[0] == 1


@pytest.mark.parametrize("boundary", ["request", "completion"])
def test_admission_decision_failure_precedes_queue_lookup_and_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    path = tmp_path / "test.db"
    container = build_container(configured(path))
    worker = container.identity_mail_worker
    assert worker is not None
    work = Mock(side_effect=AssertionError("work before admission"))
    monkeypatch.setattr(worker, "submit_reset", work)
    monkeypatch.setattr(container.administration.reset_password.passwords, "hash", work)
    monkeypatch.setattr(container.administration.reset_password.links, "owner", work)
    with transaction(path) as connection:
        connection.execute("DROP TABLE reset_request_attempts")
    client = TestClient(create_app(container), raise_server_exceptions=False)
    response = client.post(
        REQUEST if boundary == "request" else COMPLETE,
        json={"email": "unknown@example.test"}
        if boundary == "request"
        else {"token": "forged", "password": "a new long password"},
    )
    assert (response.status_code, response.json()["code"]) == (503, "reset_storage_unavailable")
    private(response)
    work.assert_not_called()


def test_admin_issuance_and_bearer_token_without_proof_are_private(tmp_path: Path) -> None:
    path = tmp_path / "test.db"
    container = build_container(Settings(path))
    client = TestClient(create_app(container))
    sign_in(client)
    add_user(path, OTHER_USER, role="user")
    response = client.post(f"/api/v1/users/{OTHER_USER.value}/password-reset-links")
    assert response.status_code == 201
    private(response)
    token = response.json()["token"]
    before = client.post(CHECK, json={"token": token})
    integration = client.post("/api/v1/integration-tokens", json={"name": "Probe"}).json()["token"]
    client.delete("/api/v1/session")
    refused = client.post(
        COMPLETE,
        json={"token": "forged", "password": "a new long password"},
        headers={"Authorization": f"Bearer {integration}"},
    )
    assert refused.status_code == 410
    assert before.json() == {"usable": True}
    assert client.post(CHECK, json={"token": token}).json() == {"usable": True}
    private(refused)


def test_every_storage_failure_has_the_same_safe_http_response(tmp_path: Path) -> None:
    path = tmp_path / "test.db"
    container = build_container(Settings(path))
    client = TestClient(create_app(container), raise_server_exceptions=False)
    with transaction(path) as connection:
        connection.execute("DROP TABLE password_reset_links")
    proof_failure = client.post(CHECK, json={"token": "private-token"})
    container = build_container(Settings(tmp_path / "durable.db", master_key=KEY))
    with transaction(tmp_path / "durable.db") as connection:
        connection.execute("DROP TABLE reset_request_attempts")
    durable_client = TestClient(create_app(container), raise_server_exceptions=False)
    admission_failure = durable_client.post(CHECK, json={"token": "private-token"})
    assert proof_failure.status_code == admission_failure.status_code == 503
    assert proof_failure.json() == admission_failure.json()


@pytest.mark.parametrize("policy", ["only_me", "invitation_only"])
def test_availability_ignores_policy_and_readiness(tmp_path: Path, policy: str) -> None:
    path = tmp_path / "test.db"
    container = build_container(configured(path))
    client = TestClient(create_app(container))
    sign_in(client)
    assert client.put("/api/v1/registration", json={"policy": policy}).status_code == 200
    with transaction(path) as connection:
        connection.execute("DROP TABLE identity_email_readiness")
    assert client.get("/api/v1/setup").json()["password_reset_available"] is True
    assert client.post(REQUEST, json={"email": ADMIN_EMAIL}).status_code == 202


def test_invalid_reset_quota_does_not_block_correct_sign_in(tmp_path: Path) -> None:
    container = build_container(Settings(tmp_path / "test.db"))
    client = TestClient(create_app(container))
    sign_in(client)
    client.delete("/api/v1/session")
    for _ in range(20):
        assert client.post(CHECK, json={"token": "forged"}).status_code == 200
    assert client.post(CHECK, json={"token": "forged"}).status_code == 429
    signed_in = client.post(
        "/api/v1/session", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    assert signed_in.status_code == 200


def test_request_network_limit_is_account_independent(tmp_path: Path) -> None:
    container = build_container(configured(tmp_path / "test.db"))
    client = TestClient(create_app(container))
    for index in range(20):
        assert (
            client.post(REQUEST, json={"email": f"unknown-{index}@example.test"}).status_code == 202
        )
    refused = client.post(REQUEST, json={"email": ADMIN_EMAIL})
    assert (refused.status_code, refused.json()["code"]) == (429, "reset_network_throttled")
    assert int(refused.headers["retry-after"]) > 0
    private(refused)


def test_rejected_bodies_and_validation_never_log_or_echo_secrets(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    container = build_container(Settings(tmp_path / "test.db"))
    client = TestClient(create_app(container))
    token = "synthetic-private-token-é"
    password = "private password to keep out of diagnostics"
    with caplog.at_level("DEBUG"):
        invalid = client.post(COMPLETE, json={"token": token, "password": password})
        oversized = client.post(COMPLETE, content=(token + password).encode() * 300)
        malformed = client.post(
            REQUEST, content=b'{"email":"synthetic-private-email@example.test", broken}'
        )
    assert invalid.status_code == malformed.status_code == 422
    assert oversized.status_code == 413
    for secret in (token, password, "synthetic-private-email@example.test"):
        assert secret not in caplog.text
        assert all(secret not in response.text for response in (invalid, oversized, malformed))
