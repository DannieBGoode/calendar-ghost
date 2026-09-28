from datetime import date

import pytest

from calendar_sync.domain.errors import DomainValidationError, InvalidStateTransition
from calendar_sync.domain.model import (
    AllDayRange,
    AllDaySyncPolicy,
    PrivacyPolicy,
    SyncRule,
    SyncRuleState,
    TransformationPolicy,
)
from tests.helpers import endpoint, rule


def test_rule_can_cross_connected_accounts() -> None:
    cross_account = rule(state=SyncRuleState.DRAFT)

    assert (
        cross_account.source.connected_account_id != cross_account.destination.connected_account_id
    )


def test_rule_cannot_target_its_source_endpoint() -> None:
    same = endpoint("account", "calendar")

    with pytest.raises(DomainValidationError, match="cannot target its source"):
        SyncRule(id=rule().id, source=same, destination=same)


def test_rule_requires_preview_before_enablement() -> None:
    draft = rule(state=SyncRuleState.DRAFT)

    with pytest.raises(InvalidStateTransition):
        draft.enable()

    assert draft.mark_dry_run_validated().enable().state is SyncRuleState.ENABLED


def test_validated_rule_can_be_degraded_before_enablement() -> None:
    validated = rule(state=SyncRuleState.DRY_RUN_VALIDATED)

    assert validated.degrade().state is SyncRuleState.DEGRADED

    with pytest.raises(InvalidStateTransition):
        rule(state=SyncRuleState.DRAFT).degrade()


def test_all_day_range_uses_exclusive_end_date() -> None:
    value = AllDayRange(date(2026, 8, 30), date(2026, 8, 31))

    assert value.ends_before == date(2026, 8, 31)

    with pytest.raises(DomainValidationError):
        AllDayRange(date(2026, 8, 30), date(2026, 8, 30))


DETAILS = TransformationPolicy(privacy=PrivacyPolicy.COPY_DETAILS)


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (SyncRuleState.DRAFT, SyncRuleState.DRAFT),
        (SyncRuleState.DRY_RUN_VALIDATED, SyncRuleState.DRAFT),
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
    assert changed.mark_dry_run_validated().enable().state is SyncRuleState.ENABLED


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
        removing.mark_dry_run_validated()
