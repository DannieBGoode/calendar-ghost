"""Verified changes preserve current access until an owned proof is confirmed."""

from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from calendar_sync.application.identity.email_changes import (
    EmailChangeConfigurationRequired,
    EmailChangedNotice,
    EmailChangeServices,
    EmailChangeUnavailable,
    EmailChangeVerificationRequired,
)
from calendar_sync.application.identity.errors import IncorrectPassword
from calendar_sync.application.identity.ports import Session
from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.identity_email import (
    IdentityEmailAdapters,
    build_identity_email,
    compose_identity_email,
)
from calendar_sync.domain.email_changes import EmailChangeMode
from calendar_sync.infrastructure.identity_mail_worker import IdentityMailWorker
from calendar_sync.infrastructure.security import CredentialCipher
from tests.adapters.test_email_change_store import setup
from tests.adapters.test_users_store import FIRST, SECOND, SequentialIds
from tests.contracts.persistence import CredentialPersistenceHarness


def services(
    tmp_path: Path, **settings_overrides: Any
) -> tuple[
    EmailChangeServices,
    IdentityMailWorker | None,
    CredentialPersistenceHarness,
    IdentityEmailAdapters,
    Session,
    Mock,
]:
    path, clock, h, _proofs, _expected, session = setup(tmp_path)
    settings = Settings(
        path,
        master_key=CredentialCipher.generate_key(),
        smtp_host="localhost",
        smtp_sender="ghost@example.test",
        public_url="https://ghost.test",
    )
    settings = replace(settings, **settings_overrides)
    adapters = build_identity_email(settings, SequentialIds(), clock)
    passwords = Mock()
    passwords.verify.side_effect = lambda password, hashed: password == "correct"
    admission = Mock(attempts=None)
    result, worker = compose_identity_email(
        adapters, h.users, clock, h.public, admission, passwords, h.changes
    )
    return result.email_changes, worker, h, adapters, session, passwords


def test_request_requires_current_password_and_preserves_old_email(tmp_path: Path) -> None:
    changes, _worker, h, adapters, session, passwords = services(tmp_path)
    with pytest.raises(IncorrectPassword):
        changes.request.execute(SECOND.id, "new@example.test", "wrong", session.token, "192.0.2.1")
    assert changes.show.execute(SECOND.id).pending is None
    changes.request.execute(SECOND.id, "new@example.test", "correct", session.token, "192.0.2.1")
    pending = changes.show.execute(SECOND.id).pending
    assert pending
    assert h.users.get(SECOND.id) == SECOND
    with pytest.raises(IncorrectPassword):
        changes.request.execute(
            SECOND.id, "replacement@example.test", "wrong", session.token, "192.0.2.1"
        )
    assert changes.show.execute(SECOND.id).pending == pending
    assert pending
    prepared = adapters.email_changes.proofs.prepare(pending.id)
    assert prepared
    assert changes.check.execute(SECOND.id, prepared.token, "192.0.2.1")
    with pytest.raises(IncorrectPassword):
        changes.confirm.execute(SECOND.id, prepared.token, "wrong", session.token, "192.0.2.1")
    changes.confirm.execute(SECOND.id, prepared.token, "correct", session.token, "192.0.2.1")
    changed = h.users.get(SECOND.id)
    assert changed
    assert changed.email == "new@example.test"
    assert passwords.verify.call_count == 5


@pytest.mark.parametrize("configuration", ["absent", "partial", "invalid", "valid"])
def test_direct_mode_never_bypasses_verification(tmp_path: Path, configuration: str) -> None:
    overrides = {
        "absent": {"smtp_host": "", "smtp_sender": ""},
        "partial": {"smtp_host": ""},
        "invalid": {"public_url": "http://lan.test"},
        "valid": {},
    }[configuration]
    changes, _, h, _, _, _ = services(tmp_path, **overrides)
    if configuration == "absent":
        assert (
            changes.direct.execute(SECOND.id, "new@example.test", "correct").email
            == "new@example.test"
        )
    else:
        error = (
            EmailChangeVerificationRequired
            if configuration == "valid"
            else EmailChangeConfigurationRequired
        )
        with pytest.raises(error):
            changes.direct.execute(SECOND.id, "new@example.test", "correct")
    # Only the original active administrator may finish the upgraded add-email step.
    from calendar_sync.infrastructure.persistence.connections import transaction

    with transaction(tmp_path / "identity.db") as connection:
        connection.execute("DELETE FROM users")
    h.users.add(replace(FIRST, email=None), "old-hash")
    assert changes.show.execute(FIRST.id).mode is EmailChangeMode.DIRECT
    assert (
        changes.direct.execute(FIRST.id, "first-new@example.test", None).email
        == "first-new@example.test"
    )
    with pytest.raises(
        (IncorrectPassword, EmailChangeVerificationRequired, EmailChangeConfigurationRequired)
    ):
        changes.direct.execute(FIRST.id, "again@example.test", None)


def test_pending_blocks_direct_after_smtp_removal_but_proof_can_finish(tmp_path: Path) -> None:
    changes, _, h, adapters, session, _ = services(tmp_path)
    changes.request.execute(SECOND.id, "new@example.test", "correct", session.token, "192.0.2.1")
    pending = changes.show.execute(SECOND.id).pending
    assert pending
    prepared = adapters.email_changes.proofs.prepare(pending.id)
    assert prepared
    from calendar_sync.bootstrap.identity_email_changes import compose_email_changes

    no_smtp = replace(
        adapters.email_changes, smtp_present=False, setup=replace(adapters.setup, fingerprint=None)
    )
    queue = Mock()
    passwords = Mock()
    passwords.verify.return_value = True
    offline = compose_email_changes(no_smtp, h.users, passwords, h.changes, queue)
    with pytest.raises(EmailChangeUnavailable):
        offline.direct.execute(SECOND.id, "direct@example.test", "correct")
    offline.confirm.execute(SECOND.id, prepared.token, "correct", session.token, "192.0.2.1")
    changed = h.users.get(SECOND.id)
    assert changed
    assert changed.email == "new@example.test"
    queue.submit_notice.assert_called_once()


def test_request_counts_network_before_password_verification(tmp_path: Path) -> None:
    changes, _, _, _, session, passwords = services(tmp_path)
    from calendar_sync.application.identity.email_change_admission import EmailChangeThrottled

    for _ in range(10):
        with pytest.raises(IncorrectPassword):
            changes.request.execute(
                SECOND.id, "new@example.test", "wrong", session.token, "192.0.2.1"
            )
    with pytest.raises(EmailChangeThrottled):
        changes.request.execute(
            SECOND.id, "new@example.test", "correct", session.token, "192.0.2.1"
        )
    assert passwords.verify.call_count == 10
    assert changes.show.execute(SECOND.id).pending is None


@pytest.mark.parametrize("queue_failure", ["full", "exception"])
def test_old_address_notice_is_after_commit_and_lossy(tmp_path: Path, queue_failure: str) -> None:
    changes, _, h, adapters, session, _ = services(tmp_path)
    queue = Mock()

    observations: list[dict[str, object]] = []

    def submit(notice: EmailChangedNotice) -> bool:
        changed = h.users.get(SECOND.id)
        observations.append(
            {
                "recipient": notice.recipient,
                "notice_repr": repr(notice),
                "current_email": changed.email if changed else None,
                "pending": changes.show.execute(SECOND.id).pending,
                "session_owner": h.sessions.user_of(session.token),
            }
        )
        if queue_failure == "exception":
            raise RuntimeError("synthetic private exception")
        return False

    queue.submit_notice.side_effect = submit
    confirm = replace(changes.confirm, queue=queue)
    changes.request.execute(SECOND.id, "new@example.test", "correct", session.token, "192.0.2.1")
    pending = changes.show.execute(SECOND.id).pending
    assert pending
    prepared = adapters.email_changes.proofs.prepare(pending.id)
    assert prepared
    confirm.execute(SECOND.id, prepared.token, "correct", session.token, "192.0.2.1")
    queue.submit_notice.assert_called_once()
    assert len(observations) == 1
    observed = observations[0]
    assert observed["recipient"] == SECOND.email
    assert SECOND.email is not None
    assert SECOND.email not in str(observed["notice_repr"])
    assert observed["current_email"] == "new@example.test"
    assert observed["pending"] is None
    assert observed["session_owner"] == SECOND.id


def test_cancel_enables_explicit_direct_change_when_smtp_removed(tmp_path: Path) -> None:
    changes, _, _, _, session, _ = services(tmp_path)
    changes.request.execute(SECOND.id, "new@example.test", "correct", session.token, "192.0.2.1")
    pending = changes.show.execute(SECOND.id).pending
    direct = replace(changes.direct, show=replace(changes.show, smtp_present=False))
    with pytest.raises(EmailChangeUnavailable):
        direct.execute(SECOND.id, "direct@example.test", "correct")
    assert pending
    changes.cancel.execute(FIRST.id, pending.id)
    assert changes.show.execute(SECOND.id).pending == pending
    changes.cancel.execute(SECOND.id, pending.id)
    assert (
        direct.execute(SECOND.id, "direct@example.test", "correct").email == "direct@example.test"
    )


def test_missing_email_exception_is_only_for_original_active_administrator(tmp_path: Path) -> None:
    changes, _, _, _, _, _ = services(tmp_path)
    from calendar_sync.domain.access import UserState

    users = Mock()
    users.find.return_value.users = (FIRST,)
    show = replace(changes.show, users=users)
    for candidate in (
        replace(SECOND, email=None),
        replace(SECOND, email=None, role=FIRST.role),
        replace(FIRST, email=None, state=UserState.DISABLED),
    ):
        assert not show.initial(candidate)
    assert show.initial(replace(FIRST, email=None))


def test_request_queue_exception_preserves_pending_and_old_email(tmp_path: Path) -> None:
    changes, _, h, _, session, _ = services(tmp_path)
    queue = Mock()
    queue.submit_change.side_effect = RuntimeError("synthetic delivery failure")
    request = replace(changes.request, queue=queue)
    request.execute(SECOND.id, "new@example.test", "correct", session.token, "192.0.2.1")
    pending = changes.show.execute(SECOND.id).pending
    assert pending
    assert pending.email == "new@example.test"
    assert h.users.get(SECOND.id) == SECOND
    payload = queue.submit_change.call_args.args[0]
    assert payload.request_id == pending.id
    assert "correct" not in repr(payload)
    assert "new@example.test" not in repr(payload)


def test_confirm_rejects_unusable_proof_before_password_verification(tmp_path: Path) -> None:
    changes, _, h, _, session, passwords = services(tmp_path)
    with pytest.raises(EmailChangeUnavailable):
        changes.confirm.execute(SECOND.id, "unknown-token", "correct", session.token, "192.0.2.1")
    passwords.verify.assert_not_called()
    assert h.users.get(SECOND.id) == SECOND


def test_no_smtp_does_not_grant_arbitrary_missing_email_upgrade_access(tmp_path: Path) -> None:
    changes, _, _, _, _, passwords = services(tmp_path, smtp_host="", smtp_sender="")
    users = Mock()
    users.get.return_value = replace(SECOND, email=None)
    users.find.return_value.users = (FIRST,)
    direct = replace(changes.direct, show=replace(changes.show, users=users))
    with pytest.raises(EmailChangeUnavailable):
        direct.execute(SECOND.id, "new@example.test", None)
    passwords.verify.assert_not_called()


def test_absent_smtp_host_and_sender_allow_direct_despite_other_mail_settings(
    tmp_path: Path,
) -> None:
    changes, _, _, _, _, _ = services(
        tmp_path,
        smtp_host="",
        smtp_sender="",
        smtp_username="synthetic-user",
        smtp_password="synthetic-password",
        smtp_recipient="operator@example.test",
    )
    assert changes.show.execute(SECOND.id).mode is EmailChangeMode.DIRECT
    assert (
        changes.direct.execute(SECOND.id, "new@example.test", "correct").email == "new@example.test"
    )


@pytest.mark.parametrize("missing", ["smtp_host", "smtp_sender"])
def test_partial_smtp_host_or_sender_requires_configuration(tmp_path: Path, missing: str) -> None:
    changes, _, _, _, _, _ = services(tmp_path, **{missing: ""})
    assert changes.show.execute(SECOND.id).mode is EmailChangeMode.UNAVAILABLE
    with pytest.raises(EmailChangeConfigurationRequired):
        changes.direct.execute(SECOND.id, "new@example.test", "correct")
