"""Setup, sign-in by email, the add-email step, and a User's own credentials over the Web API."""

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import build_container
from calendar_sync.infrastructure.persistence.sqlite import initialize_database
from calendar_sync.infrastructure.security import hash_password
from calendar_sync.interfaces.api.app import create_app
from tests.adapters.test_user_migration import database_at_version

EMAIL = "admin@example.test"
PASSWORD = "correct horse battery staple"


def _client(database: Path) -> TestClient:
    return TestClient(create_app(build_container(Settings(database))))


def test_setup_asks_for_an_email_and_a_password_and_signs_the_administrator_in(
    tmp_path: Path,
) -> None:
    with _client(tmp_path / "test.db") as client:
        before = client.get("/api/v1/setup").json()
        refused = client.post("/api/v1/setup/admin", json={"email": "nope", "password": PASSWORD})
        created = client.post("/api/v1/setup/admin", json={"email": EMAIL, "password": PASSWORD})
        session = client.get("/api/v1/session").json()
        after = client.get("/api/v1/setup").json()
        again = client.post("/api/v1/setup/admin", json={"email": EMAIL, "password": PASSWORD})

    assert before == {"administrator_configured": False, "password_only_sign_in": False}
    assert (refused.status_code, refused.json()["code"]) == (422, "invalid_email")
    assert created.status_code == 200
    assert session["authenticated"] is True
    assert session["user"]["email"] == EMAIL
    assert session["user"]["role"] == "installation_administrator"
    assert after == {"administrator_configured": True, "password_only_sign_in": False}
    assert (again.status_code, again.json()["code"]) == (409, "setup_complete")


def test_a_user_signs_in_by_email_and_password(tmp_path: Path) -> None:
    with _client(tmp_path / "test.db") as client:
        client.post("/api/v1/setup/admin", json={"email": EMAIL, "password": PASSWORD})
        client.delete("/api/v1/session")
        wrong = client.post("/api/v1/session", json={"email": EMAIL, "password": "wrong password"})
        signed_out = client.get("/api/v1/dashboard").status_code
        right = client.post(
            "/api/v1/session", json={"email": "Admin@Example.test", "password": PASSWORD}
        )
        dashboard = client.get("/api/v1/dashboard").status_code

    assert (wrong.status_code, wrong.json()["code"]) == (401, "incorrect_credentials")
    assert signed_out == 401
    assert right.json()["user"]["email"] == EMAIL
    assert dashboard == 200


def test_repeated_failed_sign_ins_are_throttled(tmp_path: Path) -> None:
    with _client(tmp_path / "test.db") as client:
        client.post("/api/v1/setup/admin", json={"email": EMAIL, "password": PASSWORD})
        client.delete("/api/v1/session")
        failures = [
            client.post("/api/v1/session", json={"email": EMAIL, "password": "wrong password"})
            for _ in range(5)
        ]
        throttled = client.post("/api/v1/session", json={"email": EMAIL, "password": PASSWORD})

    assert {failure.status_code for failure in failures} == {401}
    assert (throttled.status_code, throttled.json()["code"]) == (429, "sign_in_throttled")
    assert int(throttled.headers["retry-after"]) > 0
    assert throttled.json()["params"]["retry_after"] > 0


def test_the_upgraded_administrator_signs_in_by_password_until_they_add_an_email(
    tmp_path: Path,
) -> None:
    database = tmp_path / "test.db"
    database_at_version(database, 20)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO installation_admin VALUES (1, ?, '2026-01-01')", (hash_password(PASSWORD),)
        )
    initialize_database(database)

    with _client(database) as client:
        setup = client.get("/api/v1/setup").json()
        signed_in = client.post("/api/v1/session", json={"email": None, "password": PASSWORD})
        session = client.get("/api/v1/session").json()
        blocked = client.get("/api/v1/dashboard")
        added = client.put("/api/v1/account/email", json={"email": EMAIL})
        dashboard = client.get("/api/v1/dashboard").status_code
        client.delete("/api/v1/session")
        password_only = client.post("/api/v1/session", json={"password": PASSWORD})
        by_email = client.post("/api/v1/session", json={"email": EMAIL, "password": PASSWORD})
        after = client.get("/api/v1/setup").json()

    assert setup == {"administrator_configured": True, "password_only_sign_in": True}
    assert signed_in.status_code == 200
    assert session["user"]["email"] is None
    assert (blocked.status_code, blocked.json()["code"]) == (403, "email_required")
    assert added.json()["email"] == EMAIL
    assert dashboard == 200
    assert password_only.status_code == 401
    assert by_email.status_code == 200
    assert after["password_only_sign_in"] is False


def test_a_user_changes_their_email_and_password_with_their_current_password(
    tmp_path: Path,
) -> None:
    with _client(tmp_path / "test.db") as client:
        client.post("/api/v1/setup/admin", json={"email": EMAIL, "password": PASSWORD})
        unconfirmed = client.put("/api/v1/account/email", json={"email": "new@example.test"})
        changed = client.put(
            "/api/v1/account/email", json={"email": "new@example.test", "password": PASSWORD}
        )
        weak = client.put(
            "/api/v1/account/password", json={"current_password": PASSWORD, "new_password": "short"}
        )
        renewed = client.put(
            "/api/v1/account/password",
            json={"current_password": PASSWORD, "new_password": "another long password"},
        )
        still_signed_in = client.get("/api/v1/dashboard").status_code
        client.delete("/api/v1/session")
        signed_in = client.post(
            "/api/v1/session",
            json={"email": "new@example.test", "password": "another long password"},
        )

    assert (unconfirmed.status_code, unconfirmed.json()["code"]) == (403, "incorrect_password")
    assert changed.json()["email"] == "new@example.test"
    assert weak.status_code == 422
    assert renewed.status_code == 204
    assert still_signed_in == 200
    assert signed_in.status_code == 200
