"""How a rule treats the Source Calendar's Invitation Response (ADR 0018)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from calendar_sync.domain.model import (
    AllDaySyncPolicy,
    CalendarEvent,
    EventId,
    EventMapping,
    EventMappingId,
    EventRef,
    Exclusion,
    InvitationResponse,
    ManagedOrigin,
    ProjectionContent,
    SyncAction,
    SyncReason,
    SyncRule,
    TentativeEventPolicy,
    TransformationPolicy,
    UnansweredInvitationPolicy,
)
from calendar_sync.domain.services import (
    EventProjector,
    ProjectionFingerprinter,
    SyncDecisionService,
)
from tests.domain.test_occurrence_decisions import SOURCE, busy_instance, decide, recorded
from tests.helpers import all_day_event, event, occurrence, rule

projector = EventProjector()
fingerprinter = ProjectionFingerprinter()
decisions = SyncDecisionService(projector, fingerprinter)

ACCEPTED = InvitationResponse.ACCEPTED
TENTATIVE = InvitationResponse.TENTATIVE
DECLINED = InvitationResponse.DECLINED
AWAITING = InvitationResponse.AWAITING


def _rule(
    tentative: TentativeEventPolicy = TentativeEventPolicy.MARK,
    unanswered: UnansweredInvitationPolicy = UnansweredInvitationPolicy.AS_TENTATIVE,
    content: ProjectionContent = ProjectionContent.BUSY_ONLY,
) -> SyncRule:
    return replace(
        rule(),
        transformation=TransformationPolicy(
            content=content, tentative=tentative, unanswered=unanswered
        ),
    )


def _answered(response: InvitationResponse, revision: str = "revision-1") -> CalendarEvent:
    return replace(event(revision=revision), response=response)


def _projection_of(
    source: CalendarEvent, sync_rule: SyncRule
) -> tuple[EventMapping, CalendarEvent]:
    """A mapping and its destination exactly as `sync_rule` would have written `source`."""
    projection = projector.project(source, sync_rule)
    destination = CalendarEvent(
        EventRef(rule().destination, EventId("destination-event")),
        projection.time,
        "destination-revision",
        title=projection.title,
        description=projection.description,
        location=projection.location,
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


def test_new_rules_mark_maybe_events_and_treat_unanswered_invitations_as_maybe() -> None:
    policy = TransformationPolicy()

    assert policy.tentative is TentativeEventPolicy.MARK
    assert policy.unanswered is UnansweredInvitationPolicy.AS_TENTATIVE


@pytest.mark.parametrize(
    ("response", "tentative", "unanswered", "expected"),
    [
        (ACCEPTED, TentativeEventPolicy.SKIP, UnansweredInvitationPolicy.WAIT, None),
        (DECLINED, TentativeEventPolicy.SYNC, UnansweredInvitationPolicy.AS_TENTATIVE, "declined"),
        (TENTATIVE, TentativeEventPolicy.SYNC, UnansweredInvitationPolicy.WAIT, None),
        (TENTATIVE, TentativeEventPolicy.MARK, UnansweredInvitationPolicy.WAIT, None),
        (TENTATIVE, TentativeEventPolicy.SKIP, UnansweredInvitationPolicy.WAIT, "tentative"),
        (AWAITING, TentativeEventPolicy.SYNC, UnansweredInvitationPolicy.WAIT, "awaiting_response"),
        (AWAITING, TentativeEventPolicy.MARK, UnansweredInvitationPolicy.AS_TENTATIVE, None),
        (AWAITING, TentativeEventPolicy.SKIP, UnansweredInvitationPolicy.AS_TENTATIVE, "tentative"),
    ],
)
def test_exclusion_follows_the_response_and_the_rule(
    response: InvitationResponse,
    tentative: TentativeEventPolicy,
    unanswered: UnansweredInvitationPolicy,
    expected: str | None,
) -> None:
    policy = TransformationPolicy(tentative=tentative, unanswered=unanswered)

    exclusion = policy.exclusion(_answered(response))

    assert exclusion == (Exclusion(expected) if expected else None)


def test_an_excluded_all_day_event_reports_its_all_day_exclusion_first() -> None:
    policy = TransformationPolicy(all_day=AllDaySyncPolicy.EXCLUDE)

    assert policy.exclusion(replace(all_day_event(), response=DECLINED)) is Exclusion.ALL_DAY


@pytest.mark.parametrize(
    ("content", "response", "unanswered", "title"),
    [
        (
            ProjectionContent.BUSY_ONLY,
            TENTATIVE,
            UnansweredInvitationPolicy.WAIT,
            "Busy (tentative)",
        ),
        (
            ProjectionContent.DETAILS,
            TENTATIVE,
            UnansweredInvitationPolicy.WAIT,
            "Maybe: Private appointment",
        ),
        (
            ProjectionContent.BUSY_ONLY,
            AWAITING,
            UnansweredInvitationPolicy.AS_TENTATIVE,
            "Busy (tentative)",
        ),
        (ProjectionContent.BUSY_ONLY, ACCEPTED, UnansweredInvitationPolicy.WAIT, "Busy"),
        (
            ProjectionContent.DETAILS,
            ACCEPTED,
            UnansweredInvitationPolicy.WAIT,
            "Private appointment",
        ),
    ],
)
def test_marked_projections_say_they_are_tentative(
    content: ProjectionContent,
    response: InvitationResponse,
    unanswered: UnansweredInvitationPolicy,
    title: str,
) -> None:
    sync_rule = _rule(unanswered=unanswered, content=content)

    assert projector.project(_answered(response), sync_rule).title == title


def test_an_untitled_maybe_event_is_titled_maybe() -> None:
    untitled = replace(_answered(TENTATIVE), title="")
    details = _rule(content=ProjectionContent.DETAILS)

    assert projector.project(untitled, details).title == "Maybe"


def test_maybe_events_synced_like_accepted_ones_keep_their_title() -> None:
    sync_rule = _rule(TentativeEventPolicy.SYNC)

    assert projector.project(_answered(TENTATIVE), sync_rule).title == "Busy"


@pytest.mark.parametrize(
    ("response", "sync_rule", "skipped", "removed"),
    [
        (DECLINED, _rule(), SyncReason.DECLINED, SyncReason.DECLINED_REMOVED),
        (
            TENTATIVE,
            _rule(TentativeEventPolicy.SKIP),
            SyncReason.TENTATIVE_EXCLUDED,
            SyncReason.TENTATIVE_EXCLUDED_REMOVED,
        ),
        (
            AWAITING,
            _rule(unanswered=UnansweredInvitationPolicy.WAIT),
            SyncReason.AWAITING_RESPONSE,
            SyncReason.AWAITING_RESPONSE_REMOVED,
        ),
    ],
)
def test_excluded_responses_are_never_created_and_their_projections_are_removed(
    response: InvitationResponse,
    sync_rule: SyncRule,
    skipped: SyncReason,
    removed: SyncReason,
) -> None:
    accepted = _answered(ACCEPTED)
    mapping, destination = _projection_of(accepted, sync_rule)
    answered = _answered(response, revision="revision-2")

    unmapped = decisions.decide(sync_rule, answered, None, None)
    mapped = decisions.decide(sync_rule, answered, mapping, destination)

    assert (unmapped.action, unmapped.reason) == (SyncAction.IGNORE, skipped)
    assert (mapped.action, mapped.reason) == (SyncAction.DELETE, removed)


def test_answering_a_marked_maybe_event_yes_is_a_source_change() -> None:
    maybe = _answered(TENTATIVE)
    mapping, destination = _projection_of(maybe, _rule())

    decision = decisions.decide(_rule(), _answered(ACCEPTED, "revision-2"), mapping, destination)

    assert (decision.action, decision.reason) == (SyncAction.UPDATE, SyncReason.SOURCE_CHANGED)
    assert decision.projection is not None
    assert decision.projection.title == "Busy"


def test_a_maybe_answer_a_rule_syncs_unmarked_needs_no_write() -> None:
    syncing = _rule(TentativeEventPolicy.SYNC)
    mapping, destination = _projection_of(_answered(ACCEPTED), syncing)

    decision = decisions.decide(syncing, _answered(TENTATIVE, "revision-2"), mapping, destination)

    assert (decision.action, decision.reason) == (SyncAction.IGNORE, SyncReason.PROJECTION_CURRENT)


def test_reprojecting_under_a_changed_policy_is_not_reported_as_a_destination_edit() -> None:
    maybe = _answered(TENTATIVE)
    mapping, destination = _projection_of(maybe, _rule(TentativeEventPolicy.SYNC))
    reprojecting = replace(_rule(), reprojection_required=True)

    reprojected = decisions.decide(reprojecting, maybe, mapping, destination)
    edited = decisions.decide(
        reprojecting, maybe, mapping, replace(destination, title="Edited in destination")
    )
    not_reprojecting = decisions.decide(_rule(), maybe, mapping, destination)

    assert (reprojected.action, reprojected.reason) == (
        SyncAction.UPDATE,
        SyncReason.POLICY_APPLIED,
    )
    assert edited.reason is SyncReason.DESTINATION_DRIFT_REPAIRED
    assert not_reprojecting.reason is SyncReason.DESTINATION_DRIFT_REPAIRED


def test_declining_one_occurrence_cancels_it_in_the_destination() -> None:
    declined = replace(occurrence(SOURCE, 1), response=DECLINED)

    decision = decide(declined, busy_instance())

    assert (decision.action, decision.reason) == (SyncAction.DELETE, SyncReason.DECLINED_REMOVED)


def test_a_declined_occurrence_already_cancelled_needs_no_write() -> None:
    declined = replace(occurrence(SOURCE, 1), response=DECLINED)

    decision = decide(declined, None)

    assert decision.action is SyncAction.IGNORE


def test_answering_one_occurrence_maybe_marks_only_that_occurrence() -> None:
    maybe = replace(occurrence(SOURCE, 1), response=TENTATIVE)

    decision = decide(maybe, busy_instance(), occurrence_mapping=recorded())

    assert decision.action is SyncAction.UPDATE
    assert decision.projection is not None
    assert decision.projection.title == "Busy (tentative)"


def test_reprojecting_an_occurrence_as_last_written_applies_the_policy() -> None:
    maybe = replace(occurrence(SOURCE, 1), response=TENTATIVE)
    written = busy_instance()
    mapping = replace(
        recorded(),
        projection_fingerprint=fingerprinter.fingerprint(decisions.as_projection(written)),
    )
    reprojecting = replace(_rule(), reprojection_required=True)

    decision = decide(maybe, written, occurrence_mapping=mapping, sync_rule=reprojecting)

    assert (decision.action, decision.reason) == (SyncAction.UPDATE, SyncReason.POLICY_APPLIED)
