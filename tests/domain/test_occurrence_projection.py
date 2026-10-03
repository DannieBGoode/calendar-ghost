"""Which occurrences a rule projects, and which differ from their series, decided once."""

from dataclasses import replace
from datetime import timedelta, timezone

from calendar_sync.domain.model import (
    AllDaySyncPolicy,
    EventStatus,
    InvitationResponse,
    TimedInterval,
    TransformationPolicy,
)
from tests.helpers import occurrence, series


def test_a_policy_projects_a_live_occurrence_it_does_not_exclude() -> None:
    assert TransformationPolicy().projects(occurrence(series()))


def test_a_policy_never_projects_a_cancelled_occurrence() -> None:
    assert not TransformationPolicy().projects(occurrence(series(), status=EventStatus.CANCELLED))


def test_a_policy_does_not_project_an_occurrence_it_excludes() -> None:
    policy = TransformationPolicy(all_day=AllDaySyncPolicy.EXCLUDE)

    assert not policy.projects(occurrence(series(all_day=True), all_day=True))


def test_an_unchanged_occurrence_is_not_an_exception() -> None:
    master = series()

    assert not occurrence(master).is_exception_of(master)


def test_an_occurrence_reported_in_another_utc_offset_is_not_an_exception() -> None:
    master = series()
    plain = occurrence(master)
    assert isinstance(plain.time, TimedInterval)
    madrid = timezone(timedelta(hours=2))
    shifted = replace(
        plain,
        time=TimedInterval(
            plain.time.starts_at.astimezone(madrid), plain.time.ends_at.astimezone(madrid)
        ),
    )

    assert not shifted.is_exception_of(master)


def test_a_cancelled_occurrence_is_an_exception() -> None:
    master = series()

    assert occurrence(master, status=EventStatus.CANCELLED).is_exception_of(master)


def test_a_moved_occurrence_is_an_exception() -> None:
    master = series()

    assert occurrence(master, moved_by=timedelta(hours=2)).is_exception_of(master)


def test_a_lengthened_occurrence_is_an_exception() -> None:
    master = series()
    plain = occurrence(master)
    assert isinstance(plain.time, TimedInterval)
    longer = replace(
        plain,
        time=TimedInterval(plain.time.starts_at, plain.time.ends_at + timedelta(minutes=30)),
    )

    assert longer.is_exception_of(master)


def test_a_retitled_occurrence_is_an_exception() -> None:
    master = series()

    assert occurrence(master, title="Moved to the café").is_exception_of(master)


def test_an_occurrence_answered_differently_is_an_exception() -> None:
    master = series()
    declined = replace(occurrence(master), response=InvitationResponse.DECLINED)

    assert declined.is_exception_of(master)


def test_an_occurrence_switched_to_all_day_is_an_exception() -> None:
    master = series()

    assert occurrence(master, all_day=True).is_exception_of(master)


def test_only_an_occurrence_of_this_series_can_be_its_exception() -> None:
    master = series()
    elsewhere = occurrence(series("other-series"), status=EventStatus.CANCELLED)

    assert not elsewhere.is_exception_of(master)
    assert not master.is_exception_of(master)
