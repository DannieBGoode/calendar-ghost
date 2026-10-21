"""Passwordless Users gain a password only through their live owning session."""

from unittest.mock import Mock

import pytest

from calendar_sync.application.identity.administration import DeleteOwnAccount
from calendar_sync.application.identity.email_changes import confirmed_credential
from calendar_sync.application.identity.errors import (
    IncorrectCredentials,
    IncorrectPassword,
    PasswordPolicyViolation,
)
from calendar_sync.application.identity.sign_in import ChangeOwnPassword, SetOwnEmail, SignIn
from calendar_sync.application.identity.sign_in_methods import SetOwnPassword
from calendar_sync.domain.model import ProjectionHandling
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.persistence.users import SqliteSessions, SqliteUserDirectory
from calendar_sync.infrastructure.security import token_hash
from calendar_sync.infrastructure.throttle import MemorySignInThrottle
from tests.adapters.test_provider_methods import MethodsHarness
from tests.adapters.test_provider_methods import methods as methods
from tests.adapters.test_users_store import SECOND
from tests.identity_fakes import PlainPasswords


def test_passwordless_sign_in_uses_decoy(methods: MethodsHarness) -> None:
    passwords = Mock(wraps=PlainPasswords())
    sessions = SqliteSessions(methods.path, methods.clock)
    sign_in = SignIn(
        SqliteUserDirectory(methods.path),
        passwords,
        sessions,
        MemorySignInThrottle(methods.clock),
        methods.clock,
    )
    decoy = sign_in._decoy
    with pytest.raises(IncorrectCredentials):
        sign_in.execute(SECOND.email, "attempt", "client")
    passwords.verify.assert_called_once_with("attempt", decoy)
    facts = SqliteUserDirectory(methods.path).sign_in_credentials(SECOND.email)
    assert facts is not None
    assert facts.credential.password_hash is None


@pytest.mark.parametrize("length", [11, 257])
def test_first_password_bounds_precede_hashing(methods: MethodsHarness, length: int) -> None:
    passwords = Mock(wraps=PlainPasswords())
    use_case = SetOwnPassword(methods.credentials, passwords, methods.methods, token_hash)
    with pytest.raises(PasswordPolicyViolation):
        use_case.execute(SECOND.id, "x" * length, "owner-session")
    passwords.hash.assert_not_called()


@pytest.mark.parametrize("length", [12, 256])
def test_first_password_hashes_outside_write_lock(methods: MethodsHarness, length: int) -> None:
    class LockCheckingPasswords(PlainPasswords):
        def hash(self, password: str) -> str:
            with transaction(methods.path, timeout=0) as connection:
                connection.execute("BEGIN IMMEDIATE")
            return super().hash(password)

    use_case = SetOwnPassword(
        methods.credentials, LockCheckingPasswords(), methods.methods, token_hash
    )
    use_case.execute(SECOND.id, "x" * length, "owner-session")
    assert SqliteUserDirectory(methods.path).password_hash(SECOND.id) == "hashed:" + "x" * length
    with pytest.raises(IncorrectPassword):
        use_case.execute(SECOND.id, "replacement password", "owner-session")


def test_first_password_losing_session_during_hash_changes_nothing(methods: MethodsHarness) -> None:
    class EndSessionPasswords(PlainPasswords):
        def hash(self, password: str) -> str:
            SqliteSessions(methods.path, methods.clock).end("owner-session")
            return super().hash(password)

    use_case = SetOwnPassword(
        methods.credentials, EndSessionPasswords(), methods.methods, token_hash
    )
    with pytest.raises(IncorrectCredentials):
        use_case.execute(SECOND.id, "first password", "owner-session")
    assert not methods.methods.show(SECOND.id).has_password


@pytest.mark.parametrize(
    "operation", ["change-password", "direct-email", "verified-email", "delete"]
)
def test_passwordless_sensitive_actions_require_setting_password_first(
    methods: MethodsHarness, operation: str
) -> None:
    users = SqliteUserDirectory(methods.path)
    passwords = Mock(wraps=PlainPasswords())

    def run() -> None:
        if operation == "change-password":
            ChangeOwnPassword(methods.credentials, passwords).execute(
                SECOND.id, "guess", "next password", "owner-session"
            )
        elif operation == "direct-email":
            SetOwnEmail(users, passwords, methods.credentials).execute(
                SECOND.id, "next@example.test", "guess"
            )
        elif operation == "verified-email":
            confirmed_credential(methods.credentials, passwords, SECOND.id, "guess")
        else:
            DeleteOwnAccount(users, passwords, Mock(), Mock(), Mock(), methods.clock).execute(
                SECOND.id, "guess", ProjectionHandling.DETACH
            )

    with pytest.raises(IncorrectPassword):
        run()
    passwords.verify.assert_not_called()
    assert users.get(SECOND.id) == SECOND


def test_existing_password_still_requires_confirmation(methods: MethodsHarness) -> None:
    passwords = PlainPasswords()
    SetOwnPassword(methods.credentials, passwords, methods.methods, token_hash).execute(
        SECOND.id, "first password", "owner-session"
    )
    change = ChangeOwnPassword(methods.credentials, passwords)
    with pytest.raises(IncorrectPassword):
        change.execute(SECOND.id, "wrong", "replacement password", "owner-session")
    change.execute(SECOND.id, "first password", "replacement password", "owner-session")
    assert (
        SqliteUserDirectory(methods.path).password_hash(SECOND.id) == "hashed:replacement password"
    )


def test_existing_password_confirmation_is_bounded(methods: MethodsHarness) -> None:
    passwords = Mock(wraps=PlainPasswords())
    SetOwnPassword(methods.credentials, passwords, methods.methods, token_hash).execute(
        SECOND.id, "first password", "owner-session"
    )
    with pytest.raises(IncorrectPassword):
        ChangeOwnPassword(methods.credentials, passwords).execute(
            SECOND.id, "x" * 1025, "replacement password", "owner-session"
        )
    passwords.verify.assert_not_called()
