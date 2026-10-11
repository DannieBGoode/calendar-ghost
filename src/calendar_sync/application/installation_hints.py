"""Installation Hints: likely causes Installation Health suggests from patterns across Users.

A hint never comes from one User's content, and never for a Cause a User fixes themself: it names
its Cause and provider, how many Users show it, and where the troubleshooting guide explains the
fix (ADR 0031). Each provider's guide says which administrator's Causes it can raise and any
pattern only it explains.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from calendar_sync.application.causes import ADMINISTRATOR_CAUSES, Cause
from calendar_sync.application.ports import CauseSighting
from calendar_sync.application.provider_descriptors import GrantLifetime, ProviderGuide
from calendar_sync.application.providers import ProviderKind
from calendar_sync.domain.access import UserId

ADMINISTRATOR_CAUSE_USERS = 1
"""Only the administrator can fix their own Cause, so one User meeting it is enough to say so."""
HINTED_USERS = 2
"""How many Users must show a pattern, such as grants expiring together, before it is a hint
rather than one person's trouble."""
HINT_WINDOW = timedelta(hours=24)
"""How recent a failure must be to count, unless its Incident is still open."""
UNRECOGNIZED_ANCHOR = "reading-the-logs"
"""The service logs name a provider's reason Calendar Ghost does not recognize."""


class HintKind(StrEnum):
    SHARED_CAUSE = "shared_cause"
    """The same administrator's Cause for several Users."""
    TESTING_MODE = "testing_mode"
    """Several grants refused about as long after they were given as the provider keeps grants
    to an app registration in some setting, such as one still being tested."""
    UNRECOGNIZED = "unrecognized"
    """Several Users failing for a reason Calendar Ghost does not recognize."""


@dataclass(frozen=True, slots=True)
class InstallationHint:
    kind: HintKind
    cause: Cause
    users: int
    """How many Users show the pattern; never who."""
    anchor: str
    """The section of the troubleshooting guide that explains the fix."""
    provider: ProviderKind | None = None
    """The provider whose answers show the pattern."""


def installation_hints(
    sightings: Iterable[CauseSighting], now: datetime, guides: Sequence[ProviderGuide]
) -> tuple[InstallationHint, ...]:
    """Hints from every User's recent failures, per provider in the guides' order.

    A failure of a provider without a guide, such as one a later release recorded, hints nothing.
    """
    current = [seen for seen in sightings if seen.open or now - seen.at <= HINT_WINDOW]
    hints: list[InstallationHint] = []
    for guide in guides:
        hints.extend(_provider_hints([s for s in current if s.provider is guide.kind], guide))
    return tuple(hints)


def _provider_hints(
    sightings: Sequence[CauseSighting], guide: ProviderGuide
) -> list[InstallationHint]:
    hints = [
        InstallationHint(HintKind.SHARED_CAUSE, cause, count, anchor, guide.kind)
        for cause in sorted(ADMINISTRATOR_CAUSES)
        if (anchor := guide.cause_anchors.get(cause)) is not None
        and (count := _users(seen for seen in sightings if seen.cause is cause))
        >= ADMINISTRATOR_CAUSE_USERS
    ]
    lifetime = guide.grant_lifetime
    if lifetime is not None:
        lapsed = _users(seen for seen in sightings if _lapsed_at_lifetime(seen, lifetime))
        if lapsed >= HINTED_USERS:
            hints.append(
                InstallationHint(
                    HintKind.TESTING_MODE, Cause.ACCESS_REVOKED, lapsed, lifetime.anchor, guide.kind
                )
            )
    unrecognized = _users(seen for seen in sightings if seen.cause is Cause.UNKNOWN)
    if unrecognized >= HINTED_USERS:
        hints.append(
            InstallationHint(
                HintKind.UNRECOGNIZED, Cause.UNKNOWN, unrecognized, UNRECOGNIZED_ANCHOR, guide.kind
            )
        )
    return hints


def _users(sightings: Iterable[CauseSighting]) -> int:
    distinct: set[UserId] = {seen.user for seen in sightings}
    return len(distinct)


def _lapsed_at_lifetime(seen: CauseSighting, lifetime: GrantLifetime) -> bool:
    """A grant still refused, and refused about when the provider's grant lifetime ends."""
    return (
        seen.open
        and seen.cause is Cause.ACCESS_REVOKED
        and seen.authorized_for is not None
        and abs(seen.authorized_for - lifetime.lifetime) <= lifetime.tolerance
    )
