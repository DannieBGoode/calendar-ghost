"""Installation Hints: likely causes Installation Health suggests from patterns across Users.

A hint never comes from one User's content, and never for a Cause a User fixes themself: it names
its Cause, how many Users show it, and where the troubleshooting guide explains the fix (ADR 0031).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from calendar_sync.application.causes import ADMINISTRATOR_CAUSES, Cause
from calendar_sync.application.ports import CauseSighting
from calendar_sync.domain.access import UserId

ADMINISTRATOR_CAUSE_USERS = 1
"""Only the administrator can fix their own Cause, so one User meeting it is enough to say so."""
HINTED_USERS = 2
"""How many Users must show a pattern, such as Testing mode, before it is a hint rather than one
person's trouble."""
HINT_WINDOW = timedelta(hours=24)
"""How recent a failure must be to count, unless its Incident is still open."""
TESTING_MODE_GRANT_LIFETIME = timedelta(days=7)
"""How long Google keeps a grant to an OAuth app whose publishing status is Testing."""
TESTING_MODE_TOLERANCE = timedelta(days=1)
"""How far from that lifetime a lapse still counts: Calendar Ghost notices a refused grant only
at its next refresh, and a scheduler that was down notices it later."""


class HintKind(StrEnum):
    SHARED_CAUSE = "shared_cause"
    """The same administrator's Cause for several Users."""
    TESTING_MODE = "testing_mode"
    """Several grants refused about 7 days after they were given."""
    UNRECOGNIZED = "unrecognized"
    """Several Users failing for a reason Calendar Ghost does not recognize."""


# Sections of docs/troubleshooting.md, by their GitHub heading anchors.
CAUSE_ANCHORS = {
    Cause.API_DISABLED: "the-google-calendar-api-is-turned-off",
    Cause.QUOTA_EXCEEDED: "the-google-cloud-projects-daily-quota-is-used-up",
    Cause.OAUTH_CLIENT_INVALID: "google-no-longer-accepts-the-oauth-client",
}
TESTING_MODE_ANCHOR = "google-accounts-stop-working-7-days-after-connecting"
UNRECOGNIZED_ANCHOR = "reading-the-logs"


@dataclass(frozen=True, slots=True)
class InstallationHint:
    kind: HintKind
    cause: Cause
    users: int
    """How many Users show the pattern; never who."""
    anchor: str
    """The section of the troubleshooting guide that explains the fix."""


def installation_hints(
    sightings: Iterable[CauseSighting], now: datetime
) -> tuple[InstallationHint, ...]:
    """Hints from every User's recent failures, in a stable order."""
    current = [seen for seen in sightings if seen.open or now - seen.at <= HINT_WINDOW]
    hints = [
        InstallationHint(HintKind.SHARED_CAUSE, cause, count, CAUSE_ANCHORS[cause])
        for cause in sorted(ADMINISTRATOR_CAUSES)
        if (count := _users(seen for seen in current if seen.cause is cause))
        >= ADMINISTRATOR_CAUSE_USERS
    ]
    testing = _users(seen for seen in current if _lapsed_like_testing_mode(seen))
    if testing >= HINTED_USERS:
        hints.append(
            InstallationHint(
                HintKind.TESTING_MODE, Cause.ACCESS_REVOKED, testing, TESTING_MODE_ANCHOR
            )
        )
    unrecognized = _users(seen for seen in current if seen.cause is Cause.UNKNOWN)
    if unrecognized >= HINTED_USERS:
        hints.append(
            InstallationHint(
                HintKind.UNRECOGNIZED, Cause.UNKNOWN, unrecognized, UNRECOGNIZED_ANCHOR
            )
        )
    return tuple(hints)


def _users(sightings: Iterable[CauseSighting]) -> int:
    distinct: set[UserId] = {seen.user for seen in sightings}
    return len(distinct)


def _lapsed_like_testing_mode(seen: CauseSighting) -> bool:
    """A grant still refused, and refused about when an app in Testing mode loses it."""
    return (
        seen.open
        and seen.cause is Cause.ACCESS_REVOKED
        and seen.authorized_for is not None
        and abs(seen.authorized_for - TESTING_MODE_GRANT_LIFETIME) <= TESTING_MODE_TOLERANCE
    )
