from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


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


class InfrastructureFailure(ApplicationError):
    """A local adapter failed to fulfill its contract."""
