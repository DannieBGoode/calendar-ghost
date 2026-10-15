"""Plans: the values an administrator saves, what each User may use now, and the limit checks."""

from collections.abc import Callable

import pytest

from calendar_sync.domain.cadence import DEFAULT_CADENCE, SCHEDULED_EVERY, SyncCadence
from calendar_sync.domain.errors import DomainError, DomainValidationError
from calendar_sync.domain.plans import (
    NO_LIMITS,
    OFFERED_INTERVALS,
    UNLIMITED,
    Allowance,
    AllowanceBasis,
    AssignmentSource,
    InvalidPlan,
    InvalidPlanReason,
    LimitedResource,
    Plan,
    PlanInUse,
    PlanIsDefault,
    PlanKey,
    PlanLimitReached,
    PlanLimits,
    PlansNeedDefault,
    SyncInterval,
    allowance_for,
    exceeds,
    has_room,
    require_offered,
    require_plans_setting,
    require_removable,
    require_room,
)

FREE = Plan(PlanKey("free"), "Free", PlanLimits(1, 1, 0, SyncInterval.EVERY_5_MINUTES))
FAMILY = Plan(PlanKey("family"), "Family", PlanLimits(5, 3, 2, SyncInterval.INSTANT))
POLLED = SyncCadence(instant=False, poll_every=SCHEDULED_EVERY)


def refusal(check: Callable[[], None]) -> DomainError | None:
    """The error a check refuses with, or None when it lets the request through."""
    try:
        check()
    except DomainError as error:
        return error
    return None


@pytest.mark.parametrize(
    ("plans_on", "administers", "own", "default", "expected"),
    [
        pytest.param(False, False, None, FREE, Allowance(AllowanceBasis.PLANS_OFF), id="plans off"),
        pytest.param(
            False,
            False,
            FAMILY,
            FREE,
            Allowance(AllowanceBasis.PLANS_OFF, assigned=FAMILY),
            id="plans off keeps their own plan",
        ),
        pytest.param(
            False,
            True,
            FAMILY,
            FREE,
            Allowance(AllowanceBasis.PLANS_OFF, assigned=FAMILY),
            id="plans off comes before the role",
        ),
        pytest.param(
            True, True, None, FREE, Allowance(AllowanceBasis.ADMINISTRATOR), id="administrator"
        ),
        pytest.param(
            True,
            True,
            FAMILY,
            FREE,
            Allowance(AllowanceBasis.ADMINISTRATOR, assigned=FAMILY),
            id="administrator with a plan of their own",
        ),
        pytest.param(
            True,
            False,
            FAMILY,
            FREE,
            Allowance(AllowanceBasis.PLAN, plan=FAMILY, assigned=FAMILY),
            id="their own plan",
        ),
        pytest.param(
            True,
            False,
            None,
            FREE,
            Allowance(AllowanceBasis.PLAN, plan=FREE, on_default=True),
            id="the default plan",
        ),
        pytest.param(
            True,
            False,
            None,
            None,
            Allowance(AllowanceBasis.PLANS_OFF),
            id="plans on and no plan found",
        ),
    ],
)
def test_an_allowance_follows_the_setting_then_the_role_then_their_own_plan(
    plans_on: bool, administers: bool, own: Plan | None, default: Plan | None, expected: Allowance
) -> None:
    allowance = allowance_for(plans_on=plans_on, administers=administers, own=own, default=default)

    assert allowance == expected
    assert allowance.assigned == own


def test_a_user_no_plan_reaches_has_the_unlimited_allowance() -> None:
    assert allowance_for(plans_on=True, administers=False, own=None, default=None) == UNLIMITED
    assert Allowance(AllowanceBasis.PLANS_OFF) == UNLIMITED


@pytest.mark.parametrize(
    "allowance",
    [
        pytest.param(UNLIMITED, id="plans off"),
        pytest.param(Allowance(AllowanceBasis.PLANS_OFF, assigned=FREE), id="plans off assigned"),
        pytest.param(Allowance(AllowanceBasis.ADMINISTRATOR, assigned=FREE), id="administrator"),
        pytest.param(Allowance(AllowanceBasis.PLAN), id="plan basis with no plan"),
    ],
)
def test_only_a_plan_that_applies_limits_anything(allowance: Allowance) -> None:
    assert allowance.limits == NO_LIMITS
    assert allowance.cadence == DEFAULT_CADENCE


@pytest.mark.parametrize(
    ("plan", "cadence"), [pytest.param(FREE, POLLED), pytest.param(FAMILY, DEFAULT_CADENCE)]
)
def test_an_allowance_has_its_plans_limits_and_cadence(plan: Plan, cadence: SyncCadence) -> None:
    allowance = allowance_for(plans_on=True, administers=False, own=plan, default=FREE)

    assert allowance.limits == plan.limits
    assert allowance.cadence == cadence


@pytest.mark.parametrize("basis", list(AllowanceBasis))
def test_only_a_plan_basis_limits_manual_runs(basis: AllowanceBasis) -> None:
    allowance = Allowance(basis, plan=FREE if basis is AllowanceBasis.PLAN else None)

    assert allowance.limits_manual_runs is (basis is AllowanceBasis.PLAN)


@pytest.mark.parametrize("key", ["free", "a", "family-2", "0", "2026-plan", "a" * 32])
def test_a_plan_key_is_lower_case_letters_digits_and_hyphens(key: str) -> None:
    assert PlanKey(key).value == key


@pytest.mark.parametrize(
    "key",
    [
        pytest.param("", id="empty"),
        pytest.param(" ", id="a space"),
        pytest.param("Free", id="upper case"),
        pytest.param("UPPER", id="all upper case"),
        pytest.param("Bad", id="upper case first"),
        pytest.param("-free", id="leading hyphen"),
        pytest.param("Bad Key", id="space inside"),
        pytest.param("x y", id="space between"),
        pytest.param(" free", id="leading space"),
        pytest.param("free\n", id="trailing newline"),
        pytest.param("plan_1", id="underscore"),
        pytest.param("a" * 33, id="33 characters"),
        pytest.param("família", id="unicode letter"),
    ],
)
def test_any_other_plan_key_is_refused_with_its_reason(key: str) -> None:
    with pytest.raises(InvalidPlan) as refused:
        PlanKey(key)

    assert refused.value.reason is InvalidPlanReason.KEY


def test_an_invalid_plan_is_a_validation_error() -> None:
    refused = InvalidPlan(InvalidPlanReason.LIMIT, "a plan allows no such limit")

    assert isinstance(refused, DomainValidationError)
    assert (refused.reason, str(refused)) == (
        InvalidPlanReason.LIMIT,
        "a plan allows no such limit",
    )


@pytest.mark.parametrize("name", ["Free", "F", "Família", "Family (5 rules)", "x" * 60])
def test_a_plan_name_is_one_to_sixty_printable_characters(name: str) -> None:
    assert Plan(PlanKey("family"), name, FAMILY.limits).name == name


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("", id="empty"),
        pytest.param("   ", id="blank"),
        pytest.param(" Free", id="leading space"),
        pytest.param("Free ", id="trailing space"),
        pytest.param("Fr\nee", id="newline"),
        pytest.param("Free\tplan", id="tab"),
        pytest.param("Free\N{LINE SEPARATOR}plan", id="line separator"),
        pytest.param("Free\N{ZERO WIDTH SPACE}", id="format character"),
        pytest.param("x" * 61, id="61 characters"),
    ],
)
def test_any_other_plan_name_is_refused_with_its_reason(name: str) -> None:
    with pytest.raises(InvalidPlan) as refused:
        Plan(PlanKey("family"), name, FAMILY.limits)

    assert refused.value.reason is InvalidPlanReason.NAME


@pytest.mark.parametrize(
    ("rules", "accounts", "tokens"),
    [(1, 1, 0), (10_000, 10_000, 10_000), (None, None, None), (5, 3, 2)],
)
def test_plan_limits_are_whole_numbers_up_to_ten_thousand_or_unlimited(
    rules: int | None, accounts: int | None, tokens: int | None
) -> None:
    limits = PlanLimits(rules, accounts, tokens, SyncInterval.INSTANT)

    assert (limits.rules, limits.connected_accounts, limits.integration_tokens) == (
        rules,
        accounts,
        tokens,
    )


@pytest.mark.parametrize(
    ("rules", "accounts", "tokens"),
    [
        pytest.param(0, 1, 0, id="no rules"),
        pytest.param(-1, 1, 0, id="negative rules"),
        pytest.param(10_001, 1, 0, id="too many rules"),
        pytest.param(1, 0, 0, id="no calendar accounts"),
        pytest.param(1, 10_001, 0, id="too many calendar accounts"),
        pytest.param(1, 1, -1, id="negative tokens"),
        pytest.param(1, 1, 10_001, id="too many tokens"),
    ],
)
def test_plan_limits_out_of_range_are_refused_with_their_reason(
    rules: int | None, accounts: int | None, tokens: int | None
) -> None:
    with pytest.raises(InvalidPlan) as refused:
        PlanLimits(rules, accounts, tokens, SyncInterval.INSTANT)

    assert refused.value.reason is InvalidPlanReason.LIMIT


def test_every_sync_interval_keeps_the_value_it_is_stored_with() -> None:
    assert [interval.value for interval in SyncInterval] == [
        "instant",
        "5_minutes",
        "10_minutes",
        "15_minutes",
        "30_minutes",
        "60_minutes",
    ]


def test_instant_is_instant_sync_and_a_five_minute_poll() -> None:
    assert SyncInterval.INSTANT.cadence == DEFAULT_CADENCE


@pytest.mark.parametrize(
    "interval", [interval for interval in SyncInterval if interval is not SyncInterval.INSTANT]
)
def test_every_other_interval_polls_every_five_minutes_without_instant_sync(
    interval: SyncInterval,
) -> None:
    assert interval.cadence == POLLED


@pytest.mark.parametrize("interval", list(SyncInterval))
def test_no_interval_polls_more_often_than_scheduled_sync(interval: SyncInterval) -> None:
    assert interval.cadence.poll_every >= SCHEDULED_EVERY


def test_administrators_may_offer_instant_or_five_minutes() -> None:
    assert OFFERED_INTERVALS == (SyncInterval.INSTANT, SyncInterval.EVERY_5_MINUTES)


@pytest.mark.parametrize("interval", OFFERED_INTERVALS)
def test_an_offered_interval_may_be_saved(interval: SyncInterval) -> None:
    assert refusal(lambda: require_offered(interval)) is None


@pytest.mark.parametrize(
    "interval", [interval for interval in SyncInterval if interval not in OFFERED_INTERVALS]
)
def test_an_interval_not_offered_is_refused_with_its_reason(interval: SyncInterval) -> None:
    with pytest.raises(InvalidPlan) as refused:
        require_offered(interval)

    assert refused.value.reason is InvalidPlanReason.INTERVAL


def test_assignments_come_from_an_administrator_or_billing() -> None:
    assert [source.value for source in AssignmentSource] == ["administrator", "billing"]


def test_plans_turn_on_only_with_a_default_plan() -> None:
    with pytest.raises(PlansNeedDefault, match="choose a default plan"):
        require_plans_setting(True, None)

    assert refusal(lambda: require_plans_setting(True, FREE.key)) is None


@pytest.mark.parametrize("default", [None, FREE.key])
def test_plans_turn_off_whatever_the_default(default: PlanKey | None) -> None:
    assert refusal(lambda: require_plans_setting(False, default)) is None


def test_the_default_plan_is_refused_before_counting_who_has_it() -> None:
    with pytest.raises(PlanIsDefault, match="this is the default plan"):
        require_removable(FREE.key, FREE.key, people=3)


def test_a_plan_someone_has_cannot_be_removed() -> None:
    with pytest.raises(PlanInUse) as refused:
        require_removable(FAMILY.key, FREE.key, people=2)

    assert refused.value.people == 2
    assert str(refused.value) == "2 people have this plan; assign them another before removing it"


@pytest.mark.parametrize("default", [None, FREE.key])
def test_a_plan_nobody_has_that_is_not_the_default_may_be_removed(
    default: PlanKey | None,
) -> None:
    assert refusal(lambda: require_removable(FAMILY.key, default, people=0)) is None


@pytest.mark.parametrize(
    ("in_use", "limit", "room", "over"),
    [
        pytest.param(0, None, True, False, id="no limit"),
        pytest.param(10_000, None, True, False, id="no limit, many in use"),
        pytest.param(2, 3, True, False, id="below"),
        pytest.param(3, 3, False, False, id="equal"),
        pytest.param(4, 3, False, True, id="above"),
        pytest.param(0, 0, False, False, id="limit 0"),
        pytest.param(1, 0, False, True, id="above a limit of 0"),
    ],
)
def test_a_limit_has_room_below_it_and_is_exceeded_above_it(
    in_use: int, limit: int | None, room: bool, over: bool
) -> None:
    assert has_room(in_use, limit) is room
    assert exceeds(in_use, limit) is over


@pytest.mark.parametrize(("in_use", "limit"), [(0, None), (2, 3), (0, 1)])
def test_room_lets_one_more_in(in_use: int, limit: int | None) -> None:
    assert refusal(lambda: require_room(LimitedResource.RULES, in_use, limit)) is None


@pytest.mark.parametrize(
    ("resource", "in_use", "limit", "message"),
    [
        (LimitedResource.RULES, 3, 3, "the plan's limit of 3 rules is reached"),
        (
            LimitedResource.CONNECTED_ACCOUNTS,
            2,
            1,
            "the plan's limit of 1 calendar accounts is reached",
        ),
        (
            LimitedResource.INTEGRATION_TOKENS,
            0,
            0,
            "the plan's limit of 0 Integration Tokens is reached",
        ),
    ],
)
def test_no_room_refuses_with_the_resource_and_its_limit(
    resource: LimitedResource, in_use: int, limit: int, message: str
) -> None:
    with pytest.raises(PlanLimitReached) as refused:
        require_room(resource, in_use, limit)

    assert (refused.value.resource, refused.value.limit, str(refused.value)) == (
        resource,
        limit,
        message,
    )


def test_a_reached_limit_is_a_domain_error_but_not_a_validation_error() -> None:
    reached = PlanLimitReached(LimitedResource.RULES, 3)

    assert isinstance(reached, DomainError)
    assert not isinstance(reached, DomainValidationError)
    assert not isinstance(reached, ValueError)
