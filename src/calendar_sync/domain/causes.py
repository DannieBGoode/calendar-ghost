"""Causes: why a provider call failed, and who fixes it (ADR 0031).

A Cause is read from the provider's own reason code by its adapter, never from its message text,
so it carries nothing a User's calendars or requests could put there.
"""

from __future__ import annotations

from enum import StrEnum


class CauseOwner(StrEnum):
    """Who fixes a Cause. An administrator never contacts a User about one of theirs."""

    ADMINISTRATOR = "administrator"
    """Only the installation's own registration with the provider can fix it."""
    USER = "user"
    """The User fixes it from their own dashboard, or it fixes itself."""


class Cause(StrEnum):
    API_DISABLED = "api_disabled"
    QUOTA_EXCEEDED = "quota_exceeded"
    OAUTH_CLIENT_INVALID = "oauth_client_invalid"
    ACCESS_REVOKED = "access_revoked"
    CALENDAR_FORBIDDEN = "calendar_forbidden"
    CALENDAR_NOT_FOUND = "calendar_not_found"
    RATE_LIMITED = "rate_limited"
    TEMPORARY = "temporary"
    UNKNOWN = "unknown"

    @property
    def owner(self) -> CauseOwner:
        return CauseOwner.ADMINISTRATOR if self in ADMINISTRATOR_CAUSES else CauseOwner.USER

    @classmethod
    def recorded(cls, value: object) -> Cause | None:
        """A stored Cause: none where a failure was recorded with no Cause, and unknown where
        nothing was stored, as before Causes, or a later release stored one this does not know."""
        return None if value == NO_CAUSE else cls.read(value)

    @classmethod
    def read(cls, value: object) -> Cause:
        """A recorded Cause; one recorded before Causes, or by a later release, is unknown."""
        if isinstance(value, str):
            try:
                return cls(value)
            except ValueError:
                return cls.UNKNOWN
        return cls.UNKNOWN


NO_CAUSE = "none"
"""What storage records for a failure no provider answer explains, apart from nothing at all."""

ADMINISTRATOR_CAUSES = frozenset(
    {Cause.API_DISABLED, Cause.QUOTA_EXCEEDED, Cause.OAUTH_CLIENT_INVALID}
)

# Failure kinds and Incident categories no provider refusal explains: a local failure, and events
# still blocked. They carry no Cause, even where an earlier release recorded one.
WITHOUT_CAUSE = frozenset({"infrastructure", "conflict"})
