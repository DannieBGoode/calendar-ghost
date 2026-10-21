"""Add a first password without weakening password confirmation for existing credentials."""

from collections.abc import Callable
from dataclasses import dataclass

from calendar_sync.application.identity.administration import UserNotFound
from calendar_sync.application.identity.credentials import CredentialChanges
from calendar_sync.application.identity.errors import (
    IncorrectCredentials,
    IncorrectPassword,
    PasswordPolicyViolation,
)
from calendar_sync.application.identity.ports import PasswordHasher, Sessions
from calendar_sync.application.identity.provider_sign_in_ports import (
    LastSignInMethod,
    LinkOwner,
    ProviderMethods,
)
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


@dataclass(frozen=True, slots=True)
class ResolveProviderOwner:
    sessions: Sessions
    credentials: CredentialChanges
    session_digest: Callable[[str], str]

    def execute(self, token: str | None) -> LinkOwner | None:
        user = self.sessions.user_of(token)
        expected = self.credentials.current(user) if user is not None else None
        if expected is None or token is None:
            return None
        return LinkOwner(expected.user_id, self.session_digest(token), expected.revision)


@dataclass(frozen=True, slots=True)
class UnlinkProviderIdentity:
    methods: ProviderMethods

    def execute(self, owner: LinkOwner, identity_id: str) -> None:
        if not any(item.id == identity_id for item in self.methods.show(owner.user_id).identities):
            raise UserNotFound("sign-in method not found")
        if not self.methods.unlink(owner, identity_id):
            raise LastSignInMethod
