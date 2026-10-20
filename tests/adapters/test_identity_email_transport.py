from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.identity_email import identity_setup
from calendar_sync.infrastructure.identity_email import IdentitySmtp, identity_origin
from calendar_sync.infrastructure.security import (
    CredentialCipher,
    InvalidMasterKey,
    identity_email_fingerprint,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://EXAMPLE.test:443/", "https://example.test"),
        ("https://example.test:8443", "https://example.test:8443"),
        ("http://localhost:80/", "http://localhost"),
        ("http://127.0.0.2:8000", "http://127.0.0.2:8000"),
        ("http://[::1]/", "http://[::1]"),
        *[
            (value, None)
            for value in (
                "http://192.168.1.2",
                "http://localhost.evil.test",
                "https://user@example.test",
                "https://example.test:bad",
                "https://example.test/path",
                "https://example.test?",
                "https://example.test#",
                " https://example.test",
                "https://exam\nple.test",
                "ftp://example.test",
                "https://example.test:0",
                "https://example.test:",
                "https://[::1]suffix",
                "https://bad^host.test",
            )
        ],
    ],
)
def test_identity_origin_requires_a_safe_root(value: str, expected: str | None) -> None:
    assert identity_origin(value) == expected


def configured() -> Settings:
    return Settings(
        database_path=Path(":memory:"),
        master_key=CredentialCipher.generate_key(),
        smtp_host="mail.example.test",
        smtp_sender="ghost@example.test",
        public_url="https://ghost.example.test",
    )


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"smtp_host": ""}, "smtp_missing"),
        ({"smtp_starttls": False}, "smtp_security"),
        ({"public_url": "http://192.168.1.2"}, "origin_insecure"),
        ({"public_url": ""}, "origin_missing"),
        ({"public_url": "bad"}, "origin_invalid"),
        ({"public_url": "http://localhost/path"}, "origin_invalid"),
        ({"master_key": ""}, "master_key_missing"),
    ],
)
def test_identity_configuration_requires_key_smtp_and_origin(
    changes: dict[str, Any], reason: str
) -> None:
    setup = identity_setup(replace(configured(), **changes))
    assert setup.reason == reason
    assert setup.fingerprint is None


def test_invalid_master_key_is_not_usable() -> None:
    with pytest.raises(InvalidMasterKey):
        identity_setup(replace(configured(), master_key="invalid"))


def test_identity_fingerprint_tracks_effective_configuration() -> None:
    settings = configured()
    original = identity_setup(settings).fingerprint
    assert original
    assert len(original) == 64
    changes: dict[str, Any] = {
        "smtp_host": "other.example.test",
        "smtp_port": 2525,
        "smtp_sender": "other@example.test",
        "smtp_username": "synthetic-user",
        "smtp_password": "synthetic-password",
        "public_url": "https://other.test",
        "master_key": CredentialCipher.generate_key(),
    }
    for name, value in changes.items():
        assert identity_setup(replace(settings, **{name: value})).fingerprint != original
    assert (
        identity_setup(replace(settings, smtp_recipient="operator@example.test")).fingerprint
        == original
    )
    assert (
        identity_setup(replace(settings, public_url="https://GHOST.example.test:443/")).fingerprint
        == original
    )
    assert "synthetic-password" not in original
    assert "synthetic-user" not in original
    values = ("localhost", 25, "ghost@example.test", "", "", False, "http://localhost")
    assert identity_email_fingerprint(settings.master_key, values) != identity_email_fingerprint(
        settings.master_key, (*values[:5], True, values[6])
    )


@pytest.mark.parametrize("host", ["mail.example.test", "localhost.evil.test", "192.168.1.2"])
def test_cleartext_identity_mail_requires_loopback(host: str) -> None:
    from calendar_sync.application.identity.identity_email import IdentityEmailDeliveryFailed

    with pytest.raises(IdentityEmailDeliveryFailed):
        IdentitySmtp(host, 25, "ghost@example.test", "", "", False, "https://ghost.test").send_test(
            "admin@example.test"
        )


@pytest.mark.parametrize("mode", ["trusted", "unknown_ca", "hostname_mismatch", "refused"])
def test_identity_smtp_verifies_tls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    from calendar_sync.application.identity.identity_email import IdentityEmailDeliveryFailed
    from tests.identity_smtp_server import certificate_context, smtp_server

    context, ca = certificate_context(
        tmp_path, "wrong.test" if mode == "hostname_mismatch" else "localhost"
    )
    if mode != "unknown_ca":
        monkeypatch.setenv("SSL_CERT_FILE", str(ca))
    else:
        monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    with smtp_server(context, refuse=mode == "refused") as (port, messages):
        sender = IdentitySmtp(
            "localhost", port, "ghost@example.test", "", "", True, "https://ghost.test"
        )
        if mode == "trusted":
            sender.send_test("admin@example.test")
            assert len(messages) == 1
        else:
            with pytest.raises(IdentityEmailDeliveryFailed):
                sender.send_test("admin@example.test")
            assert messages == []


def test_test_mail_contains_only_literal_copy_and_configured_origin() -> None:
    from email import policy
    from email.parser import BytesParser

    from calendar_sync.domain.access import Role, User, UserId, UserState
    from tests.helpers import NOW
    from tests.identity_smtp_server import smtp_server

    user = User(
        UserId("admin"),
        "admin@example.test",
        Role.INSTALLATION_ADMINISTRATOR,
        UserState.ACTIVE,
        NOW,
        notify_by_email=False,
    )
    assert user.email is not None
    with smtp_server(None) as (port, messages):
        settings = replace(
            configured(),
            smtp_host="localhost",
            smtp_port=port,
            smtp_starttls=False,
            smtp_recipient="operator@example.test",
        )
        IdentitySmtp(
            settings.smtp_host,
            settings.smtp_port,
            settings.smtp_sender,
            settings.smtp_username,
            settings.smtp_password,
            settings.smtp_starttls,
            settings.public_url,
        ).send_test(user.email)
    message = BytesParser(policy=policy.default).parsebytes(messages[0])
    assert message["Subject"] == "Calendar Ghost: test email"
    assert message["To"] == user.email
    assert "operator@example.test" not in messages[0].decode()
    assert message.get_content().replace("\r\n", "\n") == (
        "Calendar Ghost can send identity email with the current settings.\n\n"
        "Open Calendar Ghost: https://ghost.example.test\n\n"
        "This test does not change who can join.\n"
    )


def test_delivery_failure_exposes_no_provider_detail(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from calendar_sync.application.identity.identity_email import IdentityEmailDeliveryFailed

    calls: list[dict[str, Any]] = []

    def fail(*args: Any, **kwargs: Any) -> None:
        calls.append(kwargs)
        raise OSError("synthetic-password admin@example.test provider detail")

    monkeypatch.setattr("calendar_sync.infrastructure.identity_email.smtplib.SMTP", fail)
    sender = IdentitySmtp(
        "localhost",
        25,
        "ghost@example.test",
        "synthetic-user",
        "synthetic-password",
        False,
        "https://ghost.test",
    )
    with pytest.raises(IdentityEmailDeliveryFailed) as failure:
        sender.send_test("admin@example.test")
    assert str(failure.value) == "Identity email delivery failed"
    assert failure.value.__suppress_context__
    assert calls == [{"timeout": 10}]
    assert caplog.text == ""
    assert "synthetic-password" not in repr(sender)
    assert "synthetic-user" not in repr(sender)
