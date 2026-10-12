"""How a provider call failed: the kinds that decide retrying, stopping, and Lapsed
Authorization (ADR 0027)."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.causes import Cause
from calendar_sync.domain.incidents import IncidentCategory
from calendar_sync.domain.model import ConnectedAccountId


class ProviderFailureKind(StrEnum):
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    RATE_LIMIT = "rate_limit"
    TEMPORARY = "temporary"
    PERMANENT = "permanent"
    INFRASTRUCTURE = "infrastructure"

    @property
    def incident_category(self) -> IncidentCategory:
        """The category of the Incidents a failure of this kind opens."""
        return IncidentCategory(self.value)


# Failures that only reauthorizing the Connected Account can resolve.
AUTHORIZATION_FAILURES = frozenset(
    {ProviderFailureKind.AUTHENTICATION, ProviderFailureKind.AUTHORIZATION}
)


# Failures a later attempt can resolve, so they are retried with backoff.
TRANSIENT_FAILURES = frozenset({ProviderFailureKind.RATE_LIMIT, ProviderFailureKind.TEMPORARY})


class ProviderFailureFacts(Protocol):
    """What the domain reads from a failed provider call. It holds no message text from the
    provider, so nothing it decides can carry event content (ADR 0031)."""

    @property
    def kind(self) -> ProviderFailureKind: ...

    @property
    def summary(self) -> str:
        """What failed, naming the provider's calendar service when it is known."""
        ...

    @property
    def account_id(self) -> ConnectedAccountId | None:
        """The Connected Account whose request failed, when the provider knows it."""
        ...

    @property
    def provider(self) -> ProviderKind | None: ...

    @property
    def provider_cause(self) -> Cause | None:
        """Why the provider refused; none for a local failure (ADR 0031)."""
        ...
