"""Instant Sync's Calendar Watches and Watch Registrations: values and decisions, no I/O.

A Calendar Watch is what one Connected Account's provider is asked to report changes to, for one
Watch Scope. Each Watch Registration is one channel or subscription the provider holds for it.
Writers move a registration between states only from a named state, so a late writer changes
nothing (ADR 0036).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

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
