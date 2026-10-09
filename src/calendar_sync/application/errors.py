from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from calendar_sync.application.providers import ProviderKind
from calendar_sync.domain.model import ConnectedAccountId, SyncRuleId


class ApplicationError(Exception):
    """Base class for use-case failures."""


class RuleNotExecutable(ApplicationError):
    """A requested rule cannot currently execute."""


class RuleNotFound(RuleNotExecutable):
    """The requested Directional Sync Rule does not exist, or is another User's (ADR 0029)."""


class DuplicateDirectionalRelationship(ApplicationError):
    """The same source-to-destination relationship already exists."""


class NotACalendarChange(ApplicationError):
    """A Rule Replacement was requested with the rule's current calendars."""


class RemovalRequiresProvider(ApplicationError):
    """Deleting projections needs a configured calendar provider."""


class RemovalRequiresAuthorization(ApplicationError):
    """Deleting projections needs an authorized destination account."""


class ProviderFailureKind(StrEnum):
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    RATE_LIMIT = "rate_limit"
    TEMPORARY = "temporary"
    PERMANENT = "permanent"
    INFRASTRUCTURE = "infrastructure"


# Failures that only reauthorizing the Connected Account can resolve.
AUTHORIZATION_FAILURES = frozenset(
    {ProviderFailureKind.AUTHENTICATION, ProviderFailureKind.AUTHORIZATION}
)
# Failures a later attempt can resolve, so they are retried with backoff.
TRANSIENT_FAILURES = frozenset({ProviderFailureKind.RATE_LIMIT, ProviderFailureKind.TEMPORARY})


_FAILURE_SUMMARIES = {
    ProviderFailureKind.AUTHENTICATION: "Authorization for {calendar} expired",
    ProviderFailureKind.AUTHORIZATION: "Access to {calendar} was denied",
    ProviderFailureKind.RATE_LIMIT: "{Calendar} is limiting requests",
    ProviderFailureKind.TEMPORARY: "{Calendar} is temporarily unavailable",
    ProviderFailureKind.PERMANENT: "{Calendar} rejected synchronization",
    ProviderFailureKind.INFRASTRUCTURE: "Local synchronization infrastructure failed",
}


@dataclass(frozen=True, slots=True)
class ProviderFailure(ApplicationError):
    kind: ProviderFailureKind
    detail: str
    retry_after_seconds: int | None = None
    account_id: ConnectedAccountId | None = None
    """The Connected Account whose request failed, when the provider knows it."""
    provider: ProviderKind | None = None
    """The provider that failed, when the adapter names it, so incidents can (ADR 0022)."""
    attempted_at: datetime | None = None
    """When the failed request read the account's credentials, when the adapter knows it, so a
    refusal of credentials since replaced is told apart from one of the current ones (ADR 0027)."""

    @property
    def retryable(self) -> bool:
        return self.kind in TRANSIENT_FAILURES

    @property
    def requires_authorization(self) -> bool:
        return self.kind in AUTHORIZATION_FAILURES

    @property
    def provider_name(self) -> str:
        """How messages name the failed provider: "Google Calendar", or a neutral phrase."""
        return self.provider.calendar_name if self.provider else "the calendar provider"

    @property
    def summary(self) -> str:
        """What failed, naming the provider when the failure says which one (ADR 0022)."""
        calendar = self.provider_name
        return _FAILURE_SUMMARIES[self.kind].format(
            calendar=calendar, Calendar=calendar[0].upper() + calendar[1:]
        )

    def __str__(self) -> str:
        return self.detail


class ProjectionOwnershipMismatch(ProviderFailure):
    """A destination event exists, but its Managed Origin metadata does not prove ownership."""

    def __init__(self, detail: str, *, provider: ProviderKind | None = None) -> None:
        super().__init__(ProviderFailureKind.PERMANENT, detail, provider=provider)


@dataclass(frozen=True, slots=True)
class RemovalInterrupted(ApplicationError):
    """Rule Removal stopped partway; the rule stays in Removing with its remaining mappings."""

    processed: int
    remaining: int
    failure: ProviderFailure

    def __str__(self) -> str:
        total = self.processed + self.remaining
        return (
            f"removal stopped after {self.processed} of {total} projections because "
            f"{self.failure.provider_name} reported {self.failure.kind.value}; retry to continue"
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


class ConnectedAccountRequired(ApplicationError):
    """A new rule names a Connected Account this installation does not have."""


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

    def __init__(
        self, detail: str, kind: ProviderFailureKind = ProviderFailureKind.PERMANENT
    ) -> None:
        super().__init__(detail)
        self.kind = kind
        """How the provider refused, so an authorization refusal can lapse the account."""


class ActivityEventNotFound(ApplicationError):
    """The Activity entry does not exist or names no source event."""


class ActivityRuleRemoved(ApplicationError):
    """The Activity entry's rule was removed, so its calendars are no longer known."""


class EventInspectionUnavailable(ApplicationError):
    """Events cannot be read live without a configured calendar provider."""


class InvalidActivityAge(ApplicationError):
    """Activity can be cleared only from one of the offered ages."""


STORAGE_BUSY_MESSAGE = (
    "Old Activity was cleared, but its space could not be reclaimed while a rule is "
    "synchronizing. Try again when it finishes."
)


class StorageBusy(ApplicationError):
    """Rule work kept the database from being compacted.

    Raised by the storage use case when a rule's lock cannot be acquired before its deadline, and
    by the SQLite adapter when `VACUUM` itself reports the database is locked -- a database user
    rule locks do not cover, such as a lifecycle change, Activity read, or health write.
    """


class FileLoggingOff(ApplicationError):
    """The installation keeps no log files to read or purge."""


class InvalidIntegrationTokenName(ValueError):
    """An Integration Token name must be 1 to 80 printable characters."""
