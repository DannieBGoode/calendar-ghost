"""Connected Account records, authorization, and calendar discovery ports."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from calendar_sync.domain.access import UserId
from calendar_sync.domain.accounts import ConnectedAccount, ConnectedAccountState, ProviderKind
from calendar_sync.domain.model import CalendarEndpoint, ConnectedAccountId


class CalendarNameRepository(Protocol):
    """The name each calendar last had in its provider, so a rule is named before it answers."""

    def remember(
        self, account_id: ConnectedAccountId, calendars: Sequence[DiscoveredCalendar]
    ) -> None:
        """Record the listed calendars' names, writing only names that changed.

        A calendar no longer listed keeps its last name, so a rule that uses it is still named.
        Nothing is recorded for an account that no longer exists.
        """
        ...

    def names(self, endpoints: Collection[CalendarEndpoint]) -> Mapping[CalendarEndpoint, str]:
        """The last name recorded for each of `endpoints`, omitting those never listed."""
        ...


class ConnectedAccountRecords(Protocol):
    """Connected Account records inside a unit of work, without their credentials."""

    def state(self, account_id: ConnectedAccountId) -> ConnectedAccountState | None: ...

    def lapse(self, account_id: ConnectedAccountId, *, attempted_at: datetime) -> bool:
        """Record Lapsed Authorization for a refused request begun at `attempted_at`; whether it
        lapsed.

        True when the connected account is lapsed now, newly or already; the lapse keeps the
        start of the latest refused request. A request made before the account was last
        authorized used superseded credentials, so its refusal lapses nothing.
        """
        ...

    def clear_lapse(self, account_id: ConnectedAccountId, *, requested_before: datetime) -> bool:
        """Clear a Lapsed Authorization whose refused requests all began before `requested_before`,
        when a request begun then was accepted; whether it cleared one.

        A refusal of a request begun later stands, so the lapse does.
        """
        ...

    def authorized(self, account_id: ConnectedAccountId) -> bool:
        """Whether the account is connected and its authorization has not lapsed."""
        ...

    def lapsed(self) -> Mapping[ConnectedAccountId, ProviderKind]:
        """Every connected account whose authorization has lapsed, with its Provider Kind."""
        ...

    def delete_disconnected(self, account_id: ConnectedAccountId) -> bool:
        """Delete the account if it is disconnected; whether it was.

        Once this deletes, no other writer can change the installation until the unit of work
        ends, so a reauthorization or new rule cannot slip in before it commits.
        """
        ...


class AccountAuthorizations(Protocol):
    def is_connected(self, account_id: ConnectedAccountId) -> bool: ...


class ConnectedAccountRepository(AccountAuthorizations, Protocol):
    def list(self) -> Sequence[ConnectedAccount]:
        """Every Connected and Disconnected Account, ordered by email."""
        ...

    def get(self, account_id: ConnectedAccountId) -> ConnectedAccount | None: ...

    def disconnect(self, account_id: ConnectedAccountId) -> ConnectedAccount:
        """Discard the account's credentials, keeping its identity for Reauthorization."""
        ...


class CalendarAccess(StrEnum):
    """What a Connected Account may do with a calendar, in provider-neutral terms."""

    OWNER = "owner"
    WRITER = "writer"
    READER = "reader"
    FREE_BUSY = "free_busy"
    """Sees when the calendar is busy, but not what its events are."""

    @property
    def writable(self) -> bool:
        """Whether rules may write projections to a calendar with this access."""
        return self in {CalendarAccess.OWNER, CalendarAccess.WRITER}


@dataclass(frozen=True, slots=True)
class DiscoveredCalendar:
    id: str
    summary: str
    """How the calendar is labelled when it is listed: its name, or what its provider shows for a
    calendar without one."""
    access: CalendarAccess
    """What this Connected Account may do with it, in provider-neutral terms."""
    primary: bool
    named: bool = field(default=True, kw_only=True)
    """Whether the provider gave it a name of its own, so its summary may name its rules."""

    @property
    def name(self) -> str:
        """The name rules show for it; empty when its provider gave it none."""
        return self.summary if self.named else ""

    @property
    def writable(self) -> bool:
        """Whether rules may write projections to it, as its provider grants this account."""
        return self.access.writable


@dataclass(frozen=True, slots=True)
class AccountAccess:
    calendars_visible: int
    writable_calendars: int


@dataclass(frozen=True, slots=True)
class AuthorizedAccount:
    """A Connected Account an OAuth flow connected or reauthorized, and the User it belongs to."""

    owner: UserId
    account: ConnectedAccount


class AccountAuthorization(Protocol):
    """The provider's OAuth flow that connects or reauthorizes an account, protected by its state
    and by the session of the User who began it."""

    def authorization_url(self, owner: UserId, login_hint: str | None = None) -> str:
        """The provider's consent URL for `owner`, whose account the flow connects;
        `login_hint` suggests the account being reauthorized."""
        ...

    def complete(self, state: str, code: str, user: UserId) -> AuthorizedAccount:
        """Connect the account for `user`, the User signed in where the flow returned, only if
        they began the flow the state names; raises AuthorizationFailed, using the state up and
        exchanging nothing, when another User began it."""
        ...

    def cancel(self, state: str) -> None: ...


class AccountCalendars(Protocol):
    def calendars(self, account_id: ConnectedAccountId) -> Sequence[DiscoveredCalendar]: ...

    def verify_access(self, account_id: ConnectedAccountId) -> AccountAccess:
        """Prove the account can list calendars and read events, or raise why it cannot."""
        ...
