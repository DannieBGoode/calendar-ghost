"""How a rule treats the birthdays a provider keeps among a calendar's events (ADR 0035)."""

from __future__ import annotations

from dataclasses import replace

from calendar_sync.domain.model import (
    AllDaySyncPolicy,
    BirthdayPolicy,
    CalendarEvent,
    EventId,
    EventMapping,
    EventMappingId,
    EventRef,
    Exclusion,
    ManagedOrigin,
    SyncAction,
    SyncReason,
    SyncRule,
    TransformationPolicy,
)
from calendar_sync.domain.services import (
    EventProjector,
    ProjectionFingerprinter,
    SyncDecisionService,
)
from tests.domain.test_occurrence_decisions import SOURCE, busy_instance, decide
from tests.helpers import all_day_event, occurrence, rule

projector = EventProjector()
fingerprinter = ProjectionFingerprinter()
decisions = SyncDecisionService(projector, fingerprinter)


def _birthday(revision: str = "birthday-revision") -> CalendarEvent:
    return replace(all_day_event(), title="Ada's birthday", revision=revision, is_birthday=True)


def _rule(birthdays: BirthdayPolicy) -> SyncRule:
    return replace(rule(), transformation=TransformationPolicy(birthdays=birthdays))


def _projection_of(source: CalendarEvent) -> tuple[EventMapping, CalendarEvent]:
    """A mapping and its destination as a rule that syncs birthdays wrote `source`."""
    projection = projector.project(source, _rule(BirthdayPolicy.INCLUDE))
    destination = CalendarEvent(
        EventRef(rule().destination, EventId("destination-event")),
        projection.time,
        "destination-revision",
        title=projection.title,
        managed_origin=ManagedOrigin(rule().id, source.reference),
    )
    mapping = EventMapping(
        EventMappingId("mapping-1"),
        rule().id,
        source.reference,
        destination.reference,
        source.revision,
        fingerprinter.fingerprint(projection),
    )
    return mapping, destination


def test_new_rules_do_not_sync_birthdays() -> None:
    assert TransformationPolicy().birthdays is BirthdayPolicy.EXCLUDE
    assert TransformationPolicy().exclusion(_birthday()) is Exclusion.BIRTHDAY


def test_a_rule_that_syncs_birthdays_projects_them_like_other_events() -> None:
    policy = TransformationPolicy(birthdays=BirthdayPolicy.INCLUDE)

    assert policy.exclusion(_birthday()) is None
    assert policy.exclusion(all_day_event()) is None


def test_a_birthday_is_excluded_as_a_birthday_even_when_all_day_events_are() -> None:
    policy = TransformationPolicy(all_day=AllDaySyncPolicy.EXCLUDE)

    assert policy.exclusion(_birthday()) is Exclusion.BIRTHDAY


def test_a_birthday_is_never_created_and_its_projection_is_removed() -> None:
    mapping, destination = _projection_of(_birthday())
    skipping = _rule(BirthdayPolicy.EXCLUDE)

    unmapped = decisions.decide(skipping, _birthday(), None, None)
    mapped = decisions.decide(skipping, _birthday("birthday-revision-2"), mapping, destination)

    assert (unmapped.action, unmapped.reason) == (SyncAction.IGNORE, SyncReason.BIRTHDAY)
    assert (mapped.action, mapped.reason) == (SyncAction.DELETE, SyncReason.BIRTHDAY_REMOVED)


def test_an_occurrence_of_a_birthday_is_cancelled_in_the_destination() -> None:
    birthday = replace(occurrence(SOURCE, 1), is_birthday=True)

    decision = decide(birthday, busy_instance())

    assert (decision.action, decision.reason) == (SyncAction.DELETE, SyncReason.BIRTHDAY_REMOVED)
