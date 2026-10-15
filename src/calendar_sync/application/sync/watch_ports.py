"""Ports of Instant Sync: watching calendars, reading notices, and the records they keep.

A provider's descriptor offers its watcher and notice reader, and descriptors live in `sync`, so
everything they expose is declared here (ADR 0036). Nothing here carries event content.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from calendar_sync.application.shared.errors import ApplicationError
from calendar_sync.application.sync.errors import ProviderFailure
from calendar_sync.domain.access import UserId
from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.cadence import DEFAULT_CADENCE, SyncCadence
from calendar_sync.domain.model import CalendarEndpoint, CalendarId, ConnectedAccountId, SyncRuleId
from calendar_sync.domain.watches import (
    CalendarWatch,
    CalendarWatchId,
    DeliveryEvidence,
    WatchRegistration,
    WatchRegistrationId,
    WatchScope,
)

if TYPE_CHECKING:
    # ports.py imports this module, so the Allowances port is named here for type checking only.
    from calendar_sync.application.sync.ports import Allowances

logger = logging.getLogger(__name__)

NOTICE_PATH = "/api/v1/watch-notices"
"""Where providers deliver notices, below the installation's public address."""


@dataclass(frozen=True, slots=True)
class Receipt:
    """A provider's answer to a registration it now holds."""

    handle: str
    """The provider's identifiers for it, opaque outside its adapter."""
    expires_at: datetime
    confirmed: bool = False
    """Whether creating it already proved the provider reaches the installation, as a provider
    that validates the address first does."""


class WatchFailureKind(StrEnum):
    """How a watch call failed, kept apart from the failures of Sync Runs."""

    UNAUTHORIZED = "unauthorized"
    """The provider refused the account's credentials, which lapses the account (ADR 0027)."""
    UNSUPPORTED = "unsupported"
    """The provider cannot watch this; it never lapses the account."""
    ACCOUNT_UNAVAILABLE = "account_unavailable"
    """The Connected Account no longer exists or is disconnected, so its credentials are gone.
    Upkeep backs off as for a temporary failure: it says nothing about what can be watched, and
    the account's rules already tell its owner."""
    DUPLICATE = "duplicate"
    """The provider already holds a registration for the same scope."""
    UNREACHABLE = "unreachable"
    """The provider said it cannot reach the notice address."""
    RATE_LIMITED = "rate_limited"
    TEMPORARY = "temporary"
    """No answer, or one a later attempt can change; the provider may have done what was asked."""


# Not frozen: raising an error sets its __traceback__, which a frozen dataclass refuses.
@dataclass(eq=False)
class WatchFailure(ApplicationError):
    kind: WatchFailureKind
    detail: str
    retry_after_seconds: int | None = None
    failure: ProviderFailure | None = None
    """For an unauthorized call, the refusal Lapsed Authorization records (ADR 0027)."""

    def __str__(self) -> str:
        return self.detail


class CalendarWatcher(Protocol):
    """Asks one provider to report changes, through channels or subscriptions it holds.

    Every method raises only WatchFailure. A Connected Account that no longer exists or is
    disconnected is `account_unavailable`, so upkeep backs off and never lapses it. The adapter
    never invents an identity during a call: the registration id and token come from upkeep,
    which persisted them first.
    """

    def scope(self, calendar: CalendarEndpoint) -> WatchScope | None:
        """What a watch covering this calendar watches; None when it cannot be watched."""
        ...

    def register(
        self,
        account: ConnectedAccountId,
        scope: WatchScope,
        registration_id: WatchRegistrationId,
        token: str,
        address: str,
        until: datetime,
    ) -> Receipt:
        """Ask the provider to deliver notices for `scope` to `address` until `until`."""
        ...

    def extend(
        self, account: ConnectedAccountId, registration: WatchRegistration, until: datetime
    ) -> datetime | None:
        """Renew a registration in place; its new expiry, or None when the provider renews only
        by replacing it with a new registration."""
        ...

    def adopt(
        self,
        account: ConnectedAccountId,
        scope: WatchScope,
        registration_id: WatchRegistrationId,
        address: str,
    ) -> Receipt | None:
        """After a duplicate, the provider's registration whose address names exactly this id;
        None when another one holds the scope. It never matches by scope alone and never deletes
        a registration it cannot identify."""
        ...

    def stop(self, account: ConnectedAccountId, registration: WatchRegistration) -> None: ...


WatcherFor = Callable[[ConnectedAccountId], CalendarWatcher | None]
"""The watcher of a Connected Account's provider; None when its provider watches nothing."""


@dataclass(frozen=True, slots=True)
class NoticeRequest:
    """A notice as it arrived, without any web framework's types."""

    headers: Mapping[str, str]
    """Header names in lower case."""
    query: Mapping[str, str]
    body: bytes


class NoticeKind(StrEnum):
    STARTED = "started"
    """The provider began delivering through a new registration."""
    CHANGED = "changed"
    MISSED = "missed"
    """The provider dropped notices, so a run catches up."""
    REAUTHORIZE = "reauthorize"
    """The provider asks for the registration to be renewed early."""
    REMOVED = "removed"
    """The provider ended the registration itself."""


@dataclass(frozen=True, slots=True)
class WatchNotice:
    """One notice: the registration its address names, and what it presented and reports."""

    registration_id: WatchRegistrationId
    token: str
    handle: str | None
    """The provider's identifiers it presented, when it carries any."""
    kind: NoticeKind


class MalformedNotice(ApplicationError):
    """A request at a notice address that is not a notice its provider sends."""


class NoticeReader(Protocol):
    """Reads one provider's notices; it makes no provider call and keeps nothing."""

    def validation_token(self, request: NoticeRequest) -> str | None:
        """The token to echo when the provider is validating the address; None otherwise."""
        ...

    def read(
        self, registration_id: WatchRegistrationId, request: NoticeRequest
    ) -> tuple[WatchNotice, ...]:
        """The notices in a request; raises MalformedNotice for anything else."""
        ...


class CalendarWatchRepository(Protocol):
    """One User's Calendar Watches and their registrations.

    Every state change is conditional on the state it leaves, so a late writer changes nothing.
    """

    def list(self) -> Sequence[CalendarWatch]: ...

    def registrations(self) -> Sequence[WatchRegistration]:
        """Every registration of every watch of the User."""
        ...

    def add(self, watch: CalendarWatch) -> None: ...

    def set_coverage(self, watch_id: CalendarWatchId, coverage: frozenset[CalendarId]) -> None: ...

    def set_retry(
        self, watch_id: CalendarWatchId, retry_at: datetime | None, failures: int
    ) -> None: ...

    def remove(self, watch_id: CalendarWatchId) -> None:
        """Delete the watch with its coverage and registrations."""
        ...

    def add_registration(self, registration: WatchRegistration) -> None: ...

    def record_receipt(
        self,
        registration_id: WatchRegistrationId,
        receipt: Receipt,
        renew_at: datetime,
        at: datetime,
    ) -> bool:
        """Make a `creating` registration live with the provider's answer; whether it was still
        being created.

        A confirming receipt sets `confirmed_at` to `at`; a confirmation a notice recorded first
        is kept.
        """
        ...

    def record_extension(
        self,
        registration_id: WatchRegistrationId,
        expires_at: datetime,
        renew_at: datetime,
        seen_request: datetime | None,
    ) -> bool:
        """Record a live registration's new expiry; whether it was still live.

        Its early renewal request is cleared only if it is still the one upkeep read, so a request
        that arrived during the renewal is not lost.
        """
        ...

    def retire(self, registration_id: WatchRegistrationId) -> bool:
        """Make a live registration retiring; whether it was live."""
        ...

    def abandon(self, registration_id: WatchRegistrationId) -> bool:
        """Make a registration in any state abandoned; whether it exists."""
        ...

    def delete_registration(self, registration_id: WatchRegistrationId) -> None: ...


@dataclass(frozen=True, slots=True)
class PendingRequest:
    """A rule's Instant Sync Request: notices counted, and how many a run has handled."""

    rule_id: SyncRuleId
    requested_seq: int
    handled_seq: int
    first_requested_at: datetime
    """When `requested_seq` first rose above `handled_seq`."""
    last_requested_at: datetime
    last_run_at: datetime | None


class InstantSyncRequestRepository(Protocol):
    """One User's Instant Sync Requests."""

    def pending(self) -> Sequence[PendingRequest]:
        """Requests with notices no run has handled yet."""
        ...

    def acknowledge(self, rule_id: SyncRuleId, seq: int, ran_at: datetime) -> None:
        """Mark notices up to `seq` handled by a run at `ran_at`, in one statement, so notices
        counted during the run stay pending."""
        ...


class DeliveryEvidenceLog(Protocol):
    """Whether each provider's notices reach a public address; installation data, no User's."""

    def succeeded(self, provider: ProviderKind, address: str, at: datetime) -> None:
        """Record a success; an older time than the one recorded changes nothing."""
        ...

    def failed(self, provider: ProviderKind, address: str, at: datetime) -> None:
        """Record a failure; an older time than the one recorded changes nothing, so recording
        one failure again is harmless."""
        ...

    def evidence(self, address: str) -> Mapping[ProviderKind, DeliveryEvidence]: ...


class SyncCadencePolicy(Protocol):
    """Each User's Sync Cadence, as their Plan allows (ADR 0028, ADR 0038).

    Both reads raise when the cadence cannot be read; readers that must not fail read through
    `cadences_of`, or fall back to `DEFAULT_CADENCE` themselves.
    """

    def cadence(self, user: UserId) -> SyncCadence:
        """One User's cadence."""
        ...

    def cadences(self, users: Collection[UserId]) -> Mapping[UserId, SyncCadence]:
        """Each User's cadence, in one read."""
        ...


@dataclass(frozen=True, slots=True)
class EveryUserInstant:
    """Every User may sync instantly, as while Plans are off (ADR 0028): the default of
    `Adapters.sync_cadence`, and a policy for tests."""

    # The port names the User so Plans can tell Users apart; this policy tells none apart.
    def cadence(self, user: UserId) -> SyncCadence:  # noqa: ARG002
        return DEFAULT_CADENCE

    def cadences(self, users: Collection[UserId]) -> Mapping[UserId, SyncCadence]:
        return dict.fromkeys(users, DEFAULT_CADENCE)


@dataclass(frozen=True, slots=True)
class PlanCadence:
    """Each User's Sync Cadence, as their Allowance says (ADR 0038).

    A failed read raises here: each reader decides how to fail open.
    """

    allowances: Allowances

    def cadence(self, user: UserId) -> SyncCadence:
        return self.allowances.of(user).cadence

    def cadences(self, users: Collection[UserId]) -> Mapping[UserId, SyncCadence]:
        """Every User's cadence in one Allowances read; a User missing from its answer gets
        the default cadence."""
        allowances = self.allowances.of_users(users)
        return {
            user: allowances[user].cadence if user in allowances else DEFAULT_CADENCE
            for user in users
        }


def cadences_of(
    policy: SyncCadencePolicy, users: Collection[UserId]
) -> dict[UserId, SyncCadence | None]:
    """Each User's cadence in one batch read; when the batch raises, each User read alone; None
    for a User whose own read raises too, or whom the batch left out. Logs only the error's class.

    Readers count None as instant, so a Plans fault never drops an Instant Sync Request,
    retires a watch, or hides Instant Sync from Installation Hints (ADR 0038).
    """
    try:
        batch = policy.cadences(users)
    except Exception as error:
        logger.warning(
            "Could not read Sync Cadences in one batch; reading each User alone (%s)",
            error.__class__.__name__,
        )
        return {user: _cadence_alone(policy, user) for user in users}
    return {user: batch.get(user) for user in users}


def _cadence_alone(policy: SyncCadencePolicy, user: UserId) -> SyncCadence | None:
    try:
        return policy.cadence(user)
    except Exception as error:
        logger.warning(
            "Could not read a User's Sync Cadence; they count as instant (%s)",
            error.__class__.__name__,
        )
        return None


def notice_address(
    public_address: str, provider_slug: str, registration_id: WatchRegistrationId
) -> str:
    """Where a provider delivers one registration's notices."""
    return f"{public_address}{NOTICE_PATH}/{provider_slug}/{registration_id.value}"
