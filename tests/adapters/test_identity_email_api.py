"""Identity email is an administrator session capability with a nonsecret status."""

from dataclasses import replace
from pathlib import Path
from time import monotonic
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient

from calendar_sync.application.identity.identity_email import IdentityEmailSetup
from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import Adapters, Container, build_adapters, compose
from calendar_sync.domain.access import UserId, UserState
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.interfaces.api.app import create_app
from tests.adapters.test_identity_email_transport import configured
from tests.adapters.test_identity_mail_worker import BarrierSender
from tests.adapters.test_users_api import ADMIN
from tests.users import OTHER_USER, USER, add_user, session_for


def client_for(tmp_path: Path, **values: Any) -> tuple[TestClient, Adapters, Container]:
    settings = Settings(tmp_path / "identity.db", **values)
    adapters = build_adapters(settings)
    container = compose(settings, adapters)
    return TestClient(create_app(container)), adapters, container


def test_identity_email_routes_require_administrator_session(tmp_path: Path) -> None:
    client, _adapters, _ = client_for(tmp_path)
    for method, path in (
        ("GET", "/api/v1/identity-email"),
        ("POST", "/api/v1/identity-email/test"),
    ):
        assert client.request(method, path).status_code == 401
        assert (
            client.request(method, path, headers={"Authorization": "Bearer synthetic"}).status_code
            == 401
        )
    add_user(tmp_path / "identity.db", USER)
    add_user(tmp_path / "identity.db", OTHER_USER, role="user")
    client.cookies.set("calendar_sync_session", session_for(tmp_path / "identity.db", OTHER_USER))
    assert client.get("/api/v1/identity-email").status_code == 403
    assert client.post("/api/v1/identity-email/test").status_code == 403


def test_current_config_only_and_no_store(tmp_path: Path) -> None:
    client, _, _ = client_for(tmp_path)
    client.post("/api/v1/setup/admin", json=ADMIN)
    response = client.get("/api/v1/identity-email")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "configured": False,
        "unavailable_reason": "smtp_missing",
        "tested_at": None,
        "test_state": "idle",
    }


def test_identity_email_api_failures_are_safe(tmp_path: Path) -> None:
    client, _, _ = client_for(tmp_path)
    client.post("/api/v1/setup/admin", json=ADMIN)
    response = client.post("/api/v1/identity-email/test")
    assert response.status_code == 503
    assert response.json()["code"] == "identity_email_not_configured"
    assert response.headers["cache-control"] == "no-store"
    assert "retry-after" not in response.headers
    assert "admin@example.test" not in response.text


def test_open_remains_unavailable(tmp_path: Path) -> None:
    client, _, _ = client_for(tmp_path)
    client.post("/api/v1/setup/admin", json=ADMIN)
    assert client.put("/api/v1/registration", json={"policy": "open"}).status_code == 422
    schema = client.get("/api/openapi.json").json()
    assert schema["components"]["schemas"]["RegistrationRequest"]["properties"]["policy"][
        "enum"
    ] == ["only_me", "invitation_only"]


def live_client(tmp_path: Path) -> tuple[TestClient, Adapters, Container, BarrierSender]:
    settings = replace(configured(), database_path=tmp_path / "identity.db")
    adapters = build_adapters(settings)
    sender = BarrierSender()
    adapters = replace(adapters, identity_email=replace(adapters.identity_email, sender=sender))
    container = replace(
        compose(settings, adapters),
        scheduler=None,
        scheduler_watch=None,
        instant_dispatcher=None,
        watch_keeper=None,
    )
    return TestClient(create_app(container)), adapters, container, sender


def wait_for_state(client: TestClient, state: str) -> dict[str, Any]:
    deadline = monotonic() + 5
    while monotonic() < deadline:
        result: dict[str, Any] = client.get("/api/v1/identity-email").json()
        if result["test_state"] == state:
            return result
    raise AssertionError(f"Identity email did not reach {state}")


def test_queued_test_is_not_ready(tmp_path: Path) -> None:
    client, adapters, container, sender = live_client(tmp_path)
    with client:
        client.post("/api/v1/setup/admin", json=ADMIN)
        before = client.get("/api/v1/identity-email").json()
        assert before["configured"] is True
        assert before["tested_at"] is None
        queued = client.post("/api/v1/identity-email/test")
        assert queued.status_code == 202
        assert queued.content == b""
        assert queued.headers["cache-control"] == "no-store"
        assert sender.started.wait(5)
        sending = client.get("/api/v1/identity-email").json()
        assert sending["tested_at"] is None
        assert sending["test_state"] == "sending"
        sender.release.set()
        accepted = wait_for_state(client, "accepted")
        assert accepted["tested_at"] is not None
        assert sender.recipients == [ADMIN["email"]]
        # Successful proof belongs only to the current installation configuration.
        changed_adapters = replace(
            adapters,
            identity_email=replace(
                adapters.identity_email, setup=IdentityEmailSetup("changed", None)
            ),
        )
        changed = TestClient(
            create_app(compose(Settings(tmp_path / "identity.db"), changed_adapters))
        )
        changed.cookies.update(client.cookies)
        response = changed.get("/api/v1/identity-email")
        assert response.json()["tested_at"] is None
        assert response.headers["cache-control"] == "no-store"
        assert set(response.json()) == {
            "configured",
            "unavailable_reason",
            "tested_at",
            "test_state",
        }
    assert container.identity_mail_worker is not None
    assert not container.identity_mail_worker.running


def test_test_recipient_cannot_be_overridden(tmp_path: Path) -> None:
    client, adapters, _, sender = live_client(tmp_path)
    with client:
        setup = client.post("/api/v1/setup/admin", json=ADMIN)
        actor = UserId(setup.json()["user"]["id"])
        adapters.users.set_notification_email(actor, False)
        adapters.users.set_email(actor, "current@example.test")
        result = client.post(
            "/api/v1/identity-email/test", json={"recipient": "other@example.test"}
        )
        assert result.status_code == 202
        assert sender.started.wait(5)
        sender.release.set()
        wait_for_state(client, "accepted")
        assert sender.recipients == ["current@example.test"]


def test_busy_throttle_and_storage_failures_are_safe(tmp_path: Path) -> None:
    client, _adapters, _, sender = live_client(tmp_path)
    with client:
        client.post("/api/v1/setup/admin", json=ADMIN)
        first = client.post("/api/v1/identity-email/test")
        assert first.status_code == 202
        assert sender.started.wait(5)
        for _ in range(4):
            busy = client.post("/api/v1/identity-email/test")
            assert busy.status_code == 503
            assert busy.json()["code"] == "identity_email_queue_busy"
            assert "retry-after" not in busy.headers
        with transaction(tmp_path / "identity.db") as connection:
            count = connection.execute(
                "SELECT count(*) FROM identity_email_test_attempts"
            ).fetchone()
            assert count[0] == 1
        sender.release.set()
        wait_for_state(client, "accepted")
        for _ in range(2):
            assert client.post("/api/v1/identity-email/test").status_code == 202
            wait_for_state(client, "accepted")
        limited = client.post("/api/v1/identity-email/test")
        assert limited.status_code == 429
        assert limited.json()["code"] == "identity_email_test_throttled"
        assert 1 <= int(limited.headers["retry-after"]) <= 3600
        assert limited.headers["cache-control"] == "no-store"
        with transaction(tmp_path / "identity.db") as connection:
            connection.execute("DELETE FROM identity_email_readiness")
        failed = client.get("/api/v1/identity-email")
        assert failed.status_code == 503
        assert failed.json()["code"] == "identity_email_storage_unavailable"
        assert failed.headers["cache-control"] == "no-store"
        for response in (busy, limited, failed):
            assert "admin@example.test" not in response.text
            assert "mail.example.test" not in response.text
            assert "retry-after" not in failed.headers
        sender.release.set()


def test_disabled_sessions_and_authenticated_administrator_races_are_refused(
    tmp_path: Path,
) -> None:
    client, adapters, _container = client_for(tmp_path)
    client.post("/api/v1/setup/admin", json=ADMIN)
    actor = adapters.users.list()[0]
    # Established sessions are revoked by disabling, consistently with other routes.
    add_user(tmp_path / "identity.db", USER)
    adapters.users.set_state(actor.id, UserState.DISABLED)
    assert client.get("/api/v1/identity-email").status_code == 401
    adapters.users.set_state(actor.id, UserState.ACTIVE)
    # Simulate a dependency that authenticated just before the User was disabled.
    disabled = replace(actor, state=UserState.DISABLED)
    for method, path in (
        ("GET", "/api/v1/identity-email"),
        ("POST", "/api/v1/identity-email/test"),
    ):
        with patch.object(adapters.users, "get", side_effect=[actor, disabled]):
            response = client.request(method, path)
        assert response.status_code == 403
        assert response.json()["code"] == "administrator_required"


def test_storage_failure_during_admission_is_safe(tmp_path: Path) -> None:
    client, _, _, sender = live_client(tmp_path)
    with client:
        client.post("/api/v1/setup/admin", json=ADMIN)
        with transaction(tmp_path / "identity.db") as connection:
            connection.execute("DROP TABLE identity_email_test_attempts")
        response = client.post("/api/v1/identity-email/test")
        assert response.status_code == 503
        assert response.json()["code"] == "identity_email_storage_unavailable"
        assert "retry-after" not in response.headers
        assert response.headers["cache-control"] == "no-store"
        assert not sender.started.is_set()


def test_repeated_lifespan_drops_old_smtp_completion(tmp_path: Path) -> None:
    client, _, container, sender = live_client(tmp_path)
    with client:
        client.post("/api/v1/setup/admin", json=ADMIN)
        assert client.post("/api/v1/identity-email/test").status_code == 202
        assert sender.started.wait(5)
    assert not sender.finished.is_set()
    assert container.identity_mail_worker is not None
    assert not container.identity_mail_worker.running
    # TestClient opens a new event loop for the same application/worker instance.
    with client:
        assert client.get("/api/v1/identity-email").json()["test_state"] == "idle"
        sender.release.set()
        assert sender.finished.wait(5)
        old = client.get("/api/v1/identity-email").json()
        assert old["tested_at"] is None
        assert old["test_state"] == "idle"
        assert client.post("/api/v1/identity-email/test").status_code == 202
        assert wait_for_state(client, "accepted")["tested_at"] is not None
    assert len(sender.recipients) == 2
