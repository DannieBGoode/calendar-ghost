"""The calendar services Connected Accounts can belong to (ADR 0022).

Provider-neutral code names a provider only by its Provider Kind. What a provider is called, and
everything else about it, comes from the descriptor its own package composes (ADR 0022).
"""

from __future__ import annotations

from enum import StrEnum


class ProviderKind(StrEnum):
    """The calendar service a Connected Account belongs to; stored, so values never change."""

    GOOGLE = "google"

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
