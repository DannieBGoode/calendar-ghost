from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from calendar_sync.domain.errors import DomainValidationError, InvalidStateTransition
from calendar_sync.domain.model import (
    AllDayRange,
    AllDaySyncPolicy,
    ConnectedAccountId,
    EventId,
    EventMapping,
    EventMappingId,
    EventRef,
    EventStatus,
    ManagedOrigin,
    OccurrenceIdentity,
    OccurrenceMapping,
    OccurrenceMappingId,
    OccurrenceState,
    ProjectionContent,
    ProjectionFingerprint,
    SyncRule,
    SyncRuleId,
    SyncRuleState,
    TimedInterval,
    TransformationPolicy,
    occurrence_start,
)
from tests.helpers import NOW, endpoint, occurrence, rule, series, week_start


def test_rule_can_cross_connected_accounts() -> None:
    cross_account = rule(state=SyncRuleState.DRAFT)

    assert (
        cross_account.source.connected_account_id != cross_account.destination.connected_account_id
    )


def test_rule_uses_the_accounts_of_its_source_and_destination() -> None:
    cross_account = rule()

    assert cross_account.uses_account(ConnectedAccountId("personal-account"))
    assert cross_account.uses_account(ConnectedAccountId("work-account"))
    assert not cross_account.uses_account(ConnectedAccountId("other-account"))


def test_rule_cannot_target_its_source_endpoint() -> None:
    same = endpoint("account", "calendar")

    with pytest.raises(DomainValidationError, match="cannot target its source"):
        SyncRule(id=rule().id, source=same, destination=same)


def test_rule_requires_preview_before_enablement() -> None:
    draft = rule(state=SyncRuleState.DRAFT)

    with pytest.raises(InvalidStateTransition):
        draft.enable()

    assert draft.mark_previewed().enable().state is SyncRuleState.ENABLED


def test_validated_rule_can_be_degraded_before_enablement() -> None:
    validated = rule(state=SyncRuleState.PREVIEWED)

    assert validated.degrade().state is SyncRuleState.DEGRADED

    with pytest.raises(InvalidStateTransition):
        rule(state=SyncRuleState.DRAFT).degrade()


def test_all_day_range_uses_exclusive_end_date() -> None:
    value = AllDayRange(date(2026, 8, 30), date(2026, 8, 31))

    assert value.ends_before == date(2026, 8, 31)

    with pytest.raises(DomainValidationError):
        AllDayRange(date(2026, 8, 30), date(2026, 8, 30))


DETAILS = TransformationPolicy(content=ProjectionContent.DETAILS)


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (SyncRuleState.DRAFT, SyncRuleState.DRAFT),
        (SyncRuleState.PREVIEWED, SyncRuleState.DRAFT),
        (SyncRuleState.ENABLED, SyncRuleState.PAUSED),
        (SyncRuleState.PAUSED, SyncRuleState.PAUSED),
        (SyncRuleState.DEGRADED, SyncRuleState.DEGRADED),
    ],
)
def test_material_policy_change_requires_a_new_preview(
    before: SyncRuleState, after: SyncRuleState
) -> None:
    changed = rule(state=before).change_policy(DETAILS)

    assert changed.state is after
    assert changed.transformation == DETAILS
    assert changed.reprojection_required is True


def test_unchanged_policy_is_not_a_material_change() -> None:
    enabled = rule(state=SyncRuleState.ENABLED)

    assert enabled.change_policy(enabled.transformation) == enabled


def test_policy_change_preserves_endpoints_and_lookback() -> None:
    original = rule(state=SyncRuleState.ENABLED)

    changed = original.change_policy(TransformationPolicy(all_day=AllDaySyncPolicy.EXCLUDE))

    assert changed.source == original.source
    assert changed.destination == original.destination
    assert changed.initial_lookback_days == original.initial_lookback_days


def test_rule_with_incomplete_removal_cannot_change_policy() -> None:
    with pytest.raises(InvalidStateTransition):
        rule(state=SyncRuleState.DISABLED).change_policy(DETAILS)


def test_changed_rule_cannot_be_enabled_until_previewed_again() -> None:
    changed = rule(state=SyncRuleState.ENABLED).change_policy(DETAILS)

    with pytest.raises(InvalidStateTransition):
        changed.enable()
    assert changed.mark_previewed().enable().state is SyncRuleState.ENABLED


def test_completed_reprojection_clears_the_flag() -> None:
    changed = rule().change_policy(DETAILS)

    assert changed.complete_reprojection().reprojection_required is False


@pytest.mark.parametrize("state", list(SyncRuleState))
def test_removal_can_begin_from_every_state_and_is_inert(state: SyncRuleState) -> None:
    removing = rule(state=state).begin_removal()

    assert removing.state is SyncRuleState.DISABLED
    with pytest.raises(InvalidStateTransition):
        removing.enable()
    with pytest.raises(InvalidStateTransition):
        removing.mark_previewed()


def test_occurrence_start_normalizes_offsets_to_one_utc_instant() -> None:
    madrid = datetime(2026, 9, 1, 10, 0, tzinfo=timezone(timedelta(hours=2)))
    utc = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)

    assert occurrence_start(madrid) == occurrence_start(utc)
    normalized = occurrence_start(madrid)
    assert isinstance(normalized, datetime)
    assert normalized.utcoffset() == timedelta(0)
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


def test_an_occurrence_reaches_the_window_through_its_original_slot_or_its_new_time() -> None:
    window = week_start(2)
    master = series()
    moved_out = occurrence(master, 3, moved_by=-timedelta(weeks=3))
    moved_in = occurrence(master, 1, moved_by=timedelta(weeks=3))
    stayed_before = occurrence(master, 1)
    cancelled_before = occurrence(master, 1, status=EventStatus.CANCELLED)

    assert moved_out.occurrence_reaches(window)
    assert moved_in.occurrence_reaches(window)
    assert not stayed_before.occurrence_reaches(window)
    assert not cancelled_before.occurrence_reaches(window)


def _mapping(rule_id: str = "rule-1", destination_calendar: str = "work-calendar") -> EventMapping:
    return EventMapping(
        EventMappingId("mapping-1"),
        SyncRuleId(rule_id),
        EventRef(rule().source, EventId("source-event")),
        EventRef(endpoint("work-account", destination_calendar), EventId("projection")),
        "revision-1",
        ProjectionFingerprint("fingerprint"),
    )


def test_mapping_belongs_to_the_rule_whose_destination_it_points_into() -> None:
    assert _mapping().belongs_to(rule())


@pytest.mark.parametrize(
    "mapping",
    [_mapping(rule_id="rule-2"), _mapping(destination_calendar="family-calendar")],
    ids=["another rule", "another destination calendar"],
)
def test_mapping_outside_the_directional_relationship_does_not_belong(
    mapping: EventMapping,
) -> None:
    assert not mapping.belongs_to(rule())


def test_managed_origin_owns_only_its_rule_and_source() -> None:
    source = EventRef(rule().source, EventId("source-event"))
    origin = ManagedOrigin(rule().id, source)

    assert origin.owns(rule(), source)
    assert not origin.owns(rule(), EventRef(rule().source, EventId("other-event")))
    assert not ManagedOrigin(SyncRuleId("rule-2"), source).owns(rule(), source)
