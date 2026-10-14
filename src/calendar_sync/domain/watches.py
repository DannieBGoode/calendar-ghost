"""Instant Sync's Calendar Watches and Watch Registrations: values and decisions, no I/O.

A Calendar Watch is what one Connected Account's provider is asked to report changes to, for one
Watch Scope. Each Watch Registration is one channel or subscription the provider holds for it.
Writers move a registration between states only from a named state, so a late writer changes
nothing (ADR 0036).
"""

from __future__ import annotations

import hashlib
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from types import MappingProxyType

from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.cadence import SyncCadence
from calendar_sync.domain.errors import DomainValidationError
from calendar_sync.domain.model import CalendarEndpoint, CalendarId, ConnectedAccountId

CREATION_DEADLINE = timedelta(minutes=10)
"""How long a registration may stay `creating` before upkeep counts its answer lost."""
CONFIRMATION_DEADLINE = timedelta(minutes=2)
"""How soon a provider that reaches the installation confirms a new registration."""
LONGEST_REGISTRATION = timedelta(days=7)
"""How long upkeep asks a provider to keep a registration; a provider may keep it for less."""
MAX_BACKOFF = timedelta(days=1)
"""The longest a watch waits after failures before upkeep calls its provider again."""

_FIRST_BACKOFF = timedelta(minutes=1)
# Doublings after which the first backoff already exceeds the longest, so a long run of failures
# never computes an interval too large to represent.
_LAST_DOUBLING = 11
_ACCOUNT_SCOPE = "account"
_CALENDAR_PREFIX = "calendar:"


def _require_non_empty(value: str, label: str) -> None:
    if not value or value.isspace():
        raise DomainValidationError(f"{label} must not be empty")


@dataclass(frozen=True, slots=True)
class CalendarWatchId:
    value: str

    def __post_init__(self) -> None:
        _require_non_empty(self.value, "calendar watch id")


@dataclass(frozen=True, slots=True)
class WatchRegistrationId:
    """Names a registration in the address its provider delivers notices to.

    Upkeep generates 32 lowercase hex characters, so the address reveals nothing else.
    """

    value: str

    def __post_init__(self) -> None:
        _require_non_empty(self.value, "watch registration id")


@dataclass(frozen=True, slots=True)
class WatchScope:
    """What one watch covers, as its provider's adapter decides: one calendar, or an account."""

    key: str
    """`account`, or `calendar:` followed by the calendar's id; stored, so the form never
    changes."""

    def __post_init__(self) -> None:
        if self.key == _ACCOUNT_SCOPE:
            return
        if not self.key.startswith(_CALENDAR_PREFIX):
            raise DomainValidationError("a watch scope covers an account or one calendar")
        _require_non_empty(self.key.removeprefix(_CALENDAR_PREFIX), "watched calendar id")

    @classmethod
    def account(cls) -> WatchScope:
        """Every calendar of the Connected Account, as one subscription watches a mailbox."""
        return cls(_ACCOUNT_SCOPE)

    @classmethod
    def calendar(cls, calendar_id: CalendarId) -> WatchScope:
        """One calendar, as one channel watches it."""
        return cls(_CALENDAR_PREFIX + calendar_id.value)

    @property
    def calendar_id(self) -> CalendarId | None:
        """The calendar a calendar scope covers; None for a whole account."""
        if self.key == _ACCOUNT_SCOPE:
            return None
        return CalendarId(self.key.removeprefix(_CALENDAR_PREFIX))


class RegistrationState(StrEnum):
    """Where a registration is in its life; stored, so values never change."""

    CREATING = "creating"
    """Persisted before its provider was asked for it; the answer is not recorded yet."""
    LIVE = "live"
    """The provider holds it, and it is the watch's current registration."""
    RETIRING = "retiring"
    """Replaced or removed; its notices still count until it is stopped or expires."""
    ABANDONED = "abandoned"
    """Its answer was lost or its stop failed; its notices are recognized and ignored until it
    would expire."""


@dataclass(frozen=True, slots=True)
class WatchRegistration:
    """One channel or subscription a provider holds for a watch.

    Only a hash of its secret token is kept. The provider's handle is opaque outside its adapter.
    """

    id: WatchRegistrationId
    watch_id: CalendarWatchId
    state: RegistrationState
    address: str
    """The full notice address it points at, which names its id."""
    token_hash: str
    created_at: datetime
    requested_until: datetime
    """When upkeep asked the provider to end it."""
    handle: str | None = None
    """The provider's identifiers for it; None until the provider answered."""
    expires_at: datetime | None = None
    """When the provider said it ends; None until the provider answered."""
    confirmed_at: datetime | None = None
    """When the provider first proved it reaches the installation through it."""
    renew_at: datetime | None = None
    """When upkeep renews it, fixed with jitter once its expiry is known."""
    renew_requested_at: datetime | None = None
    """When its provider asked for it to be renewed early."""

    def usable(self, now: datetime, address: str) -> bool:
        """Whether it is live, unexpired, and points at `address`."""
        return (
            self.state is RegistrationState.LIVE
            and self.address == address
            and self.expires_at is not None
            and self.expires_at > now
        )

    def delivering(self, now: datetime) -> bool:
        """Whether notices arrive through it: live, unexpired, and confirmed."""
        return (
            self.state is RegistrationState.LIVE
            and self.confirmed_at is not None
            and self.expires_at is not None
            and self.expires_at > now
        )

    def creation_stale(self, now: datetime) -> bool:
        """Whether it was persisted so long ago that its provider's answer is lost."""
        return self.state is RegistrationState.CREATING and now - self.created_at >= (
            CREATION_DEADLINE
        )

    def confirmation_overdue(self, now: datetime) -> bool:
        """Whether its provider has not confirmed it within the deadline after creation."""
        return (
            self.state is RegistrationState.LIVE
            and self.confirmed_at is None
            and now - self.created_at >= CONFIRMATION_DEADLINE
        )

    def renewal_due(self, now: datetime) -> bool:
        """Whether upkeep renews it now: its renewal time passed, or its provider asked."""
        return self.state is RegistrationState.LIVE and (
            self.renew_requested_at is not None
            or (self.renew_at is not None and self.renew_at <= now)
        )

    def gone(self, now: datetime) -> bool:
        """Whether its provider no longer keeps it, so its row can be deleted.

        A registration being created is never gone: its row turns abandoned first, so its notices
        stay recognized until it would have expired.
        """
        if self.state is RegistrationState.CREATING:
            return False
        return (self.expires_at or self.requested_until) <= now


@dataclass(frozen=True, slots=True)
class CalendarWatch:
    """One Connected Account's watch for one Watch Scope, and the calendars it covers.

    Notices it receives wake only rules whose Source Calendar it covers.
    """

    id: CalendarWatchId
    account: ConnectedAccountId
    scope: WatchScope
    coverage: frozenset[CalendarId] = frozenset()
    """The Source Calendars its scope covers, as upkeep last found them watchable."""
    retry_at: datetime | None = None
    """Until when upkeep leaves it alone after failures; None when it may call now."""
    failures: int = 0
    """Consecutive failed provider calls, which set how long it waits."""

    def covers(self, calendar: CalendarEndpoint) -> bool:
        return (
            calendar.connected_account_id == self.account and calendar.calendar_id in self.coverage
        )

    def waiting(self, now: datetime) -> bool:
        """Whether it is still waiting out a backoff."""
        return self.retry_at is not None and self.retry_at > now


def renewal_time(created_at: datetime, expires_at: datetime, jitter: float) -> datetime:
    """When to renew a registration: a point in the last third of its lifetime.

    It starts at the last third and adds `jitter` times a sixth of the lifetime, so registrations
    made together are not all renewed together. Jitter is chosen once, in [0, 1).
    """
    if not 0 <= jitter < 1:
        raise DomainValidationError("renewal jitter must be at least 0 and below 1")
    lifetime = expires_at - created_at
    return created_at + lifetime * 2 / 3 + lifetime / 6 * jitter


def backoff(failures: int, retry_after: timedelta | None = None) -> timedelta:
    """How long a watch waits after `failures` consecutive failures.

    One minute after the first, doubling up to a day, and never less than the provider asked.
    """
    if failures < 1:
        raise DomainValidationError("backoff follows at least one failure")
    delay = min(MAX_BACKOFF, _FIRST_BACKOFF * (1 << min(failures - 1, _LAST_DOUBLING)))
    return delay if retry_after is None else max(delay, retry_after)


def token_hash(token: str) -> str:
    """The hash a registration keeps of its secret token, so the store never holds the token."""
    return hashlib.sha256(token.encode()).hexdigest()


class DeliveryState(StrEnum):
    """Whether a provider's notices reach the installation's public address."""

    UNKNOWN = "unknown"
    """No evidence yet for this address."""
    WORKING = "working"
    FAILING = "failing"


@dataclass(frozen=True, slots=True)
class DeliveryEvidence:
    """The latest proof that one provider's notices reach one public address, and the latest
    sign that they do not."""

    provider: ProviderKind
    address: str
    last_success_at: datetime | None = None
    """An authenticated notice, or a creation that itself proves delivery."""
    last_failure_at: datetime | None = None
    """A registration not confirmed in time, or a provider that could not reach the address."""

    @property
    def state(self) -> DeliveryState:
        """Failing when the latest failure is newer than the latest success."""
        if self.last_failure_at is not None and (
            self.last_success_at is None or self.last_failure_at > self.last_success_at
        ):
            return DeliveryState.FAILING
        if self.last_success_at is not None:
            return DeliveryState.WORKING
        return DeliveryState.UNKNOWN


class Availability(StrEnum):
    """Whether a User's rules may sync instantly, or the one reason they may not."""

    ON = "on"
    OFF_BY_USER = "off_by_user"
    NOT_IN_PLAN = "not_in_plan"
    NO_PUBLIC_ADDRESS = "no_public_address"
    NOT_REACHING = "not_reaching"


AVAILABILITY_ANCHORS: Mapping[Availability, str] = MappingProxyType(
    {
        Availability.NOT_IN_PLAN: "not-in-your-plan",
        Availability.NO_PUBLIC_ADDRESS: "no-public-https-address",
        Availability.NOT_REACHING: "providers-cannot-reach-the-installation",
    }
)
"""The section of docs/instant-sync.md that explains each reason only an administrator or a Plan
can change."""


def instant_sync_availability(
    *,
    address_is_https: bool,
    cadence: SyncCadence,
    wanted: bool,
    delivery: Collection[DeliveryState],
) -> Availability:
    """Whether a User's rules may sync instantly, with the first reason that stops them.

    `delivery` holds the Delivery State of each provider the User's watched sources use. Providers
    are known not to reach the installation only when at least one is used and every one used is
    failing; a User with no watchable source is on.
    """
    if not address_is_https:
        return Availability.NO_PUBLIC_ADDRESS
    if not cadence.instant:
        return Availability.NOT_IN_PLAN
    if not wanted:
        return Availability.OFF_BY_USER
    if delivery and all(state is DeliveryState.FAILING for state in delivery):
        return Availability.NOT_REACHING
    return Availability.ON


class CadenceReason(StrEnum):
    """How a rule syncs now: instantly, or on schedule for one reason."""

    INSTANT = "instant"
    NOT_WATCHABLE = "not_watchable"
    """Upkeep found that its Source Calendar's provider cannot watch it, such as a calendar
    shared from another mailbox."""
    WAITING_FOR_PROVIDER = "waiting_for_provider"
    """No registration has proved yet that notices arrive: upkeep has not watched its source
    yet, or its provider has not confirmed the watch."""
    OFF_BY_USER = "off_by_user"
    NOT_IN_PLAN = "not_in_plan"
    NO_PUBLIC_ADDRESS = "no_public_address"
    NOT_REACHING = "not_reaching"


_AVAILABILITY_REASONS: Mapping[Availability, CadenceReason] = MappingProxyType(
    {
        Availability.OFF_BY_USER: CadenceReason.OFF_BY_USER,
        Availability.NOT_IN_PLAN: CadenceReason.NOT_IN_PLAN,
        Availability.NO_PUBLIC_ADDRESS: CadenceReason.NO_PUBLIC_ADDRESS,
        Availability.NOT_REACHING: CadenceReason.NOT_REACHING,
    }
)


def effective_cadence(
    availability: Availability,
    watch: CalendarWatch | None,
    registrations: Collection[WatchRegistration],
    now: datetime,
    *,
    unwatchable: bool = False,
) -> CadenceReason:
    """How a rule syncs now, given its owner's availability and the watch covering its source.

    It syncs instantly only while one of that watch's registrations is delivering. A source no
    watch covers is `unwatchable` only when upkeep found that its provider cannot watch it; until
    upkeep reaches a new or resumed rule, it waits for the provider like one being watched.
    """
    if availability is not Availability.ON:
        return _AVAILABILITY_REASONS[availability]
    if watch is None:
        return CadenceReason.NOT_WATCHABLE if unwatchable else CadenceReason.WAITING_FOR_PROVIDER
    if any(
        registration.watch_id == watch.id and registration.delivering(now)
        for registration in registrations
    ):
        return CadenceReason.INSTANT
    return CadenceReason.WAITING_FOR_PROVIDER
