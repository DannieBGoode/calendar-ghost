from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from calendar_sync.domain.model import SyncRuleId


class ApplicationError(Exception):
    """Base class for use-case failures."""


class RuleNotExecutable(ApplicationError):
    """A requested rule cannot currently execute."""


class RuleNotFound(ApplicationError):
    """The requested Directional Sync Rule does not exist."""


class DuplicateDirectionalRelationship(ApplicationError):
    """The same source-to-destination relationship already exists."""


class NotACalendarChange(ApplicationError):
    """A Rule Replacement was requested with the rule's current calendars."""


class RemovalRequiresProvider(ApplicationError):
    """Deleting projections needs a configured Google adapter."""


class RemovalRequiresAuthorization(ApplicationError):
    """Deleting projections needs an authorized destination account."""


class ProviderFailureKind(StrEnum):
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    RATE_LIMIT = "rate_limit"
    TEMPORARY = "temporary"
    PERMANENT = "permanent"
    INFRASTRUCTURE = "infrastructure"


@dataclass(frozen=True, slots=True)
class ProviderFailure(ApplicationError):
    kind: ProviderFailureKind
    detail: str
    retry_after_seconds: int | None = None

    @property
    def retryable(self) -> bool:
        return self.kind in {ProviderFailureKind.RATE_LIMIT, ProviderFailureKind.TEMPORARY}

    def __str__(self) -> str:
        return self.detail


class ProjectionOwnershipMismatch(ProviderFailure):
    """A destination event exists, but its Managed Origin metadata does not prove ownership."""

    def __init__(self, detail: str) -> None:
        super().__init__(ProviderFailureKind.PERMANENT, detail)


@dataclass(frozen=True, slots=True)
class RemovalInterrupted(ApplicationError):
    """Rule Removal stopped partway; the rule stays Disabled with its remaining mappings."""

    processed: int
    remaining: int
    failure: ProviderFailure

    def __str__(self) -> str:
        total = self.processed + self.remaining
        return (
            f"removal stopped after {self.processed} of {total} projections because Google "
            f"reported {self.failure.kind.value}; retry to continue"
        )


@dataclass(frozen=True, slots=True)
class ReplacementInterrupted(ApplicationError):
    """The replacement draft exists, but removing the previous rule stopped partway."""

    replacement_rule_id: SyncRuleId
    removal: RemovalInterrupted

    def __str__(self) -> str:
        return (
            "the new draft rule was created, but removing the previous rule stopped after "
            f"{self.removal.processed} of {self.removal.processed + self.removal.remaining} "
            "projections; open the previous rule to retry its removal"
        )


class InfrastructureFailure(ApplicationError):
    """A local adapter failed to fulfill its contract."""


class AdminAlreadyConfigured(ApplicationError):
    """The Installation Administrator already exists."""


class PasswordPolicyViolation(ApplicationError):
    """A proposed administrator password is too weak."""


class ConnectedAccountNotFound(ApplicationError):
    """The requested Connected Account does not exist."""


class ConnectedAccountDisconnected(ApplicationError):
    """The Connected Account has no stored credentials until it is reauthorized."""


class ConnectedAccountMustBeDisconnected(ApplicationError):
    """Only a Disconnected Account can be permanently deleted."""


class AuthorizationNotConfigured(ApplicationError):
    """The provider OAuth client is not configured for this installation."""


class InvalidAuthorizationState(ApplicationError):
    """An authorization callback's state is missing, expired, or already used."""


class AuthorizationFailed(ApplicationError):
    """The provider did not complete an authorization."""


class CalendarPermissionRequired(AuthorizationFailed):
    """An authorization was completed without the calendar permissions synchronization needs."""


class AccountAccessCheckFailed(ApplicationError):
    """The provider did not confirm a Connected Account's calendar access."""


class ActivityEventNotFound(ApplicationError):
    """The Activity entry does not exist or names no source event."""


class ActivityRuleRemoved(ApplicationError):
    """The Activity entry's rule was removed, so its calendars are no longer known."""


class EventInspectionUnavailable(ApplicationError):
    """Events cannot be read live without a configured calendar provider."""
