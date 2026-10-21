"""Add a first password without weakening password confirmation for existing credentials."""

from collections.abc import Callable
from dataclasses import dataclass

from calendar_sync.application.identity.credentials import CredentialChanges
from calendar_sync.application.identity.errors import (
    IncorrectCredentials,
    IncorrectPassword,
    PasswordPolicyViolation,
)
from calendar_sync.application.identity.ports import PasswordHasher
from calendar_sync.application.identity.provider_sign_in_ports import LinkOwner, ProviderMethods
from calendar_sync.application.identity.sign_in import require_password
from calendar_sync.domain.access import UserId


@dataclass(frozen=True, slots=True)
class SetOwnPassword:
    credentials: CredentialChanges
    passwords: PasswordHasher
    methods: ProviderMethods
    session_digest: Callable[[str], str]

    def execute(self, user_id: UserId, new: str, session: str) -> None:
        expected = self.credentials.current(user_id)
        if expected is None:
            raise IncorrectCredentials("the signed-in User is no longer active")
        if expected.password_hash is not None:
            raise IncorrectPassword("confirm your current password to replace it")
        if len(new) > 256:
            raise PasswordPolicyViolation("password must contain at most 256 characters")
        hashed = self.passwords.hash(require_password(new))
        owner = LinkOwner(user_id, self.session_digest(session), expected.revision)
        if not self.methods.set_password(owner, expected, hashed):
            raise IncorrectCredentials("the credentials or session changed; sign in again")
