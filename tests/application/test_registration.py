"""Anonymous joining queues work; only atomic proof completion creates a User."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from typing import cast
from unittest.mock import Mock, patch

import pytest

from calendar_sync.application.identity.administration import LinkUnusable
from calendar_sync.application.identity.errors import IncorrectCredentials, PasswordPolicyViolation
from calendar_sync.application.identity.ports import Session
from calendar_sync.application.identity.registration import (
    CheckRegistration,
    CompleteRegistration,
    RequestRegistration,
)
from calendar_sync.application.identity.registration_ports import (
    RegistrationEmailRequest,
    RegistrationUnavailable,
)
from calendar_sync.domain.access import UserId
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.persistence.registration_proofs import SqliteRegistrationProofs
from calendar_sync.infrastructure.persistence.users import SqliteSessions
from tests.adapters.test_registration_store import registration


def test_request_never_looks_up_user_or_awaits_mail(tmp_path: Path) -> None:
    _, _, users, _, proofs = registration(tmp_path)
    admission, readiness, queue = Mock(), Mock(), Mock()
    calls = Mock()
    for name, spy in [("admission", admission), ("readiness", readiness), ("queue", queue)]:
        calls.attach_mock(spy, name)
    request = RequestRegistration(admission, readiness, queue, "current")
    release = Event()
    with (
        patch.object(users, "by_email", side_effect=AssertionError("request lookup")),
        patch.object(proofs, "issue", side_effect=AssertionError("request preparation")),
        patch(
            "calendar_sync.infrastructure.identity_email.IdentitySmtp.send_registration",
            side_effect=lambda *_: release.wait(5),
        ) as smtp,
    ):
        with ThreadPoolExecutor(max_workers=1) as pool:
            try:
                pool.submit(
                    request.execute, " NEW@EXAMPLE.TEST ", "192.0.2.1", "invitation"
                ).result(timeout=1)
            finally:
                release.set()
        smtp.assert_not_called()
    assert [call[0] for call in calls.mock_calls] == [
        "admission.admit_front",
        "readiness.public_available",
        "admission.admit_durable",
        "queue.submit_registration",
    ]
    queued = queue.submit_registration.call_args.args[0]
    assert queued == RegistrationEmailRequest("new@example.test", "current", "invitation")
    assert all(value not in repr(queued) for value in ("new@example.test", "invitation"))


def test_unavailable_and_lossy_queue_outcomes() -> None:
    admission, readiness, queue = Mock(), Mock(), Mock()
    request = RequestRegistration(admission, readiness, queue, "current")
    readiness.public_available.return_value = False
    with pytest.raises(RegistrationUnavailable):
        request.execute("new@example.test", "network")
    admission.admit_durable.assert_not_called()
    readiness.public_available.return_value = True
    admission.admit_durable.return_value = False
    request.execute("new@example.test", "network")
    queue.submit_registration.assert_not_called()
    admission.admit_durable.return_value = True
    queue.submit_registration.return_value = False
    request.execute("new@example.test", "network")
    queue.submit_registration.side_effect = RuntimeError("private")
    request.execute("new@example.test", "network")


def completion(tmp_path: Path) -> tuple[CompleteRegistration, str]:
    database, clock, users, _, proofs = registration(tmp_path)
    pending = proofs.issue("new@example.test", None, "current")
    assert pending
    admission = Mock()
    admission.check_token.side_effect = lambda client, check: check()
    return CompleteRegistration(
        proofs, Mock(), SqliteSessions(database, clock), users, clock, admission, "current"
    ), pending.link.token


def test_completion_gates_before_hash_and_starts_session_after_commit(tmp_path: Path) -> None:
    use_case, token = completion(tmp_path)
    order: list[str] = []
    cast(Mock, use_case.admission).admit_completion.side_effect = lambda _: order.append("gate")

    def hash_password(password: str) -> str:
        order.append("hash")
        with transaction(cast(SqliteRegistrationProofs, use_case.proofs)._database) as connection:
            connection.execute("BEGIN IMMEDIATE")
        return "hashed"

    cast(Mock, use_case.passwords).hash.side_effect = hash_password
    original = use_case.sessions.start

    def start(
        user_id: UserId, password_hash: str, email: str | None, revision: int
    ) -> Session | None:
        order.append("session")
        # A separate connection observes the committed User and consumed proof.
        assert use_case.users.by_email("new@example.test")
        assert use_case.proofs.check(token, "current") is None
        return original(user_id, password_hash, email, revision)

    with patch.object(use_case.sessions, "start", side_effect=start):
        session = use_case.execute(token, "long-password", "network")
    assert order == ["gate", "hash", "session"]
    user = use_case.users.get(session.user_id)
    assert user
    assert user.last_sign_in_at == use_case.clock.now()
    with pytest.raises(LinkUnusable):
        use_case.execute(token, "long-password", "network")
    assert cast(Mock, use_case.passwords).hash.call_count == 1


@pytest.mark.parametrize("failure", ["storage", "credential-race"])
def test_session_failure_keeps_created_user(tmp_path: Path, failure: str) -> None:
    from calendar_sync.application.identity.sign_in import SignIn
    from calendar_sync.infrastructure.throttle import MemorySignInThrottle

    use_case, token = completion(tmp_path)
    cast(Mock, use_case.passwords).hash.return_value = "hashed"
    with (
        patch.object(
            use_case.sessions,
            "start",
            **(
                {"side_effect": RuntimeError("unavailable")}
                if failure == "storage"
                else {"return_value": None}
            ),
        ),
        pytest.raises(RuntimeError if failure == "storage" else IncorrectCredentials),
    ):
        use_case.execute(token, "long-password", "network")
    user = use_case.users.by_email("new@example.test")
    assert user
    assert use_case.users.password_hash(user.id) == "hashed"
    assert use_case.proofs.check(token, "current") is None
    cast(Mock, use_case.passwords).verify.return_value = True
    signed_in = SignIn(
        use_case.users,
        use_case.passwords,
        use_case.sessions,
        MemorySignInThrottle(use_case.clock),
        use_case.clock,
    ).execute("new@example.test", "long-password", "192.0.2.1")
    assert signed_in.user_id == user.id


@pytest.mark.parametrize("password", ["x" * 11, "x" * 1025])
def test_password_bounds_before_hash(tmp_path: Path, password: str) -> None:
    use_case, token = completion(tmp_path)
    with pytest.raises(PasswordPolicyViolation):
        use_case.execute(token, password, "network")
    cast(Mock, use_case.passwords).hash.assert_not_called()


@pytest.mark.parametrize("token", ["x" * 129, "é", ""])
def test_token_bounds_precede_proof_storage(token: str) -> None:
    proofs, admission = Mock(), Mock()
    admission.check_token.side_effect = lambda client, check: check()
    assert CheckRegistration(proofs, admission, "current").execute(token, "network") is None
    proofs.check.assert_not_called()


@pytest.mark.parametrize("key", [True, False])
def test_composition_retains_maintenance_without_smtp(tmp_path: Path, key: bool) -> None:
    from calendar_sync.bootstrap.config import Settings
    from calendar_sync.bootstrap.container import build_container
    from calendar_sync.infrastructure.security import CredentialCipher

    container = build_container(
        Settings(
            tmp_path / "composed.db", master_key=CredentialCipher.generate_key() if key else ""
        )
    )
    assert not container.registrations.readiness.public_available()
    assert (container.identity_mail_worker is not None) is key
    assert container.registrations.request.admission is container.registrations.complete.admission


def test_keyless_invitation_bound_proof_can_finish(tmp_path: Path) -> None:
    from calendar_sync.domain.access import RegistrationPolicy
    from calendar_sync.infrastructure.persistence.registration import SqliteInvitations
    from calendar_sync.infrastructure.persistence.registration_admission import (
        SqliteRegistrationAdmission,
    )
    from tests.adapters.test_registration_store import RandomIds
    from tests.adapters.test_users_store import FIRST

    use_case, _ = completion(tmp_path)
    database = cast(SqliteRegistrationProofs, use_case.proofs)._database
    invitation = SqliteInvitations(database, RandomIds(), use_case.clock).issue(
        FIRST.id, use_case.clock.now()
    )
    assert invitation
    pending = use_case.proofs.issue("bound@example.test", invitation.token, "current")
    assert pending
    with transaction(database) as connection:
        connection.execute(
            "UPDATE installation_settings SET registration_policy = ?",
            (RegistrationPolicy.INVITATION_ONLY.value,),
        )
    use_case = CompleteRegistration(
        use_case.proofs,
        use_case.passwords,
        use_case.sessions,
        use_case.users,
        use_case.clock,
        SqliteRegistrationAdmission(database, "", use_case.clock),
        None,
    )
    cast(Mock, use_case.passwords).hash.return_value = "hashed"
    session = use_case.execute(pending.link.token, "long-password", "192.0.2.1")
    user = use_case.users.get(session.user_id)
    assert user
    assert user.email == "bound@example.test"
