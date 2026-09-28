# Recurring-Event Synchronization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Project recurring series and occurrence exceptions from a Source Calendar under the same
Directional Sync Rule guarantees as single events.

**Architecture:** A series master maps through an ordinary Event Mapping (a Series Mapping). Each
occurrence the application writes gets a child Occurrence Mapping keyed by a normalized Occurrence
Start. The domain decides occurrences through a new `SyncDecisionService.decide_occurrence`; the
application routes exceptions through a new `SynchronizeOccurrences` collaborator; the Google
adapter resolves instances with `events.instances(originalStart=...)`.

**Tech Stack:** Python 3.12, SQLite, FastAPI, pytest, mypy (strict), ruff; React/TypeScript/Vitest.

**Spec:** `docs/adr/0011-recurring-event-synchronization.md`

## Global Constraints

- Domain (`src/calendar_sync/domain/`) imports only the standard library and domain modules.
- Application code depends only on protocols in `application/ports.py`.
- Raw Google dictionaries stay inside `infrastructure/google/`.
- Every Google write uses `sendUpdates="none"`.
- Event titles, descriptions, and locations never enter SQLite, audit entries, or logs.
- Every sync audit entry carries `run_id` and a `SyncReason` value.
- Migration `0005` is forward-only, runs through `_FORWARD_MIGRATIONS`, and commits atomically with
  its `schema_migrations` row.
- Occurrence writes never call `delete_projection`; masters and single events never call the
  occurrence operations.
- A destination occurrence is cancelled only when the source proves it cancelled or absent from an
  existing source series.
- Keep `eligible_events` and `excluded_events` in the preview response.
- Coverage floor 80%; run the full backend and frontend gates from `AGENTS.md`.

## Review Focus

- Source and destination report the same original start with different offsets (`+02:00` vs `Z`):
  they must match the same occurrence (Task 1 and Task 5 tests).
- Google's cancelled exceptions arrive with only `id`, `status`, `recurringEventId`, and
  `originalStartTime`: translation must accept them (Task 5 test).
- A Busy-Only rule receives a modified source occurrence with a new title: the destination
  occurrence must show the busy title only (Task 2 test).
- A destination occurrence is edited while its source occurrence is unmodified: it must be repaired,
  not reported as a Conflict (Task 7 test).
- A reverse rule observes metadata-less cancelled instances of a managed series: they must be
  ignored (Task 9 test).

---

### Task 1: Domain values for occurrences and time zones

**Files:**
- Modify: `src/calendar_sync/domain/model.py`
- Modify: `src/calendar_sync/domain/services.py` (`ProjectionFingerprinter`)
- Test: `tests/domain/test_model.py`, `tests/domain/test_services.py`

**Interfaces:**
- Produces: `OccurrenceStart = datetime | date`; `occurrence_start(value: datetime | date) -> OccurrenceStart`;
  `OccurrenceIdentity(series_event_id: EventId, original_start: OccurrenceStart)` (timed starts must
  be UTC); `TimedInterval(starts_at, ends_at, time_zone: str | None = None)`;
  `OccurrenceState.MODIFIED|CANCELLED`; `OccurrenceMappingId(value: str)`;
  `OccurrenceMapping(id, series_mapping_id: EventMappingId, original_start, source: EventRef,
  destination: EventRef, state, source_revision: str, projection_fingerprint: ProjectionFingerprint | None = None)`;
  new `SyncReason` members `OCCURRENCE_CHANGED`, `OCCURRENCE_CANCELLED`,
  `OCCURRENCE_REMOVED_FROM_SERIES`, `OCCURRENCE_DRIFT_REPAIRED`, `OCCURRENCE_CURRENT`,
  `OCCURRENCE_ALREADY_CANCELLED`, `OCCURRENCE_RETIRED`, `SERIES_NOT_SYNCHRONIZED`,
  `DESTINATION_OCCURRENCE_MISSING`.

- [ ] **Step 1: Write failing tests**

Append to `tests/domain/test_model.py`:

```python
def test_occurrence_start_normalizes_offsets_to_one_utc_instant() -> None:
    madrid = datetime(2026, 9, 1, 10, 0, tzinfo=timezone(timedelta(hours=2)))
    utc = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)

    assert occurrence_start(madrid) == occurrence_start(utc)
    assert occurrence_start(madrid).utcoffset() == timedelta(0)
    assert occurrence_start(date(2026, 9, 1)) == date(2026, 9, 1)


def test_occurrence_start_rejects_naive_times() -> None:
    with pytest.raises(DomainValidationError):
        occurrence_start(datetime(2026, 9, 1, 8, 0))


def test_occurrence_identity_requires_a_normalized_start() -> None:
    with pytest.raises(DomainValidationError):
        OccurrenceIdentity(
            EventId("series"), datetime(2026, 9, 1, 10, 0, tzinfo=timezone(timedelta(hours=2)))
        )


def test_timed_interval_rejects_a_blank_time_zone() -> None:
    with pytest.raises(DomainValidationError):
        TimedInterval(NOW, NOW + timedelta(hours=1), " ")


def test_only_modified_occurrence_mappings_carry_a_fingerprint() -> None:
    source = EventRef(rule().source, EventId("series_20260901T080000Z"))
    destination = EventRef(rule().destination, EventId("projection_20260901T080000Z"))
    start = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)

    with pytest.raises(DomainValidationError):
        OccurrenceMapping(
            OccurrenceMappingId("o-1"),
            EventMappingId("m-1"),
            start,
            source,
            destination,
            OccurrenceState.MODIFIED,
            "r-1",
        )
    with pytest.raises(DomainValidationError):
        OccurrenceMapping(
            OccurrenceMappingId("o-1"),
            EventMappingId("m-1"),
            start,
            source,
            destination,
            OccurrenceState.CANCELLED,
            "r-1",
            ProjectionFingerprint("f"),
        )
```

Add imports to `tests/domain/test_model.py`: `from datetime import UTC, date, datetime, timedelta, timezone`,
`import pytest`, and from `calendar_sync.domain.model`: `EventId, EventMappingId, EventRef,
OccurrenceIdentity, OccurrenceMapping, OccurrenceMappingId, OccurrenceState, ProjectionFingerprint,
TimedInterval, occurrence_start`; `from calendar_sync.domain.errors import DomainValidationError`;
`from tests.helpers import NOW, rule` (merge with existing imports).

Append to `tests/domain/test_services.py`:

```python
def test_fingerprint_compares_timed_bounds_as_instants() -> None:
    fingerprinter = ProjectionFingerprinter()
    offset = timezone(timedelta(hours=2))
    utc = EventProjection(TimedInterval(NOW, NOW + timedelta(hours=1)), "Busy")
    local = EventProjection(
        TimedInterval(NOW.astimezone(offset), (NOW + timedelta(hours=1)).astimezone(offset)), "Busy"
    )

    assert fingerprinter.fingerprint(utc) == fingerprinter.fingerprint(local)


def test_fingerprint_includes_time_zone_only_for_series() -> None:
    fingerprinter = ProjectionFingerprinter()
    zoned = TimedInterval(NOW, NOW + timedelta(hours=1), "Europe/Madrid")
    plain = TimedInterval(NOW, NOW + timedelta(hours=1))
    weekly = Recurrence(("RRULE:FREQ=WEEKLY",))

    assert fingerprinter.fingerprint(EventProjection(zoned, "Busy")) == fingerprinter.fingerprint(
        EventProjection(plain, "Busy")
    )
    assert fingerprinter.fingerprint(
        EventProjection(zoned, "Busy", recurrence=weekly)
    ) != fingerprinter.fingerprint(EventProjection(plain, "Busy", recurrence=weekly))
```

Add `EventProjection`, `TimedInterval` and `from datetime import timedelta, timezone` imports and
`from tests.helpers import NOW` where missing.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/domain -q`
Expected: FAIL (ImportError for `occurrence_start`, `OccurrenceMapping`, and friends).

- [ ] **Step 3: Implement the domain values**

In `src/calendar_sync/domain/model.py`, change the datetime import to
`from datetime import UTC, date, datetime, timedelta`. Replace `TimedInterval`:

```python
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
```

Replace `OccurrenceIdentity` with:

```python
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
```

After `EventMappingId`, add:

```python
@dataclass(frozen=True, slots=True)
class OccurrenceMappingId:
    value: str

    def __post_init__(self) -> None:
        _require_non_empty(self.value, "occurrence mapping id")
```

After `EventMapping`, add:

```python
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
```

Add to `SyncReason` (after `SOURCE_UNVERIFIABLE`):

```python
    OCCURRENCE_CHANGED = "occurrence_changed"
    OCCURRENCE_CANCELLED = "occurrence_cancelled"
    OCCURRENCE_REMOVED_FROM_SERIES = "occurrence_removed_from_series"
    OCCURRENCE_DRIFT_REPAIRED = "occurrence_drift_repaired"
    OCCURRENCE_CURRENT = "occurrence_current"
    OCCURRENCE_ALREADY_CANCELLED = "occurrence_already_cancelled"
    OCCURRENCE_RETIRED = "occurrence_retired"
    SERIES_NOT_SYNCHRONIZED = "series_not_synchronized"
    DESTINATION_OCCURRENCE_MISSING = "destination_occurrence_missing"
```

In `src/calendar_sync/domain/services.py`, add `UTC` to the datetime import and replace the
fingerprint time serialization:

```python
def fingerprint(self, projection: EventProjection) -> ProjectionFingerprint:
    payload = {
        "time": self._serialize_time(projection.time, recurring=projection.recurrence is not None),
        "title": projection.title,
        "description": projection.description,
        "location": projection.location,
        "recurrence": projection.recurrence.lines if projection.recurrence else None,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return ProjectionFingerprint(hashlib.sha256(encoded.encode()).hexdigest())


@staticmethod
def _serialize_time(value: TimedInterval | AllDayRange, *, recurring: bool) -> dict[str, str]:
    if isinstance(value, TimedInterval):
        serialized = {
            "kind": "timed",
            "starts_at": value.starts_at.astimezone(UTC).isoformat(),
            "ends_at": value.ends_at.astimezone(UTC).isoformat(),
        }
        # Only a series expands in its zone; single instants are zone-independent.
        if recurring and value.time_zone is not None:
            serialized["time_zone"] = value.time_zone
        return serialized
    return {
        "kind": "all_day",
        "starts_on": _serialize_temporal(value.starts_on),
        "ends_before": _serialize_temporal(value.ends_before),
    }
```

In `src/calendar_sync/infrastructure/google/translation.py`, keep it compiling by replacing the
occurrence parsing block temporarily with the typed start (Task 5 extends it):

```python
    if isinstance(recurring_event_id, str) and isinstance(original_start, Mapping):
        parsed_start = _parse_original_start(original_start)
        if parsed_start is not None:
            occurrence = OccurrenceIdentity(EventId(recurring_event_id), parsed_start)
```

and add:

```python
def _parse_original_start(value: Mapping[str, Any]) -> OccurrenceStart | None:
    timed = value.get("dateTime")
    if isinstance(timed, str):
        return occurrence_start(_parse_datetime(timed))
    all_day = value.get("date")
    if isinstance(all_day, str):
        return date.fromisoformat(all_day)
    return None
```

importing `OccurrenceStart` and `occurrence_start` from the domain model.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests -q -p no:warnings && .venv/bin/mypy`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/calendar_sync/domain src/calendar_sync/infrastructure/google/translation.py tests/domain
git commit -m "feat: model occurrence starts, occurrence mappings, and series time zones"
```

---

### Task 2: Series and occurrence decisions

**Files:**
- Modify: `src/calendar_sync/domain/services.py` (`SyncDecisionService`)
- Modify: `tests/helpers.py`
- Create: `tests/domain/test_occurrence_decisions.py`
- Modify: `tests/domain/test_services.py` (replace the recurring-skip test)

**Interfaces:**
- Consumes: Task 1 values.
- Produces:
  `SyncDecisionService.decide(...)` now projects series (with `recurrence` and the series
  `time_zone`) and raises `DomainValidationError` for events carrying `occurrence`;
  `SyncDecisionService.decide_occurrence(rule, source_series, series_mapping, original_start,
  source_occurrence, occurrence_mapping, destination_series, destination_occurrence, *,
  destination_reported=False) -> SyncDecision` — `UPDATE` writes or restores the destination
  occurrence (projection set), `DELETE` cancels it, `IGNORE` with `OCCURRENCE_CURRENT` carries the
  projection. Test helpers `SERIES_START`, `week_start(week)`, `series(...)`, `occurrence(...)`,
  `instance_id(series_id, start)`.

- [ ] **Step 1: Add test helpers**

Append to `tests/helpers.py` (extend the model import with `EventStatus, ManagedOrigin,
OccurrenceIdentity, OccurrenceStart, Recurrence`):

```python
SERIES_START = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)


def week_start(week: int) -> datetime:
    return SERIES_START + timedelta(weeks=week)


def instance_id(series_id: str, start: OccurrenceStart) -> str:
    token = (
        start.strftime("%Y%m%dT%H%M%SZ")
        if isinstance(start, datetime)
        else start.strftime("%Y%m%d")
    )
    return f"{series_id}_{token}"


def series(
    event_id: str = "source-series",
    *,
    calendar: CalendarEndpoint | None = None,
    revision: str = "series-revision-1",
    title: str = "Weekly private sync",
    all_day: bool = False,
    managed_origin: ManagedOrigin | None = None,
    status: EventStatus = EventStatus.CONFIRMED,
) -> CalendarEvent:
    time = (
        AllDayRange(SERIES_START.date(), SERIES_START.date() + timedelta(days=1))
        if all_day
        else TimedInterval(SERIES_START, SERIES_START + timedelta(hours=1), "Europe/Madrid")
    )
    return CalendarEvent(
        reference=EventRef(calendar or rule().source, EventId(event_id)),
        time=None if status is EventStatus.CANCELLED else time,
        revision=revision,
        status=status,
        title=title,
        description="Sensitive description",
        location="Sensitive location",
        recurrence=Recurrence(("RRULE:FREQ=WEEKLY;COUNT=10",)),
        managed_origin=managed_origin,
    )


def occurrence(
    parent: CalendarEvent,
    week: int = 1,
    *,
    moved_by: timedelta = timedelta(0),
    revision: str = "occurrence-revision-1",
    title: str | None = None,
    status: EventStatus = EventStatus.CONFIRMED,
    all_day: bool = False,
    managed_origin: ManagedOrigin | None = None,
) -> CalendarEvent:
    start = week_start(week)
    time: TimedInterval | AllDayRange | None
    if status is EventStatus.CANCELLED:
        time = None
    elif all_day:
        time = AllDayRange(start.date(), start.date() + timedelta(days=1))
    else:
        time = TimedInterval(start + moved_by, start + moved_by + timedelta(hours=1))
    return CalendarEvent(
        reference=EventRef(
            parent.reference.calendar,
            EventId(instance_id(parent.reference.event_id.value, start)),
        ),
        time=time,
        revision=revision,
        status=status,
        title="" if status is EventStatus.CANCELLED else (title or parent.title),
        description="" if status is EventStatus.CANCELLED else parent.description,
        location="" if status is EventStatus.CANCELLED else parent.location,
        occurrence=OccurrenceIdentity(parent.reference.event_id, start),
        managed_origin=managed_origin,
    )
```

- [ ] **Step 2: Write failing decision tests**

Create `tests/domain/test_occurrence_decisions.py`:

```python
from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from calendar_sync.domain.errors import DomainValidationError
from calendar_sync.domain.model import (
    AllDaySyncPolicy,
    CalendarEvent,
    EventId,
    EventMapping,
    EventMappingId,
    EventRef,
    EventStatus,
    ManagedOrigin,
    OccurrenceMapping,
    OccurrenceMappingId,
    OccurrenceState,
    PrivacyPolicy,
    ProjectionFingerprint,
    SyncAction,
    SyncReason,
    SyncRule,
    SyncRuleId,
    TimedInterval,
    TransformationPolicy,
)
from calendar_sync.domain.services import (
    EventProjector,
    ProjectionFingerprinter,
    SyncDecisionService,
)
from tests.helpers import occurrence, rule, series, week_start

SOURCE = series()
DESTINATION = series(
    "projection-1",
    calendar=rule().destination,
    title="Busy",
    managed_origin=ManagedOrigin(rule().id, SOURCE.reference),
)
SERIES_MAPPING = EventMapping(
    EventMappingId("series-mapping"),
    rule().id,
    SOURCE.reference,
    DESTINATION.reference,
    SOURCE.revision,
    ProjectionFingerprint("series-fingerprint"),
)
START = week_start(1)


def service() -> SyncDecisionService:
    return SyncDecisionService(EventProjector(), ProjectionFingerprinter())


def busy_instance(**changes: object) -> CalendarEvent:
    instance = occurrence(DESTINATION, 1, title="Busy")
    return replace(instance, description="", location="", **changes)  # type: ignore[arg-type]


def recorded(
    state: OccurrenceState = OccurrenceState.MODIFIED, revision: str = "occurrence-revision-1"
) -> OccurrenceMapping:
    return OccurrenceMapping(
        OccurrenceMappingId("occurrence-mapping"),
        SERIES_MAPPING.id,
        START,
        occurrence(SOURCE, 1).reference,
        busy_instance().reference,
        state,
        revision,
        ProjectionFingerprint("f") if state is OccurrenceState.MODIFIED else None,
    )


def decide(
    source_occurrence: CalendarEvent | None,
    destination_occurrence: CalendarEvent | None,
    *,
    sync_rule: SyncRule | None = None,
    source_series: CalendarEvent = SOURCE,
    series_mapping: EventMapping | None = SERIES_MAPPING,
    occurrence_mapping: OccurrenceMapping | None = None,
    destination_series: CalendarEvent | None = DESTINATION,
    destination_reported: bool = False,
):  # type: ignore[no-untyped-def]
    return service().decide_occurrence(
        sync_rule or rule(),
        source_series,
        series_mapping,
        START,
        source_occurrence,
        occurrence_mapping,
        destination_series,
        destination_occurrence,
        destination_reported=destination_reported,
    )


def test_series_master_projects_as_a_series_with_its_time_zone() -> None:
    decision = service().decide(rule(), SOURCE, None, None)

    assert decision.action is SyncAction.CREATE
    assert decision.projection is not None
    assert decision.projection.recurrence == SOURCE.recurrence
    assert isinstance(decision.projection.time, TimedInterval)
    assert decision.projection.time.time_zone == "Europe/Madrid"
    assert decision.projection.title == "Busy"


def test_single_event_decision_rejects_occurrence_exceptions() -> None:
    with pytest.raises(DomainValidationError):
        service().decide(rule(), occurrence(SOURCE, 1), None, None)


def test_moved_occurrence_updates_destination_with_busy_title_only() -> None:
    moved = occurrence(SOURCE, 1, moved_by=timedelta(hours=2), title="Secret offsite")

    decision = decide(moved, busy_instance())

    assert decision.action is SyncAction.UPDATE
    assert decision.reason is SyncReason.OCCURRENCE_CHANGED
    assert decision.projection is not None
    assert decision.projection.title == "Busy"
    assert decision.projection.description == ""
    assert decision.projection.location == ""
    assert decision.projection.recurrence is None
    assert decision.projection.time == moved.time


def test_details_rule_copies_occurrence_details() -> None:
    details = replace(
        rule(), transformation=TransformationPolicy(privacy=PrivacyPolicy.COPY_DETAILS)
    )
    moved = occurrence(SOURCE, 1, title="Offsite")

    decision = decide(moved, busy_instance(), sync_rule=details)

    assert decision.projection is not None
    assert decision.projection.title == "Offsite"


def test_matching_occurrence_is_current_and_keeps_its_projection() -> None:
    decision = decide(occurrence(SOURCE, 1), busy_instance())

    assert decision.action is SyncAction.IGNORE
    assert decision.reason is SyncReason.OCCURRENCE_CURRENT
    assert decision.projection is not None


def test_destination_edit_with_unchanged_source_is_drift_repair() -> None:
    edited = busy_instance(title="Edited in destination")

    decision = decide(occurrence(SOURCE, 1), edited, occurrence_mapping=recorded())

    assert decision.action is SyncAction.UPDATE
    assert decision.reason is SyncReason.OCCURRENCE_DRIFT_REPAIRED


def test_unmapped_destination_edit_reported_by_the_feed_is_drift_repair() -> None:
    edited = busy_instance(title="Edited in destination")

    decision = decide(occurrence(SOURCE, 1), edited, destination_reported=True)

    assert decision.reason is SyncReason.OCCURRENCE_DRIFT_REPAIRED


def test_cancelled_destination_occurrence_is_restored() -> None:
    cancelled = occurrence(DESTINATION, 1, status=EventStatus.CANCELLED)

    decision = decide(occurrence(SOURCE, 1), cancelled, destination_reported=True)

    assert decision.action is SyncAction.UPDATE
    assert decision.projection is not None


def test_cancelled_source_occurrence_cancels_the_destination_occurrence() -> None:
    cancelled = occurrence(SOURCE, 1, status=EventStatus.CANCELLED)

    decision = decide(cancelled, busy_instance())

    assert decision.action is SyncAction.DELETE
    assert decision.reason is SyncReason.OCCURRENCE_CANCELLED


def test_already_cancelled_destination_occurrence_is_left_alone() -> None:
    cancelled = occurrence(SOURCE, 1, status=EventStatus.CANCELLED)
    destination = occurrence(DESTINATION, 1, status=EventStatus.CANCELLED)

    decision = decide(cancelled, destination)

    assert decision.action is SyncAction.IGNORE
    assert decision.reason is SyncReason.OCCURRENCE_ALREADY_CANCELLED


def test_occurrence_no_longer_in_source_series_is_cancelled() -> None:
    decision = decide(None, busy_instance(), occurrence_mapping=recorded())

    assert decision.action is SyncAction.DELETE
    assert decision.reason is SyncReason.OCCURRENCE_REMOVED_FROM_SERIES


def test_occurrence_absent_on_both_sides_is_retired() -> None:
    decision = decide(None, None, occurrence_mapping=recorded())

    assert decision.action is SyncAction.IGNORE
    assert decision.reason is SyncReason.OCCURRENCE_RETIRED


def test_all_day_occurrence_under_an_excluding_rule_is_cancelled() -> None:
    timed_only = replace(
        rule(), transformation=TransformationPolicy(all_day=AllDaySyncPolicy.EXCLUDE)
    )

    decision = decide(occurrence(SOURCE, 1, all_day=True), busy_instance(), sync_rule=timed_only)

    assert decision.action is SyncAction.DELETE
    assert decision.reason is SyncReason.ALL_DAY_EXCLUDED_REMOVED


def test_occurrence_of_an_unsynchronized_series_is_ignored() -> None:
    decision = decide(occurrence(SOURCE, 1), None, series_mapping=None, destination_series=None)

    assert decision.action is SyncAction.IGNORE
    assert decision.reason is SyncReason.SERIES_NOT_SYNCHRONIZED


def test_occurrence_of_a_managed_series_is_ignored() -> None:
    managed = replace(SOURCE, managed_origin=ManagedOrigin(SyncRuleId("other"), SOURCE.reference))

    decision = decide(occurrence(managed, 1), None, source_series=managed, series_mapping=None)

    assert decision.reason is SyncReason.MANAGED_PROJECTION_SOURCE


def test_destination_series_owned_by_another_rule_blocks_the_write() -> None:
    foreign = replace(
        DESTINATION, managed_origin=ManagedOrigin(SyncRuleId("other"), SOURCE.reference)
    )

    decision = decide(occurrence(SOURCE, 1), busy_instance(), destination_series=foreign)

    assert decision.action is SyncAction.CONFLICT
    assert decision.reason is SyncReason.DESTINATION_OWNERSHIP_INCONSISTENT


def test_destination_occurrence_of_another_series_blocks_the_write() -> None:
    other_parent = replace(
        DESTINATION, reference=EventRef(rule().destination, EventId("unrelated"))
    )

    decision = decide(occurrence(SOURCE, 1), occurrence(other_parent, 1))

    assert decision.action is SyncAction.CONFLICT
    assert decision.reason is SyncReason.DESTINATION_IDENTITY_INCONSISTENT


def test_destination_occurrence_naming_another_source_blocks_the_write() -> None:
    wrong_origin = busy_instance(
        managed_origin=ManagedOrigin(rule().id, EventRef(rule().source, EventId("someone-else")))
    )

    decision = decide(occurrence(SOURCE, 1), wrong_origin)

    assert decision.action is SyncAction.CONFLICT
    assert decision.reason is SyncReason.DESTINATION_OWNERSHIP_INCONSISTENT


def test_occurrence_mapping_of_another_series_is_inconsistent() -> None:
    foreign = replace(recorded(), series_mapping_id=EventMappingId("other-series"))

    decision = decide(occurrence(SOURCE, 1), busy_instance(), occurrence_mapping=foreign)

    assert decision.action is SyncAction.CONFLICT
    assert decision.reason is SyncReason.MAPPING_INCONSISTENT


def test_missing_destination_occurrence_is_a_conflict_not_a_guess() -> None:
    decision = decide(occurrence(SOURCE, 1), None)

    assert decision.action is SyncAction.CONFLICT
    assert decision.reason is SyncReason.DESTINATION_OCCURRENCE_MISSING
```

In `tests/domain/test_services.py`, replace
`test_recurring_event_is_skipped_until_series_mapping_is_supported` with:

```python
def test_recurring_series_is_created_as_a_series() -> None:
    source = replace(event(), recurrence=Recurrence(("RRULE:FREQ=WEEKLY",)))

    decision = SyncDecisionService(EventProjector(), ProjectionFingerprinter()).decide(
        rule(), source, None, None
    )

    assert decision.action is SyncAction.CREATE
    assert decision.projection is not None
    assert decision.projection.recurrence == source.recurrence
```

In `tests/application/test_execute_sync_rule.py`, the single-event fake cannot project a second
event, so rewrite `test_each_run_groups_its_audit_entries_and_skips_recurring_events` as
`test_each_run_groups_its_audit_entries` using a managed event instead of a recurring one:

```python
    managed = replace(event("managed"), managed_origin=ManagedOrigin(rule().id, event().reference))
    provider = FakeCalendarProvider(event())
    provider.source_changes = (event(), managed)
    ...
    provider.source_changes = (managed,)
    ...
    assert first.created == 1
    assert first.ignored == 1
    assert [...] == [
        ("run-1", "create", "completed", SyncReason.SOURCE_CREATED),
        ("run-1", "ignore", "skipped", SyncReason.MANAGED_PROJECTION_SOURCE),
        ("run-2", "ignore", "skipped", SyncReason.MANAGED_PROJECTION_SOURCE),
    ]
```

(keep the rest of the test body unchanged).

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/domain -q -p no:warnings`
Expected: FAIL (`decide_occurrence` missing; recurring series still ignored).

- [ ] **Step 4: Implement the decisions**

In `SyncDecisionService.decide`, replace the recurring exclusion with:

```python
        if source_event.occurrence is not None:
            raise DomainValidationError("occurrence exceptions are decided through their series")
```

Add to `SyncDecisionService` (extend imports with `OccurrenceMapping`, `OccurrenceStart`,
`ManagedOrigin`):

```python
def decide_occurrence(
    self,
    rule: SyncRule,
    source_series: CalendarEvent,
    series_mapping: EventMapping | None,
    original_start: OccurrenceStart,
    source_occurrence: CalendarEvent | None,
    occurrence_mapping: OccurrenceMapping | None,
    destination_series: CalendarEvent | None,
    destination_occurrence: CalendarEvent | None,
    *,
    destination_reported: bool = False,
) -> SyncDecision:
    """Decide one occurrence of a mapped series; `None` occurrences mean "no such occurrence"."""
    if source_series.reference.calendar != rule.source:
        return SyncDecision(SyncAction.IGNORE, SyncReason.OUTSIDE_SOURCE_CALENDAR)
    if source_series.managed_origin is not None:
        return SyncDecision(SyncAction.IGNORE, SyncReason.MANAGED_PROJECTION_SOURCE)
    if series_mapping is None or source_series.status is EventStatus.CANCELLED:
        return SyncDecision(SyncAction.IGNORE, SyncReason.SERIES_NOT_SYNCHRONIZED)
    if (
        series_mapping.rule_id != rule.id
        or series_mapping.source != source_series.reference
        or series_mapping.destination.calendar != rule.destination
        or (
            occurrence_mapping is not None
            and (
                occurrence_mapping.series_mapping_id != series_mapping.id
                or occurrence_mapping.original_start != original_start
            )
        )
        or (
            source_occurrence is not None
            and not _is_occurrence_of(source_occurrence, source_series.reference, original_start)
        )
    ):
        return SyncDecision(SyncAction.CONFLICT, SyncReason.MAPPING_INCONSISTENT)
    if (
        destination_series is None
        or destination_series.status is EventStatus.CANCELLED
        or destination_series.reference != series_mapping.destination
    ):
        return SyncDecision(SyncAction.CONFLICT, SyncReason.DESTINATION_OCCURRENCE_MISSING)
    if not _owned_by(destination_series.managed_origin, rule, source_series.reference):
        return SyncDecision(SyncAction.CONFLICT, SyncReason.DESTINATION_OWNERSHIP_INCONSISTENT)
    if destination_occurrence is not None:
        if not _is_occurrence_of(
            destination_occurrence, series_mapping.destination, original_start
        ):
            return SyncDecision(SyncAction.CONFLICT, SyncReason.DESTINATION_IDENTITY_INCONSISTENT)
        # Google omits metadata on cancelled instances; the parent series proves ownership.
        if destination_occurrence.managed_origin is not None and not _owned_by(
            destination_occurrence.managed_origin, rule, source_series.reference
        ):
            return SyncDecision(SyncAction.CONFLICT, SyncReason.DESTINATION_OWNERSHIP_INCONSISTENT)

    destination_absent = (
        destination_occurrence is None or destination_occurrence.status is EventStatus.CANCELLED
    )
    if source_occurrence is None:
        if destination_absent:
            return SyncDecision(SyncAction.IGNORE, SyncReason.OCCURRENCE_RETIRED)
        return SyncDecision(SyncAction.DELETE, SyncReason.OCCURRENCE_REMOVED_FROM_SERIES)
    excluded_all_day = (
        source_occurrence.is_all_day and rule.transformation.all_day is AllDaySyncPolicy.EXCLUDE
    )
    if source_occurrence.status is EventStatus.CANCELLED or excluded_all_day:
        if destination_absent:
            return SyncDecision(SyncAction.IGNORE, SyncReason.OCCURRENCE_ALREADY_CANCELLED)
        reason = (
            SyncReason.OCCURRENCE_CANCELLED
            if source_occurrence.status is EventStatus.CANCELLED
            else SyncReason.ALL_DAY_EXCLUDED_REMOVED
        )
        return SyncDecision(SyncAction.DELETE, reason)
    if destination_occurrence is None:
        return SyncDecision(SyncAction.CONFLICT, SyncReason.DESTINATION_OCCURRENCE_MISSING)

    projection = self._projector.project(source_occurrence, rule)
    source_unchanged = (
        occurrence_mapping is not None
        and occurrence_mapping.source_revision == source_occurrence.revision
    )
    changed = (
        SyncReason.OCCURRENCE_DRIFT_REPAIRED
        if source_unchanged or destination_reported
        else SyncReason.OCCURRENCE_CHANGED
    )
    if destination_occurrence.status is EventStatus.CANCELLED:
        return SyncDecision(SyncAction.UPDATE, changed, projection)
    expected = self._fingerprinter.fingerprint(projection)
    actual = self._fingerprinter.fingerprint(self._as_projection(destination_occurrence))
    if expected == actual and (occurrence_mapping is None or source_unchanged):
        return SyncDecision(SyncAction.IGNORE, SyncReason.OCCURRENCE_CURRENT, projection)
    return SyncDecision(SyncAction.UPDATE, changed, projection)
```

Module-level helpers in `services.py`:

```python
def _is_occurrence_of(event: CalendarEvent, series: EventRef, start: OccurrenceStart) -> bool:
    return (
        event.occurrence is not None
        and event.reference.calendar == series.calendar
        and event.occurrence.series_event_id == series.event_id
        and event.occurrence.original_start == start
    )


def _owned_by(origin: ManagedOrigin | None, rule: SyncRule, source: EventRef) -> bool:
    return origin is not None and origin.rule_id == rule.id and origin.source == source
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/pytest tests -q -p no:warnings && .venv/bin/mypy`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/calendar_sync/domain/services.py tests/helpers.py tests/domain tests/application/test_execute_sync_rule.py
git commit -m "feat: decide recurring series and occurrence exceptions in the domain"
```

---

### Task 3: Reconciliation of occurrences in the domain

**Files:**
- Modify: `src/calendar_sync/domain/model.py` (add `OccurrenceCheck`)
- Modify: `src/calendar_sync/domain/services.py` (`ReconciliationService.reconcile`)
- Test: `tests/domain/test_services.py`

**Interfaces:**
- Produces: `OccurrenceCheck(mapping: OccurrenceMapping, destination_series: EventRef,
  expected: EventProjection | None, actual: CalendarEvent | None)`;
  `ReconciliationService.reconcile(rule, mappings, expected_by_source, actual_by_destination,
  occurrences: Iterable[OccurrenceCheck] = ())`.

- [ ] **Step 1: Write failing tests**

Append to `tests/domain/test_services.py`:

```python
def _series_reconciliation_inputs():  # type: ignore[no-untyped-def]
    source = series()
    destination = series(
        "projection-1",
        calendar=rule().destination,
        title="Busy",
        managed_origin=ManagedOrigin(rule().id, source.reference),
    )
    destination = replace(destination, description="", location="")
    mapping = EventMapping(
        EventMappingId("series-mapping"),
        rule().id,
        source.reference,
        destination.reference,
        source.revision,
        ProjectionFingerprint("f"),
    )
    expected = {source.reference: EventProjector().project(source, rule())}
    return source, destination, mapping, expected


def _occurrence_mapping(mapping: EventMapping, destination: CalendarEvent, state: OccurrenceState):  # type: ignore[no-untyped-def]
    return OccurrenceMapping(
        OccurrenceMappingId("o-1"),
        mapping.id,
        week_start(1),
        occurrence(series(), 1).reference,
        occurrence(destination, 1).reference,
        state,
        "r-1",
        ProjectionFingerprint("f") if state is OccurrenceState.MODIFIED else None,
    )


def test_reconciliation_reports_edited_and_resurrected_occurrences() -> None:
    source, destination, mapping, expected = _series_reconciliation_inputs()
    edited = replace(occurrence(destination, 1, title="Edited"), description="", location="")
    service = ReconciliationService(ProjectionFingerprinter())

    report = service.reconcile(
        rule(),
        [mapping],
        expected,
        {destination.reference: destination, edited.reference: edited},
        [
            OccurrenceCheck(
                _occurrence_mapping(mapping, destination, OccurrenceState.MODIFIED),
                destination.reference,
                EventProjector().project(occurrence(source, 1), rule()),
                edited,
            ),
            OccurrenceCheck(
                replace(
                    _occurrence_mapping(mapping, destination, OccurrenceState.CANCELLED),
                    original_start=week_start(2),
                ),
                destination.reference,
                None,
                replace(occurrence(destination, 2, title="Busy"), description="", location=""),
            ),
        ],
    )

    assert [item.kind for item in report.drift] == [
        DriftKind.INCORRECT_PROJECTION,
        DriftKind.INCORRECT_PROJECTION,
    ]
    assert report.checked_mappings == 1


def test_reconciliation_reports_a_missing_occurrence() -> None:
    source, destination, mapping, expected = _series_reconciliation_inputs()

    report = ReconciliationService(ProjectionFingerprinter()).reconcile(
        rule(),
        [mapping],
        expected,
        {destination.reference: destination},
        [
            OccurrenceCheck(
                _occurrence_mapping(mapping, destination, OccurrenceState.MODIFIED),
                destination.reference,
                EventProjector().project(occurrence(source, 1), rule()),
                None,
            )
        ],
    )

    assert [item.kind for item in report.drift] == [DriftKind.MISSING]


def test_unmapped_managed_exception_of_a_mapped_series_is_incorrect_not_unexpected() -> None:
    _source, destination, mapping, expected = _series_reconciliation_inputs()
    stray = replace(
        occurrence(destination, 3, title="Edited"),
        managed_origin=destination.managed_origin,
    )

    report = ReconciliationService(ProjectionFingerprinter()).reconcile(
        rule(),
        [mapping],
        expected,
        {destination.reference: destination, stray.reference: stray},
    )

    assert [item.kind for item in report.drift] == [DriftKind.INCORRECT_PROJECTION]
```

Add imports: `CalendarEvent`, `DriftKind`, `EventMapping`, `EventMappingId`, `ManagedOrigin`,
`OccurrenceCheck`, `OccurrenceMapping`, `OccurrenceMappingId`, `OccurrenceState`,
`ProjectionFingerprint`, `ReconciliationService` and `occurrence, series, week_start` from helpers.

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/domain/test_services.py -q -p no:warnings`
Expected: FAIL (`OccurrenceCheck` missing).

- [ ] **Step 3: Implement**

In `model.py` after `ReconciliationDrift`:

```python
@dataclass(frozen=True, slots=True)
class OccurrenceCheck:
    """Expected and actual state of one recorded occurrence; `expected=None` means cancelled."""

    mapping: OccurrenceMapping
    destination_series: EventRef
    expected: EventProjection | None
    actual: CalendarEvent | None
```

In `ReconciliationService.reconcile`, add the parameter `occurrences: Iterable[OccurrenceCheck] = ()`
and, before the unexpected-destination loop:

```python
checked_occurrences: set[tuple[EventRef, OccurrenceStart]] = set()
for check in occurrences:
    checked_occurrences.add((check.destination_series, check.mapping.original_start))
    present = check.actual is not None and check.actual.status is EventStatus.CONFIRMED
    if check.expected is None:
        if present:
            drift.append(
                ReconciliationDrift(
                    DriftKind.INCORRECT_PROJECTION,
                    check.mapping.source,
                    check.mapping.destination,
                    "managed occurrence should be cancelled",
                )
            )
    elif not present:
        drift.append(
            ReconciliationDrift(
                DriftKind.MISSING,
                check.mapping.source,
                check.mapping.destination,
                "managed occurrence is missing",
            )
        )
    elif self._fingerprinter.fingerprint(check.expected) != self._fingerprinter.fingerprint(
        SyncDecisionService._as_projection(check.actual)  # type: ignore[arg-type]
    ):
        drift.append(
            ReconciliationDrift(
                DriftKind.INCORRECT_PROJECTION,
                check.mapping.source,
                check.mapping.destination,
                "managed occurrence differs from source authority",
            )
        )
```

Replace the unexpected-destination loop with:

```python
        for destination in actual_by_destination.keys() - managed_destinations:
            parent = actual_by_destination[destination].occurrence
            if parent is not None:
                series_ref = EventRef(destination.calendar, parent.series_event_id)
                if series_ref in managed_destinations:
                    if (series_ref, parent.original_start) not in checked_occurrences:
                        drift.append(
                            ReconciliationDrift(
                                DriftKind.INCORRECT_PROJECTION,
                                None,
                                destination,
                                "managed occurrence has no occurrence mapping",
                            )
                        )
                    continue
            drift.append(
                ReconciliationDrift(
                    DriftKind.UNEXPECTED,
                    None,
                    destination,
                    "managed provider event has no mapping",
                )
            )
```

If mypy rejects the `type: ignore` in the fingerprint branch, bind
`actual = check.actual` and `assert actual is not None` before comparing instead.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/domain -q -p no:warnings && .venv/bin/mypy`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/calendar_sync/domain tests/domain
git commit -m "feat: reconcile recorded occurrences against source authority"
```

---

### Task 4: Occurrence Mapping persistence and migration 0005

**Files:**
- Modify: `src/calendar_sync/application/ports.py`
- Modify: `src/calendar_sync/infrastructure/persistence/memory.py`
- Modify: `src/calendar_sync/infrastructure/persistence/sqlite.py`
- Create: `src/calendar_sync/infrastructure/persistence/0005_occurrence_mappings.sql`
- Test: `tests/adapters/test_sqlite.py`, create `tests/adapters/test_memory_persistence.py`

**Interfaces:**
- Produces: `OccurrenceMappingRepository` protocol with `for_series(series_mapping_id) ->
  Sequence[OccurrenceMapping]`, `get(series_mapping_id, original_start) -> OccurrenceMapping | None`,
  `save(mapping)`, `delete(mapping)`; `UnitOfWork.occurrences`; `MemoryState.occurrences:
  dict[tuple[EventMappingId, OccurrenceStart], OccurrenceMapping]`.

- [ ] **Step 1: Write failing SQLite tests**

Append to `tests/adapters/test_sqlite.py` (add imports `OccurrenceMapping, OccurrenceMappingId,
OccurrenceState` and `from tests.helpers import week_start`; keep existing helpers):

```python
def _series_mapping() -> EventMapping:
    return EventMapping(
        EventMappingId("series-mapping"),
        rule().id,
        EventRef(rule().source, EventId("source-series")),
        EventRef(rule().destination, EventId("projection-1")),
        "r-1",
        ProjectionFingerprint("f"),
    )


def _occurrence(
    start: datetime | date, state: OccurrenceState = OccurrenceState.MODIFIED
) -> OccurrenceMapping:
    return OccurrenceMapping(
        OccurrenceMappingId(f"o-{start}"),
        EventMappingId("series-mapping"),
        start,
        EventRef(rule().source, EventId(f"source-series_{start}")),
        EventRef(rule().destination, EventId(f"projection-1_{start}")),
        state,
        "r-1",
        ProjectionFingerprint("f") if state is OccurrenceState.MODIFIED else None,
    )


def test_occurrence_mappings_round_trip_timed_and_all_day_starts(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    factory = SqliteUnitOfWorkFactory(database)
    timed = _occurrence(week_start(1))
    all_day = _occurrence(date(2026, 9, 15), OccurrenceState.CANCELLED)
    with factory() as uow:
        uow.rules.add(rule())
        uow.mappings.save(_series_mapping())
        uow.occurrences.save(timed)
        uow.occurrences.save(all_day)
        uow.occurrences.save(
            replace(timed, state=OccurrenceState.CANCELLED, projection_fingerprint=None)
        )
        uow.commit()

    with factory() as uow:
        stored = uow.occurrences.get(EventMappingId("series-mapping"), week_start(1))
        assert stored == replace(
            timed, state=OccurrenceState.CANCELLED, projection_fingerprint=None
        )
        assert uow.occurrences.get(EventMappingId("series-mapping"), date(2026, 9, 15)) == all_day
        assert len(uow.occurrences.for_series(EventMappingId("series-mapping"))) == 2


def test_occurrence_mappings_cascade_with_their_series_mapping_and_rule(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    factory = SqliteUnitOfWorkFactory(database)
    with factory() as uow:
        uow.rules.add(rule())
        uow.mappings.save(_series_mapping())
        uow.occurrences.save(_occurrence(week_start(1)))
        uow.commit()
    with factory() as uow:
        uow.mappings.delete(_series_mapping())
        uow.commit()
    with factory() as uow:
        assert uow.occurrences.for_series(EventMappingId("series-mapping")) == ()
        uow.mappings.save(_series_mapping())
        uow.occurrences.save(_occurrence(week_start(1)))
        uow.commit()
    with factory() as uow:
        uow.rules.remove(rule().id)
        uow.commit()
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM occurrence_mappings").fetchone()[0] == 0


def test_migration_5_upgrades_a_version_4_installation_and_resets_cursors(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    factory = SqliteUnitOfWorkFactory(database)
    with factory() as uow:
        uow.rules.add(rule())
        uow.mappings.save(_series_mapping())
        uow.cursors.save(rule().id, "source-cursor")
        uow.destination_cursors.save(rule().id, "destination-cursor")
        uow.commit()
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TABLE occurrence_mappings")
        connection.execute("DELETE FROM schema_migrations WHERE version = 5")

    initialize_database(database)
    initialize_database(database)

    with factory() as uow:
        assert uow.cursors.get(rule().id) is None
        assert uow.destination_cursors.get(rule().id) is None
        assert uow.mappings.count_for_rule(rule().id) == 1
        assert uow.occurrences.for_series(EventMappingId("series-mapping")) == ()
    with sqlite3.connect(database) as connection:
        versions = [row[0] for row in connection.execute("SELECT version FROM schema_migrations")]
    assert versions.count(5) == 1
```

Update the existing expectation `assert versions == [1, 2, 3, 4]` to `[1, 2, 3, 4, 5]`.

Create `tests/adapters/test_memory_persistence.py`:

```python
from __future__ import annotations

from calendar_sync.domain.model import (
    EventId,
    EventMapping,
    EventMappingId,
    EventRef,
    OccurrenceMapping,
    OccurrenceMappingId,
    OccurrenceState,
    ProjectionFingerprint,
)
from calendar_sync.infrastructure.persistence.memory import InMemoryUnitOfWorkFactory
from tests.helpers import rule, week_start

SERIES = EventMapping(
    EventMappingId("series-mapping"),
    rule().id,
    EventRef(rule().source, EventId("source-series")),
    EventRef(rule().destination, EventId("projection-1")),
    "r-1",
    ProjectionFingerprint("f"),
)
OCCURRENCE = OccurrenceMapping(
    OccurrenceMappingId("o-1"),
    SERIES.id,
    week_start(1),
    EventRef(rule().source, EventId("source-series_1")),
    EventRef(rule().destination, EventId("projection-1_1")),
    OccurrenceState.CANCELLED,
    "r-1",
)


def _factory() -> InMemoryUnitOfWorkFactory:
    factory = InMemoryUnitOfWorkFactory()
    with factory() as uow:
        uow.rules.add(rule())
        uow.mappings.save(SERIES)
        uow.occurrences.save(OCCURRENCE)
        uow.commit()
    return factory


def test_memory_occurrences_cascade_with_their_series_mapping() -> None:
    factory = _factory()
    with factory() as uow:
        uow.mappings.delete(SERIES)
        uow.commit()

    assert factory.state.occurrences == {}


def test_memory_occurrences_cascade_with_rule_removal() -> None:
    factory = _factory()
    with factory() as uow:
        uow.rules.remove(rule().id)
        uow.commit()

    assert factory.state.occurrences == {}


def test_memory_occurrences_require_an_existing_series_mapping() -> None:
    factory = InMemoryUnitOfWorkFactory()
    with factory() as uow:
        try:
            uow.occurrences.save(OCCURRENCE)
        except KeyError:
            return
    raise AssertionError("an occurrence mapping without its series mapping was accepted")
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/adapters/test_sqlite.py tests/adapters/test_memory_persistence.py -q -p no:warnings`
Expected: FAIL (`occurrences` attribute missing).

- [ ] **Step 3: Implement ports**

In `application/ports.py` add (import `EventMappingId`, `OccurrenceMapping`, `OccurrenceStart`):

```python
class OccurrenceMappingRepository(Protocol):
    def for_series(self, series_mapping_id: EventMappingId) -> Sequence[OccurrenceMapping]: ...

    def get(
        self, series_mapping_id: EventMappingId, original_start: OccurrenceStart
    ) -> OccurrenceMapping | None: ...

    def save(self, mapping: OccurrenceMapping) -> None: ...

    def delete(self, mapping: OccurrenceMapping) -> None: ...
```

and `occurrences: OccurrenceMappingRepository` on `UnitOfWork`.

- [ ] **Step 4: Implement memory persistence**

In `memory.py`: add `occurrences: dict[tuple[EventMappingId, OccurrenceStart], OccurrenceMapping] =
field(default_factory=dict)` to `MemoryState`; in `InMemorySyncRuleRepository.remove` compute
`removed = {m.id for key, m in self._state.mappings.items() if key[0] == rule_id}` before dropping
mappings, then `self._state.occurrences = {k: o for k, o in self._state.occurrences.items() if k[0] not in removed}`;
in `InMemoryEventMappingRepository.delete` also drop occurrences whose key `[0] == mapping.id`;
copy `occurrences` in `InMemoryUnitOfWork.commit` and bind
`self.occurrences = InMemoryOccurrenceMappingRepository(self._working)` in `__enter__`. Add:

```python
class InMemoryOccurrenceMappingRepository:
    def __init__(self, state: MemoryState) -> None:
        self._state = state

    def for_series(self, series_mapping_id: EventMappingId) -> tuple[OccurrenceMapping, ...]:
        return tuple(
            mapping
            for key, mapping in self._state.occurrences.items()
            if key[0] == series_mapping_id
        )

    def get(
        self, series_mapping_id: EventMappingId, original_start: OccurrenceStart
    ) -> OccurrenceMapping | None:
        return self._state.occurrences.get((series_mapping_id, original_start))

    def save(self, mapping: OccurrenceMapping) -> None:
        # Mirror the SQLite foreign key to event_mappings.
        if not any(m.id == mapping.series_mapping_id for m in self._state.mappings.values()):
            raise KeyError(mapping.series_mapping_id)
        self._state.occurrences[(mapping.series_mapping_id, mapping.original_start)] = mapping

    def delete(self, mapping: OccurrenceMapping) -> None:
        self._state.occurrences.pop((mapping.series_mapping_id, mapping.original_start), None)
```

- [ ] **Step 5: Implement SQLite persistence**

Create `0005_occurrence_mappings.sql`:

```sql
CREATE TABLE occurrence_mappings (
    id TEXT PRIMARY KEY,
    series_mapping_id TEXT NOT NULL REFERENCES event_mappings(id) ON DELETE CASCADE,
    original_start TEXT NOT NULL,
    source_account_id TEXT NOT NULL,
    source_calendar_id TEXT NOT NULL,
    source_event_id TEXT NOT NULL,
    destination_account_id TEXT NOT NULL,
    destination_calendar_id TEXT NOT NULL,
    destination_event_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('modified', 'cancelled')),
    source_revision TEXT NOT NULL,
    projection_fingerprint TEXT,
    CHECK ((state = 'modified') = (projection_fingerprint IS NOT NULL)),
    UNIQUE (series_mapping_id, original_start)
);

-- Recurring events were skipped before this release; re-read every source window to backfill them.
DELETE FROM sync_cursors;
DELETE FROM destination_sync_cursors;
```

In `sqlite.py`: append `(5, "0005_occurrence_mappings.sql")` to `_FORWARD_MIGRATIONS`, bind
`self.occurrences = SqliteOccurrenceMappingRepository(connection)` in `SqliteUnitOfWork.__enter__`
(annotate the class attribute), and add:

```python
class SqliteOccurrenceMappingRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def for_series(self, series_mapping_id: EventMappingId) -> Sequence[OccurrenceMapping]:
        rows = self._connection.execute(
            "SELECT * FROM occurrence_mappings WHERE series_mapping_id = ? ORDER BY original_start",
            (series_mapping_id.value,),
        ).fetchall()
        return tuple(_occurrence_from_row(row) for row in rows)

    def get(
        self, series_mapping_id: EventMappingId, original_start: OccurrenceStart
    ) -> OccurrenceMapping | None:
        row = self._connection.execute(
            "SELECT * FROM occurrence_mappings WHERE series_mapping_id = ? AND original_start = ?",
            (series_mapping_id.value, _serialize_start(original_start)),
        ).fetchone()
        return _occurrence_from_row(row) if row else None

    def save(self, mapping: OccurrenceMapping) -> None:
        self._connection.execute(
            """
            INSERT INTO occurrence_mappings (
                id, series_mapping_id, original_start,
                source_account_id, source_calendar_id, source_event_id,
                destination_account_id, destination_calendar_id, destination_event_id,
                state, source_revision, projection_fingerprint
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(series_mapping_id, original_start) DO UPDATE SET
                source_account_id = excluded.source_account_id,
                source_calendar_id = excluded.source_calendar_id,
                source_event_id = excluded.source_event_id,
                destination_account_id = excluded.destination_account_id,
                destination_calendar_id = excluded.destination_calendar_id,
                destination_event_id = excluded.destination_event_id,
                state = excluded.state,
                source_revision = excluded.source_revision,
                projection_fingerprint = excluded.projection_fingerprint
            """,
            (
                mapping.id.value,
                mapping.series_mapping_id.value,
                _serialize_start(mapping.original_start),
                mapping.source.calendar.connected_account_id.value,
                mapping.source.calendar.calendar_id.value,
                mapping.source.event_id.value,
                mapping.destination.calendar.connected_account_id.value,
                mapping.destination.calendar.calendar_id.value,
                mapping.destination.event_id.value,
                mapping.state.value,
                mapping.source_revision,
                mapping.projection_fingerprint.value if mapping.projection_fingerprint else None,
            ),
        )

    def delete(self, mapping: OccurrenceMapping) -> None:
        self._connection.execute(
            "DELETE FROM occurrence_mappings WHERE series_mapping_id = ? AND original_start = ?",
            (mapping.series_mapping_id.value, _serialize_start(mapping.original_start)),
        )


def _serialize_start(value: OccurrenceStart) -> str:
    return value.isoformat()


def _parse_start(value: str) -> OccurrenceStart:
    return date.fromisoformat(value) if len(value) == 10 else datetime.fromisoformat(value)


def _ref(row: sqlite3.Row, prefix: str) -> EventRef:
    return EventRef(
        CalendarEndpoint(
            ConnectedAccountId(str(row[f"{prefix}_account_id"])),
            CalendarId(str(row[f"{prefix}_calendar_id"])),
        ),
        EventId(str(row[f"{prefix}_event_id"])),
    )


def _occurrence_from_row(row: sqlite3.Row) -> OccurrenceMapping:
    fingerprint = row["projection_fingerprint"]
    return OccurrenceMapping(
        id=OccurrenceMappingId(str(row["id"])),
        series_mapping_id=EventMappingId(str(row["series_mapping_id"])),
        original_start=_parse_start(str(row["original_start"])),
        source=_ref(row, "source"),
        destination=_ref(row, "destination"),
        state=OccurrenceState(str(row["state"])),
        source_revision=str(row["source_revision"]),
        projection_fingerprint=ProjectionFingerprint(str(fingerprint)) if fingerprint else None,
    )
```

Add `date` to the datetime import and the new domain types to the model import. Confirm
`SqliteUnitOfWork.__enter__` still executes `PRAGMA foreign_keys = ON`.

- [ ] **Step 6: Run tests**

Run: `.venv/bin/pytest tests -q -p no:warnings && .venv/bin/mypy`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/calendar_sync/application/ports.py src/calendar_sync/infrastructure/persistence tests/adapters
git commit -m "feat: persist occurrence mappings and reset cursors for recurring backfill"
```

---

### Task 5: Google translation and occurrence operations

**Files:**
- Modify: `src/calendar_sync/application/ports.py` (`CalendarProvider`)
- Modify: `src/calendar_sync/infrastructure/google/translation.py`
- Modify: `src/calendar_sync/infrastructure/google/provider.py`
- Modify: `tests/application/test_execute_sync_rule.py` (`FakeCalendarProvider` gains the new methods)
- Create: `tests/fixtures/google_recurring_master.json`, `google_modified_occurrence.json`,
  `google_cancelled_occurrence.json`
- Test: `tests/adapters/test_google_translation.py`, `tests/adapters/test_google_provider.py`

**Interfaces:**
- Produces on `CalendarProvider`:
  `get_occurrence(series: EventRef, original_start: OccurrenceStart) -> CalendarEvent | None`;
  `write_occurrence(destination_series: EventRef, original_start: OccurrenceStart, source_series:
  EventRef, rule_id: SyncRuleId, projection: EventProjection, operation_key: str) -> CalendarEvent`;
  `cancel_occurrence(destination_series: EventRef, original_start: OccurrenceStart, source_series:
  EventRef, rule_id: SyncRuleId, operation_key: str) -> None`.
  Translation: `ORIGINAL_START_PROPERTY = "gcs_source_original_start"`,
  `format_occurrence_start(value) -> str`, `projection_payload(..., *, original_start=None)`.

- [ ] **Step 1: Add synthetic fixtures**

`tests/fixtures/google_recurring_master.json`:

```json
{
  "id": "synthetic-series-001",
  "etag": "synthetic-series-revision-001",
  "status": "confirmed",
  "summary": "Synthetic weekly sync",
  "start": { "dateTime": "2026-09-01T10:00:00+02:00", "timeZone": "Europe/Madrid" },
  "end": { "dateTime": "2026-09-01T11:00:00+02:00", "timeZone": "Europe/Madrid" },
  "recurrence": ["RRULE:FREQ=WEEKLY;COUNT=10", "EXDATE;TZID=Europe/Madrid:20260915T100000"]
}
```

`tests/fixtures/google_modified_occurrence.json`:

```json
{
  "id": "synthetic-series-001_20260908T080000Z",
  "etag": "synthetic-occurrence-revision-001",
  "status": "confirmed",
  "summary": "Synthetic weekly sync (moved)",
  "recurringEventId": "synthetic-series-001",
  "originalStartTime": { "dateTime": "2026-09-08T10:00:00+02:00", "timeZone": "Europe/Madrid" },
  "start": { "dateTime": "2026-09-08T12:00:00+02:00", "timeZone": "Europe/Madrid" },
  "end": { "dateTime": "2026-09-08T13:00:00+02:00", "timeZone": "Europe/Madrid" }
}
```

`tests/fixtures/google_cancelled_occurrence.json`:

```json
{
  "id": "synthetic-series-001_20260922T080000Z",
  "status": "cancelled",
  "recurringEventId": "synthetic-series-001",
  "originalStartTime": { "dateTime": "2026-09-22T08:00:00Z" }
}
```

- [ ] **Step 2: Write failing translation tests**

Append to `tests/adapters/test_google_translation.py` (import `json`, `Path`, `EventStatus`,
`OccurrenceIdentity`, `EventId`, `ORIGINAL_START_PROPERTY`):

```python
FIXTURES = Path(__file__).parent.parent / "fixtures"


def _fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text())


def test_series_master_keeps_its_time_zone_and_recurrence_lines() -> None:
    translated = to_domain_event(_fixture("google_recurring_master.json"), endpoint("a", "c"))

    assert isinstance(translated.time, TimedInterval)
    assert translated.time.time_zone == "Europe/Madrid"
    assert translated.recurrence is not None
    assert translated.recurrence.lines[1].startswith("EXDATE")


def test_modified_occurrence_normalizes_its_original_start_to_utc() -> None:
    translated = to_domain_event(_fixture("google_modified_occurrence.json"), endpoint("a", "c"))

    assert translated.occurrence == OccurrenceIdentity(
        EventId("synthetic-series-001"), datetime(2026, 9, 8, 8, 0, tzinfo=UTC)
    )


def test_minimal_cancelled_occurrence_translates() -> None:
    translated = to_domain_event(_fixture("google_cancelled_occurrence.json"), endpoint("a", "c"))

    assert translated.status is EventStatus.CANCELLED
    assert translated.time is None
    assert translated.occurrence == OccurrenceIdentity(
        EventId("synthetic-series-001"), datetime(2026, 9, 22, 8, 0, tzinfo=UTC)
    )


def test_all_day_occurrence_keeps_its_original_date() -> None:
    payload = {
        "id": "series_20260908",
        "status": "cancelled",
        "recurringEventId": "series",
        "originalStartTime": {"date": "2026-09-08"},
    }

    translated = to_domain_event(payload, endpoint("a", "c"))

    assert translated.occurrence == OccurrenceIdentity(EventId("series"), date(2026, 9, 8))


def test_series_payload_writes_time_zone_and_single_payload_does_not() -> None:
    zoned = TimedInterval(
        datetime(2026, 9, 1, 8, 0, tzinfo=UTC),
        datetime(2026, 9, 1, 9, 0, tzinfo=UTC),
        "Europe/Madrid",
    )
    series_body = projection_payload(
        EventProjection(zoned, "Busy", recurrence=Recurrence(("RRULE:FREQ=WEEKLY",))),
        SyncRuleId("rule-1"),
        event().reference,
        "key",
    )
    single_body = projection_payload(
        EventProjection(zoned, "Busy"), SyncRuleId("rule-1"), event().reference, "key"
    )

    assert series_body["start"]["timeZone"] == "Europe/Madrid"
    assert series_body["end"]["timeZone"] == "Europe/Madrid"
    assert "timeZone" not in single_body["start"]


def test_occurrence_payload_records_the_original_start() -> None:
    body = projection_payload(
        EventProjection(
            TimedInterval(
                datetime(2026, 9, 8, 8, 0, tzinfo=UTC), datetime(2026, 9, 8, 9, 0, tzinfo=UTC)
            ),
            "Busy",
        ),
        SyncRuleId("rule-1"),
        event().reference,
        "key",
        original_start=datetime(2026, 9, 8, 8, 0, tzinfo=UTC),
    )

    assert private_properties(body)[ORIGINAL_START_PROPERTY] == "2026-09-08T08:00:00Z"
    assert "attendees" not in body
```

- [ ] **Step 3: Write failing provider tests**

Append to `tests/adapters/test_google_provider.py` (import `EventId, EventRef, EventStatus,
ManagedOrigin`, `RULE_PROPERTY, SOURCE_ACCOUNT_PROPERTY, SOURCE_CALENDAR_PROPERTY,
SOURCE_EVENT_PROPERTY` from translation):

```python
DESTINATION = endpoint("work-account", "work-calendar")
SERIES = EventRef(DESTINATION, EventId("projection-1"))
SOURCE_SERIES = EventRef(
    endpoint("personal-account", "personal-calendar"), EventId("source-series")
)
START = datetime(2026, 9, 8, 8, 0, tzinfo=UTC)


def _owned(payload: dict[str, object]) -> dict[str, object]:
    return {
        **payload,
        "extendedProperties": {
            "private": {
                RULE_PROPERTY: "rule-1",
                SOURCE_ACCOUNT_PROPERTY: "personal-account",
                SOURCE_CALENDAR_PROPERTY: "personal-calendar",
                SOURCE_EVENT_PROPERTY: "source-series",
            }
        },
    }


def _instance(status: str = "confirmed") -> dict[str, object]:
    payload: dict[str, object] = {
        "id": "projection-1_20260908T080000Z",
        "etag": "instance-etag",
        "status": status,
        "recurringEventId": "projection-1",
        "originalStartTime": {"dateTime": "2026-09-08T08:00:00Z"},
    }
    if status == "confirmed":
        payload |= {
            "summary": "Busy",
            "start": {"dateTime": "2026-09-08T08:00:00Z"},
            "end": {"dateTime": "2026-09-08T09:00:00Z"},
        }
    return payload


def _master() -> dict[str, object]:
    return _owned({**google_event_payload("projection-1"), "recurrence": ["RRULE:FREQ=WEEKLY"]})


def test_get_occurrence_resolves_through_instances_and_verifies_the_start() -> None:
    events_api = MagicMock()
    events_api.instances.return_value = request_returning({"items": [_instance()]})
    provider = provider_with_events_api(events_api)

    resolved = provider.get_occurrence(SERIES, START)

    assert resolved is not None
    assert resolved.occurrence is not None and resolved.occurrence.original_start == START
    events_api.instances.assert_called_once_with(
        calendarId="work-calendar",
        eventId="projection-1",
        originalStart="2026-09-08T08:00:00Z",
        showDeleted=True,
        maxResults=1,
    )


def test_get_occurrence_returns_none_for_a_different_start_or_missing_series() -> None:
    events_api = MagicMock()
    events_api.instances.side_effect = [
        request_returning({"items": [_instance()]}),
        request_raising(404),
    ]
    provider = provider_with_events_api(events_api)

    assert provider.get_occurrence(SERIES, datetime(2026, 9, 15, 8, 0, tzinfo=UTC)) is None
    assert provider.get_occurrence(SERIES, START) is None


def test_write_occurrence_restores_a_cancelled_instance_without_notifications() -> None:
    events_api = MagicMock()
    events_api.instances.return_value = request_returning({"items": [_instance("cancelled")]})
    events_api.get.return_value = request_returning(_master())
    events_api.patch.return_value = request_returning(_owned(_instance()))
    provider = provider_with_events_api(events_api)
    projection = EventProjection(
        TimedInterval(START, datetime(2026, 9, 8, 9, 0, tzinfo=UTC)), "Busy"
    )

    written = provider.write_occurrence(
        SERIES, START, SOURCE_SERIES, SyncRuleId("rule-1"), projection, "key"
    )

    kwargs = events_api.patch.call_args.kwargs
    assert kwargs["eventId"] == "projection-1_20260908T080000Z"
    assert kwargs["sendUpdates"] == "none"
    assert kwargs["body"]["status"] == "confirmed"
    assert written.status is EventStatus.CONFIRMED


def test_write_occurrence_refuses_a_series_owned_by_another_rule() -> None:
    events_api = MagicMock()
    events_api.instances.return_value = request_returning({"items": [_instance()]})
    foreign = _master()
    foreign["extendedProperties"]["private"][RULE_PROPERTY] = "other-rule"  # type: ignore[index]
    events_api.get.return_value = request_returning(foreign)
    provider = provider_with_events_api(events_api)

    with pytest.raises(ProviderFailure) as failure:
        provider.write_occurrence(
            SERIES,
            START,
            SOURCE_SERIES,
            SyncRuleId("rule-1"),
            EventProjection(TimedInterval(START, datetime(2026, 9, 8, 9, 0, tzinfo=UTC)), "Busy"),
            "key",
        )

    assert failure.value.kind is ProviderFailureKind.PERMANENT
    events_api.patch.assert_not_called()


def test_cancel_occurrence_deletes_only_the_instance_and_skips_cancelled_ones() -> None:
    events_api = MagicMock()
    events_api.instances.side_effect = [
        request_returning({"items": [_instance()]}),
        request_returning({"items": [_instance("cancelled")]}),
    ]
    events_api.get.return_value = request_returning(_master())
    events_api.delete.return_value = request_returning({})
    provider = provider_with_events_api(events_api)

    provider.cancel_occurrence(SERIES, START, SOURCE_SERIES, SyncRuleId("rule-1"), "key")
    provider.cancel_occurrence(SERIES, START, SOURCE_SERIES, SyncRuleId("rule-1"), "key")

    events_api.delete.assert_called_once_with(
        calendarId="work-calendar", eventId="projection-1_20260908T080000Z", sendUpdates="none"
    )
```

- [ ] **Step 4: Run to verify failure**

Run: `.venv/bin/pytest tests/adapters/test_google_translation.py tests/adapters/test_google_provider.py -q -p no:warnings`
Expected: FAIL.

- [ ] **Step 5: Implement translation**

In `translation.py`:
- Add `ORIGINAL_START_PROPERTY = "gcs_source_original_start"`.
- In `_parse_time`, build timed values as
  `TimedInterval(_parse_datetime(start_time), _parse_datetime(end_time), _time_zone(start))`.
- Add:

```python
def _time_zone(value: Mapping[str, Any]) -> str | None:
    zone = value.get("timeZone")
    return zone if isinstance(zone, str) and zone.strip() else None


def format_occurrence_start(value: OccurrenceStart) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return value.isoformat()
```

- `projection_payload` gains `*, original_start: OccurrenceStart | None = None`; when set add
  `private[ORIGINAL_START_PROPERTY] = format_occurrence_start(original_start)`.
- `_time_payload` for timed projections:

```python
    start = {"dateTime": projection.time.starts_at.isoformat()}
    end = {"dateTime": projection.time.ends_at.isoformat()}
    if projection.recurrence is not None and projection.time.time_zone is not None:
        start["timeZone"] = projection.time.time_zone
        end["timeZone"] = projection.time.time_zone
    return start, end
```

Import `UTC` from datetime.

- [ ] **Step 6: Implement provider operations**

In `ports.py` add the three protocol methods listed under Interfaces. In `provider.py` add:

```python
def get_occurrence(self, series: EventRef, original_start: OccurrenceStart) -> CalendarEvent | None:
    try:
        response = (
            self._service_for(series.calendar.connected_account_id)
            .events()
            .instances(
                calendarId=series.calendar.calendar_id.value,
                eventId=series.event_id.value,
                originalStart=format_occurrence_start(original_start),
                showDeleted=True,
                maxResults=1,
            )
            .execute()
        )
    except Exception as error:
        if _status_code(error) in {404, 410}:
            return None
        raise _provider_failure(error) from error
    for item in response.get("items", []):
        candidate = to_domain_event(item, series.calendar)
        # Never trust a positional result: the instance must name the requested start.
        if (
            candidate.occurrence is not None
            and candidate.occurrence.series_event_id == series.event_id
            and candidate.occurrence.original_start == original_start
        ):
            return candidate
    return None


def write_occurrence(
    self,
    destination_series: EventRef,
    original_start: OccurrenceStart,
    source_series: EventRef,
    rule_id: SyncRuleId,
    projection: EventProjection,
    operation_key: str,
) -> CalendarEvent:
    instance = self._owned_occurrence(destination_series, original_start, source_series, rule_id)
    if instance is None:
        raise ProviderFailure(
            ProviderFailureKind.PERMANENT, "Google occurrence could not be resolved"
        )
    body = projection_payload(
        projection, rule_id, source_series, operation_key, original_start=original_start
    )
    body["status"] = "confirmed"
    try:
        payload = (
            self._service_for(destination_series.calendar.connected_account_id)
            .events()
            .patch(
                calendarId=destination_series.calendar.calendar_id.value,
                eventId=instance.reference.event_id.value,
                body=body,
                sendUpdates="none",
            )
            .execute()
        )
        return to_domain_event(payload, destination_series.calendar)
    except Exception as error:
        raise _provider_failure(error) from error


def cancel_occurrence(
    self,
    destination_series: EventRef,
    original_start: OccurrenceStart,
    source_series: EventRef,
    rule_id: SyncRuleId,
    operation_key: str,
) -> None:
    instance = self._owned_occurrence(destination_series, original_start, source_series, rule_id)
    if instance is None or instance.status is EventStatus.CANCELLED:
        return
    try:
        (
            self._service_for(destination_series.calendar.connected_account_id)
            .events()
            .delete(
                calendarId=destination_series.calendar.calendar_id.value,
                eventId=instance.reference.event_id.value,
                sendUpdates="none",
            )
            .execute()
        )
    except Exception as error:
        if _status_code(error) not in {404, 410}:
            raise _provider_failure(error) from error


def _owned_occurrence(
    self,
    destination_series: EventRef,
    original_start: OccurrenceStart,
    source_series: EventRef,
    rule_id: SyncRuleId,
) -> CalendarEvent | None:
    instance = self.get_occurrence(destination_series, original_start)
    if instance is None:
        return None
    master = self.get_event(destination_series)
    if not (
        master is not None
        and _owned(master.managed_origin, rule_id, source_series)
        and (
            instance.managed_origin is None
            or _owned(instance.managed_origin, rule_id, source_series)
        )
    ):
        raise ProviderFailure(
            ProviderFailureKind.PERMANENT,
            "Google occurrence does not carry compatible ownership metadata",
        )
    return instance
```

Module helper:

```python
def _owned(origin: ManagedOrigin | None, rule_id: SyncRuleId, source: EventRef) -> bool:
    return origin is not None and origin.rule_id == rule_id and origin.source == source
```

`write_occurrence` for a missing instance raises instead of returning because the domain only
decides `UPDATE` after resolving the instance.

- [ ] **Step 7: Update the existing test fake**

Add to `FakeCalendarProvider` in `tests/application/test_execute_sync_rule.py`:

```python
def get_occurrence(self, series: EventRef, original_start: OccurrenceStart) -> CalendarEvent | None:
    return None


def write_occurrence(
    self,
    destination_series: EventRef,
    original_start: OccurrenceStart,
    source_series: EventRef,
    rule_id: SyncRuleId,
    projection: EventProjection,
    operation_key: str,
) -> CalendarEvent:
    raise AssertionError("single-event tests never write occurrences")


def cancel_occurrence(
    self,
    destination_series: EventRef,
    original_start: OccurrenceStart,
    source_series: EventRef,
    rule_id: SyncRuleId,
    operation_key: str,
) -> None:
    raise AssertionError("single-event tests never cancel occurrences")
```

(format with ruff).

- [ ] **Step 8: Run tests**

Run: `.venv/bin/pytest tests -q -p no:warnings && .venv/bin/mypy`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/calendar_sync/application/ports.py src/calendar_sync/infrastructure/google tests
git commit -m "feat: resolve, write, and cancel Google occurrences with ownership checks"
```

---

### Task 6: Series-aware provider fake for application tests

**Files:**
- Create: `tests/fake_calendar.py`
- Test: `tests/application/test_fake_calendar.py`

**Interfaces:**
- Produces: `FakeCalendars` implementing `CalendarProvider`, with test setup helpers
  `put(event, *, starts=())`, `report(*events)`, and inspection `writes: list[tuple[str, str]]`,
  `unreadable: set[EventRef]`; `FixedClock`; `sync_use_case(factory, calendars) -> ExecuteSyncRule`;
  `enabled_rule_factory(rule_=None) -> InMemoryUnitOfWorkFactory`.

- [ ] **Step 1: Write the fake**

Create `tests/fake_calendar.py`:

```python
"""A provider fake that models series masters, their expansions, exceptions, and change feeds."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime

from calendar_sync.application.errors import ProviderFailure, ProviderFailureKind
from calendar_sync.application.ports import CreatedProjection, ProviderChangeSet, UnitOfWorkFactory
from calendar_sync.application.synchronization import ExecuteSyncRule
from calendar_sync.domain.model import (
    AllDayRange,
    CalendarEndpoint,
    CalendarEvent,
    EventId,
    EventProjection,
    EventRef,
    EventStatus,
    ManagedOrigin,
    OccurrenceIdentity,
    OccurrenceStart,
    SyncRule,
    SyncRuleId,
    TimedInterval,
)
from calendar_sync.domain.services import (
    EventProjector,
    ProjectionFingerprinter,
    SyncDecisionService,
)
from calendar_sync.infrastructure.persistence.memory import InMemoryUnitOfWorkFactory
from tests.helpers import NOW, instance_id, rule


@dataclass
class FixedClock:
    def now(self) -> datetime:
        return NOW


def _owned(origin: ManagedOrigin | None, rule_id: SyncRuleId, source: EventRef) -> bool:
    return origin is not None and origin.rule_id == rule_id and origin.source == source


def _denied() -> ProviderFailure:
    return ProviderFailure(ProviderFailureKind.PERMANENT, "incompatible ownership metadata")


@dataclass
class FakeCalendars:
    events: dict[EventRef, CalendarEvent] = field(default_factory=dict)
    expansions: dict[EventRef, tuple[OccurrenceStart, ...]] = field(default_factory=dict)
    feeds: dict[CalendarEndpoint, list[CalendarEvent]] = field(default_factory=dict)
    writes: list[tuple[str, str]] = field(default_factory=list)
    unreadable: set[EventRef] = field(default_factory=set)
    created: int = 0

    def put(
        self, event: CalendarEvent, *, starts: tuple[OccurrenceStart, ...] = ()
    ) -> CalendarEvent:
        self.events[event.reference] = event
        if event.recurrence is not None:
            self.expansions[event.reference] = starts
        return event

    def report(self, *events: CalendarEvent) -> None:
        for event in events:
            self.feeds.setdefault(event.reference.calendar, []).append(event)

    def instances_of(self, series: EventRef) -> list[CalendarEvent]:
        return [
            event
            for event in self.events.values()
            if event.occurrence is not None
            and event.reference.calendar == series.calendar
            and event.occurrence.series_event_id == series.event_id
        ]

    def changes(
        self, source: CalendarEndpoint, cursor: str | None, not_ended_before: datetime
    ) -> ProviderChangeSet:
        if cursor is None:
            self.feeds.pop(source, None)
            items = tuple(
                event
                for event in self.events.values()
                if event.reference.calendar == source and self._in_window(event, not_ended_before)
            )
        else:
            items = tuple(self.feeds.pop(source, []))
        return ProviderChangeSet(items, f"cursor-{source.calendar_id.value}")

    @staticmethod
    def _in_window(event: CalendarEvent, not_ended_before: datetime) -> bool:
        # Series masters span their expansion; exceptions and singles are filtered by end.
        if event.recurrence is not None or not isinstance(event.time, TimedInterval):
            return True
        return event.time.ends_at >= not_ended_before

    def get_event(self, reference: EventRef) -> CalendarEvent | None:
        if reference in self.unreadable:
            return None
        return self.events.get(reference)

    def get_occurrence(
        self, series: EventRef, original_start: OccurrenceStart
    ) -> CalendarEvent | None:
        master = self.events.get(series)
        if master is None or master.status is EventStatus.CANCELLED:
            return None
        if original_start not in self.expansions.get(series, ()):
            return None
        reference = EventRef(
            series.calendar, EventId(instance_id(series.event_id.value, original_start))
        )
        stored = self.events.get(reference)
        return stored if stored is not None else self._expand(master, original_start, reference)

    @staticmethod
    def _expand(
        master: CalendarEvent, start: OccurrenceStart, reference: EventRef
    ) -> CalendarEvent:
        if isinstance(master.time, TimedInterval):
            assert isinstance(start, datetime)
            time: TimedInterval | AllDayRange = TimedInterval(
                start, start + (master.time.ends_at - master.time.starts_at)
            )
        else:
            assert isinstance(master.time, AllDayRange) and not isinstance(start, datetime)
            time = AllDayRange(start, start + (master.time.ends_before - master.time.starts_on))
        return CalendarEvent(
            reference=reference,
            time=time,
            revision=master.revision,
            title=master.title,
            description=master.description,
            location=master.location,
            occurrence=OccurrenceIdentity(master.reference.event_id, start),
            managed_origin=master.managed_origin,
        )

    def create_projection(
        self,
        destination: CalendarEndpoint,
        source: EventRef,
        rule_id: SyncRuleId,
        projection: EventProjection,
        operation_key: str,
    ) -> CreatedProjection:
        self.created += 1
        reference = EventRef(destination, EventId(f"projection-{self.created}"))
        created = CalendarEvent(
            reference=reference,
            time=projection.time,
            revision=f"projection-{self.created}-r1",
            title=projection.title,
            description=projection.description,
            location=projection.location,
            recurrence=projection.recurrence,
            managed_origin=ManagedOrigin(rule_id, source),
        )
        self.events[reference] = created
        if projection.recurrence is not None:
            self.expansions[reference] = self.expansions.get(source, ())
        self.writes.append(("create", reference.event_id.value))
        return CreatedProjection(created)

    def update_projection(
        self,
        destination: EventRef,
        source: EventRef,
        rule_id: SyncRuleId,
        projection: EventProjection,
        operation_key: str,
    ) -> CalendarEvent:
        existing = self.events.get(destination)
        if existing is None or not _owned(existing.managed_origin, rule_id, source):
            raise _denied()
        updated = replace(
            existing,
            time=projection.time,
            title=projection.title,
            description=projection.description,
            location=projection.location,
            recurrence=projection.recurrence,
            revision=f"{existing.revision}+",
            status=EventStatus.CONFIRMED,
        )
        self.events[destination] = updated
        if projection.recurrence is not None:
            starts = self.expansions.get(source, ())
            self.expansions[destination] = starts
            # Like Google, a series update drops exceptions that left the series.
            for instance in self.instances_of(destination):
                assert instance.occurrence is not None
                if instance.occurrence.original_start not in starts:
                    del self.events[instance.reference]
        self.writes.append(("update", destination.event_id.value))
        return updated

    def delete_projection(
        self, destination: EventRef, source: EventRef, rule_id: SyncRuleId, operation_key: str
    ) -> None:
        existing = self.events.get(destination)
        if existing is None or existing.status is EventStatus.CANCELLED:
            return
        if not _owned(existing.managed_origin, rule_id, source):
            raise _denied()
        for instance in self.instances_of(destination):
            del self.events[instance.reference]
        del self.events[destination]
        self.expansions.pop(destination, None)
        self.writes.append(("delete", destination.event_id.value))

    def write_occurrence(
        self,
        destination_series: EventRef,
        original_start: OccurrenceStart,
        source_series: EventRef,
        rule_id: SyncRuleId,
        projection: EventProjection,
        operation_key: str,
    ) -> CalendarEvent:
        instance = self._owned_occurrence(
            destination_series, original_start, source_series, rule_id
        )
        if instance is None:
            raise ProviderFailure(ProviderFailureKind.PERMANENT, "occurrence could not be resolved")
        written = replace(
            instance,
            time=projection.time,
            title=projection.title,
            description=projection.description,
            location=projection.location,
            status=EventStatus.CONFIRMED,
            revision=f"{instance.revision}+",
            managed_origin=ManagedOrigin(rule_id, source_series),
        )
        self.events[instance.reference] = written
        self.writes.append(("write_occurrence", instance.reference.event_id.value))
        return written

    def cancel_occurrence(
        self,
        destination_series: EventRef,
        original_start: OccurrenceStart,
        source_series: EventRef,
        rule_id: SyncRuleId,
        operation_key: str,
    ) -> None:
        instance = self._owned_occurrence(
            destination_series, original_start, source_series, rule_id
        )
        if instance is None or instance.status is EventStatus.CANCELLED:
            return
        # Google's cancelled exceptions carry no content and no private metadata.
        self.events[instance.reference] = replace(
            instance,
            status=EventStatus.CANCELLED,
            time=None,
            title="",
            description="",
            location="",
            managed_origin=None,
            revision=f"{instance.revision}+",
        )
        self.writes.append(("cancel_occurrence", instance.reference.event_id.value))

    def _owned_occurrence(
        self,
        destination_series: EventRef,
        original_start: OccurrenceStart,
        source_series: EventRef,
        rule_id: SyncRuleId,
    ) -> CalendarEvent | None:
        instance = self.get_occurrence(destination_series, original_start)
        if instance is None:
            return None
        master = self.events.get(destination_series)
        if master is None or not _owned(master.managed_origin, rule_id, source_series):
            raise _denied()
        if instance.managed_origin is not None and not _owned(
            instance.managed_origin, rule_id, source_series
        ):
            raise _denied()
        return instance

    def managed_events(
        self, destination: CalendarEndpoint, rule_id: SyncRuleId
    ) -> tuple[CalendarEvent, ...]:
        return tuple(
            event
            for event in self.events.values()
            if event.reference.calendar == destination
            and event.status is EventStatus.CONFIRMED
            and event.managed_origin is not None
            and event.managed_origin.rule_id == rule_id
        )


def enabled_rule_factory(rule_: SyncRule | None = None) -> InMemoryUnitOfWorkFactory:
    factory = InMemoryUnitOfWorkFactory()
    with factory() as uow:
        uow.rules.add(rule_ or rule())
        uow.commit()
    return factory


def sync_use_case(factory: UnitOfWorkFactory, calendars: FakeCalendars) -> ExecuteSyncRule:
    fingerprinter = ProjectionFingerprinter()
    return ExecuteSyncRule(
        factory,
        calendars,
        SyncDecisionService(EventProjector(), fingerprinter),
        fingerprinter,
        FixedClock(),
    )
```

- [ ] **Step 2: Test the fake's Google-like behavior**

Create `tests/application/test_fake_calendar.py`:

```python
from __future__ import annotations

from calendar_sync.domain.model import EventStatus, ManagedOrigin
from tests.fake_calendar import FakeCalendars
from tests.helpers import instance_id, occurrence, rule, series, week_start


def test_fake_expands_series_and_prefers_stored_exceptions() -> None:
    calendars = FakeCalendars()
    master = calendars.put(series(), starts=(week_start(0), week_start(1)))
    moved = calendars.put(occurrence(master, 1, title="Moved"))

    assert calendars.get_occurrence(master.reference, week_start(1)) == moved
    expanded = calendars.get_occurrence(master.reference, week_start(0))
    assert expanded is not None
    assert expanded.reference.event_id.value == instance_id("source-series", week_start(0))
    assert calendars.get_occurrence(master.reference, week_start(5)) is None


def test_fake_cancelled_instances_lose_their_metadata() -> None:
    calendars = FakeCalendars()
    origin = ManagedOrigin(rule().id, series().reference)
    master = calendars.put(
        series("projection-1", calendar=rule().destination, managed_origin=origin),
        starts=(week_start(1),),
    )

    calendars.cancel_occurrence(master.reference, week_start(1), series().reference, rule().id, "k")

    cancelled = calendars.get_occurrence(master.reference, week_start(1))
    assert cancelled is not None
    assert cancelled.status is EventStatus.CANCELLED
    assert cancelled.managed_origin is None
```

Run: `.venv/bin/pytest tests/application/test_fake_calendar.py -q -p no:warnings`
Expected: PASS (the fake only needs Tasks 1–5).

- [ ] **Step 3: Commit**

```bash
git add tests/fake_calendar.py tests/application/test_fake_calendar.py
git commit -m "test: add a series-aware calendar provider fake"
```

---

### Task 7: Synchronize series and occurrences in Sync Runs

**Files:**
- Create: `src/calendar_sync/application/sync_run.py`
- Create: `src/calendar_sync/application/occurrences.py`
- Modify: `src/calendar_sync/application/synchronization.py`
- Modify: `tests/application/test_execute_sync_rule.py` (rewrite the recurring audit test)
- Create: `tests/application/test_recurring_sync.py`

**Interfaces:**
- Consumes: Tasks 1–6.
- Produces: `SyncRunContext(uow, rule, run_id, counts, reproject=False, handled=set())`,
  `require_unchanged(run) -> None`, `OUTCOMES`; `SynchronizeOccurrences(provider, decisions,
  fingerprinter, clock, repair_series)` with `apply(run, series_mapping, source_series,
  original_start, source_occurrence, *, record_current, destination_reported=False) -> None` and
  `reverify(run, series_mapping, source_series) -> None`; `occurrence_operation_key(rule_id,
  source_series, original_start, revision, action) -> str`.

- [ ] **Step 1: Write failing application tests**

Create `tests/application/test_recurring_sync.py`:

```python
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from calendar_sync.application.errors import RuleNotExecutable
from calendar_sync.application.ports import ProviderChangeSet
from calendar_sync.domain.model import (
    CalendarEndpoint,
    EventRef,
    EventStatus,
    ManagedOrigin,
    OccurrenceState,
    OccurrenceStart,
    PrivacyPolicy,
    Recurrence,
    SyncReason,
    SyncRule,
    SyncRuleId,
    SyncRuleState,
    TimedInterval,
    TransformationPolicy,
)
from calendar_sync.infrastructure.persistence.memory import InMemoryUnitOfWorkFactory
from calendar_sync.infrastructure.persistence.sqlite import (
    SqliteUnitOfWorkFactory,
    initialize_database,
)
from tests.fake_calendar import FakeCalendars, enabled_rule_factory, sync_use_case
from tests.helpers import occurrence, rule, series, week_start

STARTS = tuple(week_start(week) for week in range(4))


def _synced() -> tuple[FakeCalendars, InMemoryUnitOfWorkFactory, EventRef]:
    calendars = FakeCalendars()
    calendars.put(series(), starts=STARTS)
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    mapping = factory.state.mappings[(rule().id, series().reference)]
    return calendars, factory, mapping.destination


def _occurrence_states(
    factory: InMemoryUnitOfWorkFactory,
) -> dict[OccurrenceStart, OccurrenceState]:
    return {key[1]: mapping.state for key, mapping in factory.state.occurrences.items()}


def test_first_run_creates_one_busy_destination_series_with_its_time_zone() -> None:
    calendars, factory, destination = _synced()

    projected = calendars.events[destination]
    assert projected.recurrence == series().recurrence
    assert projected.title == "Busy"
    assert isinstance(projected.time, TimedInterval)
    assert projected.time.time_zone == "Europe/Madrid"
    assert calendars.writes == [("create", destination.event_id.value)]


def test_exception_listed_before_its_series_is_applied_after_the_series_is_created() -> None:
    calendars = FakeCalendars()
    master = calendars.put(series(), starts=STARTS)
    moved = occurrence(master, 1, moved_by=timedelta(hours=2), title="Secret offsite")
    factory = enabled_rule_factory()
    calendars.put(moved)
    # A full listing may return the exception first; the run must still create the series first.
    calendars.events = {moved.reference: moved, master.reference: master}

    result = sync_use_case(factory, calendars).execute(rule().id)

    destination = factory.state.mappings[(rule().id, master.reference)].destination
    written = calendars.get_occurrence(destination, week_start(1))
    assert written is not None
    assert written.title == "Busy"
    assert written.time == moved.time
    assert [kind for kind, _ in calendars.writes] == ["create", "write_occurrence"]
    assert _occurrence_states(factory) == {week_start(1): OccurrenceState.MODIFIED}
    assert result.conflicts == 0


def test_exception_without_its_series_in_the_batch_uses_the_existing_series_mapping() -> None:
    calendars, factory, destination = _synced()
    moved = calendars.put(occurrence(series(), 2, moved_by=timedelta(minutes=30)))
    calendars.report(moved)

    sync_use_case(factory, calendars).execute(rule().id)

    written = calendars.get_occurrence(destination, week_start(2))
    assert written is not None and written.time == moved.time


def test_exception_of_an_unmapped_series_creates_the_series_first() -> None:
    calendars = FakeCalendars()
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    master = calendars.put(series(), starts=STARTS)
    moved = calendars.put(occurrence(master, 1, moved_by=timedelta(hours=1)))
    calendars.report(moved)

    sync_use_case(factory, calendars).execute(rule().id)

    assert (rule().id, master.reference) in factory.state.mappings
    assert [kind for kind, _ in calendars.writes] == ["create", "write_occurrence"]


def test_cancelled_source_occurrence_cancels_only_that_destination_occurrence() -> None:
    calendars, factory, destination = _synced()
    cancelled = calendars.put(occurrence(series(), 1, status=EventStatus.CANCELLED))
    calendars.report(cancelled)

    sync_use_case(factory, calendars).execute(rule().id)

    assert calendars.get_occurrence(destination, week_start(1)).status is EventStatus.CANCELLED  # type: ignore[union-attr]
    assert calendars.events[destination].status is EventStatus.CONFIRMED
    assert calendars.writes[-1][0] == "cancel_occurrence"
    assert _occurrence_states(factory) == {week_start(1): OccurrenceState.CANCELLED}


def test_cancelled_series_deletes_the_destination_series_and_its_occurrence_mappings() -> None:
    calendars, factory, destination = _synced()
    calendars.report(calendars.put(occurrence(series(), 1, status=EventStatus.CANCELLED)))
    sync_use_case(factory, calendars).execute(rule().id)
    cancelled_master = calendars.put(
        replace(series(), status=EventStatus.CANCELLED, time=None, recurrence=None)
    )
    calendars.report(cancelled_master)

    sync_use_case(factory, calendars).execute(rule().id)

    assert destination not in calendars.events
    assert factory.state.mappings == {}
    assert factory.state.occurrences == {}
    assert ("delete", destination.event_id.value) in calendars.writes
    assert not any(kind == "delete" and "_" in ref for kind, ref in calendars.writes)


def test_this_and_following_split_truncates_the_old_series_and_creates_the_new_one() -> None:
    calendars, factory, destination = _synced()
    calendars.report(calendars.put(occurrence(series(), 3, moved_by=timedelta(hours=1))))
    sync_use_case(factory, calendars).execute(rule().id)
    truncated = calendars.put(
        replace(
            series(),
            revision="series-revision-2",
            recurrence=Recurrence(("RRULE:FREQ=WEEKLY;UNTIL=20260915T080000Z",)),
        ),
        starts=STARTS[:2],
    )
    del calendars.events[occurrence(series(), 3).reference]
    following = calendars.put(series("source-series-2"), starts=STARTS[2:])
    calendars.report(truncated, following)

    sync_use_case(factory, calendars).execute(rule().id)

    assert calendars.events[destination].recurrence == truncated.recurrence
    assert (rule().id, following.reference) in factory.state.mappings
    assert factory.state.occurrences == {}
    assert not any(
        kind in {"write_occurrence", "cancel_occurrence"} for kind, _ in calendars.writes[-2:]
    )


def test_destination_edit_of_an_unmodified_occurrence_is_repaired() -> None:
    calendars, factory, destination = _synced()
    edited = calendars.get_occurrence(destination, week_start(2))
    assert edited is not None
    edited = calendars.put(replace(edited, title="Edited in destination"))
    calendars.report(edited)

    result = sync_use_case(factory, calendars).execute(rule().id)

    assert calendars.get_occurrence(destination, week_start(2)).title == "Busy"  # type: ignore[union-attr]
    assert result.conflicts == 0
    assert factory.state.audit[-1].reason == SyncReason.OCCURRENCE_DRIFT_REPAIRED.value


def test_destination_cancellation_of_a_confirmed_occurrence_is_restored() -> None:
    calendars, factory, destination = _synced()
    calendars.cancel_occurrence(destination, week_start(2), series().reference, rule().id, "user")
    calendars.report(calendars.get_occurrence(destination, week_start(2)))  # type: ignore[arg-type]

    sync_use_case(factory, calendars).execute(rule().id)

    assert calendars.get_occurrence(destination, week_start(2)).status is EventStatus.CONFIRMED  # type: ignore[union-attr]


def test_recreated_destination_series_keeps_source_cancellations() -> None:
    calendars, factory, destination = _synced()
    calendars.report(calendars.put(occurrence(series(), 1, status=EventStatus.CANCELLED)))
    sync_use_case(factory, calendars).execute(rule().id)
    deleted = replace(calendars.events.pop(destination), status=EventStatus.CANCELLED, time=None)
    for instance in calendars.instances_of(destination):
        del calendars.events[instance.reference]
    calendars.report(deleted)

    sync_use_case(factory, calendars).execute(rule().id)

    recreated = factory.state.mappings[(rule().id, series().reference)].destination
    assert recreated != destination
    assert calendars.get_occurrence(recreated, week_start(1)).status is EventStatus.CANCELLED  # type: ignore[union-attr]
    assert _occurrence_states(factory) == {week_start(1): OccurrenceState.CANCELLED}


def test_reverse_rule_ignores_managed_series_and_their_metadata_less_cancellations() -> None:
    calendars, factory, destination = _synced()
    calendars.cancel_occurrence(destination, week_start(1), series().reference, rule().id, "k")
    reverse = SyncRule(SyncRuleId("reverse"), rule().destination, rule().source, state=rule().state)
    reverse_factory = enabled_rule_factory(reverse)
    before = list(calendars.writes)

    result = sync_use_case(reverse_factory, calendars).execute(reverse.id)

    assert calendars.writes == before
    assert result.created == 0 and result.updated == 0 and result.deleted == 0
    assert reverse_factory.state.mappings == {}


def test_destination_series_owned_by_another_rule_blocks_occurrence_writes() -> None:
    calendars, factory, destination = _synced()
    master = calendars.events[destination]
    calendars.events[destination] = replace(
        master, managed_origin=ManagedOrigin(SyncRuleId("other"), series().reference)
    )
    calendars.report(calendars.put(occurrence(series(), 1, moved_by=timedelta(hours=1))))
    before = list(calendars.writes)

    result = sync_use_case(factory, calendars).execute(rule().id)

    assert result.conflicts >= 1
    assert [write for write in calendars.writes if write not in before] == []


def test_unverifiable_source_series_blocks_without_deleting() -> None:
    calendars, factory, destination = _synced()
    calendars.unreadable.add(series().reference)
    edited = calendars.get_occurrence(destination, week_start(2))
    assert edited is not None
    calendars.report(calendars.put(replace(edited, title="Edited")))
    before = list(calendars.writes)

    result = sync_use_case(factory, calendars).execute(rule().id)

    assert result.conflicts == 1
    assert calendars.writes == before
    assert factory.state.audit[-1].reason == SyncReason.SOURCE_UNVERIFIABLE.value


def test_missing_destination_occurrence_after_repair_is_a_conflict() -> None:
    calendars, factory, destination = _synced()
    # The destination series has drifted: it no longer expands to the source's occurrences.
    calendars.expansions[destination] = ()
    calendars.report(calendars.put(occurrence(series(), 2, moved_by=timedelta(hours=1))))
    before = list(calendars.writes)

    result = sync_use_case(factory, calendars).execute(rule().id)

    assert result.conflicts == 1
    assert factory.state.audit[-1].reason == SyncReason.DESTINATION_OCCURRENCE_MISSING.value
    assert [kind for kind, _ in calendars.writes[len(before) :]] == []


def test_rule_change_during_a_run_stops_occurrence_writes(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    factory = SqliteUnitOfWorkFactory(database)
    with factory() as uow:
        uow.rules.add(rule())
        uow.commit()
    calendars = FakeCalendars()
    calendars.put(series(), starts=STARTS)
    sync_use_case(factory, calendars).execute(rule().id)
    calendars.report(calendars.put(occurrence(series(), 1, moved_by=timedelta(hours=1))))

    class EditingCalendars(FakeCalendars):
        def changes(
            self, source: CalendarEndpoint, cursor: str | None, not_ended_before: datetime
        ) -> ProviderChangeSet:
            with factory() as concurrent:
                current = concurrent.rules.get(rule().id)
                assert current is not None
                if current.state is SyncRuleState.ENABLED:
                    concurrent.rules.save(current.pause())
                    concurrent.commit()
            return super().changes(source, cursor, not_ended_before)

    editing = EditingCalendars(calendars.events, calendars.expansions, calendars.feeds)
    with factory() as uow:
        cursor_before = uow.cursors.get(rule().id)

    with pytest.raises(RuleNotExecutable):
        sync_use_case(factory, editing).execute(rule().id)

    assert editing.writes == []
    with factory() as uow:
        assert uow.cursors.get(rule().id) == cursor_before


def test_every_occurrence_audit_entry_has_a_run_id_and_reason_but_no_content() -> None:
    calendars, factory, _destination = _synced()
    calendars.report(
        calendars.put(occurrence(series(), 1, title="Secret offsite", moved_by=timedelta(hours=1)))
    )

    sync_use_case(factory, calendars).execute(rule().id)

    assert all(entry.run_id and entry.reason for entry in factory.state.audit)
    assert all(
        "Secret" not in repr(entry) and "Sensitive" not in repr(entry)
        for entry in factory.state.audit
    )
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/application/test_recurring_sync.py -q -p no:warnings`
Expected: FAIL (occurrences routed to `decide` raise `DomainValidationError`).

- [ ] **Step 3: Create `application/sync_run.py`**

```python
from __future__ import annotations

from dataclasses import dataclass, field

from calendar_sync.application.errors import RuleNotExecutable
from calendar_sync.application.ports import UnitOfWork
from calendar_sync.domain.model import EventRef, SyncAction, SyncRule, SyncRuleState

OUTCOMES = {SyncAction.IGNORE: "skipped", SyncAction.CONFLICT: "blocked"}


@dataclass(slots=True)
class SyncRunContext:
    """State shared by every decision of one Sync Run."""

    uow: UnitOfWork
    rule: SyncRule
    run_id: str
    counts: dict[SyncAction, int]
    reproject: bool = False
    handled: set[EventRef] = field(default_factory=set)


def require_unchanged(run: SyncRunContext) -> None:
    """Stop before writing if the rule was paused, edited, or removed during this run."""
    current = run.uow.rules.get(run.rule.id)
    if (
        current is None
        or current.state is not SyncRuleState.ENABLED
        or current.material_signature != run.rule.material_signature
    ):
        raise RuleNotExecutable("sync rule changed during synchronization; run stopped")
```

- [ ] **Step 4: Create `application/occurrences.py`**

```python
from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass

from calendar_sync.application.ports import AuditEntry, CalendarProvider, Clock
from calendar_sync.application.sync_run import OUTCOMES, SyncRunContext, require_unchanged
from calendar_sync.domain.model import (
    CalendarEvent,
    EventMapping,
    EventRef,
    EventStatus,
    OccurrenceMapping,
    OccurrenceMappingId,
    OccurrenceStart,
    OccurrenceState,
    ProjectionFingerprint,
    SyncAction,
    SyncDecision,
    SyncReason,
    SyncRuleId,
)
from calendar_sync.domain.services import ProjectionFingerprinter, SyncDecisionService

_RECORDED_WHEN_UNCHANGED = {
    SyncReason.OCCURRENCE_CURRENT: OccurrenceState.MODIFIED,
    SyncReason.OCCURRENCE_ALREADY_CANCELLED: OccurrenceState.CANCELLED,
}


@dataclass(slots=True)
class SynchronizeOccurrences:
    """Applies source authority to single occurrences of mapped series."""

    provider: CalendarProvider
    decisions: SyncDecisionService
    fingerprinter: ProjectionFingerprinter
    clock: Clock
    repair_series: Callable[[SyncRunContext, CalendarEvent], None]

    def reverify(
        self, run: SyncRunContext, series_mapping: EventMapping, source_series: CalendarEvent
    ) -> None:
        """Re-decide every recorded occurrence of a series after its master changed."""
        for recorded in run.uow.occurrences.for_series(series_mapping.id):
            if recorded.source in run.handled:
                continue
            source_occurrence = self.provider.get_occurrence(
                source_series.reference, recorded.original_start
            )
            self.apply(
                run,
                series_mapping,
                source_series,
                recorded.original_start,
                source_occurrence,
                record_current=True,
            )

    def apply(
        self,
        run: SyncRunContext,
        series_mapping: EventMapping | None,
        source_series: CalendarEvent,
        original_start: OccurrenceStart,
        source_occurrence: CalendarEvent | None,
        *,
        record_current: bool,
        destination_reported: bool = False,
    ) -> None:
        require_unchanged(run)
        recorded = (
            run.uow.occurrences.get(series_mapping.id, original_start) if series_mapping else None
        )
        decision, destination = self._decide(
            run,
            series_mapping,
            source_series,
            original_start,
            source_occurrence,
            recorded,
            destination_reported,
        )
        if decision.reason is SyncReason.DESTINATION_OCCURRENCE_MISSING:
            self.repair_series(run, source_series)
            series_mapping = run.uow.mappings.for_source(run.rule.id, source_series.reference)
            decision, destination = self._decide(
                run,
                series_mapping,
                source_series,
                original_start,
                source_occurrence,
                recorded,
                destination_reported,
            )
        run.counts[decision.action] += 1
        source_ref = (
            source_occurrence.reference
            if source_occurrence is not None
            else recorded.source
            if recorded is not None
            else None
        )
        key = occurrence_operation_key(
            run.rule.id,
            source_series.reference,
            original_start,
            source_occurrence.revision if source_occurrence is not None else "absent",
            decision.action,
        )
        destination_ref = destination.reference if destination is not None else None

        if decision.action is SyncAction.UPDATE and decision.projection is not None:
            assert series_mapping is not None and source_occurrence is not None
            written = self.provider.write_occurrence(
                series_mapping.destination,
                original_start,
                source_series.reference,
                run.rule.id,
                decision.projection,
                key,
            )
            destination_ref = written.reference
            self._record(
                run,
                recorded,
                series_mapping,
                original_start,
                source_occurrence,
                destination_ref,
                OccurrenceState.MODIFIED,
                self.fingerprinter.fingerprint(decision.projection),
                key,
            )
        elif decision.action is SyncAction.DELETE:
            assert series_mapping is not None
            self.provider.cancel_occurrence(
                series_mapping.destination,
                original_start,
                source_series.reference,
                run.rule.id,
                key,
            )
            if source_occurrence is None:
                if recorded is not None:
                    run.uow.occurrences.delete(recorded)
            else:
                assert destination_ref is not None
                self._record(
                    run,
                    recorded,
                    series_mapping,
                    original_start,
                    source_occurrence,
                    destination_ref,
                    OccurrenceState.CANCELLED,
                    None,
                    key,
                )
        elif decision.reason is SyncReason.OCCURRENCE_RETIRED and recorded is not None:
            run.uow.occurrences.delete(recorded)
        elif (
            record_current
            and decision.reason in _RECORDED_WHEN_UNCHANGED
            and series_mapping is not None
            and source_occurrence is not None
            and destination_ref is not None
        ):
            state = _RECORDED_WHEN_UNCHANGED[decision.reason]
            fingerprint = (
                self.fingerprinter.fingerprint(decision.projection)
                if state is OccurrenceState.MODIFIED and decision.projection is not None
                else None
            )
            if (
                recorded is None
                or recorded.state is not state
                or recorded.source_revision != source_occurrence.revision
            ):
                self._record(
                    run,
                    recorded,
                    series_mapping,
                    original_start,
                    source_occurrence,
                    destination_ref,
                    state,
                    fingerprint,
                    key,
                )

        if source_ref is not None:
            run.handled.add(source_ref)
        run.uow.audit.append(
            AuditEntry(
                occurred_at=self.clock.now(),
                rule_id=run.rule.id,
                action=decision.action.value,
                outcome=OUTCOMES.get(decision.action, "completed"),
                source_event_id=(source_ref or source_series.reference).event_id.value,
                destination_event_id=destination_ref.event_id.value if destination_ref else None,
                reason=decision.reason.value,
                run_id=run.run_id,
            )
        )

    def _decide(
        self,
        run: SyncRunContext,
        series_mapping: EventMapping | None,
        source_series: CalendarEvent,
        original_start: OccurrenceStart,
        source_occurrence: CalendarEvent | None,
        recorded: OccurrenceMapping | None,
        destination_reported: bool,
    ) -> tuple[SyncDecision, CalendarEvent | None]:
        destination_series = destination = None
        if series_mapping is not None and source_series.managed_origin is None:
            destination_series = self.provider.get_event(series_mapping.destination)
            if (
                destination_series is not None
                and destination_series.status is EventStatus.CONFIRMED
            ):
                destination = self.provider.get_occurrence(
                    series_mapping.destination, original_start
                )
        decision = self.decisions.decide_occurrence(
            run.rule,
            source_series,
            series_mapping,
            original_start,
            source_occurrence,
            recorded,
            destination_series,
            destination,
            destination_reported=destination_reported,
        )
        return decision, destination

    @staticmethod
    def _record(
        run: SyncRunContext,
        recorded: OccurrenceMapping | None,
        series_mapping: EventMapping,
        original_start: OccurrenceStart,
        source_occurrence: CalendarEvent,
        destination: EventRef,
        state: OccurrenceState,
        fingerprint: ProjectionFingerprint | None,
        key: str,
    ) -> None:
        run.uow.occurrences.save(
            OccurrenceMapping(
                id=recorded.id if recorded is not None else OccurrenceMappingId(key),
                series_mapping_id=series_mapping.id,
                original_start=original_start,
                source=source_occurrence.reference,
                destination=destination,
                state=state,
                source_revision=source_occurrence.revision,
                projection_fingerprint=fingerprint,
            )
        )


def occurrence_operation_key(
    rule_id: SyncRuleId,
    source_series: EventRef,
    original_start: OccurrenceStart,
    revision: str,
    action: SyncAction,
) -> str:
    raw = "|".join(
        (
            rule_id.value,
            source_series.calendar.connected_account_id.value,
            source_series.calendar.calendar_id.value,
            source_series.event_id.value,
            original_start.isoformat(),
            revision,
            action.value,
        )
    )
    return hashlib.sha256(raw.encode()).hexdigest()
```

- [ ] **Step 5: Rewire `ExecuteSyncRule`**

In `synchronization.py`:
- Remove `_OUTCOMES` and `_require_unchanged`; import `OUTCOMES`, `SyncRunContext`,
  `require_unchanged` from `sync_run` and `SynchronizeOccurrences` from `occurrences`.
- Add a field `occurrences: SynchronizeOccurrences = field(init=False, repr=False)` and:

```python
    def __post_init__(self) -> None:
        self.occurrences = SynchronizeOccurrences(
            self.provider, self.decisions, self.fingerprinter, self.clock, self._repair_series
        )
```

- In `_execute_serialized`, after computing `reproject`, create
  `run = SyncRunContext(uow, rule, run_id, counts, reproject)` and replace the two loops with:

```python
# Series masters first, so an exception can always resolve its parent's mapping.
for source_event in sorted(changes.events, key=lambda item: item.occurrence is not None):
    if source_event.occurrence is not None:
        self._synchronize_source_exception(run, source_event)
    else:
        self._synchronize_event(
            run, source_event, destination_loaded=False, actual_destination=None
        )
        run.handled.add(source_event.reference)
    uow.commit()

for destination_event in destination_changes.events:
    if destination_event.occurrence is not None:
        self._repair_destination_occurrence(run, destination_event)
        uow.commit()
        continue
    mapping = uow.mappings.for_destination(rule.id, destination_event.reference)
    if mapping is None:
        continue
    authoritative_source = self.provider.get_event(mapping.source)
    if authoritative_source is None:
        self._record_unverifiable(run, mapping.source, mapping.destination)
        uow.commit()
        continue
    self._synchronize_event(
        run,
        authoritative_source,
        destination_loaded=True,
        actual_destination=(
            None if destination_event.status is EventStatus.CANCELLED else destination_event
        ),
    )
    run.handled.add(mapping.source)
    uow.commit()

if reproject:
    self._reproject_remaining(run)
```

- Replace `_reproject_remaining`, `_synchronize_event`, and add helpers:

```python
def _reproject_remaining(self, run: SyncRunContext) -> None:
    """Apply a changed policy to mappings the change feeds did not report."""
    for mapping in run.uow.mappings.for_rule(run.rule.id):
        if mapping.source in run.handled:
            continue
        authoritative_source = self.provider.get_event(mapping.source)
        if authoritative_source is None:
            self._record_unverifiable(run, mapping.source, mapping.destination)
        else:
            # Reprojection re-verifies every recorded occurrence of a series as well.
            self._synchronize_event(
                run, authoritative_source, destination_loaded=False, actual_destination=None
            )
        run.handled.add(mapping.source)
        run.uow.commit()


def _synchronize_source_exception(self, run: SyncRunContext, exception: CalendarEvent) -> None:
    identity = exception.occurrence
    assert identity is not None
    series_ref = EventRef(run.rule.source, identity.series_event_id)
    source_series = self.provider.get_event(series_ref)
    if source_series is None:
        self._record_unverifiable(run, exception.reference, None)
        return
    series_mapping = run.uow.mappings.for_source(run.rule.id, series_ref)
    if series_mapping is None and series_ref not in run.handled:
        self._synchronize_event(
            run, source_series, destination_loaded=False, actual_destination=None
        )
        run.handled.add(series_ref)
        series_mapping = run.uow.mappings.for_source(run.rule.id, series_ref)
    self.occurrences.apply(
        run,
        series_mapping,
        source_series,
        identity.original_start,
        exception,
        record_current=True,
    )


def _repair_destination_occurrence(
    self, run: SyncRunContext, destination_event: CalendarEvent
) -> None:
    identity = destination_event.occurrence
    assert identity is not None
    series_mapping = run.uow.mappings.for_destination(
        run.rule.id, EventRef(run.rule.destination, identity.series_event_id)
    )
    if series_mapping is None:
        return
    source_series = self.provider.get_event(series_mapping.source)
    if source_series is None:
        self._record_unverifiable(run, series_mapping.source, destination_event.reference)
        return
    source_occurrence = self.provider.get_occurrence(series_mapping.source, identity.original_start)
    if source_occurrence is not None and source_occurrence.reference in run.handled:
        return
    self.occurrences.apply(
        run,
        series_mapping,
        source_series,
        identity.original_start,
        source_occurrence,
        record_current=False,
        destination_reported=True,
    )


def _repair_series(self, run: SyncRunContext, source_series: CalendarEvent) -> None:
    self._synchronize_event(
        run, source_series, destination_loaded=False, actual_destination=None, cascade=False
    )


def _record_unverifiable(
    self, run: SyncRunContext, source: EventRef, destination: EventRef | None
) -> None:
    run.counts[SyncAction.CONFLICT] += 1
    run.uow.audit.append(
        AuditEntry(
            occurred_at=self.clock.now(),
            rule_id=run.rule.id,
            action=SyncAction.CONFLICT.value,
            outcome="blocked",
            source_event_id=source.event_id.value,
            destination_event_id=destination.event_id.value if destination else None,
            reason=SyncReason.SOURCE_UNVERIFIABLE.value,
            run_id=run.run_id,
        )
    )
```

`_synchronize_event(self, run, source_event, *, destination_loaded, actual_destination, cascade=True)`
treats a fetched destination whose status is cancelled as missing (as the destination-feed path
already does), so a deleted series master is recreated instead of failing ownership checks on
Google's metadata-less cancelled events. It otherwise keeps its body, reading `uow`/`rule`/`run_id`/`counts` from `run`, calling `require_unchanged(run)`
first, using `OUTCOMES`, and ending with:

```python
        series_changed = decision.action in {SyncAction.CREATE, SyncAction.UPDATE}
        if (
            cascade
            and mapping is not None
            and decision.action is not SyncAction.DELETE
            and (series_changed or (run.reproject and decision.action is SyncAction.IGNORE))
        ):
            self.occurrences.reverify(run, mapping, source_event)
```

- [ ] **Step 6: Run tests**

Run: `.venv/bin/pytest tests -q -p no:warnings && .venv/bin/mypy && .venv/bin/ruff check .`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/calendar_sync/application tests/application
git commit -m "feat: synchronize recurring series and occurrence exceptions"
```

---

### Task 8: Policy-change reprojection for series

**Files:**
- Test: `tests/application/test_recurring_sync.py`
- Modify (only if tests fail): `src/calendar_sync/application/synchronization.py`

**Interfaces:**
- Consumes: Task 7 `_reproject_remaining` and `SynchronizeOccurrences.reverify`.

- [ ] **Step 1: Write the tests**

Append to `tests/application/test_recurring_sync.py`:

```python
def _change_policy(factory: InMemoryUnitOfWorkFactory, policy: TransformationPolicy) -> None:
    with factory() as uow:
        current = uow.rules.get(rule().id)
        assert current is not None
        uow.rules.save(current.change_policy(policy).mark_dry_run_validated().enable())
        uow.commit()


def test_details_to_busy_change_rewrites_the_master_and_exceptions_outside_the_window() -> None:
    details = TransformationPolicy(privacy=PrivacyPolicy.COPY_DETAILS)
    calendars = FakeCalendars()
    master = calendars.put(replace(series(), title="Weekly private sync"), starts=STARTS)
    factory = enabled_rule_factory(replace(rule(), transformation=details))
    sync_use_case(factory, calendars).execute(rule().id)
    early = week_start(-10)
    calendars.expansions[master.reference] = (early, *STARTS)
    destination = factory.state.mappings[(rule().id, master.reference)].destination
    calendars.expansions[destination] = (early, *STARTS)
    old_exception = calendars.put(
        replace(occurrence(master, -10, title="Old secret"), revision="old-r1")
    )
    calendars.report(old_exception)
    sync_use_case(factory, calendars).execute(rule().id)
    assert calendars.get_occurrence(destination, early).title == "Old secret"  # type: ignore[union-attr]

    _change_policy(factory, TransformationPolicy(privacy=PrivacyPolicy.BUSY_ONLY))
    sync_use_case(factory, calendars).execute(rule().id)

    assert calendars.events[destination].title == "Busy"
    rewritten = calendars.get_occurrence(destination, early)
    assert rewritten is not None
    assert (rewritten.title, rewritten.description, rewritten.location) == ("Busy", "", "")
    assert factory.state.rules[rule().id].reprojection_required is False
    occurrence_writes = [ref for kind, ref in calendars.writes if kind == "write_occurrence"]
    assert occurrence_writes.count(rewritten.reference.event_id.value) == 2


def test_all_day_exclusion_deletes_all_day_series_and_cancels_all_day_exceptions() -> None:
    calendars = FakeCalendars()
    all_day_master = calendars.put(
        series("all-day-series", all_day=True), starts=(STARTS[0].date(),)
    )
    timed_master = calendars.put(series(), starts=STARTS)
    calendars.put(occurrence(timed_master, 1, all_day=True))
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    timed_destination = factory.state.mappings[(rule().id, timed_master.reference)].destination
    all_day_destination = factory.state.mappings[(rule().id, all_day_master.reference)].destination

    _change_policy(factory, TransformationPolicy(all_day=AllDaySyncPolicy.EXCLUDE))
    sync_use_case(factory, calendars).execute(rule().id)

    assert all_day_destination not in calendars.events
    assert (
        calendars.get_occurrence(timed_destination, week_start(1)).status is EventStatus.CANCELLED
    )  # type: ignore[union-attr]
    assert factory.state.rules[rule().id].reprojection_required is False
```

Add `AllDaySyncPolicy` to the imports.

- [ ] **Step 2: Run**

Run: `.venv/bin/pytest tests/application/test_recurring_sync.py -q -p no:warnings`
Expected: PASS if Task 7's cascade handles reprojection. If the exception is written more than
twice or missed, fix `_reproject_remaining`/`reverify` so handled occurrence sources are skipped
and every Series Mapping reverifies once.

- [ ] **Step 3: Commit**

```bash
git add tests/application/test_recurring_sync.py src/calendar_sync/application
git commit -m "test: reproject recurring series and exceptions after a policy change"
```

---

### Task 9: Rule Removal with recurring projections

**Files:**
- Test: `tests/application/test_remove_sync_rule.py`

**Interfaces:**
- Consumes: `RemoveSyncRule(unit_of_work, provider, accounts, clock, locks)`, `ProjectionHandling`.

- [ ] **Step 1: Write the tests**

Append to `tests/application/test_remove_sync_rule.py`:

```python
def _synced_series() -> tuple[FakeCalendars, InMemoryUnitOfWorkFactory, EventRef]:
    calendars = FakeCalendars()
    master = calendars.put(series(), starts=tuple(week_start(w) for w in range(3)))
    calendars.put(occurrence(master, 1, status=EventStatus.CANCELLED))
    calendars.put(occurrence(master, 2, moved_by=timedelta(hours=1)))
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    return calendars, factory, factory.state.mappings[(rule().id, master.reference)].destination


def test_removing_a_series_deletes_only_its_destination_master() -> None:
    calendars, factory, destination = _synced_series()
    assert len(factory.state.occurrences) == 2
    before = len(calendars.writes)

    result = RemoveSyncRule(factory, calendars, Accounts(), FixedClock(), RuleLocks()).execute(
        rule().id, ProjectionHandling.DELETE
    )

    assert result.deleted == 1
    assert calendars.writes[before:] == [("delete", destination.event_id.value)]
    assert calendars.instances_of(destination) == []
    assert factory.state.occurrences == {}
    assert factory.state.mappings == {}


def test_detaching_a_series_keeps_it_ignored_by_a_reverse_rule() -> None:
    calendars, factory, destination = _synced_series()
    before = list(calendars.writes)

    RemoveSyncRule(factory, calendars, Accounts(), FixedClock(), RuleLocks()).execute(
        rule().id, ProjectionHandling.DETACH
    )
    reverse = SyncRule(
        SyncRuleId("reverse"), rule().destination, rule().source, state=SyncRuleState.ENABLED
    )
    reverse_factory = enabled_rule_factory(reverse)
    result = sync_use_case(reverse_factory, calendars).execute(reverse.id)

    assert calendars.writes == before
    assert factory.state.occurrences == {}
    assert result.created == result.updated == result.deleted == 0
    cancelled = calendars.get_occurrence(destination, week_start(1))
    assert cancelled is not None and cancelled.managed_origin is None
```

Add imports: `from datetime import timedelta`, `EventStatus`, `from tests.fake_calendar import
FakeCalendars, enabled_rule_factory, sync_use_case` and `occurrence, series, week_start` from helpers.
The existing `FixedClock` import from `test_execute_sync_rule` stays.

- [ ] **Step 2: Run**

Run: `.venv/bin/pytest tests/application/test_remove_sync_rule.py -q -p no:warnings`
Expected: PASS with no production change (memory cascade from Task 4, SQLite cascade tested in
Task 4). If the reverse rule creates anything, fix routing in Task 7 code, not the test.

- [ ] **Step 3: Commit**

```bash
git add tests/application/test_remove_sync_rule.py
git commit -m "test: remove and detach recurring projections through their series master"
```

---

### Task 10: Reconcile recorded occurrences

**Files:**
- Modify: `src/calendar_sync/application/reconciliation.py`
- Test: `tests/application/test_reconcile_sync_rule.py`

**Interfaces:**
- Consumes: `OccurrenceCheck`, `ReconciliationService.reconcile(..., occurrences=...)`,
  `UnitOfWork.occurrences`, `CalendarProvider.get_occurrence`.

- [ ] **Step 1: Write the test**

Append to `tests/application/test_reconcile_sync_rule.py`:

```python
def test_reconciliation_counts_occurrence_drift_in_the_recorded_outcome() -> None:
    calendars = FakeCalendars()
    master = calendars.put(series(), starts=tuple(week_start(w) for w in range(3)))
    calendars.put(occurrence(master, 1, moved_by=timedelta(hours=1)))
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    destination = factory.state.mappings[(rule().id, master.reference)].destination
    edited = calendars.get_occurrence(destination, week_start(1))
    assert edited is not None
    calendars.put(replace(edited, title="Edited"))

    report = ReconcileSyncRule(
        factory,
        calendars,
        EventProjector(),
        ReconciliationService(ProjectionFingerprinter()),
        FixedClock(),
    ).execute(rule().id)

    assert [item.kind for item in report.drift] == [DriftKind.INCORRECT_PROJECTION]
    outcome = factory.state.outcomes[(rule().id, RunKind.RECONCILIATION)]
    assert outcome.checked_mappings == 1
    assert outcome.drift == 1
```

Add the needed imports (`replace`, `timedelta`, `DriftKind`, `RunKind`, `ReconcileSyncRule`,
`EventProjector`, `ProjectionFingerprinter`, `ReconciliationService`, fake and helpers).

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/application/test_reconcile_sync_rule.py -q -p no:warnings`
Expected: FAIL (edited occurrence is not reported: it appears as `UNEXPECTED` or not at all).

- [ ] **Step 3: Implement**

In `ReconcileSyncRule.execute`, read occurrences inside the first unit of work:

```python
            mappings = uow.mappings.for_rule(rule.id)
            recorded = {mapping.id: uow.occurrences.for_series(mapping.id) for mapping in mappings}
```

pass `recorded` into `_reconcile`, and build checks there:

```python
        checks: list[OccurrenceCheck] = []
        for mapping in mappings:
            if mapping.source not in expected:
                continue  # the master's own inconsistency is already reported
            for occurrence in recorded.get(mapping.id, ()):
                source = self.provider.get_occurrence(mapping.source, occurrence.original_start)
                checks.append(
                    OccurrenceCheck(
                        occurrence,
                        mapping.destination,
                        self.projector.project(source, rule)
                        if source is not None and self._eligible(source, rule)
                        else None,
                        self.provider.get_occurrence(mapping.destination, occurrence.original_start),
                    )
                )
        return self.reconciliation.reconcile(rule, mappings, expected, actual, checks)
```

Extract the existing eligibility condition into `_eligible(source, rule) -> bool` (confirmed, not
managed, not an excluded all-day event) and reuse it for masters.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests -q -p no:warnings && .venv/bin/mypy`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/calendar_sync/application/reconciliation.py tests/application/test_reconcile_sync_rule.py
git commit -m "feat: reconcile recorded occurrences and count their drift"
```

---

### Task 11: Preview recurring events

**Files:**
- Modify: `src/calendar_sync/application/preview.py`
- Modify: `src/calendar_sync/bootstrap/container.py`
- Modify: `src/calendar_sync/interfaces/api/app.py` (preview response)
- Modify: `tests/application/test_preview_sync_rule.py`, `tests/adapters/test_api.py` if it asserts
  the preview body
- Modify: `web/src/lib/api.ts`, `web/src/features/dashboard.tsx`, `web/src/features/rule-details.tsx`
- Create: `web/src/lib/rule-preview.ts`, `web/src/lib/rule-preview.test.ts`

**Interfaces:**
- Produces: `PreviewItem(source_event_id, projected_title, all_day, kind: str, planned_action:
  SyncAction)`; `RulePreview(rule_id, eligible_events, excluded_events, sample, recurring_series=0,
  occurrence_changes=0)`; `PreviewSyncRule(unit_of_work, provider, projector, clock, decisions)`;
  API adds `recurring_series`, `occurrence_changes`, and per-item `kind`, `planned_action`;
  `previewSummary(preview: RulePreview): string`.

- [ ] **Step 1: Write failing tests**

Replace the `PreviewSyncRule(...)` constructions in `tests/application/test_preview_sync_rule.py`
with a helper `_preview(unit_of_work, provider)` that passes
`SyncDecisionService(EventProjector(), ProjectionFingerprinter())` as `decisions`, and append:

```python
def test_preview_counts_series_and_occurrence_changes_with_planned_actions() -> None:
    calendars = FakeCalendars()
    master = calendars.put(series(), starts=tuple(week_start(w) for w in range(3)))
    calendars.put(occurrence(master, 1, moved_by=timedelta(hours=1)))
    calendars.put(occurrence(master, 2, status=EventStatus.CANCELLED))
    managed = calendars.put(
        series("managed", managed_origin=ManagedOrigin(SyncRuleId("other"), master.reference))
    )
    calendars.put(occurrence(managed, 1))
    factory = enabled_rule_factory(rule(state=SyncRuleState.DRAFT))

    preview = _preview(factory, calendars).execute(rule().id)

    assert preview.eligible_events == 1
    assert preview.recurring_series == 1
    assert preview.occurrence_changes == 2
    assert preview.excluded_events == 2
    assert [(item.kind, item.planned_action) for item in preview.sample] == [
        ("series", SyncAction.CREATE),
        ("occurrence", SyncAction.UPDATE),
        ("occurrence", SyncAction.DELETE),
    ]
    assert calendars.writes == []
    assert factory.state.mappings == {}
```

(`enabled_rule_factory` accepts any rule; the draft state keeps preview legal.)

Create `web/src/lib/rule-preview.test.ts`:

```ts
import { describe, expect, it } from "vitest"

import { previewSummary } from "./rule-preview"

describe("previewSummary", () => {
  it("keeps the single-event summary unchanged", () => {
    expect(previewSummary({ eligible_events: 3, excluded_events: 1, recurring_series: 0, occurrence_changes: 0 })).toBe(
      "Preview found 3 eligible and 1 excluded events.",
    )
  })

  it("mentions recurring series and occurrence changes", () => {
    expect(previewSummary({ eligible_events: 3, excluded_events: 0, recurring_series: 2, occurrence_changes: 1 })).toBe(
      "Preview found 3 eligible and 0 excluded events, including 2 recurring series and 1 changed occurrence.",
    )
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/application/test_preview_sync_rule.py -q -p no:warnings; npm --prefix web run test -- rule-preview`
Expected: FAIL.

- [ ] **Step 3: Implement preview**

Replace the body of `preview.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from calendar_sync.application.errors import RuleNotExecutable
from calendar_sync.application.ports import CalendarProvider, Clock, UnitOfWork, UnitOfWorkFactory
from calendar_sync.domain.model import (
    AllDaySyncPolicy,
    CalendarEvent,
    EventRef,
    EventStatus,
    SyncAction,
    SyncRule,
    SyncRuleId,
    SyncRuleState,
)
from calendar_sync.domain.services import EventProjector, SyncDecisionService

_SAMPLE_SIZE = 10


@dataclass(frozen=True, slots=True)
class PreviewItem:
    source_event_id: str
    projected_title: str
    all_day: bool
    kind: str
    planned_action: SyncAction


@dataclass(frozen=True, slots=True)
class RulePreview:
    rule_id: SyncRuleId
    eligible_events: int
    excluded_events: int
    sample: tuple[PreviewItem, ...]
    recurring_series: int = 0
    occurrence_changes: int = 0


def _excluded(event: CalendarEvent, rule: SyncRule) -> bool:
    return (
        event.managed_origin is not None
        or event.status is EventStatus.CANCELLED
        or (event.is_all_day and rule.transformation.all_day is AllDaySyncPolicy.EXCLUDE)
    )


@dataclass(slots=True)
class PreviewSyncRule:
    unit_of_work: UnitOfWorkFactory
    provider: CalendarProvider
    projector: EventProjector
    clock: Clock
    decisions: SyncDecisionService

    def execute(self, rule_id: SyncRuleId) -> RulePreview:
        with self.unit_of_work() as uow:
            rule = uow.rules.get(rule_id)
        if rule is None:
            raise RuleNotExecutable(f"sync rule {rule_id.value} does not exist")
        if rule.state not in {
            SyncRuleState.DRAFT,
            SyncRuleState.PAUSED,
            SyncRuleState.DEGRADED,
        }:
            raise RuleNotExecutable(f"sync rule cannot preview from state {rule.state}")

        cutoff = self.clock.now() - timedelta(days=rule.initial_lookback_days)
        events = self.provider.changes(rule.source, None, cutoff).events
        masters = {event.reference: event for event in events if event.occurrence is None}
        eligible: list[tuple[CalendarEvent, CalendarEvent | None]] = []
        excluded = series_count = occurrence_changes = 0
        for event in events:
            if event.occurrence is None:
                if _excluded(event, rule):
                    excluded += 1
                    continue
                series_count += event.recurrence is not None
                eligible.append((event, None))
                continue
            parent_ref = EventRef(rule.source, event.occurrence.series_event_id)
            parent = masters.get(parent_ref) or self.provider.get_event(parent_ref)
            if parent is None or _excluded(parent, rule):
                excluded += 1
                continue
            occurrence_changes += 1
            eligible.append((event, parent))

        with self.unit_of_work() as uow:
            sample = tuple(
                self._item(uow, rule, event, parent) for event, parent in eligible[:_SAMPLE_SIZE]
            )
        with self.unit_of_work() as uow:
            current = uow.rules.get(rule.id)
            if current is None or current.material_signature != rule.material_signature:
                raise RuleNotExecutable("sync rule changed while preview was running")
            uow.rules.save(current.mark_dry_run_validated())
            uow.commit()

        return RulePreview(
            rule.id,
            len(eligible) - occurrence_changes,
            excluded,
            sample,
            recurring_series=series_count,
            occurrence_changes=occurrence_changes,
        )

    def _item(
        self, uow: UnitOfWork, rule: SyncRule, event: CalendarEvent, parent: CalendarEvent | None
    ) -> PreviewItem:
        """Plan one item with provider reads only; nothing is written."""
        title = self.projector.project(event, rule).title if event.time is not None else ""
        if parent is None:
            mapping = uow.mappings.for_source(rule.id, event.reference)
            actual = self.provider.get_event(mapping.destination) if mapping else None
            action = self.decisions.decide(rule, event, mapping, actual).action
            kind = "series" if event.recurrence is not None else "single"
            return PreviewItem(
                event.reference.event_id.value, title, event.is_all_day, kind, action
            )
        assert event.occurrence is not None
        start = event.occurrence.original_start
        series_mapping = uow.mappings.for_source(rule.id, parent.reference)
        if series_mapping is None:
            cancels = event.status is EventStatus.CANCELLED or (
                event.is_all_day and rule.transformation.all_day is AllDaySyncPolicy.EXCLUDE
            )
            action = SyncAction.DELETE if cancels else SyncAction.UPDATE
        else:
            destination_series = self.provider.get_event(series_mapping.destination)
            action = self.decisions.decide_occurrence(
                rule,
                parent,
                series_mapping,
                start,
                event,
                uow.occurrences.get(series_mapping.id, start),
                destination_series,
                self.provider.get_occurrence(series_mapping.destination, start),
            ).action
        return PreviewItem(
            event.reference.event_id.value, title, event.is_all_day, "occurrence", action
        )
```

Pass `SyncDecisionService(projector, fingerprinter)` as the fifth argument in
`bootstrap/container.py`. In `app.py` add `"recurring_series"` and `"occurrence_changes"` to the
response and `"kind": item.kind, "planned_action": item.planned_action.value` to each sample item.

- [ ] **Step 4: Implement the web summary**

`web/src/lib/api.ts` — extend `RulePreview`:

```ts
export type RulePreview = {
  rule_id: string
  eligible_events: number
  excluded_events: number
  recurring_series: number
  occurrence_changes: number
  sample: {
    source_event_id: string
    projected_title: string
    all_day: boolean
    kind: "single" | "series" | "occurrence"
    planned_action: "create" | "update" | "delete" | "ignore" | "conflict"
  }[]
}
```

`web/src/lib/rule-preview.ts`:

```ts
import type { RulePreview } from "@/lib/api"

type PreviewCounts = Pick<RulePreview, "eligible_events" | "excluded_events" | "recurring_series" | "occurrence_changes">

function plural(count: number, noun: string, pluralNoun = `${noun}s`): string {
  return `${count} ${count === 1 ? noun : pluralNoun}`
}

export function previewSummary(preview: PreviewCounts): string {
  const base = `Preview found ${preview.eligible_events} eligible and ${preview.excluded_events} excluded events`
  const recurring = [
    preview.recurring_series > 0 ? plural(preview.recurring_series, "recurring series", "recurring series") : null,
    preview.occurrence_changes > 0 ? plural(preview.occurrence_changes, "changed occurrence") : null,
  ].filter(Boolean)
  return recurring.length ? `${base}, including ${recurring.join(" and ")}.` : `${base}.`
}
```

Replace both `Preview found {…} eligible and {…} excluded events.` renderings in
`web/src/features/dashboard.tsx` and `web/src/features/rule-details.tsx` with
`{previewSummary(latestPreview)}` / `{previewSummary(preview.data)}`.

- [ ] **Step 5: Run tests**

Run: `.venv/bin/pytest tests -q -p no:warnings && .venv/bin/mypy && npm --prefix web run typecheck && npm --prefix web run test`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/calendar_sync tests web/src
git commit -m "feat: preview recurring series and occurrence changes with planned actions"
```

---

### Task 12: Activity copy for occurrence reasons

**Files:**
- Modify: `web/src/lib/activity.ts`, `web/src/lib/activity.test.ts`
- Create: `tests/domain/test_reason_copy.py`

- [ ] **Step 1: Write failing tests**

`tests/domain/test_reason_copy.py` guards the "keep in sync" comment:

```python
from pathlib import Path

from calendar_sync.domain.model import SyncReason

ACTIVITY = Path(__file__).resolve().parents[2] / "web" / "src" / "lib" / "activity.ts"


def test_every_sync_reason_has_activity_copy() -> None:
    source = ACTIVITY.read_text()

    missing = [reason.value for reason in SyncReason if f"  {reason.value}: {{" not in source]

    assert missing == []
```

In `web/src/lib/activity.test.ts`, change the first test to expect
`copy.explanation` to contain `"Earlier versions"` and add:

```ts
  it("explains cancelled occurrences in calendar language", () => {
    const copy = describeEntry(entry({ action: "delete", reason: "occurrence_cancelled" }))
    expect(copy.summary).toBe("Removed one occurrence")
  })
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/domain/test_reason_copy.py -q; npm --prefix web run test -- activity`
Expected: FAIL.

- [ ] **Step 3: Add copy**

In `REASONS` in `activity.ts`, change `recurring_unsupported.explanation` to
`"Earlier versions did not sync recurring events. No projection was created or changed."` and add:

```ts
  occurrence_changed: {
    summary: "Updated one occurrence",
    explanation: "One occurrence of a recurring event was moved or edited in the source, so its projection was updated.",
  },
  occurrence_cancelled: {
    summary: "Removed one occurrence",
    explanation: "One occurrence of a recurring event was cancelled in the source. The rest of the series is unchanged.",
  },
  occurrence_removed_from_series: {
    summary: "Removed an occurrence that left its series",
    explanation: "The source series no longer includes this occurrence, so its projection was removed.",
  },
  occurrence_drift_repaired: {
    summary: "Repaired an edited occurrence",
    explanation:
      "One occurrence was edited or deleted directly in the destination calendar. The source is authoritative, so it was restored.",
  },
  occurrence_current: {
    summary: "No change needed",
    explanation: "The occurrence already matches the source.",
  },
  occurrence_already_cancelled: {
    summary: "No change needed",
    explanation: "The occurrence is cancelled in both calendars.",
  },
  occurrence_retired: {
    summary: "Forgot an occurrence that no longer exists",
    explanation: "The occurrence no longer exists in either calendar, so its record was removed. Nothing was written.",
  },
  series_not_synchronized: {
    summary: "Skipped an occurrence",
    explanation: "The occurrence belongs to a recurring event this rule does not sync.",
  },
  destination_occurrence_missing: {
    summary: "Blocked: the occurrence was not found in the destination series",
    explanation:
      "The destination series has no matching occurrence, even after repairing the series. Nothing was written. Reconcile the rule to investigate.",
  },
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/domain/test_reason_copy.py -q && npm --prefix web run test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib tests/domain/test_reason_copy.py
git commit -m "feat: explain occurrence decisions in the Activity feed"
```

---

### Task 13: Documentation

**Files:**
- Modify: `README.md`, `CONTEXT.md`, `AGENTS.md`, `docs/domain-model.md`, `docs/sync-model.md`,
  `docs/deployment.md`, `docs/troubleshooting.md`, `CHANGELOG.md`

- [ ] **Step 1: Update each document**

- `README.md` capabilities table, Events row: `Timed events, all-day events, recurring series,
  single-occurrence changes, and cancellations`.
- `CONTEXT.md` Recurrence section: replace the exclusion paragraph with the supported behavior
  (series project as series; occurrence changes and cancellations follow the source) and add terms
  **Series Mapping** (an Event Mapping whose source is an Event Series master; _Avoid_: parent
  mapping) and **Occurrence Mapping** (ownership evidence for one destination occurrence the
  application wrote under a Series Mapping, retained for cancellations so recreated series cannot
  resurrect them; _Avoid_: instance record, child event). Extend **Operational Record** with
  "occurrence starts".
- `AGENTS.md`: replace the recurrence exclusion invariant with: "Recurring series project as
  series. Occurrence writes require a Series Mapping plus parent-series and Managed Origin
  ownership, and a destination occurrence is cancelled only when the source proves it cancelled or
  absent from an existing series."
- `docs/domain-model.md`: Event Mapping aggregate gains the Occurrence Mapping child and its
  invariants (one per series mapping and Occurrence Start; removed with its Series Mapping; not
  counted as a managed projection); Calendar Event values paragraph describes typed Occurrence
  Start and series time zones.
- `docs/sync-model.md`: rewrite "Recurrence" per ADR 0011 (identity, ordering, source updates
  table, drift, reprojection, preview); mention occurrence checks in "Reconciliation".
- `docs/deployment.md`: upgrade note — migration 5 resets incremental cursors; enabled rules
  backfill recurring events on their next run; pause rules before upgrading to preview first; back
  up the database.
- `docs/troubleshooting.md`: entry for "Blocked: the occurrence was not found in the destination
  series" → run Reconcile Now; if it persists, remove and recreate the rule.
- `CHANGELOG.md` Unreleased: Added "Recurring series and single-occurrence changes synchronize
  under the same ownership, privacy, and repair guarantees as single events."; Changed "Upgrading
  resets incremental positions once so enabled rules backfill recurring events; pause a rule
  before upgrading to preview it first."

- [ ] **Step 2: Commit**

```bash
git add README.md CONTEXT.md AGENTS.md docs CHANGELOG.md
git commit -m "docs: document recurring-event synchronization"
```

---

### Task 14: Quality gates and static assets

- [ ] **Step 1: Backend gate**

```sh
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy
.venv/bin/pytest --cov --cov-report=term-missing --cov-fail-under=80
```

- [ ] **Step 2: Frontend gate and static build**

```sh
npm --prefix web run typecheck
npm --prefix web run lint
npm --prefix web run test
npm --prefix web run build
```

Commit the regenerated `src/calendar_sync/interfaces/api/static/` assets.

- [ ] **Step 3: Container build**

Run `docker compose build` if Docker is available; otherwise report it as not run.

- [ ] **Step 4: Commit**

```bash
git add src/calendar_sync/interfaces/api/static
git commit -m "build: rebuild the Web UI for recurring-event previews and activity copy"
```
