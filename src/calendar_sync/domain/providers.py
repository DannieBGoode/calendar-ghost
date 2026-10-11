"""How a provider call failed: the kinds that decide retrying, stopping, and Lapsed
Authorization (ADR 0027)."""

from __future__ import annotations

from enum import StrEnum

from calendar_sync.domain.incidents import IncidentCategory


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
