"""Authority deliberately withdrawn when bringing an old installation back online."""

from dataclasses import dataclass
from enum import StrEnum

from calendar_sync.domain.access import RegistrationPolicy, User, UserId, UserState
from calendar_sync.domain.errors import DomainValidationError


class RestoreAuthority(StrEnum):
    PASSWORDS = "passwords"
    SESSIONS = "sessions"
    INVITATIONS = "invitations"
    INTEGRATION_TOKENS = "integration_tokens"
    OAUTH_STATES = "oauth_states"
    REGISTRATION_PROOFS = "registration_proofs"
    RESET_LINKS = "reset_links"
    EMAIL_CHANGE_PROOFS = "email_change_proofs"
    PROVIDER_FLOWS = "provider_flows"
    PROVIDER_IDENTITIES = "provider_identities"
    PROVIDER_SIGN_IN = "provider_sign_in_enablement"
    WATCH_REGISTRATIONS = "watch_registrations"
    INSTANT_SYNC_REQUESTS = "instant_sync_requests"
    DELIVERY_EVIDENCE = "delivery_evidence"
    IDENTITY_EMAIL_READINESS = "identity_email_readiness"


@dataclass(frozen=True)
class RestoreDecision:
    registration_policy: RegistrationPolicy
    administrator_id: UserId
    administrator_state: UserState
    other_user_state: UserState
    disconnect_accounts: bool
    invalidate: frozenset[RestoreAuthority]


def decide_restoration(
    policy: RegistrationPolicy, user_count: int, administrator: User | None
) -> RestoreDecision:
    if user_count <= 0 or administrator is None or not administrator.administers:
        raise DomainValidationError("restoration requires an existing administrator")
    if policy is RegistrationPolicy.OPEN:
        policy = (
            RegistrationPolicy.ONLY_ME if user_count == 1 else RegistrationPolicy.INVITATION_ONLY
        )
    return RestoreDecision(
        policy,
        administrator.id,
        UserState.ACTIVE,
        UserState.DISABLED,
        True,
        frozenset(RestoreAuthority),
    )
