"""How a source event compares with the rule's Source Observation of it."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta, timezone

from calendar_sync.domain.changes import (
    ComparisonKind,
    SourceComparison,
    SourceField,
    SourceObservation,
    same_time,
)
from calendar_sync.domain.model import EventStatus, TimedInterval
from tests.helpers import NOW, event

GUESTS = ("ana@example.com",)


def _observed(**changes: object) -> SourceObservation:
    details = {"guests": GUESTS, **changes}
    observation = SourceObservation.of(replace(event(), **details))  # type: ignore[arg-type]
    assert observation is not None
    return observation


def test_no_observation_is_no_baseline_and_saves_the_event() -> None:
    comparison = SourceComparison.of(None, replace(event(), guests=GUESTS))
    assert comparison.kind is ComparisonKind.NO_BASELINE
    assert comparison.change is None
    assert comparison.observation is not None


def test_the_same_revision_saves_nothing() -> None:
    comparison = SourceComparison.of(_observed(), replace(event(), guests=GUESTS))
    assert comparison.kind is ComparisonKind.SAME_REVISION
    assert comparison.observation is None
    assert not comparison.completes_baseline


def test_a_new_revision_with_the_same_tracked_fields_is_untracked() -> None:
    comparison = SourceComparison.of(_observed(), replace(event(), guests=GUESTS, revision="r2"))
    assert comparison.kind is ComparisonKind.UNTRACKED
    assert comparison.change is None
    assert comparison.observation is not None
    assert comparison.observation.revision == "r2"
    assert not comparison.completes_baseline


def test_a_new_revision_with_a_new_title_is_changed() -> None:
    comparison = SourceComparison.of(
        _observed(), replace(event(), guests=GUESTS, revision="r2", title="Renamed")
    )
    assert comparison.kind is ComparisonKind.CHANGED
    assert comparison.change is not None
    assert comparison.change.fields == (SourceField.TITLE,)


def test_learning_a_complete_guest_list_completes_the_baseline() -> None:
    previous = _observed(guests=None)
    comparison = SourceComparison.of(previous, replace(event(), guests=GUESTS, revision="r2"))
    assert comparison.kind is ComparisonKind.UNTRACKED
    assert comparison.completes_baseline


def test_a_partial_guest_list_keeps_the_known_one() -> None:
    comparison = SourceComparison.of(_observed(), replace(event(), guests=None, revision="r2"))
    assert comparison.observation is not None
    assert comparison.observation.guests == GUESTS
    assert not comparison.completes_baseline


def test_a_cancelled_event_is_cancelled_and_saves_nothing() -> None:
    cancelled = replace(event(), status=EventStatus.CANCELLED, time=None, revision="r2")
    comparison = SourceComparison.of(_observed(), cancelled)
    assert comparison.kind is ComparisonKind.CANCELLED
    assert comparison.observation is None


def test_times_are_the_same_when_they_name_the_same_instants() -> None:
    utc = TimedInterval(NOW, NOW + timedelta(hours=1))
    shifted = timezone(timedelta(hours=2))
    local = TimedInterval(NOW.astimezone(shifted), (NOW + timedelta(hours=1)).astimezone(shifted))
    assert same_time(utc, local)
    assert same_time(None, None)
    assert not same_time(utc, None)
    assert not same_time(utc, TimedInterval(NOW, NOW + timedelta(hours=2)))
