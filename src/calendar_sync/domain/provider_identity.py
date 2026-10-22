"""Pure provider identity ownership, admission, and sign-in method decisions."""

from dataclasses import dataclass, field
from enum import StrEnum, auto

from calendar_sync.domain.access import RegistrationPolicy, UserId, email_address
from calendar_sync.domain.errors import DomainValidationError


@dataclass(frozen=True, slots=True)
class ProviderIdentityKey:
    """An exact issuer and subject binding, independent of mutable email claims."""

    issuer: str = field(repr=False)
    subject: str = field(repr=False)

    def __post_init__(self) -> None:
        if not self.issuer.strip() or not self.subject.strip():
            raise DomainValidationError("provider identity requires issuer and subject")


@dataclass(frozen=True, slots=True)
class ProviderClaims:
    key: ProviderIdentityKey = field(repr=False)
    email: str | None = field(repr=False)
    email_verified: bool

    def __post_init__(self) -> None:
        if self.email is not None:
            object.__setattr__(self, "email", email_address(self.email))


@dataclass(frozen=True, slots=True)
class ProviderAdmissionFacts:
    """New User admission evidence; a matching Invitation is still live and valid."""

    policy: RegistrationPolicy
    operational: bool
    verified_email: bool
    invitation_matches: bool


class LinkDecision(StrEnum):
    EXISTING = auto()
    LINK = auto()
    PASSWORD_REQUIRED = auto()
    REFUSE = auto()


def decide_provider_link(
    existing_owner: UserId | None,
    signed_in_user: UserId | None,
    matching_email_user: UserId | None,
    email_verified: bool,
    local_email_verified: bool,
) -> LinkDecision:
    """An existing identity binding wins; email alone never moves its ownership.

    ``signed_in_user`` is the owner of the live session that began explicit linking.
    Without an existing User to link, REFUSE leaves new User admission to
    ``may_admit_provider_user``; it does not decide registration eligibility.
    """
    if existing_owner is not None:
        if signed_in_user is not None and signed_in_user != existing_owner:
            return LinkDecision.REFUSE
        return LinkDecision.EXISTING
    if signed_in_user is not None:
        return LinkDecision.LINK
    if matching_email_user is not None:
        return (
            LinkDecision.LINK
            if email_verified and local_email_verified
            else LinkDecision.PASSWORD_REQUIRED
        )
    return LinkDecision.REFUSE


def may_admit_provider_user(facts: ProviderAdmissionFacts) -> bool:
    """Open requires operational readiness; closed policies require a matching Invitation."""
    if not facts.verified_email:
        return False
    if facts.policy is RegistrationPolicy.OPEN:
        return facts.operational
    return facts.invitation_matches


def may_remove_sign_in_method(has_password: bool, remaining_enabled: int) -> bool:
    """Keep a password or at least one enabled provider method after removal."""
    return has_password or remaining_enabled > 0
