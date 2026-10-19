"""Plans: the values an administrator saves, what each User may use now, and the limit checks."""

from collections.abc import Callable
from datetime import timedelta

import pytest

from calendar_sync.domain.cadence import DEFAULT_CADENCE, SyncCadence
from calendar_sync.domain.errors import DomainError, DomainValidationError
from calendar_sync.domain.plans import (
    NO_LIMITS,
    NO_LIMITS_PLAN,
    OFFERED_INTERVALS,
    PEOPLE_PER_ASSIGNMENT,
    UNLIMITED,
    Allowance,
    AllowanceBasis,
    AssignmentSource,
    InvalidAssignment,
    InvalidAssignmentReason,
    InvalidPlan,
    InvalidPlanReason,
    LimitedResource,
    NewPlan,
    OverLimit,
    Plan,
    PlanInUse,
    PlanIsDefault,
    PlanKey,
    PlanLimitReached,
    PlanLimits,
    PlanNameTaken,
    PlanReach,
    PlansNeedDefault,
    PlanUse,
    SyncInterval,
    UseCount,
    allowance_for,
    exceeds,
    has_room,
    needs_no_limits_plan,
    plan_key_from,
    plan_reach,
    require_assignable,
    require_removable,
    require_room,
    require_unique_name,
)

FREE = Plan(PlanKey("free"), "Free", PlanLimits(1, 1, 0, SyncInterval.EVERY_5_MINUTES))
FAMILY = Plan(PlanKey("family"), "Family", PlanLimits(5, 3, 2, SyncInterval.INSTANT))
HOURLY = Plan(PlanKey("hourly"), "Hourly", PlanLimits(1, 1, 0, SyncInterval.EVERY_60_MINUTES))


def polled_every(minutes: int) -> SyncCadence:
    """The cadence of an interval that polls every `minutes`, without Instant Sync."""
    return SyncCadence(instant=False, poll_every=timedelta(minutes=minutes))


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
    # Manual runs are limited exactly when a Plan limits the User, whether their own or the default.
    assert allowance.limits_manual_runs is (expected.plan is not None)


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
    assert not allowance.limits_manual_runs


@pytest.mark.parametrize(
    ("plan", "cadence"),
    [
        pytest.param(FREE, polled_every(5)),
        pytest.param(HOURLY, polled_every(60)),
        pytest.param(FAMILY, DEFAULT_CADENCE),
    ],
)
def test_an_allowance_has_its_plans_limits_and_cadence(plan: Plan, cadence: SyncCadence) -> None:
    allowance = allowance_for(plans_on=True, administers=False, own=plan, default=FREE)

    assert allowance.limits == plan.limits
    assert allowance.cadence == cadence


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
@pytest.mark.parametrize(
    "build",
    [
        pytest.param(lambda name: Plan(PlanKey("family"), name, FAMILY.limits), id="plan"),
        pytest.param(lambda name: NewPlan(name, FAMILY.limits), id="new plan"),
    ],
)
def test_any_other_plan_name_is_refused_with_its_reason(
    name: str, build: Callable[[str], object]
) -> None:
    with pytest.raises(InvalidPlan) as refused:
        build(name)

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
    ("interval", "minutes"),
    [
        (SyncInterval.EVERY_5_MINUTES, 5),
        (SyncInterval.EVERY_10_MINUTES, 10),
        (SyncInterval.EVERY_15_MINUTES, 15),
        (SyncInterval.EVERY_30_MINUTES, 30),
        (SyncInterval.EVERY_60_MINUTES, 60),
    ],
)
def test_each_interval_polls_every_its_own_minutes_without_instant_sync(
    interval: SyncInterval, minutes: int
) -> None:
    assert interval.cadence == polled_every(minutes)


def test_every_interval_is_offered_instant_first() -> None:
    assert OFFERED_INTERVALS == (
        SyncInterval.INSTANT,
        SyncInterval.EVERY_5_MINUTES,
        SyncInterval.EVERY_10_MINUTES,
        SyncInterval.EVERY_15_MINUTES,
        SyncInterval.EVERY_30_MINUTES,
        SyncInterval.EVERY_60_MINUTES,
    )


def test_assignments_come_from_an_administrator_or_billing() -> None:
    assert [source.value for source in AssignmentSource] == ["administrator", "billing"]


@pytest.mark.parametrize(
    ("enabled", "default", "chosen", "needed"),
    [
        pytest.param(True, None, None, True, id="turning on with no default"),
        pytest.param(True, FREE.key, None, False, id="turning on with a default named"),
        pytest.param(True, FREE.key, FAMILY.key, False, id="choosing another default"),
        pytest.param(True, FREE.key, FREE.key, False, id="keeping the default"),
        pytest.param(False, None, None, False, id="off with no default"),
        pytest.param(False, None, FREE.key, False, id="clearing the default while off"),
        pytest.param(False, FREE.key, None, False, id="choosing a default while off"),
    ],
)
def test_plans_turned_on_with_no_default_need_the_no_limits_plan(
    enabled: bool, default: PlanKey | None, chosen: PlanKey | None, needed: bool
) -> None:
    assert needs_no_limits_plan(enabled, default, chosen) is needed


def test_a_chosen_default_is_never_cleared_while_plans_are_on() -> None:
    with pytest.raises(PlansNeedDefault, match="plans cannot be on without a default plan"):
        needs_no_limits_plan(True, None, FREE.key)


def test_the_no_limits_plan_limits_nobody_and_syncs_instantly() -> None:
    # Its key is made from its name when it is stored.
    assert NO_LIMITS_PLAN.key is None
    assert NO_LIMITS_PLAN.keyed(()) == Plan(
        PlanKey("no-limits"), "No limits", PlanLimits(None, None, None, SyncInterval.INSTANT)
    )


# A new Plan's key


@pytest.mark.parametrize(
    ("name", "key"),
    [
        pytest.param("Free", "free", id="one word"),
        pytest.param("Family Plan", "family-plan", id="words"),
        pytest.param("Free + Family (2026)", "free-family-2026", id="other characters"),
        pytest.param("Família Grande", "familia-grande", id="accents"),
        pytest.param("FREE", "free", id="upper case"),
        pytest.param("x" * 40, "x" * 32, id="at most 32 characters"),
        pytest.param("a" * 31 + " b", "a" * 31, id="no hyphen at the end"),
        pytest.param("日本", "plan", id="no usable character"),
        pytest.param("!!!", "plan", id="punctuation only"),
    ],
)
def test_a_new_plans_key_is_made_from_its_name(name: str, key: str) -> None:
    assert plan_key_from(name, ()) == PlanKey(key)


@pytest.mark.parametrize(
    ("name", "taken", "key"),
    [
        pytest.param("Free", {"free"}, "free-2", id="taken"),
        pytest.param("Free", {"free", "free-2"}, "free-3", id="taken twice"),
        pytest.param("Free", {"free-2", "family"}, "free", id="others taken"),
        pytest.param("日本", {"plan"}, "plan-2", id="plan taken"),
        pytest.param("x" * 40, {"x" * 32}, "x" * 30 + "-2", id="at most 32 with the number"),
        pytest.param(
            "x" * 40,
            {"x" * 32, *(f"{'x' * 30}-{number}" for number in range(2, 10))},
            "x" * 29 + "-10",
            id="a longer number",
        ),
        pytest.param("a" * 30 + " b", {"a" * 30 + "-b"}, "a" * 30 + "-2", id="no double hyphen"),
    ],
)
def test_a_key_another_plan_has_gets_the_first_free_number(
    name: str, taken: set[str], key: str
) -> None:
    assert plan_key_from(name, taken) == PlanKey(key)


def test_a_new_plan_keeps_the_key_asked_for_or_gets_one_from_its_name() -> None:
    asked = NewPlan("Free", FREE.limits, PlanKey("starter"))
    made = NewPlan("Free", FREE.limits)

    assert asked.keyed({"free"}) == Plan(PlanKey("starter"), "Free", FREE.limits)
    assert made.keyed({"free"}) == Plan(PlanKey("free-2"), "Free", FREE.limits)


@pytest.mark.parametrize(
    ("name", "taken", "key"),
    [
        pytest.param("New", set(), "new-2", id="new"),
        pytest.param("NEW!", set(), "new-2", id="in any spelling"),
        pytest.param("New", {"new-2"}, "new-3", id="new-2 taken"),
        pytest.param("Newsletter", set(), "newsletter", id="only the whole key"),
        pytest.param("New plan", set(), "new-plan", id="a longer key"),
    ],
)
def test_no_key_made_from_a_name_is_new_which_names_the_new_plan_page(
    name: str, taken: set[str], key: str
) -> None:
    """The New plan panel's address is /people/plans/new, beside each Plan's own (ADR 0038)."""
    assert plan_key_from(name, taken) == PlanKey(key)


def test_a_new_plan_may_not_ask_for_the_key_new() -> None:
    with pytest.raises(InvalidPlan) as refused:
        NewPlan("Starter", FREE.limits, PlanKey("new"))

    assert refused.value.reason is InvalidPlanReason.KEY
    assert "reserved" in str(refused.value)
    # Any other key that starts with it may be asked for.
    assert NewPlan("Starter", FREE.limits, PlanKey("new-2")).key == PlanKey("new-2")


@pytest.mark.parametrize("people", [1, PEOPLE_PER_ASSIGNMENT])
def test_a_plan_is_given_to_one_to_a_hundred_people_at_once(people: int) -> None:
    assert refusal(lambda: require_assignable(people)) is None


@pytest.mark.parametrize(
    ("people", "reason"),
    [
        pytest.param(0, InvalidAssignmentReason.NO_PEOPLE, id="nobody"),
        pytest.param(101, InvalidAssignmentReason.TOO_MANY, id="more than a hundred"),
    ],
)
def test_a_plan_given_to_nobody_or_to_more_than_a_hundred_people_is_refused(
    people: int, reason: InvalidAssignmentReason
) -> None:
    refused = refusal(lambda: require_assignable(people))

    assert isinstance(refused, InvalidAssignment)
    assert refused.reason is reason
    assert not isinstance(refused, DomainValidationError)


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


FAMILY_USE = PlanUse(rules=6, connected_accounts=3, integration_tokens=1)


def test_a_use_is_over_each_limit_it_passes_rules_first() -> None:
    lowered = PlanLimits(4, 2, 0, SyncInterval.INSTANT)

    assert FAMILY_USE.over(lowered) == (
        OverLimit(LimitedResource.RULES, in_use=6, allowed=4),
        OverLimit(LimitedResource.CONNECTED_ACCOUNTS, in_use=3, allowed=2),
        OverLimit(LimitedResource.INTEGRATION_TOKENS, in_use=1, allowed=0),
    )


@pytest.mark.parametrize(
    "limits",
    [
        pytest.param(PlanLimits(6, 3, 1, SyncInterval.INSTANT), id="at every limit"),
        pytest.param(NO_LIMITS, id="no limits"),
    ],
)
def test_a_use_at_or_within_its_limits_is_over_none(limits: PlanLimits) -> None:
    assert FAMILY_USE.over(limits) == ()


def test_a_use_counts_each_resource_a_plan_limits() -> None:
    assert [FAMILY_USE.of(resource) for resource in LimitedResource] == [6, 3, 1]


def test_a_plans_reach_counts_who_is_over_and_how_many_have_each_count() -> None:
    uses = [
        PlanUse(rules=1, connected_accounts=2, integration_tokens=0),
        PlanUse(rules=1, connected_accounts=1, integration_tokens=0),
        PlanUse(rules=0, connected_accounts=2, integration_tokens=1),
        PlanUse(rules=0, connected_accounts=0, integration_tokens=0),
    ]

    reach = plan_reach(FREE.limits, uses)

    # Two have 2 calendar accounts where Free allows 1, and one of them also has a token.
    assert reach.over == 2
    assert reach.rules == (UseCount(in_use=1, people=2),)
    assert reach.connected_accounts == (UseCount(2, 2), UseCount(1, 1))
    assert reach.integration_tokens == (UseCount(1, 1),)


def test_a_plan_nobody_uses_reaches_nobody() -> None:
    assert plan_reach(FREE.limits, []) == PlanReach(over=0)
    assert plan_reach(NO_LIMITS, [FAMILY_USE]).over == 0


# Plan names


@pytest.mark.parametrize(
    "other",
    [
        pytest.param("Family", id="same"),
        pytest.param("family", id="lower case"),
        pytest.param("FAMILY", id="upper case"),
        pytest.param(" Family ", id="spaces around"),
        pytest.param("\uff46\uff41\uff4d\uff49\uff4c\uff59", id="full-width letters"),
    ],
)
def test_a_name_another_plan_reads_as_is_refused_with_that_plans_name(other: str) -> None:
    with pytest.raises(PlanNameTaken) as refused:
        require_unique_name("Family", [FREE.name, other])

    assert refused.value.name == other
    assert isinstance(refused.value, DomainError)
    assert not isinstance(refused.value, DomainValidationError)


@pytest.mark.parametrize("others", [[], ["Free", "Family 2", "Famly"]])
def test_a_name_no_other_plan_reads_as_may_be_saved(others: list[str]) -> None:
    assert refusal(lambda: require_unique_name("Family", others)) is None


@pytest.mark.parametrize(
    ("names", "name"),
    [
        pytest.param(["Free"], "No limits", id="free"),
        pytest.param(["no limits"], "No limits 2", id="taken"),
        pytest.param(["No limits", "No limits 2"], "No limits 3", id="taken twice"),
    ],
)
def test_the_no_limits_plan_is_named_apart_from_every_plan(names: list[str], name: str) -> None:
    assert NO_LIMITS_PLAN.named_apart(names) == NewPlan(name, NO_LIMITS)


def test_a_long_name_stays_within_sixty_characters_when_named_apart() -> None:
    long = NewPlan("x" * 60, NO_LIMITS)

    assert long.named_apart(["x" * 60]).name == "x" * 58 + " 2"


def test_a_reached_limit_is_a_domain_error_but_not_a_validation_error() -> None:
    reached = PlanLimitReached(LimitedResource.RULES, 3)

    assert isinstance(reached, DomainError)
    assert not isinstance(reached, DomainValidationError)
    assert not isinstance(reached, ValueError)
