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
@pytest.mark.parametrize("kind", ["test", "reset", "change", "notice"])
def test_identity_smtp_verifies_tls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str, kind: str
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

        def send() -> None:
            if kind == "reset":
                sender.send_reset("admin@example.test", "synthetic-token")
            elif kind == "change":
                sender.send_email_change("admin@example.test", "synthetic-token")
            elif kind == "notice":
                sender.send_email_changed("admin@example.test")
            else:
                sender.send_test("admin@example.test")

        if mode == "trusted":
            send()
            assert len(messages) == 1
        else:
            with pytest.raises(IdentityEmailDeliveryFailed):
                send()
            assert messages == []


def test_reset_transport_uses_current_recipient_and_configured_fragment_origin() -> None:
    from email import policy
    from email.parser import BytesParser

    from tests.identity_smtp_server import smtp_server

    with smtp_server(None) as (port, messages):
        IdentitySmtp(
            "localhost",
            port,
            "ghost@example.test",
            "",
            "",
            False,
            "https://GHOST.example.test:443/",
        ).send_reset("current@example.test", "synthetic-token")
    message = BytesParser(policy=policy.default).parsebytes(messages[0])
    assert message["Subject"] == "Calendar Ghost: reset your password"
    assert message["To"] == "current@example.test"
    assert message.get_content().replace("\r\n", "\n") == (
        "A password reset was requested for your Calendar Ghost account.\n\n"
        "Reset your password: https://ghost.example.test/password-reset#synthetic-token\n\n"
        "This link expires in one hour and can be used once.\n"
        "If you did not request this, you can ignore this email.\n"
    )


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


@pytest.mark.parametrize("field", ["sender", "recipient"])
@pytest.mark.parametrize(
    "address",
    [
        "victim,admin@example.test",
        "Group:admin@example.test;",
        "Admin <admin@example.test>",
        "admin@example.test,other@example.test",
        "admin..test@example.test",
        "admin@example.test\r\nBcc:other@example.test",
    ],
)
def test_invalid_identity_mailbox_never_connects(
    monkeypatch: pytest.MonkeyPatch, field: str, address: str
) -> None:
    from unittest.mock import Mock

    from calendar_sync.application.identity.identity_email import IdentityEmailDeliveryFailed

    connection = Mock()
    monkeypatch.setattr("calendar_sync.infrastructure.identity_email.smtplib.SMTP", connection)
    sender = IdentitySmtp(
        "localhost",
        25,
        address if field == "sender" else "ghost@example.test",
        "",
        "",
        False,
        "https://ghost.test",
    )
    with pytest.raises(IdentityEmailDeliveryFailed, match=r"^Identity email delivery failed$"):
        sender.send_test(address if field == "recipient" else "admin@example.test")
    connection.assert_not_called()


def test_identity_mail_uses_one_explicit_envelope_recipient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import smtplib
    from unittest.mock import Mock

    smtp = smtplib.SMTP()
    captured = Mock(return_value={})
    send_message = Mock(wraps=smtp.send_message)
    monkeypatch.setattr(smtp, "send_message", send_message)
    monkeypatch.setattr(smtp, "sendmail", captured)
    monkeypatch.setattr(smtp, "ehlo_or_helo_if_needed", Mock())
    monkeypatch.setattr(smtp, "quit", Mock(return_value=(221, b"bye")))
    monkeypatch.setattr(smtp, "close", Mock())
    monkeypatch.setattr(
        "calendar_sync.infrastructure.identity_email.smtplib.SMTP", lambda *args, **kwargs: smtp
    )
    IdentitySmtp(
        "localhost", 25, "ghost@example.test", "", "", False, "https://ghost.test"
    ).send_test("admin@example.test")
    assert send_message.call_args.kwargs == {
        "from_addr": "ghost@example.test",
        "to_addrs": ["admin@example.test"],
    }
    assert captured.call_args.args[:2] == ("ghost@example.test", ["admin@example.test"])


def test_email_change_mail_is_private() -> None:
    from unittest.mock import patch

    sender = IdentitySmtp(
        "mail.example.test",
        587,
        "ghost@example.test",
        "synthetic-user",
        "synthetic-password",
        True,
        "https://GHOST.test:443/",
    )
    with patch("calendar_sync.infrastructure.identity_email.smtplib.SMTP") as smtp:
        sender.send_email_change("new@example.test", "synthetic-token")
        smtp.assert_called_once_with("mail.example.test", 587, timeout=10)
        transport = smtp.return_value.__enter__.return_value
        context = transport.starttls.call_args.kwargs["context"]
        assert context.check_hostname
        import ssl

        assert context.verify_mode == ssl.CERT_REQUIRED
        message = transport.send_message.call_args.args[0]
        assert message["To"] == "new@example.test"
        body = message.get_content()
        assert "https://ghost.test/email-change#synthetic-token" in body
        assert "24 hours" in body
        assert "synthetic-password" not in body
        sender.send_email_changed("previous@example.test")
        notice = transport.send_message.call_args.args[0]
        assert notice["To"] == "previous@example.test"
        assert notice.get_content() == (
            "Your Calendar Ghost sign-in email has changed.\n\n"
            "If you did not make this change, contact your installation administrator.\n\n"
            "Open Calendar Ghost: https://ghost.test\n"
        )
        assert "synthetic-token" not in notice.get_content()
        assert "new@example.test" not in notice.get_content()
    assert "synthetic-password" not in repr(sender)

    assert "ghost@example.test" not in repr(sender)
