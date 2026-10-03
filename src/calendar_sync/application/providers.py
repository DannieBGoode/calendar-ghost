"""The calendar services Connected Accounts can belong to (ADR 0022)."""

from __future__ import annotations

from enum import StrEnum


class ProviderKind(StrEnum):
    """The calendar service a Connected Account belongs to; stored, so values never change."""

    GOOGLE = "google"

    @property
    def calendar_name(self) -> str:
        """How messages name the service, such as "Google Calendar"."""
        return _CALENDAR_NAMES[self]


_CALENDAR_NAMES = {ProviderKind.GOOGLE: "Google Calendar"}
