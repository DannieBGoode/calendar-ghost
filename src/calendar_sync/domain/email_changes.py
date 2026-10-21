"""Decisions and proof ownership for changes to a User's sign-in email."""

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from calendar_sync.domain.access import UserId
from calendar_sync.domain.errors import DomainValidationError

_SHA256_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class EmailChangeMode(StrEnum):
    DIRECT = "direct"
    VERIFIED = "verified"
    UNAVAILABLE = "unavailable"


def email_change_mode(smtp_present: bool, configured: bool, initial_email: bool) -> EmailChangeMode:
    """The initial add-email step stays possible for the upgraded first administrator.

    Callers derive ``initial_email`` from that active administrator with no existing email.
    An unsafe or incomplete SMTP setup cannot silently enable a direct change.
    """
    if initial_email or not smtp_present:
        return EmailChangeMode.DIRECT
    if configured:
        return EmailChangeMode.VERIFIED
    return EmailChangeMode.UNAVAILABLE


@dataclass(frozen=True, slots=True)
class CredentialRevision:
    value: int

    def __post_init__(self) -> None:
        if self.value < 0:
            raise DomainValidationError("credential revision must not be negative")

    def next(self) -> "CredentialRevision":
        return CredentialRevision(self.value + 1)


@dataclass(frozen=True, slots=True)
class EmailChangeProof:
    user_id: UserId
    revision: CredentialRevision
    token_hash: str = field(repr=False)
    expires_at: datetime
    used_at: datetime | None = None
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        if _SHA256_DIGEST.fullmatch(self.token_hash) is None:
            raise DomainValidationError("email change proof requires a SHA-256 digest")

    def usable_by(
        self, user_id: UserId, revision: CredentialRevision, active: bool, at: datetime
    ) -> bool:
        return (
            active
            and self.user_id == user_id
            and self.revision == revision
            and self.used_at is None
            and self.revoked_at is None
            and at < self.expires_at
        )
