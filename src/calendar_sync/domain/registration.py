"""Pure decisions for verified admission under the installation's Registration Policy."""

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from calendar_sync.domain.access import RegistrationPolicy
from calendar_sync.domain.errors import DomainValidationError


@dataclass(frozen=True, slots=True)
class RegistrationProof:
    token_hash: str = field(repr=False)
    email: str = field(repr=False)
    expires_at: datetime
    invitation_id: str | None = None
    used_at: datetime | None = None
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        if re.fullmatch(r"[0-9a-f]{64}", self.token_hash) is None:
            raise DomainValidationError("registration proof requires a SHA-256 digest")

    def usable(self, at: datetime) -> bool:
        return self.used_at is None and self.revoked_at is None and at < self.expires_at


def may_issue_invitation(policy: RegistrationPolicy) -> bool:
    return policy is not RegistrationPolicy.ONLY_ME


def may_accept_invitation_directly(policy: RegistrationPolicy) -> bool:
    return policy is RegistrationPolicy.INVITATION_ONLY


def may_request_registration(policy: RegistrationPolicy, operational: bool) -> bool:
    return policy is RegistrationPolicy.OPEN and operational


def may_finish_registration(
    policy: RegistrationPolicy, invitation_bound: bool, operational: bool
) -> bool:
    return (policy is RegistrationPolicy.OPEN and operational) or (
        policy is RegistrationPolicy.INVITATION_ONLY and invitation_bound
    )


def registration_expiry(at: datetime, invitation_expires_at: datetime | None = None) -> datetime:
    expiry = at + timedelta(hours=24)
    return min(expiry, invitation_expires_at) if invitation_expires_at is not None else expiry
