"""Which rules take a place under their User's rule limit, and how each transition keeps a Rule
Replacement draft's place or gives it up (ADR 0038)."""

from collections.abc import Callable
from dataclasses import replace

import pytest

from calendar_sync.domain.errors import DomainValidationError, InvalidStateTransition
from calendar_sync.domain.model import (
    ProjectionContent,
    SyncRule,
    SyncRuleId,
    SyncRuleState,
    TransformationPolicy,
)
from calendar_sync.domain.plans import may_start
from tests.helpers import endpoint, rule

DRAFT = SyncRuleState.DRAFT
PREVIEWED = SyncRuleState.PREVIEWED
ENABLED = SyncRuleState.ENABLED
PAUSED = SyncRuleState.PAUSED
DEGRADED = SyncRuleState.DEGRADED
REMOVING = SyncRuleState.REMOVING
DETAILS = TransformationPolicy(content=ProjectionContent.DETAILS)
PLACE_STATES = (DRAFT, PREVIEWED)


def _rule(state: SyncRuleState, *, awaiting: bool = False, keeps: bool = False) -> SyncRule:
    return replace(rule(state=state), awaiting_reauthorization=awaiting, keeps_place=keeps)


def _successor(state: SyncRuleState = DRAFT) -> SyncRule:
    """The new rule Replace calendars makes: another id and another destination calendar."""
    return SyncRule(
        id=SyncRuleId("rule-2"),
        source=endpoint("personal-account", "personal-calendar"),
        destination=endpoint("work-account", "other-work-calendar"),
        state=state,
    )


SHAPES = [
    (state, awaiting, keeps)
    for state in SyncRuleState
    for awaiting in (False, True)
    for keeps in (False, True)
    if not keeps or state in PLACE_STATES
]


@pytest.mark.parametrize(("state", "awaiting", "keeps"), SHAPES)
def test_only_enabled_lapse_stopped_and_place_keeping_rules_count(
    state: SyncRuleState, awaiting: bool, keeps: bool
) -> None:
    shaped = _rule(state, awaiting=awaiting, keeps=keeps)
    holdable = state is ENABLED or (state is DEGRADED and awaiting)

    assert shaped.holdable is holdable
    assert shaped.counts_toward_plan is (holdable or keeps)


@pytest.mark.parametrize("state", PLACE_STATES)
def test_a_draft_or_previewed_rule_may_keep_a_place(state: SyncRuleState) -> None:
    assert _rule(state, keeps=True).keeps_place


@pytest.mark.parametrize("state", [state for state in SyncRuleState if state not in PLACE_STATES])
def test_no_other_rule_keeps_a_place(state: SyncRuleState) -> None:
    with pytest.raises(DomainValidationError, match="only a draft or previewed rule keeps a place"):
        _rule(state, keeps=True)


@pytest.mark.parametrize(
    ("before", "change", "state", "keeps"),
    [
        pytest.param(DRAFT, SyncRule.mark_previewed, PREVIEWED, True, id="preview a draft"),
        pytest.param(PREVIEWED, SyncRule.mark_previewed, PREVIEWED, True, id="preview again"),
        pytest.param(PREVIEWED, SyncRule.enable, ENABLED, False, id="enable"),
        pytest.param(PREVIEWED, SyncRule.degrade, DEGRADED, False, id="degrade"),
        pytest.param(
            PREVIEWED,
            lambda kept: kept.degrade(awaiting_reauthorization=True),
            DEGRADED,
            False,
            id="degrade by a lapse",
        ),
        pytest.param(DRAFT, SyncRule.require_preview, DRAFT, False, id="require preview"),
        pytest.param(DRAFT, SyncRule.begin_removal, REMOVING, False, id="remove a draft"),
        pytest.param(PREVIEWED, SyncRule.begin_removal, REMOVING, False, id="remove previewed"),
        pytest.param(
            DRAFT,
            lambda kept: kept.change_policy(DETAILS),
            DRAFT,
            True,
            id="change the policy of a draft",
        ),
        pytest.param(
            PREVIEWED,
            lambda kept: kept.change_policy(DETAILS),
            DRAFT,
            True,
            id="change the policy of a previewed rule",
        ),
        pytest.param(
            DRAFT,
            lambda kept: kept.change_policy(kept.transformation),
            DRAFT,
            True,
            id="save an unchanged policy",
        ),
        pytest.param(
            DRAFT,
            lambda kept: kept.change_policy(DETAILS).complete_reprojection(),
            DRAFT,
            True,
            id="complete the reprojection",
        ),
        pytest.param(
            DRAFT, SyncRule.on_account_disconnected, DRAFT, False, id="disconnect a draft"
        ),
        pytest.param(
            PREVIEWED,
            SyncRule.on_account_disconnected,
            DEGRADED,
            False,
            id="disconnect a previewed rule",
        ),
    ],
)
def test_each_transition_keeps_the_place_or_gives_it_up(
    before: SyncRuleState,
    change: Callable[[SyncRule], SyncRule],
    state: SyncRuleState,
    keeps: bool,
) -> None:
    after = change(_rule(before, keeps=True))

    assert (after.state, after.keeps_place) == (state, keeps)


@pytest.mark.parametrize(
    ("before", "change", "state"),
    [
        pytest.param(_rule(ENABLED), SyncRule.pause, PAUSED, id="pause an enabled rule"),
        pytest.param(_rule(DEGRADED), SyncRule.pause, PAUSED, id="pause a degraded rule"),
        pytest.param(
            _rule(DEGRADED, awaiting=True),
            SyncRule.resume_after_reauthorization,
            ENABLED,
            id="resume after reauthorization",
        ),
        pytest.param(_rule(ENABLED), SyncRule.degrade, DEGRADED, id="degrade an enabled rule"),
        pytest.param(
            _rule(ENABLED),
            lambda enabled: enabled.change_policy(DETAILS),
            PAUSED,
            id="change the policy of an enabled rule",
        ),
        pytest.param(
            _rule(DEGRADED, awaiting=True),
            SyncRule.on_account_disconnected,
            DEGRADED,
            id="disconnect a lapse-stopped rule",
        ),
        pytest.param(
            _rule(DRAFT), SyncRule.on_account_disconnected, DRAFT, id="disconnect a draft"
        ),
    ],
)
def test_a_rule_that_keeps_no_place_never_gains_one(
    before: SyncRule, change: Callable[[SyncRule], SyncRule], state: SyncRuleState
) -> None:
    after = change(before)

    assert (after.state, after.keeps_place) == (state, False)


@pytest.mark.parametrize(
    ("old", "keeps"),
    [
        pytest.param(_rule(ENABLED), True, id="enabled"),
        pytest.param(_rule(DEGRADED, awaiting=True), True, id="lapse-stopped"),
        pytest.param(_rule(DRAFT, keeps=True), True, id="a draft that keeps a place"),
        pytest.param(_rule(PAUSED), False, id="paused"),
        pytest.param(_rule(DEGRADED), False, id="plain degraded"),
        pytest.param(_rule(DRAFT), False, id="draft"),
        pytest.param(_rule(PREVIEWED), False, id="previewed"),
    ],
)
@pytest.mark.parametrize("successor_state", PLACE_STATES)
def test_a_replacement_keeps_the_place_of_a_rule_that_counted(
    old: SyncRule, keeps: bool, successor_state: SyncRuleState
) -> None:
    placed = _successor(successor_state).take_place_of(old)

    assert placed.keeps_place is keeps is old.counts_toward_plan
    assert placed.counts_toward_plan is keeps
    assert replace(placed, keeps_place=False) == _successor(successor_state)


@pytest.mark.parametrize("state", [ENABLED, PAUSED, DEGRADED, REMOVING])
def test_only_a_new_draft_takes_the_place_of_the_rule_it_replaces(state: SyncRuleState) -> None:
    with pytest.raises(InvalidStateTransition, match="only a new draft takes the place"):
        _successor(state).take_place_of(_rule(ENABLED))


def test_keeping_a_place_is_not_a_material_change() -> None:
    assert _rule(DRAFT, keeps=True).material_signature == _rule(DRAFT).material_signature


@pytest.mark.parametrize(
    ("before", "counting_after", "limit", "allowed"),
    [
        pytest.param(_rule(PREVIEWED), 50, None, True, id="no limit"),
        pytest.param(_rule(PREVIEWED, keeps=True), 4, 3, True, id="keeps a place over the limit"),
        pytest.param(_rule(PREVIEWED), 2, 3, True, id="within the limit"),
        pytest.param(_rule(PREVIEWED), 3, 3, True, id="equal to the limit"),
        pytest.param(_rule(PREVIEWED), 4, 3, False, id="over the limit"),
    ],
)
def test_a_start_fits_with_no_limit_with_a_kept_place_or_within_the_limit(
    before: SyncRule, counting_after: int, limit: int | None, allowed: bool
) -> None:
    assert may_start(before, counting_after, limit) is allowed
