"""Public reset admission never consults account eligibility or sends mail."""

from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from calendar_sync.application.identity.identity_email import IdentityEmailSetup
from calendar_sync.application.identity.password_reset import (
    DeliverPasswordReset,
    RequestPasswordReset,
    ResetEmailRequest,
)
from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import build_adapters
from calendar_sync.domain.access import Role, UserId, UserState
from calendar_sync.infrastructure.persistence.connections import transaction
from tests.adapters.test_users_store import FIRST


@pytest.mark.parametrize("configured", [True, False])
@pytest.mark.parametrize("key", [True, False])
def test_actual_composition_always_persists_limits_when_key_exists(
    tmp_path: Path, configured: bool, key: bool
) -> None:
    from calendar_sync.bootstrap.container import compose
    from calendar_sync.infrastructure.security import CredentialCipher

    settings = Settings(
        tmp_path / "composition.db",
        master_key=CredentialCipher.generate_key() if key else "",
        smtp_host="localhost" if configured else "",
        smtp_sender="ghost@example.test" if configured else "",
        public_url="https://ghost.test",
    )
    adapters = build_adapters(settings)
    container = compose(settings, adapters)
    assert (container.reset_admission.attempts is not None) is key
    assert container.identity_email.configured is (configured and key)
    assert (container.identity_mail_worker is not None) is key
    assert container.identity_email.request_reset.admission is container.reset_admission


def test_request_never_looks_up_user_or_sends_mail(tmp_path: Path) -> None:
    from calendar_sync.infrastructure.security import CredentialCipher

    settings = Settings(
        tmp_path / "request.db",
        master_key=CredentialCipher.generate_key(),
        smtp_host="localhost",
        smtp_sender="ghost@example.test",
        public_url="https://ghost.test",
    )
    adapters = build_adapters(settings)
    adapters.users.add(replace(FIRST, email="admin@example.test"), "synthetic")
    for email, state in [
        ("active@example.test", UserState.ACTIVE),
        ("disabled@example.test", UserState.DISABLED),
    ]:
        adapters.users.add(
            replace(FIRST, id=UserId(email), email=email, role=Role.USER, state=state), "synthetic"
        )
    queue = Mock()
    request = RequestPasswordReset(adapters.reset_admission, adapters.identity_email.setup, queue)
    addresses = [
        "active@example.test",
        "admin@example.test",
        "disabled@example.test",
        "unknown@example.test",
    ]
    with (
        patch.object(adapters.users, "by_email", side_effect=AssertionError("lookup on request")),
        patch.object(
            adapters.self_service_resets,
            "issue_for_email",
            side_effect=AssertionError("issuance on request"),
        ),
        patch(
            "calendar_sync.infrastructure.identity_email.IdentitySmtp.send_reset",
            side_effect=AssertionError("SMTP on request"),
        ),
    ):
        for email in addresses:
            request.execute(f"  {email.upper()}  ", "192.0.2.1")
    fingerprint = adapters.identity_email.setup.fingerprint
    assert fingerprint is not None
    assert [call.args[0] for call in queue.submit_reset.call_args_list] == [
        ResetEmailRequest(email, fingerprint) for email in addresses
    ]
    assert "active@example.test" not in repr(ResetEmailRequest(addresses[0], "current"))


def test_suppression_and_queue_failure_have_identical_outcomes() -> None:
    admission, queue = Mock(), Mock()
    request = RequestPasswordReset(admission, IdentityEmailSetup("current", None), queue)
    admission.admit.return_value = False
    request.execute("user@example.test", "192.0.2.1")
    queue.submit_reset.assert_not_called()
    admission.admit.return_value = True
    queue.submit_reset.return_value = False
    request.execute("user@example.test", "192.0.2.1")
    queue.submit_reset.side_effect = RuntimeError("synthetic-private")
    request.execute("user@example.test", "192.0.2.1")


@pytest.mark.parametrize(
    "change", ["none", "disabled", "deleted", "email", "configuration", "ordinary"]
)
def test_reset_worker_rechecks_eligibility(tmp_path: Path, change: str) -> None:
    adapters = build_adapters(Settings(tmp_path / "identity.db"))
    adapters.users.add(replace(FIRST, notify_by_email=False), "synthetic")
    sender = Mock()
    delivery = DeliverPasswordReset(
        adapters.self_service_resets, IdentityEmailSetup("current", None), sender
    )
    with transaction(tmp_path / "identity.db") as connection:
        if change == "disabled":
            connection.execute("UPDATE users SET state = 'disabled'")
        elif change == "deleted":
            connection.execute("DELETE FROM users")
        elif change == "email":
            connection.execute("UPDATE users SET email = 'new@example.test'")
        elif change == "ordinary":
            connection.execute("UPDATE users SET role = ?", (Role.USER.value,))
    request = ResetEmailRequest(
        FIRST.email or "", "stale" if change == "configuration" else "current"
    )
    prepared = delivery.prepare(request)
    if change in {"none", "ordinary"}:
        assert prepared is not None
        # Issuance committed before SMTP; SMTP may acquire the writer lock itself.
        with transaction(tmp_path / "identity.db") as connection:
            connection.execute("BEGIN IMMEDIATE")
            delivery.send(prepared)
        sender.send_reset.assert_called_once_with(FIRST.email, prepared.link.token)
        assert "synthetic" not in repr(prepared)
    else:
        assert prepared is None
        sender.send_reset.assert_not_called()
