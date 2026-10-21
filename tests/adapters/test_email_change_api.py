"""Signed-in email changes stay private, bounded, and scoped to their owner."""

import asyncio
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from starlette.types import Message, Scope

from calendar_sync.application.identity.email_change_admission import (
    EmailChangeStorageUnavailable,
    EmailChangeThrottled,
)
from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import Container, build_container
from calendar_sync.infrastructure.persistence.migrations import initialize_database
from calendar_sync.infrastructure.security import CredentialCipher, hash_password
from calendar_sync.interfaces.api.app import create_app
from calendar_sync.interfaces.api.dependencies import SESSION_COOKIE
from tests.adapters.test_user_migration import database_at_version
from tests.users import ADMIN_EMAIL, ADMIN_PASSWORD, OTHER_USER, add_user, session_for, sign_in

BASE = "/api/v1/account/email-change"
LEGACY = "/api/v1/account/email"
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


def private(response: object) -> None:
    headers = response.headers  # type: ignore[attr-defined]
    assert headers["cache-control"] == "no-store"
    assert headers["referrer-policy"] == "no-referrer"


def owner_client(path: Path, **changes: object) -> tuple[TestClient, Container]:
    container = build_container(configured(path, **changes))
    client = TestClient(create_app(container))
    sign_in(client)
    return client, container


def test_session_guard_and_legacy_direct_bypass(tmp_path: Path) -> None:
    path = tmp_path / "test.db"
    client, _ = owner_client(path)
    client.cookies.clear()
    for method, url, kwargs in (
        ("get", BASE, {}),
        ("post", BASE, {"json": {"email": "next@example.test", "password": ADMIN_PASSWORD}}),
        ("delete", BASE, {"params": {"request_id": "unknown"}}),
        ("post", BASE + "/check", {"json": {"token": "forged"}}),
        ("post", BASE + "/confirm", {"json": {"token": "forged", "password": ADMIN_PASSWORD}}),
    ):
        response = getattr(client, method)(
            url, **kwargs, headers={"Authorization": "Bearer forged"}
        )
        assert (response.status_code, response.json()["code"]) == (401, "session_required")
        private(response)
    sign_in(client)
    status = client.get(BASE)
    assert status.json() == {"mode": "verified", "reason": None, "pending": None}
    direct = client.put(LEGACY, json={"email": "next@example.test", "password": ADMIN_PASSWORD})
    assert (direct.status_code, direct.json()["code"]) == (
        409,
        "email_change_verification_required",
    )
    private(direct)
    assert client.get("/api/v1/session").json()["user"]["email"] == ADMIN_EMAIL


def test_request_owner_cancel_and_confirm_password_twice(tmp_path: Path) -> None:
    path = tmp_path / "test.db"
    client, container = owner_client(path)
    wrong = client.post(BASE, json={"email": "next@example.test", "password": "wrong"})
    assert (wrong.status_code, wrong.json()["code"]) == (403, "incorrect_password")
    assert client.get(BASE).json()["pending"] is None
    requested = client.post(BASE, json={"email": "NEXT@example.test", "password": ADMIN_PASSWORD})
    assert (requested.status_code, requested.json()) == (202, {"accepted": True})
    pending = client.get(BASE).json()["pending"]
    assert pending["email"] == "next@example.test"
    assert pending["id"]
    assert pending["expires_at"]
    other = OTHER_USER
    add_user(path, other, role="user")
    other_client = TestClient(create_app(container))
    other_client.cookies.set(SESSION_COOKIE, session_for(path, other))
    cancel_other = other_client.delete(BASE, params={"request_id": pending["id"]})
    assert cancel_other.status_code == 204
    assert other_client.get(BASE).json()["pending"] is None
    assert client.get(BASE).json()["pending"] == pending
    assert client.delete(BASE, params={"request_id": "stale"}).status_code == 204
    assert client.get(BASE).json()["pending"] == pending
    assert client.delete(BASE, params={"request_id": pending["id"]}).status_code == 204
    assert client.delete(BASE, params={"request_id": pending["id"]}).status_code == 204
    assert client.get(BASE).json()["pending"] is None


def test_proof_check_confirm_and_session_refresh(tmp_path: Path) -> None:
    path = tmp_path / "test.db"
    client, container = owner_client(path)
    assert client.post(BASE + "/check", json={"token": "forged"}).json() == {"usable": False}
    gone = client.post(BASE + "/confirm", json={"token": "forged", "password": ADMIN_PASSWORD})
    assert (gone.status_code, gone.json()["code"]) == (410, "email_change_proof_unusable")
    client.post(BASE, json={"email": "next@example.test", "password": ADMIN_PASSWORD})
    pending = client.get(BASE).json()["pending"]
    prepared = container.identity_email.email_changes.show.proofs.prepare(pending["id"])
    assert prepared is not None
    token = prepared.token
    add_user(path, OTHER_USER, role="user")
    other_client = TestClient(create_app(container))
    other_client.cookies.set(SESSION_COOKIE, session_for(path, OTHER_USER))
    assert other_client.post(BASE + "/check", json={"token": token}).json() == {"usable": False}
    wrong_owner = other_client.post(
        BASE + "/confirm", json={"token": token, "password": ADMIN_PASSWORD}
    )
    assert (wrong_owner.status_code, wrong_owner.json()["code"]) == (
        410,
        "email_change_proof_unusable",
    )
    check = client.post(BASE + "/check", json={"token": token})
    assert check.json() == {"usable": True}
    bad = client.post(BASE + "/confirm", json={"token": token, "password": "wrong"})
    assert (bad.status_code, bad.json()["code"]) == (403, "incorrect_password")
    assert client.post(BASE + "/check", json={"token": token}).json() == {"usable": True}
    done = client.post(BASE + "/confirm", json={"token": token, "password": ADMIN_PASSWORD})
    assert done.status_code == 204
    private(done)
    assert client.get("/api/v1/session").json()["user"]["email"] == "next@example.test"
    assert client.post(BASE + "/check", json={"token": token}).json() == {"usable": False}


def test_taken_address_stays_generic_until_confirmation(tmp_path: Path) -> None:
    path = tmp_path / "test.db"
    client, container = owner_client(path)
    add_user(path, OTHER_USER, email="taken@example.test", role="user")
    requested = client.post(BASE, json={"email": "TAKEN@example.test", "password": ADMIN_PASSWORD})
    assert (requested.status_code, requested.json()) == (202, {"accepted": True})
    pending = client.get(BASE).json()["pending"]
    prepared = container.identity_email.email_changes.show.proofs.prepare(pending["id"])
    assert prepared is not None
    refused = client.post(
        BASE + "/confirm", json={"token": prepared.token, "password": ADMIN_PASSWORD}
    )
    assert (refused.status_code, refused.json()["code"]) == (409, "email_change_unavailable")
    assert "taken@example.test" not in refused.text
    assert client.get("/api/v1/session").json()["user"]["email"] == ADMIN_EMAIL
    private(requested)
    private(refused)


def test_upgraded_first_administrator_can_add_email_in_restricted_session(tmp_path: Path) -> None:
    path = tmp_path / "test.db"
    database_at_version(path, 20)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO installation_admin VALUES (1, ?, '2026-01-01')",
            (hash_password(ADMIN_PASSWORD),),
        )
    initialize_database(path)
    client = TestClient(create_app(build_container(configured(path))))
    signed_in = client.post("/api/v1/session", json={"email": None, "password": ADMIN_PASSWORD})
    assert signed_in.status_code == 200
    blocked = client.get(BASE)
    assert (blocked.status_code, blocked.json()["code"]) == (403, "email_required")
    added = client.put(LEGACY, json={"email": ADMIN_EMAIL})
    assert (added.status_code, added.json()["email"]) == (200, ADMIN_EMAIL)
    private(blocked)
    private(added)
    later = client.put(LEGACY, json={"email": "next@example.test", "password": ADMIN_PASSWORD})
    assert (later.status_code, later.json()["code"]) == (
        409,
        "email_change_verification_required",
    )


def test_pending_proof_blocks_direct_fallback_until_owner_cancels(tmp_path: Path) -> None:
    path = tmp_path / "test.db"
    client, _ = owner_client(path)
    assert (
        client.post(
            BASE, json={"email": "next@example.test", "password": ADMIN_PASSWORD}
        ).status_code
        == 202
    )
    pending = client.get(BASE).json()["pending"]
    session = client.cookies.get(SESSION_COOKIE)
    assert session is not None
    offline = TestClient(create_app(build_container(Settings(path, master_key=KEY))))
    offline.cookies.set(SESSION_COOKIE, session)
    assert offline.get(BASE).json()["mode"] == "direct"
    blocked = offline.put(LEGACY, json={"email": "direct@example.test", "password": ADMIN_PASSWORD})
    assert (blocked.status_code, blocked.json()["code"]) == (409, "email_change_unavailable")
    private(blocked)
    assert offline.delete(BASE, params={"request_id": pending["id"]}).status_code == 204
    changed = offline.put(LEGACY, json={"email": "direct@example.test", "password": ADMIN_PASSWORD})
    assert (changed.status_code, changed.json()["email"]) == (200, "direct@example.test")


def test_exact_field_limits_are_accepted(tmp_path: Path) -> None:
    client, _ = owner_client(tmp_path / "test.db")
    token = client.post(BASE + "/check", json={"token": "a" * 128})
    assert (token.status_code, token.json()) == (200, {"usable": False})
    address = "a" * 241 + "@example.test"
    assert len(address) == 254
    requested = client.post(BASE, json={"email": address, "password": ADMIN_PASSWORD})
    assert (requested.status_code, requested.json()) == (202, {"accepted": True})
    long_password = client.post(BASE, json={"email": address, "password": "p" * 1024})
    assert (long_password.status_code, long_password.json()["code"]) == (
        403,
        "incorrect_password",
    )


def test_confirmation_budget_precedes_proof_lookup_and_password_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, container = owner_client(tmp_path / "test.db")
    changes = container.identity_email.email_changes
    lookup = Mock(side_effect=AssertionError("proof lookup after exhausted allowance"))
    verify = Mock(side_effect=AssertionError("password hash after exhausted allowance"))
    monkeypatch.setattr(changes.show.proofs, "check", lookup)
    monkeypatch.setattr(changes.confirm.passwords, "verify", verify)
    monkeypatch.setattr(
        changes.confirm.admission,
        "admit_completion",
        Mock(side_effect=EmailChangeThrottled(37)),
    )
    response = client.post(BASE + "/confirm", json={"token": "forged", "password": ADMIN_PASSWORD})
    assert (response.status_code, response.json()["code"]) == (429, "email_change_throttled")
    assert response.headers["retry-after"] == "37"
    lookup.assert_not_called()
    verify.assert_not_called()
    private(response)


@pytest.mark.parametrize(
    ("changes", "mode", "reason"),
    [
        ({"smtp_host": "", "smtp_sender": ""}, "direct", None),
        ({"public_url": "http://192.0.2.1"}, "unavailable", "origin_insecure"),
        ({"smtp_starttls": False}, "unavailable", "smtp_security"),
    ],
)
def test_configuration_modes(
    tmp_path: Path, changes: dict[str, object], mode: str, reason: str | None
) -> None:
    client, _ = owner_client(tmp_path / "test.db", **changes)
    status = client.get(BASE)
    assert status.json() == {"mode": mode, "reason": reason, "pending": None}
    requested = client.post(BASE, json={"email": "next@example.test", "password": ADMIN_PASSWORD})
    assert requested.status_code == 503
    assert requested.json()["code"] == "email_change_configuration_required"
    assert requested.json()["params"] == {"reason": reason or "smtp_missing"}
    assert "smtp.example.test" not in requested.text
    private(requested)
    direct = client.put(LEGACY, json={"email": "next@example.test", "password": ADMIN_PASSWORD})
    assert direct.status_code == (200 if mode == "direct" else 503)
    private(direct)


@pytest.mark.parametrize(
    ("url", "method", "payload"),
    [
        (BASE, "post", {"email": "a" * 242 + "@example.test", "password": ADMIN_PASSWORD}),
        (BASE, "post", {"email": "next@example.test", "password": "p" * 1025}),
        (BASE + "/check", "post", {"token": "a" * 129}),
        (BASE + "/check", "post", {"token": "é"}),
        (BASE + "/confirm", "post", {"token": "a" * 129, "password": ADMIN_PASSWORD}),
        (BASE + "/confirm", "post", {"token": "a", "password": "p" * 1025}),
        (LEGACY, "put", {"email": "a" * 242 + "@example.test", "password": ADMIN_PASSWORD}),
        (LEGACY, "put", {"email": "next@example.test", "password": "p" * 1025}),
    ],
)
def test_validation_before_service_and_no_secret_echo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, url: str, method: str, payload: dict[str, str]
) -> None:
    client, container = owner_client(tmp_path / "test.db")
    monkeypatch.setattr(
        container.identity_email.email_changes.show.proofs,
        "pending",
        Mock(side_effect=AssertionError("lookup")),
    )
    response = getattr(client, method)(url, json=payload)
    assert response.status_code == 422
    private(response)
    for secret in payload.values():
        if len(secret) > 3:
            assert secret not in response.text


@pytest.mark.parametrize(
    ("method", "url"),
    [("POST", BASE), ("POST", BASE + "/check"), ("POST", BASE + "/confirm"), ("PUT", LEGACY)],
)
@pytest.mark.parametrize("length", [8192, 8193])
@pytest.mark.parametrize("content_length", [None, "1", "99999"])
def test_streamed_boundary_ignores_content_length(
    tmp_path: Path, method: str, url: str, length: int, content_length: str | None
) -> None:
    app = create_app(build_container(configured(tmp_path / "test.db")))
    data = b"{}".ljust(length)
    headers = [(b"content-type", b"application/json")]
    if content_length is not None:
        headers.append((b"content-length", content_length.encode()))
    pieces = [data[:100], data[100:8000], data[8000:]]
    messages: list[Message] = []

    async def receive() -> Message:
        chunk = pieces.pop(0)
        return {"type": "http.request", "body": chunk, "more_body": bool(pieces)}

    async def send(message: Message) -> None:
        messages.append(message)

    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": url,
        "raw_path": url.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("192.0.2.1", 1234),
        "server": ("test", 80),
    }
    asyncio.run(app(scope, receive, send))
    assert messages[0]["status"] == (401 if length == 8192 else 413)
    response_headers = dict(messages[0]["headers"])
    assert response_headers[b"cache-control"] == b"no-store"
    assert response_headers[b"referrer-policy"] == b"no-referrer"


def test_email_change_private_headers_on_every_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "test.db"
    client, container = owner_client(path)
    responses = [
        client.get("/email-change"),
        client.get(BASE),
        client.post(BASE + "/check", json={"token": "forged"}),
        client.post(BASE + "/confirm", json={"token": "forged", "password": ADMIN_PASSWORD}),
        client.post(BASE, json={"email": "next@example.test", "password": "wrong"}),
        client.post(BASE, json={"email": "bad", "password": ADMIN_PASSWORD}),
        client.put(LEGACY, json={"email": "next@example.test", "password": ADMIN_PASSWORD}),
    ]
    monkeypatch.setattr(
        container.identity_email.email_changes.request.admission,
        "admit_request",
        Mock(side_effect=EmailChangeThrottled(61)),
    )
    throttled = client.post(BASE, json={"email": "next@example.test", "password": ADMIN_PASSWORD})
    assert throttled.status_code == 429
    assert throttled.headers["retry-after"] == "61"
    responses.append(throttled)
    monkeypatch.setattr(
        container.identity_email.email_changes.show.proofs,
        "pending",
        Mock(side_effect=EmailChangeStorageUnavailable()),
    )
    responses.append(client.get(BASE))
    client.cookies.clear()
    responses.append(client.get(BASE))
    assert {answer.status_code for answer in responses} >= {200, 401, 403, 409, 410, 422, 429, 503}
    for response in responses:
        private(response)


def test_rejected_email_change_inputs_never_echo_or_log_secrets(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    client, _ = owner_client(tmp_path / "test.db")
    token = "synthetic-private-token-é"
    password = "synthetic-private-password"
    address = "synthetic-private-address@example.test"
    with caplog.at_level("DEBUG"):
        invalid = client.post(BASE + "/confirm", json={"token": token, "password": password})
        malformed = client.put(LEGACY, content=(f'{{"email":"{address}", broken}}').encode())
        oversized = client.post(BASE, content=(token + password).encode() * 300)
    assert (invalid.status_code, malformed.status_code, oversized.status_code) == (422, 422, 413)
    for response in (invalid, malformed, oversized):
        private(response)
        for secret in (token, password, address):
            assert secret not in response.text
    for secret in (token, password, address):
        assert secret not in caplog.text
