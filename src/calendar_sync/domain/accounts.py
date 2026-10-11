"""Connected Accounts and the calendar services they belong to (ADR 0022).

Provider-neutral code names a provider only by its Provider Kind. What a provider is called, and
everything else about it, comes from the descriptor its own package composes (ADR 0022).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from calendar_sync.domain.model import ConnectedAccountId


class ProviderKind(StrEnum):
    """The calendar service a Connected Account belongs to; stored, so values never change."""

    GOOGLE = "google"
    OUTLOOK = "outlook"

    @classmethod
    def recorded(cls, value: object) -> ProviderKind | None:
        """A stored Provider Kind; None where none was stored, or a later release stored one this
        release does not know."""
        if isinstance(value, str):
            try:
                return cls(value)
            except ValueError:
                return None
        return None


class ConnectedAccountState(StrEnum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"


@dataclass(frozen=True, slots=True)
class ConnectedAccount:
    id: ConnectedAccountId
    display_name: str
    email: str
    state: ConnectedAccountState
    avatar_url: str | None = None
    authorized_at: datetime | None = None
    """When the account was last connected or reauthorized; None while disconnected."""
    provider: ProviderKind = field(kw_only=True)
    """The calendar service the account belongs to; it never changes (ADR 0022)."""
    authorization_lapsed_at: datetime | None = field(default=None, kw_only=True)
    """While the provider refuses a connected account's credentials, when the latest refused
    request began; None while it accepts them (ADR 0027)."""
