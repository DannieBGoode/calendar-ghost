"""Connected Accounts and the calendar services they belong to (ADR 0022)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from calendar_sync.domain.model import ConnectedAccountId


class ProviderKind(StrEnum):
    """The calendar service a Connected Account belongs to; stored, so values never change."""

    GOOGLE = "google"

    @property
    def calendar_name(self) -> str:
        """How messages name the service, such as "Google Calendar"."""
        return _CALENDAR_NAMES[self]


_CALENDAR_NAMES = {ProviderKind.GOOGLE: "Google Calendar"}


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
    authorized_at: str | None = None
    """When the account was last connected or reauthorized; None while disconnected."""
    provider: ProviderKind = field(kw_only=True)
    """The calendar service the account belongs to; it never changes (ADR 0022)."""
    authorization_lapsed_at: str | None = field(default=None, kw_only=True)
    """While the provider refuses a connected account's credentials, when the latest refused
    request began; None while it accepts them (ADR 0027)."""
