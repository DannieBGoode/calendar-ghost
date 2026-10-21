"""Guard credential writes against a reset landing during password confirmation."""

from dataclasses import dataclass, field
from typing import Protocol

from calendar_sync.domain.access import UserId


@dataclass(frozen=True, slots=True)
class CredentialSnapshot:
    user_id: UserId
    revision: int
    password_hash: str = field(repr=False)
    email: str | None = field(repr=False)


class CredentialChanges(Protocol):
    def current(self, user_id: UserId) -> CredentialSnapshot | None:
        """The active User's current credential, or None."""
        ...

    def change_password(self, expected: CredentialSnapshot, hashed: str, keep: str | None) -> bool:
        """Compare and change, revoke reset proofs and end other sessions atomically.

        False changes nothing when the active credential no longer matches, or a supplied kept
        session is not live and owned by that User.
        """
        ...

    def change_email(self, expected: CredentialSnapshot, email: str) -> bool:
        """Compare and change the active credential and revoke reset proofs atomically.

        False changes nothing on a stale credential; EmailTaken also changes nothing.
        """
        ...
