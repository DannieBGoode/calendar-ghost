from __future__ import annotations

from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Self

from calendar_sync.domain.errors import DomainValidationError, InvalidStateTransition


def _require_non_empty(value: str, label: str) -> None:
    if not value or value.isspace():
        raise DomainValidationError(f"{label} must not be empty")


@dataclass(frozen=True, slots=True)
class ConnectedAccountId:
    value: str

    def __post_init__(self) -> None:
        _require_non_empty(self.value, "connected account id")


@dataclass(frozen=True, slots=True)
class CalendarId:
    value: str

    def __post_init__(self) -> None:
        _require_non_empty(self.value, "calendar id")


@dataclass(frozen=True, slots=True)
class EventId:
    value: str

    def __post_init__(self) -> None:
        _require_non_empty(self.value, "event id")


@dataclass(frozen=True, slots=True)
class SyncRuleId:
    value: str

    def __post_init__(self) -> None:
        _require_non_empty(self.value, "sync rule id")


@dataclass(frozen=True, slots=True)
class EventMappingId:
    value: str

    def __post_init__(self) -> None:
        _require_non_empty(self.value, "event mapping id")


@dataclass(frozen=True, slots=True)
class OccurrenceMappingId:
    value: str

    def __post_init__(self) -> None:
        _require_non_empty(self.value, "occurrence mapping id")


@dataclass(frozen=True, slots=True)
class CalendarEndpoint:
    connected_account_id: ConnectedAccountId
    calendar_id: CalendarId


@dataclass(frozen=True, slots=True)
class EventRef:
    calendar: CalendarEndpoint
    event_id: EventId


@dataclass(frozen=True, slots=True)
class TimedInterval:
    starts_at: datetime
    ends_at: datetime
    time_zone: str | None = None
    """IANA zone that anchors recurrence expansion; meaningful only for a series."""

    def __post_init__(self) -> None:
        if self.starts_at.tzinfo is None or self.ends_at.tzinfo is None:
            raise DomainValidationError("timed event bounds must include a timezone")
        if self.ends_at <= self.starts_at:
            raise DomainValidationError("event end must be after its start")
        if self.time_zone is not None:
            _require_non_empty(self.time_zone, "time zone")


@dataclass(frozen=True, slots=True)
class AllDayRange:
    starts_on: date
    ends_before: date

    def __post_init__(self) -> None:
        if self.ends_before <= self.starts_on:
            raise DomainValidationError("all-day event end date must follow its start date")


EventTime = TimedInterval | AllDayRange


@dataclass(frozen=True, slots=True)
class Recurrence:
    """Provider-neutral iCalendar recurrence lines, including RRULE/RDATE/EXDATE."""

    lines: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.lines or any(not line.strip() for line in self.lines):
            raise DomainValidationError("recurrence must contain non-empty iCalendar lines")


OccurrenceStart = datetime | date
"""An occurrence's original start: a UTC instant for timed series, a date for all-day series."""


def occurrence_start(value: datetime | date) -> OccurrenceStart:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise DomainValidationError("timed occurrence starts must include a timezone")
        return value.astimezone(UTC)
    return value


@dataclass(frozen=True, slots=True)
class OccurrenceIdentity:
    series_event_id: EventId
    original_start: OccurrenceStart

    def __post_init__(self) -> None:
        if isinstance(
            self.original_start, datetime
        ) and self.original_start.utcoffset() != timedelta(0):
            raise DomainValidationError("occurrence original start must be normalized to UTC")


@dataclass(frozen=True, slots=True)
class ManagedOrigin:
    rule_id: SyncRuleId
    source: EventRef

    def owns(self, rule: SyncRule, source: EventRef) -> bool:
        """Whether this origin marks the projection `rule` manages for `source`."""
        return self.rule_id == rule.id and self.source == source


class EventStatus(StrEnum):
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class ProjectionContent(StrEnum):
    """Whether a rule writes Busy-Only or Details Projections; stored and sent as privacy_policy."""

    BUSY_ONLY = "busy_only"
    DETAILS = "copy_details"


class AllDaySyncPolicy(StrEnum):
    INCLUDE = "include"
    EXCLUDE = "exclude"


class ProjectionHandling(StrEnum):
    """What Rule Removal does with mapped Managed Projections."""

    DELETE = "delete"
    DETACH = "detach"


class SyncRuleState(StrEnum):
    DRAFT = "draft"
    PREVIEWED = "dry_run_validated"
    ENABLED = "enabled"
    PAUSED = "paused"
    DEGRADED = "degraded"
    REMOVING = "disabled"


@dataclass(frozen=True, slots=True)
class TransformationPolicy:
    content: ProjectionContent = ProjectionContent.BUSY_ONLY
    all_day: AllDaySyncPolicy = AllDaySyncPolicy.INCLUDE
    busy_title: str = "Busy"

    def __post_init__(self) -> None:
        if self.content is ProjectionContent.BUSY_ONLY:
            _require_non_empty(self.busy_title, "busy title")

    @property
    def includes_all_day(self) -> bool:
        return self.all_day is not AllDaySyncPolicy.EXCLUDE


@dataclass(frozen=True, slots=True)
class CalendarEvent:
    reference: EventRef
    time: EventTime | None
    revision: str
    status: EventStatus = EventStatus.CONFIRMED
    title: str = ""
    description: str = ""
    location: str = ""
    recurrence: Recurrence | None = None
    occurrence: OccurrenceIdentity | None = None
    managed_origin: ManagedOrigin | None = None
    web_link: str | None = None
    guests: tuple[str, ...] | None = None
    """Attendee email addresses, never projected; None when the provider did not list them all."""
    conferencing: tuple[str, ...] | None = None
    """Conferencing entry points, never projected; None when the provider did not return them."""

    def __post_init__(self) -> None:
        _require_non_empty(self.revision, "event revision")
        if self.status is EventStatus.CONFIRMED and self.time is None:
            raise DomainValidationError("confirmed events must include a time")

    @property
    def is_all_day(self) -> bool:
        return isinstance(self.time, AllDayRange)

    def ended_before(self, instant: datetime) -> bool:
        """Whether a single event ended before an instant; a series spans its whole expansion."""
        if self.recurrence is not None or self.time is None:
            return False
        if isinstance(self.time, AllDayRange):
            return self.time.ends_before < instant.date()
        return self.time.ends_at < instant

    def occurrence_reaches(self, instant: datetime) -> bool:
        """Whether an occurrence's original slot, or the time it was moved to, reaches an instant.

        Either one inside the sync window matters: a destination series shows the original slot
        until the exception is applied, and a moved occurrence belongs where it now is.
        """
        if self.occurrence is None:
            raise DomainValidationError("only an occurrence has an original slot")
        original = self.occurrence.original_start
        boundary: date | datetime = instant if isinstance(original, datetime) else instant.date()
        return original >= boundary or (self.time is not None and not self.ended_before(instant))


@dataclass(frozen=True, slots=True)
class EventProjection:
    time: EventTime
    title: str
    description: str = ""
    location: str = ""
    recurrence: Recurrence | None = None


@dataclass(frozen=True, slots=True)
class SyncRule:
    id: SyncRuleId
    source: CalendarEndpoint
    destination: CalendarEndpoint
    transformation: TransformationPolicy = field(default_factory=TransformationPolicy)
    initial_lookback_days: int = 30
    state: SyncRuleState = SyncRuleState.DRAFT
    reprojection_required: bool = False

    def __post_init__(self) -> None:
        if self.source == self.destination:
            raise DomainValidationError("a directional sync rule cannot target its source")
        if self.initial_lookback_days < 0:
            raise DomainValidationError("initial lookback days cannot be negative")

    def uses_account(self, account_id: ConnectedAccountId) -> bool:
        """Whether either calendar of this rule belongs to the Connected Account."""
        return account_id in {
            self.source.connected_account_id,
            self.destination.connected_account_id,
        }

    @property
    def material_signature(self) -> tuple[object, ...]:
        return (self.source, self.destination, self.transformation, self.initial_lookback_days)

    def mark_previewed(self) -> Self:
        if self.state not in {
            SyncRuleState.DRAFT,
            SyncRuleState.PAUSED,
            SyncRuleState.DEGRADED,
        }:
            raise InvalidStateTransition(f"cannot validate a rule in state {self.state}")
        return replace(self, state=SyncRuleState.PREVIEWED)

    def enable(self) -> Self:
        if self.state is not SyncRuleState.PREVIEWED:
            raise InvalidStateTransition(f"cannot enable a rule in state {self.state}")
        return replace(self, state=SyncRuleState.ENABLED)

    def pause(self) -> Self:
        if self.state not in {SyncRuleState.ENABLED, SyncRuleState.DEGRADED}:
            raise InvalidStateTransition(f"cannot pause a rule in state {self.state}")
        return replace(self, state=SyncRuleState.PAUSED)

    def degrade(self) -> Self:
        if self.state not in {SyncRuleState.PREVIEWED, SyncRuleState.ENABLED}:
            raise InvalidStateTransition(f"cannot degrade a rule in state {self.state}")
        return replace(self, state=SyncRuleState.DEGRADED)

    def change_policy(self, transformation: TransformationPolicy) -> Self:
        """Apply a Material Rule Change; the rule must pass a new Rule Preview afterwards."""
        if self.state is SyncRuleState.REMOVING:
            raise InvalidStateTransition("cannot change a rule while its removal is incomplete")
        if transformation == self.transformation:
            return self
        if self.state in {SyncRuleState.ENABLED, SyncRuleState.PAUSED}:
            state = SyncRuleState.PAUSED
        elif self.state is SyncRuleState.DEGRADED:
            state = SyncRuleState.DEGRADED
        else:
            state = SyncRuleState.DRAFT
        return replace(self, transformation=transformation, state=state, reprojection_required=True)

    def complete_reprojection(self) -> Self:
        return replace(self, reprojection_required=False)

    def begin_removal(self) -> Self:
        """Removing marks a Rule Removal that started and has not finished."""
        return replace(self, state=SyncRuleState.REMOVING)


@dataclass(frozen=True, slots=True)
class ProjectionFingerprint:
    value: str

    def __post_init__(self) -> None:
        _require_non_empty(self.value, "projection fingerprint")


@dataclass(frozen=True, slots=True)
class EventMapping:
    id: EventMappingId
    rule_id: SyncRuleId
    source: EventRef
    destination: EventRef
    source_revision: str
    projection_fingerprint: ProjectionFingerprint

    def __post_init__(self) -> None:
        _require_non_empty(self.source_revision, "mapped source revision")

    def belongs_to(self, rule: SyncRule) -> bool:
        """Whether this mapping lies within the rule's directional relationship."""
        return self.rule_id == rule.id and self.destination.calendar == rule.destination


class OccurrenceState(StrEnum):
    MODIFIED = "modified"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class OccurrenceMapping:
    """Ownership evidence for one destination occurrence written under a Series Mapping."""

    id: OccurrenceMappingId
    series_mapping_id: EventMappingId
    original_start: OccurrenceStart
    source: EventRef
    destination: EventRef
    state: OccurrenceState
    source_revision: str
    projection_fingerprint: ProjectionFingerprint | None = None

    def __post_init__(self) -> None:
        _require_non_empty(self.source_revision, "mapped source revision")
        if (self.state is OccurrenceState.MODIFIED) != (self.projection_fingerprint is not None):
            raise DomainValidationError("only modified occurrences carry a projection fingerprint")


class SyncAction(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    IGNORE = "ignore"
    CONFLICT = "conflict"


class SyncReason(StrEnum):
    """Stable, content-free explanation codes recorded with every synchronization decision."""

    SOURCE_CREATED = "source_created"
    PROJECTION_MISSING = "projection_missing"
    SOURCE_CHANGED = "source_changed"
    DESTINATION_DRIFT_REPAIRED = "destination_drift_repaired"
    SOURCE_CANCELLED = "source_cancelled"
    ALL_DAY_EXCLUDED_REMOVED = "all_day_excluded_removed"
    PROJECTION_CURRENT = "projection_current"
    OUTSIDE_SOURCE_CALENDAR = "outside_source_calendar"
    MANAGED_PROJECTION_SOURCE = "managed_projection_source"
    RECURRING_UNSUPPORTED = "recurring_unsupported"
    CANCELLED_WITHOUT_PROJECTION = "cancelled_without_projection"
    ALL_DAY_EXCLUDED = "all_day_excluded"
    BEFORE_SYNC_WINDOW = "before_sync_window"
    MAPPING_INCONSISTENT = "mapping_inconsistent"
    DESTINATION_IDENTITY_INCONSISTENT = "destination_identity_inconsistent"
    DESTINATION_OWNERSHIP_INCONSISTENT = "destination_ownership_inconsistent"
    SOURCE_UNVERIFIABLE = "source_unverifiable"
    OCCURRENCE_CHANGED = "occurrence_changed"
    OCCURRENCE_CANCELLED = "occurrence_cancelled"
    OCCURRENCE_REMOVED_FROM_SERIES = "occurrence_removed_from_series"
    OCCURRENCE_DRIFT_REPAIRED = "occurrence_drift_repaired"
    OCCURRENCE_CURRENT = "occurrence_current"
    OCCURRENCE_ALREADY_CANCELLED = "occurrence_already_cancelled"
    OCCURRENCE_RETIRED = "occurrence_retired"
    SERIES_NOT_SYNCHRONIZED = "series_not_synchronized"
    DESTINATION_OCCURRENCE_MISSING = "destination_occurrence_missing"
    SERIES_WITHOUT_OCCURRENCES = "series_without_occurrences"
    SERIES_WITHOUT_OCCURRENCES_REMOVED = "series_without_occurrences_removed"
    PROJECTION_UNMAPPED = "projection_unmapped"


@dataclass(frozen=True, slots=True)
class SyncDecision:
    action: SyncAction
    reason: SyncReason
    projection: EventProjection | None = None


class DriftKind(StrEnum):
    """How a mapped projection differs from what its source calls for; content, never identity."""

    MISSING = "missing"
    UNEXPECTED = "unexpected"
    INCORRECT_PROJECTION = "incorrect_projection"


@dataclass(frozen=True, slots=True)
class ReconciliationDrift:
    kind: DriftKind
    source: EventRef | None
    destination: EventRef | None
    detail: str


@dataclass(frozen=True, slots=True)
class ReconciliationConflict:
    """A mapping or managed event whose identity a Full Reconciliation cannot prove.

    Like a Sync Run's, it blocks writes to that one event, so it is never counted as drift.
    """

    reason: SyncReason
    source: EventRef | None
    destination: EventRef | None
    detail: str


class NoProjectionExpected(StrEnum):
    """Why a mapped source that could be read calls for no projection."""

    INELIGIBLE = "ineligible"
    """Cancelled, or excluded by the rule's policy: a projection left behind is drift."""
    MANAGED_SOURCE = "managed_source"
    """The source is itself a Managed Projection, so the mapping is a Conflict."""


@dataclass(frozen=True, slots=True)
class OccurrenceCheck:
    """Expected and actual state of one recorded occurrence; `expected=None` means cancelled."""

    mapping: OccurrenceMapping
    destination_series: EventRef
    expected: EventProjection | None
    actual: CalendarEvent | None


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    rule_id: SyncRuleId
    checked_mappings: int
    drift: tuple[ReconciliationDrift, ...]
    conflicts: tuple[ReconciliationConflict, ...] = ()

    @property
    def is_consistent(self) -> bool:
        return not self.drift and not self.conflicts

    def excluding(self, sources: AbstractSet[EventRef]) -> ReconciliationReport:
        """This report without findings about `sources`, which were already reported elsewhere."""
        return replace(
            self,
            drift=tuple(item for item in self.drift if item.source not in sources),
            conflicts=tuple(item for item in self.conflicts if item.source not in sources),
        )
