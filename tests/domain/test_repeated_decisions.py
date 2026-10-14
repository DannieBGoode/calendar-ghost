"""An ignore decision that repeats the event's previous entry, with nothing new, is not recorded."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta, timezone

import pytest

from calendar_sync.domain.audit import (
    AuditAction,
    AuditEntry,
    AuditOutcome,
    RecordedDecision,
    RecordedEvent,
    repeats_previous,
)
from calendar_sync.domain.changes import ComparisonKind, SourceComparison
from calendar_sync.domain.model import SyncReason, TimedInterval
from tests.helpers import NOW, rule

TIME = TimedInterval(NOW, NOW + timedelta(hours=1))
SEMINAR = RecordedEvent(title="Seminar", time=TIME, recurring=True)
UNTRACKED = SourceComparison(ComparisonKind.UNTRACKED)


def _entry(**changes: object) -> AuditEntry:
    entry = AuditEntry(
        occurred_at=NOW,
        rule_id=rule().id,
        action=AuditAction.IGNORE,
        outcome=AuditOutcome.SKIPPED,
        source_event_id="seminar",
        destination_event_id=None,
        reason=SyncReason.SERIES_WITHOUT_OCCURRENCES,
        event=SEMINAR,
    )
    return replace(entry, **changes)  # type: ignore[arg-type]


PREVIOUS = RecordedDecision.of(_entry())


def test_an_unchanged_repeat_of_the_previous_skip_is_a_repeat() -> None:
    assert repeats_previous(PREVIOUS, _entry(), UNTRACKED)
    assert repeats_previous(PREVIOUS, _entry(), SourceComparison(ComparisonKind.SAME_REVISION))


def test_the_same_instant_in_another_offset_is_a_repeat() -> None:
    offset = timezone(timedelta(hours=2))
    shifted = TimedInterval(TIME.starts_at.astimezone(offset), TIME.ends_at.astimezone(offset))
    entry = _entry(event=replace(SEMINAR, time=shifted))
    assert repeats_previous(PREVIOUS, entry, UNTRACKED)


def test_a_cancelled_repeat_of_a_cancelled_previous_entry_is_a_repeat() -> None:
    cancelled = replace(SEMINAR, cancelled=True)
    previous = RecordedDecision.of(_entry(event=cancelled))
    comparison = SourceComparison(ComparisonKind.CANCELLED)
    assert repeats_previous(previous, _entry(event=cancelled), comparison)


@pytest.mark.parametrize(
    ("previous", "entry", "comparison"),
    [
        pytest.param(None, _entry(), UNTRACKED, id="no previous entry"),
        pytest.param(
            PREVIOUS,
            _entry(action=AuditAction.CONFLICT, outcome=AuditOutcome.BLOCKED),
            UNTRACKED,
            id="not an ignore",
        ),
        pytest.param(
            PREVIOUS, _entry(), SourceComparison(ComparisonKind.CHANGED), id="tracked change"
        ),
        pytest.param(
            PREVIOUS, _entry(), SourceComparison(ComparisonKind.NO_BASELINE), id="no baseline"
        ),
        pytest.param(
            PREVIOUS,
            _entry(event=replace(SEMINAR, cancelled=True)),
            SourceComparison(ComparisonKind.CANCELLED),
            id="cancelled after live",
        ),
        pytest.param(
            PREVIOUS,
            _entry(),
            SourceComparison(ComparisonKind.UNTRACKED, completes_baseline=True),
            id="completes the baseline",
        ),
        pytest.param(
            RecordedDecision.of(_entry(action=AuditAction.CONFLICT)),
            _entry(),
            UNTRACKED,
            id="previous was a block",
        ),
        pytest.param(
            RecordedDecision.of(_entry(reason=SyncReason.PROJECTION_CURRENT)),
            _entry(),
            UNTRACKED,
            id="different reason",
        ),
        pytest.param(
            RecordedDecision.of(_entry(destination_event_id="other")),
            _entry(),
            UNTRACKED,
            id="different destination",
        ),
        pytest.param(
            RecordedDecision.of(_entry(event=None)),
            _entry(),
            UNTRACKED,
            id="previous has no event",
        ),
        pytest.param(PREVIOUS, _entry(event=None), UNTRACKED, id="entry has no event"),
        pytest.param(
            PREVIOUS,
            _entry(event=replace(SEMINAR, title="Renamed")),
            UNTRACKED,
            id="different title",
        ),
        pytest.param(
            PREVIOUS,
            _entry(event=replace(SEMINAR, time=TimedInterval(NOW, NOW + timedelta(hours=2)))),
            UNTRACKED,
            id="different time",
        ),
        pytest.param(
            PREVIOUS,
            _entry(event=replace(SEMINAR, recurring=False)),
            UNTRACKED,
            id="no longer recurring",
        ),
        pytest.param(
            RecordedDecision.of(_entry(event=replace(SEMINAR, cancelled=True))),
            _entry(),
            UNTRACKED,
            id="restored",
        ),
    ],
)
def test_anything_new_is_recorded(
    previous: RecordedDecision | None, entry: AuditEntry, comparison: SourceComparison
) -> None:
    assert not repeats_previous(previous, entry, comparison)
