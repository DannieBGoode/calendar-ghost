"""Installation Hints: likely causes Installation Health suggests from patterns across Users.

A hint never comes from one User's content, and never for a Cause a User fixes themself: it names
its Cause and provider when it has them, how many Users show it, and where the troubleshooting
guide explains the fix (ADR 0031). Each provider's guide says which administrator's Causes it can
raise and any pattern only it explains. While any User wants Instant Sync, a public address the
providers cannot use, or a provider whose Delivery Evidence is failing, is a hint too (ADR 0036).
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from urllib.parse import urlsplit

from calendar_sync.application.operations.ports import CauseSighting, InstantSyncOwner
from calendar_sync.application.sync.provider_descriptors import GrantLifetime, ProviderGuide
from calendar_sync.application.sync.watch_ports import SyncCadencePolicy
from calendar_sync.domain.access import UserId
from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.causes import ADMINISTRATOR_CAUSES, Cause
from calendar_sync.domain.watches import DeliveryEvidence, DeliveryState

ADMINISTRATOR_CAUSE_USERS = 1
"""Only the administrator can fix their own Cause, so one User meeting it is enough to say so."""
HINTED_USERS = 2
"""How many Users must show a pattern, such as grants expiring together, before it is a hint
rather than one person's trouble."""
HINT_WINDOW = timedelta(hours=24)
"""How recent a failure must be to count, unless its Incident is still open."""
UNRECOGNIZED_ANCHOR = "reading-the-logs"
"""The service logs name a provider's reason Calendar Ghost does not recognize."""
PLAIN_HTTP_ANCHOR = "instant-sync-needs-an-https-public-address"
"""Providers send Watch Notices only to an https address."""
NOT_ARRIVING_ANCHOR = "calendar-providers-cannot-reach-the-installation"
"""A provider's notices do not reach the public address."""
LOCAL_SUFFIXES = (".localhost", ".local", ".lan", ".home.arpa", ".internal")
"""Host names that only resolve on this machine or inside a home network."""


class HintKind(StrEnum):
    SHARED_CAUSE = "shared_cause"
    """The same administrator's Cause for several Users."""
    TESTING_MODE = "testing_mode"
    """Several grants refused about as long after they were given as the provider keeps grants
    to an app registration in some setting, such as one still being tested."""
    UNRECOGNIZED = "unrecognized"
    """Several Users failing for a reason Calendar Ghost does not recognize."""
    PLAIN_HTTP_ADDRESS = "plain_http_address"
    """Users want Instant Sync, but the public address the internet reaches is plain http, which
    no provider sends Watch Notices to."""
    NOTICES_NOT_ARRIVING = "notices_not_arriving"
    """Users want Instant Sync, but a provider's Delivery Evidence for the public address is
    failing."""


@dataclass(frozen=True, slots=True)
class InstallationHint:
    kind: HintKind
    cause: Cause | None
    """The administrator's Cause the pattern shows; None for a hint about Instant Sync, which no
    failed provider call explains."""
    users: int
    """How many Users show the pattern; never who."""
    anchor: str
    """The section of the troubleshooting guide that explains the fix."""
    provider: ProviderKind | None = None
    """The provider whose answers show the pattern."""


@dataclass(frozen=True, slots=True)
class InstantSyncSignals:
    """What Installation Hints read about Instant Sync, as a count and Provider Kinds only."""

    wanting: int = 0
    """Users who may sign in, want Instant Sync, and whose Sync Cadence allows it."""
    plain_http: bool = False
    """The public address is plain http at a host the internet reaches."""
    failing: frozenset[ProviderKind] = frozenset()
    """Providers whose Delivery Evidence for the public address is failing."""


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


def instant_sync_signals(
    owners: Iterable[InstantSyncOwner],
    cadence: SyncCadencePolicy,
    address: str | None,
    evidence: Mapping[ProviderKind, DeliveryEvidence],
) -> InstantSyncSignals:
    """Who wants Instant Sync, and what keeps providers from the installation's public address.

    Plain http on this machine or a home network is the homelab norm and signals nothing: each
    User's switch already says Instant Sync needs a public address.
    """
    wanting = sum(1 for owner in owners if _wants_instant_sync(owner, cadence))
    if not wanting or address is None:
        return InstantSyncSignals(wanting)
    if urlsplit(address).scheme == "http":
        return InstantSyncSignals(wanting, plain_http=_internet_host(address))
    failing = frozenset(
        kind for kind, seen in evidence.items() if seen.state is DeliveryState.FAILING
    )
    return InstantSyncSignals(wanting, failing=failing)


def instant_sync_hints(
    signals: InstantSyncSignals, guides: Sequence[ProviderGuide]
) -> tuple[InstallationHint, ...]:
    """Hints about Instant Sync while anyone wants it: a plain http public address, or else each
    provider, in the guides' order, whose notices do not arrive."""
    if not signals.wanting:
        return ()
    if signals.plain_http:
        return (
            InstallationHint(HintKind.PLAIN_HTTP_ADDRESS, None, signals.wanting, PLAIN_HTTP_ANCHOR),
        )
    return tuple(
        InstallationHint(
            HintKind.NOTICES_NOT_ARRIVING, None, signals.wanting, NOT_ARRIVING_ANCHOR, guide.kind
        )
        for guide in guides
        if guide.kind in signals.failing
    )


def _wants_instant_sync(owner: InstantSyncOwner, cadence: SyncCadencePolicy) -> bool:
    return owner.wanted and not owner.disabled and cadence.cadence(owner.user).instant


def _internet_host(address: str) -> bool:
    """Whether the internet could reach the address's host: not this machine, not a name only a
    home network resolves, and not a private, shared, or local IP address."""
    host = (urlsplit(address).hostname or "").lower()
    local_name = host == "localhost" or ("." not in host and ":" not in host)
    if local_name or host.endswith(LOCAL_SUFFIXES):
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        return True


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
