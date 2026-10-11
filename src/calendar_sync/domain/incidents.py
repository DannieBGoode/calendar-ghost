"""Incidents: what Calendar Ghost reports when a rule or account needs attention."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from calendar_sync.domain.causes import Cause
from calendar_sync.domain.model import ConnectedAccountId, SyncRuleId


@dataclass(frozen=True, slots=True)
class IncidentMessage:
    """What an Incident says, as a stable code and parameters the Web UI translates (ADR 0026)."""

    code: str
    params: Mapping[str, str | int | None] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class IncidentReport:
    """An Incident to open or refresh; repeated reports under one key update one Incident."""

    key: str
    rule_id: SyncRuleId | None
    """None for an Incident about a Connected Account rather than one rule."""
    category: str
    summary: str
    """Operational wording only; never an event title or other event content."""
    account_id: ConnectedAccountId | None = None
    """The Connected Account whose failure opened or last refreshed the Incident, if known."""
    message: IncidentMessage | None = None
    """The summary as a code and parameters; the English `summary` stays for email and logs."""
    cause: Cause | None = None
    """Why the provider failure behind it happened, when one did (ADR 0031)."""


class IncidentResolution(StrEnum):
    """Why an Incident resolved, so Activity can tell recovery apart from removal."""

    SYNC_SUCCEEDED = "sync_succeeded"
    BLOCKS_CLEARED = "blocks_cleared"
    RULE_REMOVED = "rule_removed"
    ACCESS_RESTORED = "access_restored"
    """The account's Lapsed Authorization cleared (ADR 0027)."""
