from dataclasses import replace
from datetime import date, timedelta

import pytest

from calendar_sync.domain.changes import SourceChange, SourceField, SourceObservation
from calendar_sync.domain.model import (
    AllDayRange,
    EventStatus,
    InvitationResponse,
    ManagedOrigin,
    Recurrence,
    TimedInterval,
)
from tests.helpers import NOW, event, rule


def observed(**changes: object) -> SourceObservation:
    details: dict[str, object] = {
        "guests": ("ana@example.com", "ben@example.com"),
        "conferencing": ("https://meet.example.com/abc",),
        **changes,
    }
    source = replace(event(), **details)  # type: ignore[arg-type]
    observation = SourceObservation.of(source)
    assert observation is not None
    return observation


def test_an_observation_keeps_the_tracked_details_of_a_confirmed_event() -> None:
    observation = observed(recurrence=Recurrence(("RRULE:FREQ=WEEKLY",)))

    assert observation.revision == "revision-1"
    assert observation.title == "Private appointment"
    assert observation.description == "Sensitive description"
    assert observation.location == "Sensitive location"
    assert observation.recurrence == ("RRULE:FREQ=WEEKLY",)
    assert observation.guests == ("ana@example.com", "ben@example.com")
    assert observation.conferencing == ("https://meet.example.com/abc",)


def test_cancelled_events_and_managed_projections_are_not_observed() -> None:
    cancelled = replace(event(), status=EventStatus.CANCELLED, time=None)
    managed = replace(event(), managed_origin=ManagedOrigin(rule().id, event().reference))

    assert SourceObservation.of(cancelled) is None
    assert SourceObservation.of(managed) is None


def test_guests_are_compared_as_a_set_of_addresses() -> None:
    reordered = SourceObservation.of(
        replace(event(), guests=("Ben@Example.com", "ana@example.com", "ben@example.com"))
    )

    assert reordered is not None
    assert reordered.guests == ("ana@example.com", "ben@example.com")
    assert SourceChange.between(observed(), replace(reordered, revision="revision-2")) is None


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"title": "Renamed"}, SourceField.TITLE),
        (
            {"time": TimedInterval(NOW + timedelta(hours=1), NOW + timedelta(hours=2))},
            SourceField.TIME,
        ),
        ({"time": AllDayRange(date(2026, 8, 30), date(2026, 8, 31))}, SourceField.TIME),
        ({"description": "New agenda"}, SourceField.DESCRIPTION),
        ({"location": "Room 2"}, SourceField.LOCATION),
        ({"guests": ("ana@example.com",)}, SourceField.GUESTS),
        ({"recurrence": Recurrence(("RRULE:FREQ=DAILY",))}, SourceField.RECURRENCE),
        ({"conferencing": ()}, SourceField.CONFERENCING),
        ({"response": InvitationResponse.TENTATIVE}, SourceField.RESPONSE),
    ],
)
def test_each_tracked_field_is_detected_on_its_own(
    changes: dict[str, object], field: SourceField
) -> None:
    change = SourceChange.between(observed(), observed(revision="revision-2", **changes))

    assert change is not None
    assert change.fields == (field,)


def test_a_new_revision_with_the_same_tracked_details_is_no_change() -> None:
    assert SourceChange.between(observed(), observed(revision="revision-2")) is None


def test_unknown_guests_or_conferencing_are_not_compared() -> None:
    partial = observed(revision="revision-2", guests=None, conferencing=None)

    assert SourceChange.between(observed(), partial) is None
    assert SourceChange.between(partial, observed(revision="revision-3")) is None


def test_a_timed_event_is_the_same_instant_in_any_offset() -> None:
    source = observed()
    assert isinstance(source.time, TimedInterval)
    shifted = TimedInterval(
        source.time.starts_at.astimezone(),
        source.time.ends_at.astimezone(),
    )

    assert SourceChange.between(source, replace(source, revision="r2", time=shifted)) is None


def test_changed_fields_follow_display_order() -> None:
    change = SourceChange.between(
        observed(), observed(revision="revision-2", location="Room 2", title="Renamed")
    )

    assert change is not None
    assert change.fields == (SourceField.TITLE, SourceField.LOCATION)
    assert change.before.title == "Private appointment"
    assert change.after.title == "Renamed"


def test_a_response_observed_before_responses_were_tracked_is_not_compared() -> None:
    earlier = replace(observed(), response=None)

    assert (
        SourceChange.between(
            earlier, observed(revision="revision-2", response=InvitationResponse.DECLINED)
        )
        is None
    )
