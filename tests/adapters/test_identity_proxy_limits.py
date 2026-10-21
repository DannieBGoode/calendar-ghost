"""Uvicorn resolves the peer before the real recovery routes apply network limits."""

import json
import threading
from pathlib import Path
from unittest.mock import Mock

import pytest
import uvicorn
from fastapi.testclient import TestClient

from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import build_container
from calendar_sync.domain.access import RegistrationPolicy
from calendar_sync.infrastructure.identity_email import IdentitySmtp
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.security import CredentialCipher
from calendar_sync.interfaces.api import app as api_app
from tests.users import ADMIN_EMAIL, add_user

ROOT = Path(__file__).resolve().parents[2]
CHECK = "/api/v1/password-resets/check"
PROXY = "192.0.2.10"


def proxy_client(path: Path, trusted: str, peer: str = PROXY) -> TestClient:
    container = build_container(Settings(path, master_key=CredentialCipher.generate_key()))
    config = uvicorn.Config(
        api_app.create_app(container),
        proxy_headers=True,
        forwarded_allow_ips=trusted,
        log_config=None,
    )
    config.load()
    return TestClient(config.loaded_app, client=(peer, 1234))


@pytest.mark.parametrize(("trusted", "peer"), [("", "127.0.0.1"), (PROXY, "192.0.2.11")])
@pytest.mark.parametrize("check", [CHECK, "/api/v1/registrations/check"])
def test_empty_or_untrusted_proxy_cannot_rotate_allowance(
    tmp_path: Path, trusted: str, peer: str, check: str
) -> None:
    client = proxy_client(tmp_path / "test.db", trusted, peer)
    for index in range(20):
        response = client.post(
            check,
            json={"token": "forged"},
            headers={"X-Forwarded-For": f"198.51.100.{index + 1}"},
        )
        assert response.status_code == 200
    assert (
        client.post(
            check,
            json={"token": "forged"},
            headers={"X-Forwarded-For": "203.0.113.1", "Forwarded": "for=203.0.113.2"},
        ).status_code
        == 429
    )


@pytest.mark.parametrize("trusted", [PROXY, "192.0.2.0/24"])
@pytest.mark.parametrize("ipv6", [False, True])
@pytest.mark.parametrize("check", [CHECK, "/api/v1/registrations/check"])
def test_trusted_proxy_separates_clients_and_groups_ipv6_by_64(
    tmp_path: Path, trusted: str, ipv6: bool, check: str
) -> None:
    client = proxy_client(tmp_path / "test.db", trusted)
    for index in range(20):
        address = f"2001:db8:1234:abcd::{index + 1:x}" if ipv6 else "198.51.100.1"
        assert (
            client.post(
                check, json={"token": "forged"}, headers={"X-Forwarded-For": address}
            ).status_code
            == 200
        )
    for address, expected in (
        ("2001:db8:1234:abcd::ffff" if ipv6 else "198.51.100.1", 429),
        ("2001:db8:1234:abce::1" if ipv6 else "198.51.100.2", 200),
    ):
        assert (
            client.post(
                check, json={"token": "forged"}, headers={"X-Forwarded-For": address}
            ).status_code
            == expected
        )


@pytest.mark.parametrize("registration", [False, True])
def test_forged_origin_headers_cannot_choose_identity_mail_origin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, registration: bool
) -> None:
    sent = threading.Event()
    bodies: list[str] = []

    def capture(_self: IdentitySmtp, _recipient: str, _subject: str, body: str) -> None:
        bodies.append(body)
        sent.set()

    monkeypatch.setattr(IdentitySmtp, "_send", capture)
    path = tmp_path / "test.db"
    container = build_container(
        Settings(
            path,
            master_key=CredentialCipher.generate_key(),
            smtp_host="smtp.example.test",
            smtp_sender="ghost@example.test",
            public_url="https://calendar.example.test",
        )
    )
    actor = add_user(path, email=ADMIN_EMAIL)
    if registration:
        with transaction(path) as connection:
            connection.execute(
                "UPDATE identity_email_readiness SET fingerprint = ?, tested_at = ?",
                (
                    container.registrations.check.fingerprint,
                    container.registrations.complete.clock.now().isoformat(),
                ),
            )
        container.administration.set_registration_policy.execute(actor, RegistrationPolicy.OPEN)
    config = uvicorn.Config(
        api_app.create_app(container), forwarded_allow_ips=PROXY, log_config=None
    )
    config.load()
    with TestClient(config.loaded_app, client=(PROXY, 1234)) as client:
        response = client.post(
            "/api/v1/registrations/request" if registration else "/api/v1/password-resets/request",
            json={"email": "new@example.test" if registration else ADMIN_EMAIL},
            headers={
                "Host": "attacker.example.test",
                "X-Forwarded-Host": "attacker.example.test",
                "X-Forwarded-Proto": "http",
                "X-Forwarded-For": "198.51.100.1",
                "Forwarded": "host=attacker.example.test;proto=http;for=203.0.113.1",
            },
        )
        assert response.status_code == 202
        assert sent.wait(3), "recovery worker did not deliver the synthetic message"
    assert len(bodies) == 1
    page = "verify-email" if registration else "password-reset"
    assert f"https://calendar.example.test/{page}#" in bodies[0]
    assert "attacker.example.test" not in bodies[0]


@pytest.mark.parametrize("trusted", [None, "", PROXY, "192.0.2.0/24"])
def test_run_has_no_implicit_loopback_trust(
    monkeypatch: pytest.MonkeyPatch, trusted: str | None
) -> None:
    if trusted is None:
        monkeypatch.delenv("FORWARDED_ALLOW_IPS", raising=False)
    else:
        monkeypatch.setenv("FORWARDED_ALLOW_IPS", trusted)
    run = Mock()
    monkeypatch.setattr(uvicorn, "run", run)
    api_app.run()
    assert run.call_args.kwargs["proxy_headers"] is True
    assert run.call_args.kwargs["forwarded_allow_ips"] == (trusted or "")


def test_image_and_compose_preserve_empty_trust_and_allow_explicit_configuration() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()
    command = json.loads(
        next(line[4:] for line in dockerfile.splitlines() if line.startswith("CMD "))
    )
    assert "--proxy-headers" in command
    assert 'FORWARDED_ALLOW_IPS=""' in dockerfile
    assert (
        'FORWARDED_ALLOW_IPS: "${FORWARDED_ALLOW_IPS:-}"'
        in (ROOT / "docker-compose.yml").read_text()
    )
    assert "FORWARDED_ALLOW_IPS=" in (ROOT / ".env.example").read_text()
