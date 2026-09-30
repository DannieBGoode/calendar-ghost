from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import TracebackType
from typing import Protocol, Self

from calendar_sync.application.errors import ProviderFailure, ProviderFailureKind
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

    def has_live_occurrences(self, series: EventRef, *, include_all_day: bool) -> bool:
        """Whether a series has an occurrence that is not cancelled.

        With `include_all_day` false, all-day occurrences do not count, because a rule that
        excludes them cancels them in the destination. Only an answered lookup may return
        `False`, because it stops a projection from being created or restored and can remove one
        left by an interrupted create; a series whose occurrences cannot be listed counts as live.
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
    """The source event's title and time; never its description, location, or attendees."""


class AuditRepository(Protocol):
    def append(self, entry: AuditEntry) -> None: ...


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


class ConnectedAccountRecords(Protocol):
    """Connected Account records inside a unit of work, without their credentials."""

    def state(self, account_id: ConnectedAccountId) -> ConnectedAccountState | None: ...

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
    run_outcomes: RuleRunOutcomeRepository
    previews: RulePreviewRepository

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


class IdGenerator(Protocol):
    def new(self) -> str: ...


class RunIdGenerator(Protocol):
    """Identifies one Sync Run's Audit Entries.

    Run identifiers are persisted and shown in Activity, so they stay 32 lowercase hex characters.
    """

    def new_run_id(self) -> str: ...


class AccountAuthorizations(Protocol):
    def is_connected(self, account_id: ConnectedAccountId) -> bool: ...


@dataclass(frozen=True, slots=True)
class IncidentReport:
    """An Incident to open or refresh; repeated reports under one key update one Incident."""

    key: str
    rule_id: SyncRuleId
    category: str
    summary: str
    """Operational wording only; never an event title or other event content."""
    account_id: ConnectedAccountId | None = None
    """The Connected Account whose failure opened or last refreshed the Incident, if known."""


class IncidentResolution(StrEnum):
    """Why an Incident resolved, so Activity can tell recovery apart from removal."""

    SYNC_SUCCEEDED = "sync_succeeded"
    BLOCKS_CLEARED = "blocks_cleared"
    RULE_REMOVED = "rule_removed"


class IncidentRepository(Protocol):
    def open(self, incident: IncidentReport, at: datetime) -> bool:
        """Open or refresh the Incident under its key; whether it was newly opened.

        Reopening a resolved Incident starts a new episode, so its opening time is `at`.
        """
        ...

    def resolve(self, key: str, at: datetime, resolution: IncidentResolution) -> None:
        """Resolve the Incident under this key, if it is open, recording why."""
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
    def removal_blocked(self, rule_id: SyncRuleId, failure: ProviderFailure) -> None:
        """Open or refresh the one Incident for a removal stopped by lost authorization."""
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


class ConnectedAccountRepository(AccountAuthorizations, Protocol):
    def list(self) -> Sequence[ConnectedAccount]:
        """Every Connected and Disconnected Account, ordered by email."""
        ...

    def get(self, account_id: ConnectedAccountId) -> ConnectedAccount | None: ...

    def disconnect(self, account_id: ConnectedAccountId) -> ConnectedAccount:
        """Discard the account's credentials, keeping its identity for Reauthorization."""
        ...


@dataclass(frozen=True, slots=True)
class DiscoveredCalendar:
    id: str
    summary: str
    access_role: str
    primary: bool


@dataclass(frozen=True, slots=True)
class AccountAccess:
    calendars_visible: int
    writable_calendars: int


class AccountAuthorization(Protocol):
    """The provider's state-protected OAuth flow that connects or reauthorizes an account."""

    def authorization_url(self) -> str: ...

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


class FullPassRecords(Protocol):
    """Bookkeeping that lets a successful full pass stand in for a rule's daily one."""

    def audit_floor(self) -> int:
        """The newest audit entry now, taken before a full pass so its decisions lie above it."""
        ...

    def record_full_pass(self, rule_id: SyncRuleId, floor: int, run_id: str | None = None) -> None:
        """A full pass that began after audit entry `floor` decided every blocked event again."""
        ...
