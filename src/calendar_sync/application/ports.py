from __future__ import annotations

from collections.abc import Collection, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import TracebackType
from typing import Protocol, Self

from calendar_sync.application.errors import ProviderFailure, ProviderFailureKind
from calendar_sync.application.providers import ProviderKind
from calendar_sync.domain.changes import SourceChange, SourceObservation
from calendar_sync.domain.model import (
    CalendarEndpoint,
    CalendarEvent,
    ConnectedAccountId,
    EventMapping,
    EventMappingId,
    EventProjection,
    EventRef,
    EventStatus,
    EventTime,
    OccurrenceMapping,
    OccurrenceStart,
    SyncAction,
    SyncReason,
    SyncRule,
    SyncRuleId,
    TransformationPolicy,
)


@dataclass(frozen=True, slots=True)
class ProviderChangeSet:
    events: tuple[CalendarEvent, ...]
    next_cursor: str
    complete: bool = False
    """Every event in the window, not only changes since a cursor, as after a rejected cursor."""


@dataclass(frozen=True, slots=True)
class CreatedProjection:
    destination_event: CalendarEvent


class CalendarReader(Protocol):
    """Provider reads. Preview and reconciliation receive only this role, so they cannot write."""

    def changes(
        self,
        source: CalendarEndpoint,
        cursor: str | None,
        not_ended_before: datetime,
    ) -> ProviderChangeSet: ...

    def get_event(self, reference: EventRef) -> CalendarEvent | None: ...

    def find_projection(
        self, destination: CalendarEndpoint, operation_key: str
    ) -> CalendarEvent | None:
        """Return the projection an earlier write with this Operation Key created, if any."""
        ...

    def list_events(
        self, calendar: CalendarEndpoint, not_ended_before: datetime
    ) -> Sequence[CalendarEvent]:
        """Every event, cancelled ones included, that ends at or after `not_ended_before`.

        Unlike `changes`, it reads no incremental position and yields none.
        """
        ...

    def managed_events(
        self, destination: CalendarEndpoint, rule_id: SyncRuleId, not_ended_before: datetime
    ) -> Sequence[CalendarEvent]:
        """This rule's live Managed Projections that end at or after `not_ended_before`."""
        ...

    def get_occurrence(
        self, series: EventRef, original_start: OccurrenceStart
    ) -> CalendarEvent | None:
        """Resolve one occurrence of a readable series, cancelled or not.

        `None` means the series answered and has no occurrence at that start. A series that cannot
        be read raises instead, because absence can authorize cancelling a destination occurrence.
        """
        ...

    def list_occurrences(
        self, series: EventRef, original_starts: Collection[OccurrenceStart]
    ) -> Mapping[OccurrenceStart, CalendarEvent]:
        """Occurrences of a series one listing found, cancelled or not, by original start.

        A requested start the answer lacks proves nothing: resolve it with `get_occurrence`.
        """
        ...

    def has_live_occurrences(self, series: EventRef, policy: TransformationPolicy) -> bool:
        """Whether a series has an occurrence that is not cancelled and that `policy` projects.

        An occurrence the policy excludes, such as an all-day one or one the Source Calendar
        declined, does not count, because the rule cancels it in the destination. Only an answered
        lookup may return `False`, because it stops a projection from being created or restored
        and can remove one left by an interrupted create; a series whose occurrences cannot be
        listed counts as live.
        """
        ...

    def occurrence_exceptions(
        self, series: EventRef, not_ended_before: datetime
    ) -> Sequence[CalendarEvent]:
        """Occurrences of a series that are cancelled or differ from its regular occurrence.

        Only occurrences whose original slot or current time reaches `not_ended_before` count.

        A series whose occurrences cannot be listed returns none; its exceptions are applied when
        a later full listing reports them.
        """


class ProjectionDeleter(Protocol):
    """Deletes an owned projection; Rule Removal needs no other provider operation."""

    def delete_projection(
        self,
        destination: EventRef,
        source: EventRef,
        rule_id: SyncRuleId,
        operation_key: str,
    ) -> None: ...


class ProjectionWriter(ProjectionDeleter, Protocol):
    """Creates, updates, and deletes owned projections."""

    def create_projection(
        self,
        destination: CalendarEndpoint,
        source: EventRef,
        rule_id: SyncRuleId,
        projection: EventProjection,
        operation_key: str,
    ) -> CreatedProjection: ...

    def update_projection(
        self,
        destination: EventRef,
        source: EventRef,
        rule_id: SyncRuleId,
        projection: EventProjection,
        operation_key: str,
    ) -> CalendarEvent: ...


class OccurrenceWriter(Protocol):
    """Writes and cancels single occurrences of owned destination series."""

    def write_occurrence(
        self,
        destination_series: EventRef,
        original_start: OccurrenceStart,
        source_series: EventRef,
        rule_id: SyncRuleId,
        projection: EventProjection,
        operation_key: str,
    ) -> CalendarEvent:
        """Write or restore an owned destination occurrence without notifying attendees."""

    def cancel_occurrence(
        self,
        destination_series: EventRef,
        original_start: OccurrenceStart,
        source_series: EventRef,
        rule_id: SyncRuleId,
        operation_key: str,
    ) -> None:
        """Cancel one owned destination occurrence; the rest of its series is unchanged."""


class CalendarProvider(CalendarReader, ProjectionWriter, OccurrenceWriter, Protocol):
    """Every provider role. Only a Sync Run needs them all."""


class SyncRuleRepository(Protocol):
    def get(self, rule_id: SyncRuleId) -> SyncRule | None: ...

    def list(self) -> Sequence[SyncRule]: ...

    def add(self, rule: SyncRule) -> None: ...

    def save(self, rule: SyncRule) -> None: ...

    def relationship_exists(
        self, source: CalendarEndpoint, destination: CalendarEndpoint
    ) -> bool: ...

    def remove(self, rule_id: SyncRuleId) -> None:
        """Delete the rule with its mappings, cursors, and outcomes; resolve its incidents."""

    def purge(self, rule_id: SyncRuleId) -> None:
        """Delete the rule like `remove`, and its audit entries and incidents with it."""


class EventMappingRepository(Protocol):
    def for_source(self, rule_id: SyncRuleId, source: EventRef) -> EventMapping | None: ...

    def for_destination(
        self, rule_id: SyncRuleId, destination: EventRef
    ) -> EventMapping | None: ...

    def for_rule(self, rule_id: SyncRuleId) -> Sequence[EventMapping]: ...

    def save(self, mapping: EventMapping) -> None: ...

    def delete(self, mapping: EventMapping) -> None: ...

    def count_for_rule(self, rule_id: SyncRuleId) -> int: ...


class OccurrenceMappingRepository(Protocol):
    def for_series(self, series_mapping_id: EventMappingId) -> Sequence[OccurrenceMapping]: ...

    def get(
        self, series_mapping_id: EventMappingId, original_start: OccurrenceStart
    ) -> OccurrenceMapping | None: ...

    def save(self, mapping: OccurrenceMapping) -> None: ...

    def delete(self, mapping: OccurrenceMapping) -> None: ...


class ExceptionReplayRepository(Protocol):
    """Series projections whose source exceptions have not all been applied yet."""

    def pending(self, rule_id: SyncRuleId) -> Sequence[EventMapping]: ...

    def add(self, series_mapping_id: EventMappingId) -> None: ...

    def remove(self, series_mapping_id: EventMappingId) -> None: ...


class SyncCursorRepository(Protocol):
    def get(self, rule_id: SyncRuleId) -> str | None: ...

    def save(self, rule_id: SyncRuleId, cursor: str) -> None: ...


@dataclass(frozen=True, slots=True)
class RecordedEvent:
    """What Activity names an entry's source event by, as the run saw it (ADR 0014)."""

    title: str
    time: EventTime | None = None
    recurring: bool = False
    cancelled: bool = False

    @classmethod
    def of(cls, event: CalendarEvent) -> RecordedEvent:
        return cls(
            title=event.title,
            time=event.time,
            recurring=event.recurrence is not None or event.occurrence is not None,
            cancelled=event.status is EventStatus.CANCELLED,
        )


class AuditAction(StrEnum):
    """What an Audit Entry records; the stored values are a compatibility surface."""

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    IGNORE = "ignore"
    CONFLICT = "conflict"
    POLICY_CHANGED = "policy_changed"
    REMOVE_PROJECTION = "remove_projection"
    DETACH_PROJECTION = "detach_projection"
    REMOVAL_CONFLICT = "removal_conflict"
    RULE_REMOVED = "rule_removed"

    @classmethod
    def of(cls, action: SyncAction) -> AuditAction:
        return cls(action.value)


class AuditOutcome(StrEnum):
    COMPLETED = "completed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"

    @classmethod
    def of(cls, action: SyncAction) -> AuditOutcome:
        if action is SyncAction.IGNORE:
            return cls.SKIPPED
        if action is SyncAction.CONFLICT:
            return cls.BLOCKED
        return cls.COMPLETED


@dataclass(frozen=True, slots=True)
class AuditEntry:
    occurred_at: datetime
    rule_id: SyncRuleId
    action: AuditAction
    outcome: AuditOutcome
    source_event_id: str | None = None
    destination_event_id: str | None = None
    detail: str = ""
    reason: SyncReason | None = None
    run_id: str | None = None
    event: RecordedEvent | None = None
    """The source event's title and time, as ADR 0014 records them."""
    change: SourceChange | None = None
    """What the source event's new revision changed since the rule last observed it (ADR 0017)."""


class AuditRepository(Protocol):
    def append(self, entry: AuditEntry) -> None: ...

    def forget_change_values(self, before: datetime) -> None:
        """Discard the values of every Source Change recorded before `before`.

        Every rule's, including paused and removed rules'. The changed fields and titles stay, so
        Activity still says what changed.
        """
        ...


class SourceObservationRepository(Protocol):
    """The tracked details of each source event a rule last observed (ADR 0017)."""

    def get(self, rule_id: SyncRuleId, source: EventRef) -> SourceObservation | None: ...

    def save(
        self,
        rule_id: SyncRuleId,
        source: EventRef,
        observation: SourceObservation,
        observed_at: datetime,
    ) -> None: ...

    def forget_stale(
        self, rule_id: SyncRuleId, source: CalendarEndpoint, ended_before: datetime
    ) -> None:
        """Forget single events that ended before `ended_before`, and other calendars' events."""
        ...


class RunKind(StrEnum):
    SYNC = "sync"
    RECONCILIATION = "reconciliation"


@dataclass(frozen=True, slots=True)
class RuleRunOutcome:
    """The latest result of one kind of run: counts and a failure category, never content."""

    rule_id: SyncRuleId
    kind: RunKind
    completed_at: datetime
    succeeded: bool
    full_run: bool = False
    created: int = 0
    updated: int = 0
    deleted: int = 0
    conflicts: int = 0
    checked_mappings: int = 0
    drift: int = 0
    failure_kind: str | None = None
    # When the most recent successful run of this kind completed. The repository keeps it across
    # later failures, so a failed run never erases evidence that calendars were once current.
    last_succeeded_at: datetime | None = None
    # When the most recent successful full run completed, kept across later incremental runs so
    # the daily full pass is due per rule and survives restarts.
    last_full_succeeded_at: datetime | None = None


class RuleRunOutcomeRepository(Protocol):
    def record(self, outcome: RuleRunOutcome) -> None: ...

    def latest(self, rule_id: SyncRuleId, kind: RunKind) -> RuleRunOutcome | None: ...


@dataclass(frozen=True, slots=True)
class RulePreviewSummary:
    """Counts from the latest Rule Preview, kept so enabling can restate them; never content."""

    rule_id: SyncRuleId
    completed_at: datetime
    eligible_events: int
    excluded_events: int
    recurring_series: int = 0
    occurrence_changes: int = 0


class RulePreviewRepository(Protocol):
    def record(self, summary: RulePreviewSummary) -> None: ...

    def latest(self, rule_id: SyncRuleId) -> RulePreviewSummary | None: ...


class CalendarNameRepository(Protocol):
    """The name each calendar last had in Google, so a rule is named before Google answers."""

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

    def delete_disconnected(self, account_id: ConnectedAccountId) -> bool:
        """Delete the account if it is disconnected; whether it was.

        Once this deletes, no other writer can change the installation until the unit of work
        ends, so a reauthorization or new rule cannot slip in before it commits.
        """
        ...


class UnitOfWork(Protocol):
    accounts: ConnectedAccountRecords
    rules: SyncRuleRepository
    mappings: EventMappingRepository
    occurrences: OccurrenceMappingRepository
    replays: ExceptionReplayRepository
    cursors: SyncCursorRepository
    destination_cursors: SyncCursorRepository
    audit: AuditRepository
    observations: SourceObservationRepository
    run_outcomes: RuleRunOutcomeRepository
    previews: RulePreviewRepository
    calendar_names: CalendarNameRepository

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...

    def commit(self) -> None: ...


class UnitOfWorkFactory(Protocol):
    def __call__(self) -> UnitOfWork: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


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


class SchedulerHeartbeat(Protocol):
    def progress(self) -> SchedulerProgress: ...


class IdGenerator(Protocol):
    def new(self) -> str: ...


class RunIdGenerator(Protocol):
    """Identifies one Sync Run's Audit Entries.

    Run identifiers are persisted and shown in Activity, so they stay 32 lowercase hex characters.
    """

    def new_run_id(self) -> str: ...


@dataclass(slots=True)
class ProviderCallTally:
    """The provider calls one run made so far; the adapter adds each call as it returns."""

    calls: int = 0
    seconds: float = 0.0
    slowest_seconds: float = 0.0
    rate_limited: int = 0
    """Calls the provider refused for its rate limit or quota."""
    server_errors: int = 0
    """Calls the provider answered with a server error."""
    token_refreshes: int = 0
    """Access tokens renewed during the run."""


class ProviderCallStats(Protocol):
    def measure(self) -> AbstractContextManager[ProviderCallTally]:
        """Tally the provider calls made in this context, by this thread, until it exits."""
        ...


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


class AccountAuthorizations(Protocol):
    def is_connected(self, account_id: ConnectedAccountId) -> bool: ...


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


class IncidentResolution(StrEnum):
    """Why an Incident resolved, so Activity can tell recovery apart from removal."""

    SYNC_SUCCEEDED = "sync_succeeded"
    BLOCKS_CLEARED = "blocks_cleared"
    RULE_REMOVED = "rule_removed"
    ACCESS_RESTORED = "access_restored"
    """The account's Lapsed Authorization cleared (ADR 0027)."""


class IncidentRepository(Protocol):
    def open(self, incident: IncidentReport, at: datetime) -> bool:
        """Open or refresh the Incident under its key; whether it was newly opened.

        Reopening a resolved Incident starts a new episode, so its opening time is `at`. One
        about an account alone opens only while that account's authorization has lapsed.
        """
        ...

    def resolve(
        self,
        key: str,
        at: datetime,
        resolution: IncidentResolution,
        *,
        while_authorized: ConnectedAccountId | None = None,
    ) -> None:
        """Resolve the Incident under this key, if it is open, recording why.

        With `while_authorized`, only if that account is authorized when it resolves, checked
        atomically, so a lapse recorded just before keeps its Incident open.
        """
        ...


class IncidentNotifications(Protocol):
    def incident_opened(self, incident: IncidentReport, at: datetime) -> None:
        """Deliver an Incident Notification; best-effort, so it never raises."""
        ...


class RuleHealthRecords(Protocol):
    """What rule health remembers between runs: failure streaks and daily block checks."""

    def record_failure(self, rule_id: SyncRuleId, kind: ProviderFailureKind, at: datetime) -> int:
        """Count one more consecutive failure; how many there are now."""
        ...

    def clear_failures(self, rule_id: SyncRuleId) -> None: ...

    def audit_floor(self) -> int:
        """The newest audit entry now, taken before a full pass so its decisions lie above it."""
        ...

    def record_block_check(
        self, rule_id: SyncRuleId, floor: int, run_id: str | None, at: datetime
    ) -> int | None:
        """Record a full pass that began after entry `floor`; how many blocks it found persisting.

        A block persists when it was its event's latest decision before the pass began and the
        pass decided it again. `None` when the rule no longer exists.
        """
        ...


class RemovalIncidents(Protocol):
    def removal_blocked(
        self, rule_id: SyncRuleId, failure: ProviderFailure, *, attempted_at: datetime
    ) -> None:
        """Open or refresh the one Incident for a removal stopped by lost authorization."""
        ...


class RecoveryIncidents(Protocol):
    def recovery_blocked(
        self, rule_id: SyncRuleId, failure: ProviderFailure, *, attempted_at: datetime
    ) -> None:
        """Record the lost authorization a preview met, lapsing the account it names."""
        ...


class ConnectedAccountState(StrEnum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"


@dataclass(frozen=True, slots=True)
class ConnectedAccount:
    id: ConnectedAccountId
    display_name: str
    email: str
    state: ConnectedAccountState
    avatar_url: str | None = None
    authorized_at: str | None = None
    """When the account was last connected or reauthorized; None while disconnected."""
    provider: ProviderKind = field(kw_only=True)
    """The calendar service the account belongs to; it never changes (ADR 0022)."""
    authorization_lapsed_at: str | None = field(default=None, kw_only=True)
    """While the provider refuses a connected account's credentials, when the latest refused
    request began; None while it accepts them (ADR 0027)."""


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
    access: CalendarAccess
    """What this Connected Account may do with it, in provider-neutral terms."""
    primary: bool

    @property
    def writable(self) -> bool:
        """Whether rules may write projections to it, as its provider grants this account."""
        return self.access.writable


@dataclass(frozen=True, slots=True)
class AccountAccess:
    calendars_visible: int
    writable_calendars: int


class AccountAuthorization(Protocol):
    """The provider's state-protected OAuth flow that connects or reauthorizes an account."""

    def authorization_url(self, login_hint: str | None = None) -> str:
        """The provider's consent URL; `login_hint` suggests the account being reauthorized."""
        ...

    def complete(self, state: str, code: str) -> ConnectedAccount: ...

    def cancel(self, state: str) -> None: ...


class AccountCalendars(Protocol):
    def calendars(self, account_id: ConnectedAccountId) -> Sequence[DiscoveredCalendar]: ...

    def verify_access(self, account_id: ConnectedAccountId) -> AccountAccess:
        """Prove the account can list calendars and read events, or raise why it cannot."""
        ...


@dataclass(frozen=True, slots=True)
class AdministratorSession:
    token: str
    expires_at: datetime


class AdministratorAccess(Protocol):
    """The Installation Administrator's password and sessions."""

    def is_configured(self) -> bool: ...

    def create_admin(self, password: str) -> None: ...

    def authenticate(self, password: str) -> AdministratorSession | None: ...

    def session_is_valid(self, token: str | None) -> bool: ...

    def revoke(self, token: str | None) -> None: ...


class IntegrationTokenScope(StrEnum):
    STATUS_READ = "status:read"


@dataclass(frozen=True, slots=True)
class IntegrationTokenSummary:
    """An Integration Token as the administrator sees it; never the token or its hash."""

    id: str
    name: str
    scope: IntegrationTokenScope
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


@dataclass(frozen=True, slots=True)
class IssuedIntegrationToken:
    summary: IntegrationTokenSummary
    token: str = field(repr=False)
    """Shown once, when issued; only its hash is kept. Kept out of the repr, so a log line or
    traceback that prints this value never shows the token."""


class IntegrationTokens(Protocol):
    """Named credentials the administrator issues so monitors and agents can read status."""

    def issue(self, name: str) -> IssuedIntegrationToken: ...

    def list(self) -> Sequence[IntegrationTokenSummary]:
        """Every token, newest first, revoked ones last."""
        ...

    def revoke(self, token_id: str) -> bool:
        """Whether a token that was not yet revoked is revoked now."""
        ...

    def authenticate(self, token: str) -> IntegrationTokenSummary | None:
        """The token's summary when it is well formed, known, and not revoked."""
        ...


class FullPassRecords(Protocol):
    """Bookkeeping that lets a successful full pass stand in for a rule's daily one."""

    def audit_floor(self) -> int:
        """The newest audit entry now, taken before a full pass so its decisions lie above it."""
        ...

    def record_full_pass(self, rule_id: SyncRuleId, floor: int, run_id: str | None = None) -> None:
        """A full pass that began after audit entry `floor` decided every blocked event again."""
        ...
