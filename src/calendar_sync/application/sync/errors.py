"""Errors of synchronization: rules, Connected Accounts, and provider calls."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from calendar_sync.application.shared.errors import ApplicationError
from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.causes import Cause
from calendar_sync.domain.model import ConnectedAccountId, SyncRuleId
from calendar_sync.domain.providers import ProviderFailureKind


class RuleNotExecutable(ApplicationError):
    """A requested rule cannot currently execute."""


class RuleNotFound(RuleNotExecutable):
    """The requested Directional Sync Rule does not exist, or is another User's (ADR 0029)."""


class RecordRefused(ApplicationError):
    """A unit of work refused a write that would break what its records must keep true.

    Every store raises one of these subclasses, at the write or when the unit commits, so a use
    case can handle a refusal without knowing which store refused it.
    """


class DuplicateDirectionalRelationship(RecordRefused):
    """The same source-to-destination relationship already exists."""


class IdentityCollision(RecordRefused):
    """An identifier, or another key only one record may hold, already names a different record,
    which may be another User's."""


class MissingReference(RecordRefused):
    """A record names a rule, Event Mapping, or Connected Account that does not exist, or that is
    another User's (ADR 0029)."""


class NotACalendarChange(ApplicationError):
    """A Rule Replacement was requested with the rule's current calendars."""


class RemovalRequiresProvider(ApplicationError):
    """Deleting projections needs a configured calendar provider."""


class RemovalRequiresAuthorization(ApplicationError):
    """Deleting projections needs an authorized destination account."""


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
    cause: Cause | None = None
    """Why the provider refused, from its reason code, so its owner can be told (ADR 0031); set
    only from a provider's answer, so a failure an adapter or Calendar Ghost raises itself has
    none."""
    provider_label: str | None = None
    """How English messages name the provider's calendar service, from its descriptor; the
    adapter that names `provider` sets it (ADR 0022)."""

    @property
    def provider_cause(self) -> Cause | None:
        """The Cause to record: none for a local failure, which no provider refused, so it is
        never mistaken for a provider reason Calendar Ghost does not recognize (ADR 0031)."""
        return None if self.kind is ProviderFailureKind.INFRASTRUCTURE else self.cause

    @property
    def retryable(self) -> bool:
        return self.kind in TRANSIENT_FAILURES

    @property
    def requires_authorization(self) -> bool:
        return self.kind in AUTHORIZATION_FAILURES

    @property
    def provider_name(self) -> str:
        """How messages name the failed provider: its calendar service, or a neutral phrase."""
        return self.provider_label or "the calendar provider"

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

    def __init__(
        self,
        detail: str,
        *,
        provider: ProviderKind | None = None,
        provider_label: str | None = None,
    ) -> None:
        super().__init__(
            ProviderFailureKind.PERMANENT, detail, provider=provider, provider_label=provider_label
        )


class UnsupportedProjection(ApplicationError):
    """The destination's provider cannot hold this projection exactly, such as a recurrence it
    cannot repeat or an occurrence it cannot restore. It is never approximated: the run blocks
    that one event as a Conflict and keeps synchronizing the rest (ADR 0034)."""


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
        self,
        detail: str,
        kind: ProviderFailureKind = ProviderFailureKind.PERMANENT,
        cause: Cause | None = None,
        provider: ProviderKind | None = None,
    ) -> None:
        super().__init__(detail)
        self.kind = kind
        """How the provider refused, so an authorization refusal can lapse the account."""
        self.cause = cause
        """Why the provider refused, so the lapse it records says who fixes it (ADR 0031)."""
        self.provider = provider
        """Which provider refused, so a message can name it; the router sets it."""
