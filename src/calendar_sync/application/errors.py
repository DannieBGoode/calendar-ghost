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


class InfrastructureFailure(ApplicationError):
    """A local adapter failed to fulfill its contract."""
