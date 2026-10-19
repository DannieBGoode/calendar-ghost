"""Ports of operations: what status, health, the Operator Overview, and storage read."""

from __future__ import annotations

from collections.abc import Collection, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from types import TracebackType
from typing import Literal, Protocol, Self

from calendar_sync.application.shared.errors import ApplicationError
from calendar_sync.application.sync.ports import RulePreviewSummary, ScheduledRule
from calendar_sync.application.sync.watch_ports import PendingRequest, WatchNotice
from calendar_sync.domain.access import UserId
from calendar_sync.domain.accounts import ConnectedAccountState, ProviderKind
from calendar_sync.domain.causes import Cause
from calendar_sync.domain.incidents import (
    AccountAuthorization,
    IncidentCategory,
    IncidentFacts,
    IncidentMessage,
    IncidentStep,
    next_step,
)
from calendar_sync.domain.model import ConnectedAccountId, SyncRule
from calendar_sync.domain.plans import PlanUse
from calendar_sync.domain.runs import RuleRunOutcome


@dataclass(frozen=True, slots=True)
class RecordedRule:
    """A rule with what Installation Status reads about it."""

    rule: SyncRule
    last_sync: RuleRunOutcome | None
    latest_preview: RulePreviewSummary | None


@dataclass(frozen=True, slots=True)
class StatusRecords:
    """What one User's Installation Status is computed from. It holds no calendar or account
    name, so nothing read here can show one."""

    rules: tuple[RecordedRule, ...]
    """In the order the rules were created."""
    overview: OperationsOverview
    incidents: tuple[IncidentSummary, ...]
    """Open incidents, most recently updated first."""


@dataclass(frozen=True, slots=True)
class ProviderCallUse:
    """One provider's calls over some days."""

    provider: ProviderKind
    calls: int
    rate_limited: int
    failed: int


@dataclass(frozen=True, slots=True)
class ResourceUse:
    """How much of the installation one User uses, in counts; never what their records say."""

    rules: int
    connected_accounts: int
    activity_entries: int
    provider_calls: tuple[ProviderCallUse, ...]
    """Each provider's calls since the day asked for, by provider."""


@dataclass(frozen=True, slots=True)
class InstantSyncOwner:
    """A User whose Calendar Watches upkeep reconciles: one with an enabled rule or a watch."""

    user: UserId
    wanted: bool
    """Whether they want Instant Sync, as their account settings say."""
    disabled: bool
    """A disabled User is listed too, so upkeep stops their watches."""
    next_due: datetime | None
    """When their watches next need upkeep: a retry, a renewal asked for or planned, a creation
    deadline, or the end of a registration. None when nothing is planned, as for a User without
    a watch yet, whose coverage is still missing."""


@dataclass(frozen=True, slots=True)
class PendingInstantRun:
    """An enabled rule of a User who is not disabled, whose Instant Sync Request waits."""

    scheduled: ScheduledRule
    request: PendingRequest
    last_run_failed: bool
    """Whether its latest Sync Run failed; Scheduled Sync retries such a rule until one succeeds."""


@dataclass(frozen=True, slots=True)
class CauseSighting:
    """One User's failure with its Cause, as Installation Hints read it (ADR 0031). It says who
    and why, never which rule, calendar, or account."""

    user: UserId
    cause: Cause
    at: datetime
    """When the failure was last recorded."""
    open: bool
    """Whether it is an Incident still open, which a stopped rule keeps open while it waits."""
    authorized_for: timedelta | None = None
    """For a lapsed account's open Incident, how long after the account was last authorized it
    lapsed; None otherwise."""
    provider: ProviderKind | None = field(default=None, kw_only=True)
    """The provider that answered, as recorded with the failure; None when it is not known."""


class InstallationUnitOfWork(Protocol):
    """What reaches across Users. Only the scheduler, migrations, and the Operator Overview
    receive it, so crossing Users is visible in a type (ADR 0029)."""

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...

    def commit(self) -> None: ...

    def scheduled_rules(self) -> Sequence[ScheduledRule]:
        """Every enabled rule of a User who is not disabled, by User and then by rule, with when
        it last ran and was last previewed, and whether it is failing: its last sync failed, or
        a store that keeps failure streaks has one recorded for it."""
        ...

    def users_with_unfinished_lapses(self) -> Sequence[UserId]:
        """Every User who is not disabled whose Lapsed Authorization an interruption may have left
        partly done, by identifier: one with a rule a lapse alone stopped, or with an account
        authorized again while its Incident is still open (ADR 0027)."""
        ...

    def forget_change_values(self, before: datetime) -> None:
        """Discard every User's Source Change values recorded before `before` (ADR 0017)."""
        ...

    def resource_use(self, users: Collection[UserId], since: date) -> Mapping[UserId, ResourceUse]:
        """How much each of `users` uses: their rules, Connected Accounts, and Activity entries,
        and their provider calls from `since` on."""
        ...

    def plan_use(self, users: Collection[UserId]) -> Mapping[UserId, PlanUse]:
        """How much each of `users` has of what a Plan limits, counted as each limit counts it:
        rules that count toward the rule limit, every Connected Account, and unrevoked
        Integration Tokens (ADR 0038). A User with none has none of each."""
        ...

    def forget_provider_calls(self, before: date) -> None:
        """Discard every User's provider call counts of days before `before`."""
        ...

    def failure_causes(self, since: datetime) -> Sequence[CauseSighting]:
        """Every User's failures with a recorded Cause: failed runs completed from `since` on,
        and provider-failure Incidents still open or updated from `since` on."""
        ...

    def status_records(self, users: Collection[UserId]) -> Mapping[UserId, StatusRecords]:
        """What each of `users`' Installation Status is computed from, read in the same number
        of queries however many rules they have. A User with no records has empty ones."""
        ...

    def instant_sync_owners(self) -> Sequence[InstantSyncOwner]:
        """Every User with an enabled rule or a Calendar Watch, disabled Users included, by
        identifier."""
        ...

    def pending_instant_runs(self) -> Sequence[PendingInstantRun]:
        """Every enabled rule of a User who is not disabled whose Instant Sync Request is not yet
        handled, by User and then by rule. Neither the User's wish nor their cadence is read
        here; dispatch decides with them."""
        ...


class InstallationUnitOfWorkFactory(Protocol):
    def __call__(self) -> InstallationUnitOfWork: ...


class InboxBusy(ApplicationError):
    """The store stayed locked past the inbox's short wait; the provider sends the notice again."""


class WatchNoticeInbox(Protocol):
    """Where every User's Watch Notices are recorded (ADR 0029, amended by ADR 0036). It reads
    and writes only Watch Registrations, Instant Sync Requests, and Delivery Evidence, and makes
    no provider call."""

    def record(
        self,
        notices: Sequence[WatchNotice],
        provider: ProviderKind,
        address_base: str,
        at: datetime,
    ) -> int:
        """Apply each authentic notice in one short transaction; how many rule requests it
        raised. A notice for an unknown or abandoned registration, another provider's, or one that
        presents a wrong token or handle changes nothing. Raises InboxBusy when the store stays
        locked past the inbox's wait."""
        ...


@dataclass(frozen=True, slots=True)
class SchedulerProgress:
    """What the scheduler did last, so Installation Status can see a scheduler that stopped."""

    running_since: datetime
    """When the scheduler was created; the baseline until its first pass completes."""
    pass_started_at: datetime | None
    """When the pass running now started; None between passes."""
    last_completed_at: datetime | None
    """When the last pass that raised nothing completed."""
    last_pass_rule_ids: frozenset[str] = frozenset()
    """The rules that pass listed, so a rule resumed since then is not yet expected to have run."""
    next_pass_at: datetime | None = None
    """When the next pass begins, so a User waiting on the provider is told when it is tried
    again; None while a pass runs."""


class SchedulerHeartbeat(Protocol):
    def progress(self) -> SchedulerProgress: ...


@dataclass(frozen=True, slots=True)
class LogUsage:
    """What the service's own log files hold: their size, count, and first and last line times."""

    bytes: int
    files: int
    oldest_at: datetime | None
    newest_at: datetime | None


class LogFiles(Protocol):
    """The service's rotating log files. They carry no event content (AGENTS.md)."""

    def usage(self) -> LogUsage: ...

    def chunks(self) -> Iterator[bytes]:
        """Every file's bytes, oldest file first; a file rotated away meanwhile is skipped."""
        ...

    def purge(self) -> None:
        """Empty the logs, leaving one line that says they were purged."""
        ...


@dataclass(frozen=True, slots=True)
class DatabaseUsage:
    bytes: int
    reclaimable_bytes: int
    """Free pages the file keeps until it is compacted."""
    activity_entries: int
    oldest_activity_at: datetime | None


class DatabaseStorage(Protocol):
    """The installation's database, as Settings → Storage reports and trims it."""

    def usage(self) -> DatabaseUsage: ...

    def clearable_activity(self, before: datetime) -> int:
        """How many Audit Entries older than `before` clearing would remove."""
        ...

    def clear_activity(self, before: datetime) -> int:
        """Remove Audit Entries older than `before`, except those Activity still reads.

        Every entry newer than `before` is kept. Of the older ones, per rule and source event, those
        Activity compares a kept entry with are kept, found by id: normally the latest entry and
        the latest that recorded a title. The rest are removed.
        """
        ...

    def compact(self) -> None:
        """Return free pages to the filesystem. It briefly blocks every other writer."""
        ...


@dataclass(frozen=True, slots=True)
class OpenBlock:
    entry_id: int
    rule_id: str


@dataclass(frozen=True, slots=True)
class AccountStanding:
    """A Connected Account's state and Provider Kind; never its email or name."""

    id: str
    state: ConnectedAccountState
    provider: ProviderKind
    lapsed: bool = False
    """Whether the provider stopped accepting a connected account (ADR 0027)."""


@dataclass(frozen=True, slots=True)
class OperationsOverview:
    connected_accounts: int
    disconnected_accounts: int
    open_incidents: int
    last_synced_at: datetime | None
    open_blocks: tuple[OpenBlock, ...]
    """Events of existing rules whose latest decision was a block, newest first."""
    accounts: tuple[AccountStanding, ...] = ()
    """Every Connected Account, ordered by id."""

    @property
    def lapsed_accounts(self) -> int:
        """Connected accounts whose authorization lapsed."""
        return sum(account.lapsed for account in self.accounts)


# The values the incidents table allows; its CHECK constraints keep stored rows to these.
IncidentState = Literal["open", "resolved"]


IncidentResolutionValue = Literal[
    "sync_succeeded", "blocks_cleared", "rule_removed", "access_restored"
]


@dataclass(frozen=True, slots=True)
class IncidentSummary:
    id: str
    rule_id: str | None
    category: IncidentCategory
    state: IncidentState
    summary: str
    opened_at: datetime
    updated_at: datetime
    resolved_at: datetime | None = None
    resolution: IncidentResolutionValue | None = None
    """Why a resolved Incident resolved; None while open or when the reason was not recorded."""
    account_id: str | None = None
    """The Connected Account whose failure opened or last refreshed it, when that was recorded."""
    message: IncidentMessage | None = None
    """The summary as a code and parameters, when it was recorded (ADR 0026)."""
    cause: Cause | None = None
    """Why the provider failure behind it happened (ADR 0031); unknown when that was not recorded,
    and None for an Incident no provider failure opened, such as events still blocked."""
    provider: ProviderKind | None = None
    """The provider whose failure opened it, when that was recorded."""
    rule_exists: bool = False
    """Whether its rule exists now; False for an account's or the installation's own Incident."""
    rule_accounts: tuple[AccountAuthorization, ...] = ()
    """Its rule's Connected Accounts as they are now, while the rule exists."""
    cursor: str = ""
    """Where a page that ends with it goes on, as it was when read; opaque to its readers."""

    @property
    def step(self) -> IncidentStep | None:
        """Its one next step, as the domain decides it for the Web UI and the email alike."""
        return next_step(
            IncidentFacts(
                self.category,
                self.cause,
                open=self.state == "open",
                rule_exists=self.rule_exists,
                rule_accounts=self.rule_accounts,
                failing_account=ConnectedAccountId(self.account_id) if self.account_id else None,
                last_failure=self.updated_at,
            )
        )
