# Plans Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An Installation Administrator can define Plans, choose a Default Plan, turn Plans on, and
give each User a Plan; new rule Starts, Connected Accounts, and Integration Tokens then respect the
Plan's limits, and a Plan can keep Instant Sync for some Users, while a self-hosted installation with
Plans off behaves exactly as today.

**Architecture:** `domain/plans.py` holds the pure Plan values and `allowance_for`, which turns the
Plans setting, the User's role, and their own or the Default Plan into an `Allowance`. `identity`
owns the Plan catalog and assignment (`SqlitePlans`); `sync` reads an `Allowances` port it declares,
so it enforces limits without importing `identity`. Limits are checked inside the writing
transaction (write, then read the Allowance, then count), so they fail closed and race-free; every
other Plans read fails open. Rule Replacement now creates its draft in the transaction that begins
the old rule's removal, so the draft keeps the old rule's place.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLite (WAL), pytest; React, TypeScript, Vite,
Tailwind, shadcn-style components, Vitest; OpenAPI-generated web types.

**Spec:** `docs/superpowers/specs/2026-10-15-plans-design.md` (slice 1: "Plans core"). The
interface contract the tasks share was checked against the code at `950934d3`; every name below is
used verbatim across tasks.

## Global Constraints

- No em dashes (U+2014) anywhere: code, comments, docs, JSON catalogs, commit messages. `tests/test_no_em_dashes.py` and `catalog.test.ts` fail otherwise.
- Use `CONTEXT.md` terms: Plan, Default Plan, Allowance (never "entitlement"), Plan Hold, Directional Sync Rule, Rule Replacement, Connected Account, Disconnected Account, Reauthorization, Integration Token, Installation Administrator, Operator Overview, Sync Cadence. Never call a Plan by the avoided words CONTEXT lists for it; never "usage" for Resource Use.
- Coverage floor 80%: `.venv/bin/pytest --cov --cov-report=term-missing --cov-fail-under=80`.
- Ruff `max-args = 7`; `tests/test_architecture.py` fails on any application dataclass with behavior whose constructor takes more than 7 init fields, unless it is already in `WIDE_DATACLASSES` (only `RemoveSyncRule` is, among classes this slice touches). Never add to that set. Never add `noqa` for C901, PLR0912, PLR0913, PLR0915 in `src/`.
- Ruff `line-length = 100`; `ruff format --check .` also formats Python code blocks inside Markdown (`docs/`, ADRs, this plan): check the whole repo before pushing.
- `lint-imports` contracts unchanged: layers `bootstrap` > `interfaces | infrastructure` > `application` > `domain`; contexts `operations` > `identity` > `sync` > `shared`; `domain` and `application` never import sqlite3, fastapi, pydantic. Never add an `ignore_imports` entry.
- ESLint bounds for `web/src` (never `eslint-disable`): `complexity` 10, `max-depth` 4, `max-params` 4, `max-lines-per-function` 150, `max-lines` 500; features compose components, components render lib, lib imports neither; no literal UI text in `.tsx`.
- `pnpm run lint` runs with `--max-warnings 0`; `pnpm run knip` fails on unused files or exports; `pnpm run doctor` fails on any warning.
- All Web UI text lives in `web/src/i18n/locales/en/*.json` and renders through `t()`; every key is named by a source file or listed in `TEMPLATE_VALUES`; every number in a plural message is passed as `count`.
- API errors go through `interfaces/api/problems.py`; every code has an English `common.apiError.<code>` message.
- Call the API only through `api` in `web/src/lib/api.ts`.
- After changing a request or response model or a route: `.venv/bin/python scripts/export_openapi.py` then `cd web && pnpm run api:types`; commit `web/openapi.json` and `web/src/lib/api-schema.ts`; never edit them by hand.
- After any change under `web/`: `cd web && pnpm run build`, and commit the regenerated `src/calendar_sync/interfaces/api/static/` in the same commit. Do not commit a rebuild whose only change is the embedded commit SHA.
- New schema `Literal` aliases mirror their enums in `tests/adapters/test_schema_enums.py`; every new route is listed in `tests/adapters/test_api_authorization.py`.
- A route that names another User's record answers 404, never 403; administrator routes depend on `administrator`.
- SQLite connections only through `infrastructure/persistence/connections.py`; Plans writes run under `BEGIN IMMEDIATE`; never hold a write lock across a provider call.
- Limit checks fail closed; every other Plans read fails open and never stops syncing, sign-in, or the rules API.
- With Plans off (the default) nothing changes: every existing test keeps its expected behavior.
- Installation Administrators are never limited.
- Persistence port changes extend `tests/contracts/persistence.py`.
- Synthetic fixtures only.
- UI follows `DESIGN.md`: no modals, inline disclosure, one visible next step, the Quiet Indicator Rule, never color alone; reuse `web/src/components/ui/` and the app components.
- Commits end with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Review Focus

1. **Reauthorization at the limit.** Reauthorizing an existing account (same provider and email) at or over the account limit succeeds, never reads Plans, and resumes its lapse-stopped rules; a different or renamed address is a new account and is refused with `account_limit_reached`, storing nothing. Disconnected Accounts count, so disconnect A, connect B, reauthorize A cannot pass the limit. Pinned in Task 11.
2. **An administrator demoted while over the limit.** Nothing stops; the next Start, new account, and new token are refused; Reauthorization and existing tokens keep working; Your plan shows the over-limit line; an `installation:read` token request answers 403 before any limit. Promoting them again lifts every limit. Pinned in Tasks 8, 9, 11, 12.
3. **Plans toggled or lowered while a Start is in flight.** Either the Start sees the new limit or the Plan change waits for the Start's commit; never a Start admitted against a limit that was already lowered. A Rule Replacement in flight keeps its place either way. Two Starts, two connects, or two token issues for the last place: exactly one wins. Pinned in Tasks 8, 9, 10, 11.
4. **A malformed Plan key** in a path, the setting's default, or an assignment answers 404 `plan_not_found`; a malformed new key answers 422 `invalid_plan` with `reason=key`; nothing answers 500, and a stored key or interval a later release wrote never breaks sign-in or the rules API. Pinned in Tasks 1, 4, 13.
5. **A User on the Default Plan when the default changes** follows the new default at once with no per-User write; Users with their own Plan do not change; the default cannot be removed or cleared while Plans are on; a lower default refuses new Starts and stops nothing; return to setup turns Plans off. Pinned in Tasks 4, 7, 13.

---


## Part 1: Domain (Tasks 1 and 2)

These two tasks add the pure domain of Plans: the values an administrator saves, the Allowance
that says what one User may use now, the limit checks, and the place a Rule Replacement draft
keeps under its User's rule limit. Nothing reads them yet, so no behavior changes and every
existing test keeps passing. Task numbers follow `.context/plans-slice1-contract.md` section 5.

Before you start: read `CONTEXT.md` (Plan, Rule Replacement, Lapsed Authorization) and
`AGENTS.md`. Run every command from the repository root. Never use an em dash in code, comments,
or commit messages. `.venv/bin/pytest` already adds `-q` through `pyproject.toml`; the commands
below leave it out so the summary line (`N passed`) shows.

---

### Task 1: Plan values and policies

**Files:**
- Create: `src/calendar_sync/domain/plans.py`
- Modify: `src/calendar_sync/domain/access.py` (the import block; class `User` gains the trailing field `plan`)
- Create: `tests/domain/test_plans.py`
- Modify: `tests/domain/test_access.py` (the import block; one new test after `test_a_user_who_adds_an_email_keeps_everything_else`)
- Test: `tests/domain/test_plans.py`, `tests/domain/test_access.py`

**Interfaces:**
- Consumes:
  - `calendar_sync.domain.cadence`: `SyncCadence(instant: bool, poll_every: timedelta)`, `DEFAULT_CADENCE` (instant, polls every 5 minutes), `SCHEDULED_EVERY = timedelta(minutes=5)`.
  - `calendar_sync.domain.errors`: `DomainError`, `DomainValidationError` (a `DomainError` and a `ValueError`).
- Produces (all in `calendar_sync.domain.plans` unless noted):
  - Constants: `PLAN_KEY_LIMIT = 32`, `PLAN_NAME_LIMIT = 60`, `COUNT_LIMIT = 10_000`.
  - `class InvalidPlanReason(StrEnum)`: `KEY = "key"`, `NAME = "name"`, `LIMIT = "limit"`, `INTERVAL = "interval"`.
  - `class InvalidPlan(DomainValidationError)`: `__init__(self, reason: InvalidPlanReason, message: str)`; attribute `reason`.
  - `@dataclass(frozen=True, slots=True) class PlanKey`: `value: str`; raises `InvalidPlan(KEY, ...)` unless it fully matches `[a-z0-9][a-z0-9-]{0,31}`.
  - `class SyncInterval(StrEnum)`: `INSTANT = "instant"`, `EVERY_5_MINUTES = "5_minutes"`, `EVERY_10_MINUTES = "10_minutes"`, `EVERY_15_MINUTES = "15_minutes"`, `EVERY_30_MINUTES = "30_minutes"`, `EVERY_60_MINUTES = "60_minutes"`; property `cadence -> SyncCadence` (`INSTANT` is `DEFAULT_CADENCE`; every other value is `SyncCadence(instant=False, poll_every=SCHEDULED_EVERY)` in slice 1).
  - `OFFERED_INTERVALS: tuple[SyncInterval, ...] = (SyncInterval.INSTANT, SyncInterval.EVERY_5_MINUTES)`.
  - `class LimitedResource(StrEnum)`: `RULES = "rules"`, `CONNECTED_ACCOUNTS = "connected_accounts"`, `INTEGRATION_TOKENS = "integration_tokens"`.
  - `@dataclass(frozen=True, slots=True) class PlanLimits`: `rules: int | None`, `connected_accounts: int | None`, `integration_tokens: int | None`, `sync_interval: SyncInterval`; raises `InvalidPlan(LIMIT, ...)` unless rules and accounts are `None` or 1 to 10000 and tokens are `None` or 0 to 10000.
  - `NO_LIMITS = PlanLimits(None, None, None, SyncInterval.INSTANT)`.
  - `@dataclass(frozen=True, slots=True) class Plan`: `key: PlanKey`, `name: str`, `limits: PlanLimits`; raises `InvalidPlan(NAME, ...)` unless the name is 1 to 60 characters, equals `name.strip()`, and has no character in a Unicode category starting with `C`, `Zl`, or `Zp`.
  - `class AssignmentSource(StrEnum)`: `ADMINISTRATOR = "administrator"`, `BILLING = "billing"`.
  - `class AllowanceBasis(StrEnum)`: `PLANS_OFF = "plans_off"`, `ADMINISTRATOR = "administrator"`, `PLAN = "plan"`.
  - `@dataclass(frozen=True, slots=True) class Allowance`: `basis: AllowanceBasis`, `plan: Plan | None = None`, `on_default: bool = False`, `assigned: Plan | None = None`; properties `limits -> PlanLimits`, `cadence -> SyncCadence`, `limits_manual_runs -> bool`. No invariant in `__post_init__`.
  - `UNLIMITED = Allowance(AllowanceBasis.PLANS_OFF)`.
  - `def allowance_for(*, plans_on: bool, administers: bool, own: Plan | None, default: Plan | None) -> Allowance`.
  - Errors: `class PlansNeedDefault(DomainError)`, `class PlanIsDefault(DomainError)` (plain message constructors, raised with a message by the policies), `class PlanInUse(DomainError)` with `__init__(self, people: int)` and attribute `people`, `class PlanLimitReached(DomainError)` with `__init__(self, resource: LimitedResource, limit: int)` and attributes `resource`, `limit`.
  - Policies: `require_plans_setting(enabled: bool, default: PlanKey | None) -> None`, `require_removable(key: PlanKey, default: PlanKey | None, people: int) -> None`, `require_offered(interval: SyncInterval) -> None`, `has_room(in_use: int, limit: int | None) -> bool`, `exceeds(in_use: int, limit: int | None) -> bool`, `require_room(resource: LimitedResource, in_use: int, limit: int | None) -> None`.
  - `calendar_sync.domain.access.User.plan: PlanKey | None = None` (trailing field, after `instant_sync`).

- [ ] **Step 1: Write the failing test**

Create `tests/domain/test_plans.py` with exactly this content. The malformed keys `"Bad Key"`, `" "`, `"UPPER"`, `"x y"`, and `"Bad"` are the ones Review Focus 4 names; every one must be refused as `InvalidPlan` with reason `key`, never anything that could become a 500.

```python
"""Plans: the values an administrator saves, what each User may use now, and the limit checks."""

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


def test_no_limits_means_no_count_is_limited_and_calendars_sync_instantly() -> None:
    assert PlanLimits(None, None, None, SyncInterval.INSTANT) == NO_LIMITS


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
    require_offered(interval)


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

    require_plans_setting(True, FREE.key)


@pytest.mark.parametrize("default", [None, FREE.key])
def test_plans_turn_off_whatever_the_default(default: PlanKey | None) -> None:
    require_plans_setting(False, default)


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
    require_removable(FAMILY.key, default, people=0)


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
    require_room(LimitedResource.RULES, in_use, limit)


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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/domain/test_plans.py`

Expected: collection fails with
`E   ModuleNotFoundError: No module named 'calendar_sync.domain.plans'`
and `Interrupted: 1 error during collection`.

- [ ] **Step 3: Implement `domain/plans.py`**

Create `src/calendar_sync/domain/plans.py` with exactly this content. It imports only the standard library, `domain/cadence.py`, and `domain/errors.py`. It must never import `domain/access.py` or `domain/model.py` at runtime: `access.py` imports `PlanKey` from here (Step 7), and Task 2 adds a type-only import of `SyncRule`.

```python
"""Plans: named limits an Installation Administrator defines and assigns (ADR 0028, ADR 0038).

An Allowance is what one User may use now. Plans are off by default, and then nothing limits
anyone; Installation Administrators are never limited. Everything here is a value or a pure
decision: the stores that keep Plans and the use cases that check limits call it.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum

from calendar_sync.domain.cadence import DEFAULT_CADENCE, SCHEDULED_EVERY, SyncCadence
from calendar_sync.domain.errors import DomainError, DomainValidationError

PLAN_KEY_LIMIT = 32
"""The longest Plan key."""
PLAN_NAME_LIMIT = 60
"""The longest Plan name."""
COUNT_LIMIT = 10_000
"""The largest number any limit of a Plan may be."""
# 1 to 32 lower-case letters, digits, and hyphens, starting with a letter or digit.
_PLAN_KEY = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
# Control and format characters, and the line and paragraph separators that break a line, refused
# as an Integration Token's name refuses them.
_REFUSED_CATEGORIES = ("C", "Zl", "Zp")


class InvalidPlanReason(StrEnum):
    """Which part of a Plan cannot be saved, so the Web UI can say how to fix it."""

    KEY = "key"
    NAME = "name"
    LIMIT = "limit"
    INTERVAL = "interval"


class InvalidPlan(DomainValidationError):
    """A Plan's key, name, limits, or sync interval cannot be saved."""

    def __init__(self, reason: InvalidPlanReason, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class PlanKey:
    """A Plan's stable key: chosen when the Plan is defined and never renamed, so billing can
    name it later."""

    value: str

    def __post_init__(self) -> None:
        if _PLAN_KEY.fullmatch(self.value) is None:
            raise InvalidPlan(
                InvalidPlanReason.KEY,
                "a plan key is 1 to 32 lower-case letters, digits, and hyphens, "
                "starting with a letter or digit",
            )


# Until the scheduler lists each rule once per window of its interval, it lists every enabled
# rule at every pass, so every interval but instant polls every five minutes.
_POLLED = SyncCadence(instant=False, poll_every=SCHEDULED_EVERY)


class SyncInterval(StrEnum):
    """How soon a Plan's rules sync. Every value is known now, so a Plan saved by a release that
    offers more intervals still reads after a rollback."""

    INSTANT = "instant"
    EVERY_5_MINUTES = "5_minutes"
    EVERY_10_MINUTES = "10_minutes"
    EVERY_15_MINUTES = "15_minutes"
    EVERY_30_MINUTES = "30_minutes"
    EVERY_60_MINUTES = "60_minutes"

    @property
    def cadence(self) -> SyncCadence:
        """Instant is Instant Sync plus a 5-minute poll; every other interval is a poll alone."""
        if self is SyncInterval.INSTANT:
            return DEFAULT_CADENCE
        return _POLLED


OFFERED_INTERVALS: tuple[SyncInterval, ...] = (SyncInterval.INSTANT, SyncInterval.EVERY_5_MINUTES)
"""The sync intervals an administrator may choose for a Plan, in the order they are offered."""


class LimitedResource(StrEnum):
    """What a Plan limits by count."""

    RULES = "rules"
    CONNECTED_ACCOUNTS = "connected_accounts"
    INTEGRATION_TOKENS = "integration_tokens"


_NOUNS = {
    LimitedResource.RULES: "rules",
    LimitedResource.CONNECTED_ACCOUNTS: "calendar accounts",
    LimitedResource.INTEGRATION_TOKENS: "Integration Tokens",
}


@dataclass(frozen=True, slots=True)
class PlanLimits:
    """How much a Plan lets each of its Users have; None is unlimited."""

    rules: int | None
    """Rules that count: enabled, stopped only by Lapsed Authorization, or keeping a place."""
    connected_accounts: int | None
    """Every Connected Account, Disconnected Accounts included."""
    integration_tokens: int | None
    """Unrevoked Integration Tokens; 0 offers none."""
    sync_interval: SyncInterval

    def __post_init__(self) -> None:
        if not (
            _within(self.rules, lowest=1)
            and _within(self.connected_accounts, lowest=1)
            and _within(self.integration_tokens, lowest=0)
        ):
            raise InvalidPlan(
                InvalidPlanReason.LIMIT,
                "a plan allows 1 to 10000 rules and calendar accounts, 0 to 10000 "
                "Integration Tokens, or no limit",
            )


def _within(limit: int | None, *, lowest: int) -> bool:
    return limit is None or lowest <= limit <= COUNT_LIMIT


NO_LIMITS = PlanLimits(None, None, None, SyncInterval.INSTANT)
"""What a User may use while no Plan limits them: everything, synced instantly."""


@dataclass(frozen=True, slots=True)
class Plan:
    """A named set of limits an Installation Administrator defines and assigns to Users."""

    key: PlanKey
    name: str
    """What people read: 1 to 60 printable characters, with no space around them. It can change."""
    limits: PlanLimits

    def __post_init__(self) -> None:
        if not _printable(self.name):
            raise InvalidPlan(InvalidPlanReason.NAME, "a plan name is 1 to 60 printable characters")


def _printable(name: str) -> bool:
    return (
        1 <= len(name) <= PLAN_NAME_LIMIT
        and name == name.strip()
        and not any(
            unicodedata.category(character).startswith(_REFUSED_CATEGORIES) for character in name
        )
    )


class AssignmentSource(StrEnum):
    """Who set a User's own Plan: an administrator now, billing later."""

    ADMINISTRATOR = "administrator"
    BILLING = "billing"


class AllowanceBasis(StrEnum):
    """Why a User's Allowance is what it is."""

    PLANS_OFF = "plans_off"
    ADMINISTRATOR = "administrator"
    PLAN = "plan"


@dataclass(frozen=True, slots=True)
class Allowance:
    """What one User may use now: their Plan's limits, or none."""

    basis: AllowanceBasis
    plan: Plan | None = None
    """The Plan that limits them; set only when the basis is `plan`."""
    on_default: bool = False
    """Whether that Plan is the Default Plan rather than their own."""
    assigned: Plan | None = None
    """Their own stored Plan, whatever the basis, so an administrator sees a Plan that does not
    apply yet."""

    @property
    def limits(self) -> PlanLimits:
        if self.basis is AllowanceBasis.PLAN and self.plan is not None:
            return self.plan.limits
        return NO_LIMITS

    @property
    def cadence(self) -> SyncCadence:
        """How soon their rules sync, as their Plan's interval says."""
        return self.limits.sync_interval.cadence

    @property
    def limits_manual_runs(self) -> bool:
        """Whether the manual-run limit applies to them: only when a Plan limits them."""
        return self.basis is AllowanceBasis.PLAN


UNLIMITED = Allowance(AllowanceBasis.PLANS_OFF)
"""The Allowance of every User while Plans are off, and of a User no store finds."""


def allowance_for(
    *, plans_on: bool, administers: bool, own: Plan | None, default: Plan | None
) -> Allowance:
    """What a User may use now: nothing limits anyone while Plans are off, nothing limits an
    Installation Administrator, and everyone else has their own Plan or the Default Plan.

    Plans cannot be on without a Default Plan. Should one still be missing, nothing limits the
    User: a fault in Plans must never limit anything.
    """
    if not plans_on:
        return Allowance(AllowanceBasis.PLANS_OFF, assigned=own)
    if administers:
        return Allowance(AllowanceBasis.ADMINISTRATOR, assigned=own)
    if own is not None:
        return Allowance(AllowanceBasis.PLAN, plan=own, assigned=own)
    if default is not None:
        return Allowance(AllowanceBasis.PLAN, plan=default, on_default=True)
    return UNLIMITED


class PlansNeedDefault(DomainError):
    """Plans turn on only once a Default Plan exists, so every User has a Plan."""


class PlanIsDefault(DomainError):
    """The Default Plan cannot be removed until another Plan is the default."""


class PlanInUse(DomainError):
    """A Plan that someone has cannot be removed until they have another."""

    def __init__(self, people: int) -> None:
        super().__init__(f"{people} people have this plan; assign them another before removing it")
        self.people = people


class PlanLimitReached(DomainError):
    """One more of a resource would pass the limit of the User's Plan (ADR 0038).

    Not a validation error, so no route answers 422 for it by accident: each route that can meet
    it catches it by name.
    """

    def __init__(self, resource: LimitedResource, limit: int) -> None:
        super().__init__(f"the plan's limit of {limit} {_NOUNS[resource]} is reached")
        self.resource = resource
        self.limit = limit


def require_plans_setting(enabled: bool, default: PlanKey | None) -> None:
    """Refuse turning Plans on without a Default Plan; turning them off is always allowed."""
    if enabled and default is None:
        raise PlansNeedDefault("choose a default plan before turning plans on")


def require_removable(key: PlanKey, default: PlanKey | None, people: int) -> None:
    """Refuse removing the Default Plan, and then a Plan that `people` Users have."""
    if key == default:
        raise PlanIsDefault("this is the default plan; choose another default before removing it")
    if people > 0:
        raise PlanInUse(people)


def require_offered(interval: SyncInterval) -> None:
    """Refuse saving a sync interval this release does not offer."""
    if interval not in OFFERED_INTERVALS:
        raise InvalidPlan(InvalidPlanReason.INTERVAL, "choose one of the offered sync intervals")


def has_room(in_use: int, limit: int | None) -> bool:
    """Whether one more fits: there is no limit, or fewer than the limit are in use."""
    return limit is None or in_use < limit


def exceeds(in_use: int, limit: int | None) -> bool:
    """Whether more are in use than the limit allows, as after a limit is lowered."""
    return limit is not None and in_use > limit


def require_room(resource: LimitedResource, in_use: int, limit: int | None) -> None:
    """Refuse one more of `resource` when `in_use` already reaches the limit."""
    if limit is not None and not has_room(in_use, limit):
        raise PlanLimitReached(resource, limit)
```

Notes for the implementer:
- `_REFUSED_CATEGORIES` repeats the tuple in `application/identity/integration_tokens.py` on purpose: the domain cannot import the application layer.
- `PlansNeedDefault` and `PlanIsDefault` keep `Exception`'s constructor, so `PlansNeedDefault("...")` and `PlansNeedDefault()` both work; the policies always pass the message.
- `allowance_for` returns `UNLIMITED` in the row that cannot happen (Plans on and no Plan found). The adapter in Task 4 logs that case itself.

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/domain/test_plans.py`

Expected: `106 passed`.

- [ ] **Step 5: Write the failing test for `User.plan`**

In `tests/domain/test_access.py`, add the `PlanKey` import after the existing `calendar_sync.domain.access` import block, so the top of the file reads:

```python
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from calendar_sync.domain.access import (
    InvalidEmail,
    LastAdministrator,
    OnlyMeNeedsOneUser,
    RegistrationPolicy,
    Role,
    User,
    UserId,
    UserState,
    email_address,
    link_expiry,
    require_administrator_remains,
    require_registration_change,
)
from calendar_sync.domain.plans import PlanKey

CREATED = datetime(2026, 10, 1, tzinfo=UTC)
```

Then add this test right after `test_a_user_who_adds_an_email_keeps_everything_else` (shown unchanged for context):

```python
def test_a_user_who_adds_an_email_keeps_everything_else() -> None:
    added = _user(email=None).with_email("person@example.test")

    assert added == _user()


def test_a_user_has_the_default_plan_until_one_of_their_own_is_assigned() -> None:
    assert _user().plan is None
    assert replace(_user(), plan=PlanKey("family")).plan == PlanKey("family")
```

- [ ] **Step 6: Run it to verify it fails**

Run: `.venv/bin/pytest tests/domain/test_access.py`

Expected: `1 failed, 27 passed`, the failure being
`E       AttributeError: 'User' object has no attribute 'plan'`.

- [ ] **Step 7: Implement `User.plan`**

In `src/calendar_sync/domain/access.py`, import `PlanKey` after the `errors` import, so the import block reads:

```python
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum

from calendar_sync.domain.errors import DomainValidationError
from calendar_sync.domain.plans import PlanKey
```

Then give `User` a trailing `plan` field after `instant_sync`. The whole class now reads:

```python
@dataclass(frozen=True, slots=True)
class User:
    """A person who signs in to the installation; what they own, no other User sees."""

    id: UserId
    email: str | None
    """None only for the first User of an upgraded installation, until they add one."""
    role: Role
    state: UserState
    created_at: datetime
    last_sign_in_at: datetime | None = None
    language: str | None = None
    notify_by_email: bool = True
    """Whether their Incident Notifications are also emailed when the installation sends email."""
    instant_sync: bool = True
    """Whether their rules run soon after a change is reported, where their Plan and the
    installation allow it."""
    plan: PlanKey | None = None
    """Their own Plan; None means the Default Plan (ADR 0038)."""

    @property
    def needs_email(self) -> bool:
        return self.email is None

    @property
    def administers(self) -> bool:
        """Whether they hold the Installation Administrator role."""
        return self.role is Role.INSTALLATION_ADMINISTRATOR

    def with_email(self, email: str) -> User:
        return replace(self, email=email_address(email))
```

The field is last and has a default, so every existing `User(...)` call (`sign_in.py`, `persistence/users.py`, the test helpers) keeps working unchanged. `SqliteUserDirectory` starts reading it in Task 3.

- [ ] **Step 8: Run the tests and the backend gates**

Run each command:

```sh
.venv/bin/pytest tests/domain/test_plans.py tests/domain/test_access.py
.venv/bin/pytest tests/domain
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy
.venv/bin/lint-imports
.venv/bin/pytest
```

Expected, in order: `134 passed`; `456 passed`; `... files already formatted`; `All checks passed!`; `Success: no issues found in ... source files`; `Contracts: 10 kept, 0 broken.`; the whole suite passes (nothing reads Plans yet, so no existing test changes).

If `ruff format --check .` reports a file, run `.venv/bin/ruff format <file>` on it and rerun; never hand-format around Ruff.

- [ ] **Step 9: Commit**

```sh
git add src/calendar_sync/domain/plans.py src/calendar_sync/domain/access.py tests/domain/test_plans.py tests/domain/test_access.py
git commit -F - <<'EOF'
Define Plans, their limits, and what each User may use now

Adds the values an administrator will save for a Plan (a stable key, a
name, limits, and a sync interval), the Allowance that says what one
User may use now, and the checks every limit uses. Plans off, and
Installation Administrators, are never limited. A User can name a Plan
of their own; none means the Default Plan. Nothing reads them yet, so
nothing changes.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 2: Rule places

**Files:**
- Modify: `src/calendar_sync/domain/model.py` (new constant `_KEEPS_PLACE` after `_DEGRADED_ON_DISCONNECT`; `SyncRule` field `keeps_place` and `__post_init__`; new properties `holdable`, `counts_toward_plan`; `enable`, `pause`, `degrade`, `resume_after_reauthorization`, `require_preview`, `on_account_disconnected`, `change_policy`, `begin_removal`; new method `take_place_of`)
- Modify: `src/calendar_sync/domain/plans.py` (type-only import of `SyncRule`; new function `may_start` at the end)
- Create: `tests/domain/test_rule_places.py`
- Test: `tests/domain/test_rule_places.py`, `tests/domain/test_model.py` (unchanged, must keep passing)

**Interfaces:**
- Consumes (Task 1): `calendar_sync.domain.plans` module; `tests.helpers.rule(*, state: SyncRuleState = SyncRuleState.ENABLED) -> SyncRule` (id `rule-1`, source `personal-account`/`personal-calendar`, destination `work-account`/`work-calendar`) and `tests.helpers.endpoint(account: str, calendar: str) -> CalendarEndpoint`.
- Produces:
  - `SyncRule.keeps_place: bool = False` (trailing field after `awaiting_reauthorization`, not in `material_signature`); `SyncRule.__post_init__` raises `DomainValidationError("only a draft or previewed rule keeps a place")` when `keeps_place` is true and `state` is neither `DRAFT` nor `PREVIEWED`.
  - `SyncRule.holdable -> bool` (property): `self.synchronizes or self.stopped_by_lapsed_authorization`.
  - `SyncRule.counts_toward_plan -> bool` (property): `self.holdable or self.keeps_place`.
  - `SyncRule.take_place_of(self, old: SyncRule) -> Self`: on `DRAFT` or `PREVIEWED`, `replace(self, keeps_place=old.counts_toward_plan)`; on any other state raises `InvalidStateTransition("only a new draft takes the place of the rule it replaces")`. Pass the old rule as it was before `begin_removal()`: a `REMOVING` rule never counts.
  - Transition behavior: `mark_previewed` keeps `keeps_place`; `enable`, `pause`, `degrade`, `resume_after_reauthorization`, `require_preview`, `begin_removal` clear it; `on_account_disconnected` clears it in every branch; `change_policy` keeps it only when the result is `DRAFT`; `complete_reprojection` keeps it.
  - `calendar_sync.domain.plans.may_start(before: SyncRule, counting_after: int, limit: int | None) -> bool`: `limit is None or before.keeps_place or counting_after <= limit`.

- [ ] **Step 1: Write the failing test**

Create `tests/domain/test_rule_places.py` with exactly this content:

```python
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


def test_a_replacement_that_starts_counts_as_enabled_instead_of_by_its_place() -> None:
    old = _rule(ENABLED)
    placed = _successor().take_place_of(old)

    started = placed.mark_previewed().enable()

    assert placed.counts_toward_plan
    assert not old.begin_removal().counts_toward_plan
    assert (started.state, started.keeps_place, started.counts_toward_plan) == (
        ENABLED,
        False,
        True,
    )


def test_a_rule_a_provider_failure_stops_does_not_count() -> None:
    stopped = _rule(PREVIEWED).enable().degrade()

    assert stopped.state is DEGRADED
    assert not stopped.counts_toward_plan


def test_a_rule_a_material_rule_change_pauses_does_not_count() -> None:
    enabled = _rule(ENABLED)

    paused = enabled.change_policy(DETAILS)

    assert enabled.counts_toward_plan
    assert paused.state is PAUSED
    assert not paused.counts_toward_plan


def test_previewing_a_lapse_stopped_rule_gives_up_its_place() -> None:
    stopped = _rule(ENABLED).degrade(awaiting_reauthorization=True)

    previewed = stopped.mark_previewed()

    assert stopped.counts_toward_plan
    assert previewed.state is PREVIEWED
    assert not previewed.counts_toward_plan


def test_replacing_a_rule_that_does_not_count_keeps_no_place() -> None:
    paused = _rule(ENABLED).pause()

    placed = _successor().take_place_of(paused)

    assert not placed.keeps_place
    assert not placed.counts_toward_plan


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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/domain/test_rule_places.py`

Expected: collection fails with
`E   ImportError: cannot import name 'may_start' from 'calendar_sync.domain.plans'`
and `Interrupted: 1 error during collection`.

- [ ] **Step 3: Add the place states and the `keeps_place` field to `SyncRule`**

In `src/calendar_sync/domain/model.py`, add `_KEEPS_PLACE` right after `_DEGRADED_ON_DISCONNECT`, so the block reads:

```python
# States that could still write, or be enabled, without a disconnected account's authorization.
_DEGRADED_ON_DISCONNECT = frozenset({SyncRuleState.PREVIEWED, SyncRuleState.ENABLED})
# A Rule Replacement draft keeps its place under the rule limit until it starts (ADR 0038).
_KEEPS_PLACE = frozenset({SyncRuleState.DRAFT, SyncRuleState.PREVIEWED})
```

Then add the trailing field and its invariant. The start of `SyncRule`, through `__post_init__`, now reads:

```python
@dataclass(frozen=True, slots=True)
class SyncRule:
    id: SyncRuleId
    source: CalendarEndpoint
    destination: CalendarEndpoint
    transformation: TransformationPolicy = field(default_factory=TransformationPolicy)
    initial_lookback_days: int = 30
    state: SyncRuleState = SyncRuleState.DRAFT
    reprojection_required: bool = False
    awaiting_reauthorization: bool = False
    """Degraded only by Lapsed Authorization, so it resumes once its accounts are authorized
    again instead of needing a recovery preview (ADR 0027)."""
    keeps_place: bool = False
    """A Rule Replacement draft that holds the place of the rule it replaced under its User's rule
    limit, until it starts or is removed (ADR 0038). Not part of material_signature."""

    def __post_init__(self) -> None:
        if self.source == self.destination:
            raise DomainValidationError("a directional sync rule cannot target its source")
        if self.initial_lookback_days < 0:
            raise DomainValidationError("initial lookback days cannot be negative")
        if self.keeps_place and self.state not in _KEEPS_PLACE:
            raise DomainValidationError("only a draft or previewed rule keeps a place")
```

`material_signature` stays `(self.source, self.destination, self.transformation, self.initial_lookback_days)`: do not add `keeps_place` to it.

- [ ] **Step 4: Add `holdable` and `counts_toward_plan`**

Add both properties right after `stopped_by_lapsed_authorization` (shown unchanged for context), before `eligible`:

```python
# Inside class SyncRule, in src/calendar_sync/domain/model.py
    @property
    def stopped_by_lapsed_authorization(self) -> bool:
        """Degraded only by Lapsed Authorization, so it resumes without a preview (ADR 0027)."""
        return self.state is SyncRuleState.DEGRADED and self.awaiting_reauthorization

    @property
    def holdable(self) -> bool:
        """Enabled, or stopped only by Lapsed Authorization: a rule that runs, or resumes on its
        own, and so takes a place under its User's rule limit (ADR 0038)."""
        return self.synchronizes or self.stopped_by_lapsed_authorization

    @property
    def counts_toward_plan(self) -> bool:
        """Whether the rule takes one of the places its User's Plan allows: it runs, resumes on
        its own, or is a Rule Replacement draft keeping the place of the rule it replaced."""
        return self.holdable or self.keeps_place
```

- [ ] **Step 5: Keep or clear the place in every transition, and add `take_place_of`**

Replace the transitions from `mark_previewed` through `begin_removal` with the block below, and add `take_place_of` after `begin_removal`. `mark_previewed` and `complete_reprojection` are unchanged and shown for context: `replace` keeps `keeps_place` on them, which is the rule (a preview keeps the place; it can only start from `DRAFT` or `PREVIEWED` with the place set). Every `replace` into a state outside `_KEEPS_PLACE` passes `keeps_place=False`, or `__post_init__` raises.

```python
# Inside class SyncRule, in src/calendar_sync/domain/model.py
    def mark_previewed(self) -> Self:
        if not self.can_preview:
            raise InvalidStateTransition(f"cannot validate a rule in state {self.state}")
        return replace(self, state=SyncRuleState.PREVIEWED, awaiting_reauthorization=False)

    def enable(self) -> Self:
        """Start the rule; a Rule Replacement draft now counts as enabled, not by a kept place."""
        if self.state is not SyncRuleState.PREVIEWED:
            raise InvalidStateTransition(f"cannot enable a rule in state {self.state}")
        return replace(self, state=SyncRuleState.ENABLED, keeps_place=False)

    def pause(self) -> Self:
        if self.state not in {SyncRuleState.ENABLED, SyncRuleState.DEGRADED}:
            raise InvalidStateTransition(f"cannot pause a rule in state {self.state}")
        return replace(
            self, state=SyncRuleState.PAUSED, awaiting_reauthorization=False, keeps_place=False
        )

    def degrade(self, *, awaiting_reauthorization: bool = False) -> Self:
        """Stop the rule; one stopped only by Lapsed Authorization awaits reauthorization."""
        if self.state not in {SyncRuleState.PREVIEWED, SyncRuleState.ENABLED}:
            raise InvalidStateTransition(f"cannot degrade a rule in state {self.state}")
        return replace(
            self,
            state=SyncRuleState.DEGRADED,
            awaiting_reauthorization=awaiting_reauthorization,
            keeps_place=False,
        )

    def resume_after_reauthorization(self) -> Self:
        """Return a rule stopped only by Lapsed Authorization to scheduled synchronization."""
        if not self.stopped_by_lapsed_authorization:
            raise InvalidStateTransition(
                "only a rule stopped by lapsed authorization resumes without a preview"
            )
        return replace(
            self, state=SyncRuleState.ENABLED, awaiting_reauthorization=False, keeps_place=False
        )

    def require_preview(self) -> Self:
        """A stopped rule whose recovery now needs a preview, whatever stopped it first; it keeps
        no place under its User's rule limit."""
        return replace(self, awaiting_reauthorization=False, keeps_place=False)

    def on_account_disconnected(self) -> Self:
        """The rule once one of its Connected Accounts is disconnected; itself if unchanged.

        A rule that could still write, or be enabled, stops. Disconnecting is a deliberate stop,
        so a rule stopped by Lapsed Authorization needs a preview to recover, and a Rule
        Replacement draft gives up the place it kept.
        """
        if self.state in _DEGRADED_ON_DISCONNECT:
            return self.degrade()
        if self.awaiting_reauthorization:
            return self.require_preview()
        if self.keeps_place:
            return replace(self, keeps_place=False)
        return self

    def change_policy(self, transformation: TransformationPolicy) -> Self:
        """Apply a Material Rule Change; the rule must pass a new Rule Preview afterwards."""
        if self.state is SyncRuleState.REMOVING:
            raise InvalidStateTransition("cannot change a rule while its removal is incomplete")
        if transformation == self.transformation:
            return self
        if self.state in {SyncRuleState.ENABLED, SyncRuleState.PAUSED}:
            state = SyncRuleState.PAUSED
        elif self.state is SyncRuleState.DEGRADED:
            state = SyncRuleState.DEGRADED
        else:
            state = SyncRuleState.DRAFT
        return replace(
            self,
            transformation=transformation,
            state=state,
            reprojection_required=True,
            awaiting_reauthorization=False,
            keeps_place=self.keeps_place and state is SyncRuleState.DRAFT,
        )

    def complete_reprojection(self) -> Self:
        return replace(self, reprojection_required=False)

    def begin_removal(self) -> Self:
        """Removing marks a Rule Removal that started and has not finished."""
        return replace(
            self, state=SyncRuleState.REMOVING, awaiting_reauthorization=False, keeps_place=False
        )

    def take_place_of(self, old: SyncRule) -> Self:
        """This new Rule Replacement draft, keeping the place `old` took under its User's rule
        limit; a rule that did not count leaves no place to keep (ADR 0038)."""
        if self.state not in _KEEPS_PLACE:
            raise InvalidStateTransition("only a new draft takes the place of the rule it replaces")
        return replace(self, keeps_place=old.counts_toward_plan)
```

`model.py` keeps importing only `domain/errors.py` from the domain; it does not import `plans.py`.

- [ ] **Step 6: Add `may_start` to `domain/plans.py`**

In `src/calendar_sync/domain/plans.py`, import `SyncRule` for type checking only (a runtime import would be circular as soon as `model.py` needs anything from Plans, and the contract allows only `cadence.py` and `errors.py` at runtime). The import block now reads:

```python
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from calendar_sync.domain.cadence import DEFAULT_CADENCE, SCHEDULED_EVERY, SyncCadence
from calendar_sync.domain.errors import DomainError, DomainValidationError

if TYPE_CHECKING:
    from calendar_sync.domain.model import SyncRule
```

Then append `may_start` at the end of the file, after `require_room` (shown unchanged for context):

```python
def require_room(resource: LimitedResource, in_use: int, limit: int | None) -> None:
    """Refuse one more of `resource` when `in_use` already reaches the limit."""
    if limit is not None and not has_room(in_use, limit):
        raise PlanLimitReached(resource, limit)


def may_start(before: SyncRule, counting_after: int, limit: int | None) -> bool:
    """Whether a Start fits the rule limit. A rule that keeps a place always starts, because its
    Start does not change the count; any other starts while `counting_after`, the rules that
    count once it runs, stays within `limit`."""
    return limit is None or before.keeps_place or counting_after <= limit
```

- [ ] **Step 7: Run the tests and the backend gates**

Run each command:

```sh
.venv/bin/pytest tests/domain/test_rule_places.py
.venv/bin/pytest tests/domain/test_model.py tests/domain/test_plans.py
.venv/bin/pytest tests/domain
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy
.venv/bin/lint-imports
.venv/bin/pytest
```

Expected, in order: `72 passed`; `169 passed`; `528 passed`; `... files already formatted`; `All checks passed!`; `Success: no issues found in ... source files`; `Contracts: 10 kept, 0 broken.`; the whole suite passes. Every `SyncRule` the adapters read or the tests build has `keeps_place=False`, so no existing test changes. The SQLite adapter does not store the field until Task 3.

- [ ] **Step 8: Commit**

```sh
git add src/calendar_sync/domain/model.py src/calendar_sync/domain/plans.py tests/domain/test_rule_places.py
git commit -F - <<'EOF'
Let a Rule Replacement draft keep the place of the rule it replaces

A rule counts toward its User's rule limit while it is enabled or
stopped only by Lapsed Authorization. A Rule Replacement draft can keep
the place of the rule it replaced until it starts or is removed; every
transition out of draft or previewed gives the place up, so a rule a
provider failure stops, or a Material Rule Change pauses, no longer
counts. may_start says whether a Start fits the limit.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Notes for later tasks (from Tasks 1 and 2)

- `PlanKey(raw)` raises `InvalidPlan` with reason `key` for any malformed key, including surrounding spaces and a trailing newline (it uses `fullmatch`). `named_plan` (Task 13) catches `InvalidPlan` and answers 404; `DefinePlan`'s route lets it become 422.
- `InvalidPlan` is a `DomainValidationError`, so it is also a `ValueError`. Task 6 must map it to `invalid_plan` ahead of any generic `DomainValidationError` mapping (`invalid_rule`). `PlanLimitReached`, `PlansNeedDefault`, `PlanIsDefault`, and `PlanInUse` are plain `DomainError`s.
- `PlanLimits(...)` validates ranges, and `SyncInterval(raw)` raises `ValueError` on an unknown value. `SqlitePlans` (Task 4) reading a stored row must catch both: an unknown interval reads as `SyncInterval.INSTANT` with a warning; a stored key `PlanKey` refuses reads as no Plan with a warning.
- `allowance_for` returns `UNLIMITED` for "Plans on and no Plan found"; it does not log. The adapter logs `Plans are on, but User %s has no Plan; nothing limits them` when `plans_on and not administers and own is None and default is None`.
- `Allowance` has no invariant: `Allowance(AllowanceBasis.PLAN)` with no Plan is constructible and reads `NO_LIMITS`, but `limits_manual_runs` is true for it. Build Allowances through `allowance_for`.
- `tests/domain/test_plans.py` defines its own `FREE` and `FAMILY`, with the same values `tests/plans.py` will hold (Task 4). Keep the test file self-contained; do not import `tests/plans.py` into it.
- `SyncRule(..., keeps_place=True)` in any state other than `DRAFT` or `PREVIEWED` raises `DomainValidationError`. `rule_from_row` (Task 3) must read `keeps_place=bool(row["keeps_place"]) and state in {SyncRuleState.DRAFT, SyncRuleState.PREVIEWED}`, and test code must move a place-keeping rule through transitions, never `replace(rule, state=...)`.
- `take_place_of(old)` reads `old.counts_toward_plan`, so `RemoveSyncRule` (Task 10) must pass the rule it read before `begin_removal()`; a `REMOVING` rule never counts and would give the successor no place.
- `require_preview()` now clears `keeps_place` in every state, and `on_account_disconnected()` clears it on a plain draft.
- `may_start` lives in `domain/plans.py` and imports `SyncRule` only under `TYPE_CHECKING`. `EnableSyncRule` (Task 9) passes the rule as read before `enable()`, so a place-keeping successor still has `keeps_place=True` when checked.
- Escape non-printing characters in test strings with `\N{...}` names (as `test_plans.py` does), never a raw character: Ruff's `RUF001` refuses ambiguous Unicode in source.

## Part 2: Persistence (Tasks 3 and 4)

These two tasks store what tasks 1 and 2 decide: migration 33, a rule's `keeps_place`, the order a
Rule Replacement inherits, each User's own Plan, and the Plans store behind the three Plans ports.
Plans stay off by default, so no existing behavior changes. Task numbers follow
`.context/plans-slice1-contract.md` section 5.

Before you start: tasks 1 and 2 must be committed (`calendar_sync.domain.plans` exists, `User` has
`plan`, and `SyncRule` has `keeps_place`, `counts_toward_plan`, and `take_place_of`). Read
`CONTEXT.md` (Plan, Default Plan, Allowance, Rule Replacement) and `AGENTS.md`. Run every command
from the repository root. Never use an em dash in code, comments, docs, or commit messages.
`.venv/bin/pytest` already adds `-q` through `pyproject.toml`.

Each "Replace" instruction below quotes the current text exactly; find it with your editor's
search, and replace only that text.

---

### Task 3: Migration 33 and rule and User persistence

**Files:**
- Create: `src/calendar_sync/infrastructure/persistence/0033_plans.sql`
- Modify: `src/calendar_sync/infrastructure/persistence/migrations.py` (`_FORWARD_MIGRATIONS`)
- Modify: `src/calendar_sync/application/sync/ports.py` (`SyncRuleRepository` gains `inherit_place`)
- Modify: `src/calendar_sync/infrastructure/persistence/sqlite.py` (`SqliteSyncRuleRepository.add`, `._update`, new `.inherit_place`; `_rule_values`; new `_KEEPS_PLACE`; `rule_from_row`)
- Modify: `src/calendar_sync/infrastructure/persistence/memory.py` (`MemoryState.rule_order`; `InMemorySyncRuleRepository.add`, `.remove`, new `.inherit_place`)
- Modify: `src/calendar_sync/infrastructure/persistence/memory_installation.py` (`_status_records`, the `rules=` argument)
- Modify: `src/calendar_sync/infrastructure/persistence/users.py` (imports, `logger`, `_COLUMNS`, `_user`, new `_own_plan`)
- Modify: `docs/deployment.md` (new "Migration 33" paragraph after the "Migration 32" paragraph)
- Create: `tests/adapters/test_plans_schema.py`
- Modify: `tests/contracts/persistence.py` (import; one test after `test_rules_round_trip_and_list_by_identifier`; two tests after `test_status_records_hold_each_users_rules_in_the_order_they_were_created`)
- Modify: `tests/adapters/test_user_isolation_schema.py` (`INSTALLATION_TABLES` and its comment)
- Modify: `tests/adapters/test_users_store.py` (imports; one test after `test_a_new_user_wants_instant_sync`)
- Test: `tests/adapters/test_plans_schema.py`, `tests/adapters/test_persistence_contract.py` (runs the contract on memory and SQLite), `tests/adapters/test_user_isolation_schema.py`, `tests/adapters/test_users_store.py`

**Interfaces:**
- Consumes:
  - Task 1, `calendar_sync.domain.plans`: `PlanKey(value: str)` (raises `InvalidPlan` unless the value fully matches `[a-z0-9][a-z0-9-]{0,31}`), `InvalidPlan` (a `DomainValidationError`).
  - Task 1, `calendar_sync.domain.access`: `User.plan: PlanKey | None = None` (trailing field).
  - Task 2, `calendar_sync.domain.model.SyncRule`: `keeps_place: bool = False` (`__post_init__` raises `DomainValidationError` when it is true outside DRAFT and PREVIEWED); `take_place_of(old: SyncRule) -> Self` (sets `keeps_place=old.counts_toward_plan`); `mark_previewed()` keeps `keeps_place`; `enable()` and `begin_removal()` clear it.
- Produces:
  - Migration 33: table `plans(key, name, rule_limit, account_limit, token_limit, sync_interval, created_at, updated_at)`; `installation_settings.plans_enabled INTEGER NOT NULL DEFAULT 0`, `installation_settings.default_plan_key REFERENCES plans(key)`; `users.plan_key REFERENCES plans(key)`, `users.plan_assigned_by`, `users.plan_assigner_id REFERENCES users(id) ON DELETE SET NULL`, `users.plan_assigned_at`; `sync_rules.keeps_place INTEGER NOT NULL DEFAULT 0`.
  - `SyncRuleRepository.inherit_place(self, rule: SyncRuleId, of: SyncRuleId) -> None` in `calendar_sync.application.sync.ports`, implemented by `SqliteSyncRuleRepository` and `InMemorySyncRuleRepository`.
  - `MemoryState.rule_order: dict[SyncRuleId, int]`; the in-memory `status_records` lists each User's rules by `(rule_order.get(rule.id, 0), rule.id.value)`, as SQLite lists them by `creation_order, id`.
  - SQLite rules write and read `keeps_place`; `rule_from_row` reads it only on DRAFT and PREVIEWED rows.
  - `SqliteUserDirectory` reads `User.plan` from `users.plan_key`: `None` for NULL, and `None` with a logged warning for a key `PlanKey` refuses.

- [ ] **Step 1: Write the failing migration and schema tests**

Create `tests/adapters/test_plans_schema.py`:

```python
"""Migration 33 keeps Plans: the limits an administrator defines, whether Plans are on and which
one is the default, each User's own Plan, and the place a Rule Replacement draft keeps
(ADR 0038)."""

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from calendar_sync.domain.model import SyncRuleId, SyncRuleState
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.persistence.installation import (
    SqliteInstallationUnitOfWorkFactory,
)
from calendar_sync.infrastructure.persistence.migrations import initialize_database
from tests.adapters.test_user_migration import database_at_version
from tests.helpers import NOW, endpoint, rule
from tests.users import OTHER_USER, USER, add_account, add_user, sqlite_units


def _release_32_records(database: Path) -> None:
    """An administrator with two accounts and an enabled rule, and a second User, as release 32
    kept them: its rules have no `keeps_place` column yet, so the rule is written directly."""
    add_user(database, USER)
    add_user(database, OTHER_USER, role="user")
    for account in ("personal-account", "work-account"):
        add_account(database, account, USER)
    with transaction(database) as connection:
        connection.execute(
            """
            INSERT INTO sync_rules (id, user_id, source_account_id, source_calendar_id,
                destination_account_id, destination_calendar_id, privacy_policy,
                all_day_policy, busy_title, initial_lookback_days, state)
            VALUES ('rule-1', ?, 'personal-account', 'personal-calendar', 'work-account',
                'work-calendar', 'busy_only', 'include', 'Busy', 30, 'enabled')
            """,
            (USER.value,),
        )


def _family_assigned(database: Path) -> None:
    """The Plan `family`, which USER assigned to OTHER_USER as their own."""
    with transaction(database) as connection:
        connection.execute(
            """
            INSERT INTO plans (key, name, rule_limit, account_limit, token_limit, sync_interval,
                created_at, updated_at)
            VALUES ('family', 'Family', 5, 3, 2, 'instant', ?, ?)
            """,
            (NOW.isoformat(), NOW.isoformat()),
        )
        connection.execute(
            """
            UPDATE users SET plan_key = 'family', plan_assigned_by = 'administrator',
                plan_assigner_id = ?, plan_assigned_at = ?
            WHERE id = ?
            """,
            (USER.value, NOW.isoformat(), OTHER_USER.value),
        )


def test_migration_33_adds_plans_turned_off_and_limits_nobody(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    database_at_version(database, 32)
    _release_32_records(database)

    initialize_database(database)
    initialize_database(database)

    with sqlite3.connect(database) as connection:
        setting = connection.execute(
            "SELECT plans_enabled, default_plan_key FROM installation_settings"
        ).fetchall()
        assignments = connection.execute(
            """
            SELECT id, plan_key, plan_assigned_by, plan_assigner_id, plan_assigned_at
            FROM users ORDER BY id
            """
        ).fetchall()
        places = connection.execute("SELECT id, keeps_place FROM sync_rules").fetchall()
        plans = connection.execute("SELECT COUNT(*) FROM plans").fetchone()
        broken = connection.execute("PRAGMA foreign_key_check").fetchall()
    with sqlite_units(database)() as uow:
        kept = uow.rules.get(rule().id)

    assert setting == [(0, None)]
    assert assignments == [
        (USER.value, None, None, None, None),
        (OTHER_USER.value, None, None, None, None),
    ]
    assert places == [("rule-1", 0)]
    assert plans == (0,)
    assert broken == []
    assert kept == rule()


def test_the_database_refuses_to_delete_a_plan_a_user_or_the_default_names(
    tmp_path: Path,
) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    add_user(database, USER)
    add_user(database, OTHER_USER, role="user")
    _family_assigned(database)

    with pytest.raises(sqlite3.IntegrityError), transaction(database) as connection:
        connection.execute("DELETE FROM plans WHERE key = 'family'")
    with transaction(database) as connection:
        connection.execute("UPDATE users SET plan_key = NULL")
        connection.execute("UPDATE installation_settings SET default_plan_key = 'family'")
    with pytest.raises(sqlite3.IntegrityError), transaction(database) as connection:
        connection.execute("DELETE FROM plans WHERE key = 'family'")

    with transaction(database) as connection:
        kept = [tuple(row) for row in connection.execute("SELECT key FROM plans")]
    assert kept == [("family",)]


def test_deleting_the_administrator_who_assigned_a_plan_keeps_the_plan_without_its_assigner(
    tmp_path: Path,
) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    add_user(database, USER)
    add_user(database, OTHER_USER, role="user")
    _family_assigned(database)

    with transaction(database) as connection:
        connection.execute("DELETE FROM users WHERE id = ?", (USER.value,))
    with transaction(database) as connection:
        assignment = connection.execute(
            """
            SELECT plan_key, plan_assigned_by, plan_assigner_id, plan_assigned_at
            FROM users WHERE id = ?
            """,
            (OTHER_USER.value,),
        ).fetchone()

    assert tuple(assignment) == ("family", "administrator", None, NOW.isoformat())


def test_a_place_left_on_a_rule_that_is_no_draft_reads_as_no_place(tmp_path: Path) -> None:
    """Only a draft or previewed rule keeps a place, so a mark left on any other row never stops
    the rule from being read."""
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    units = sqlite_units(database)
    draft = replace(
        rule(),
        id=SyncRuleId("rule-9"),
        destination=endpoint("work-account", "replacement-calendar"),
        state=SyncRuleState.DRAFT,
    )
    with units() as uow:
        uow.rules.add(rule())
        uow.rules.add(draft)
        uow.commit()
    with transaction(database) as connection:
        connection.execute("UPDATE sync_rules SET keeps_place = 1")

    with units() as uow:
        enabled, kept = uow.rules.get(rule().id), uow.rules.get(draft.id)
    with SqliteInstallationUnitOfWorkFactory(database)() as installation:
        scheduled = installation.scheduled_rules()

    assert enabled == rule()
    assert kept == replace(draft, keeps_place=True)
    assert [item.rule for item in scheduled] == [rule()]
```

- [ ] **Step 2: Write the failing persistence contract tests**

In `tests/contracts/persistence.py`, replace the end of the `calendar_sync.domain.model` import:

```python
    SyncRule,
    SyncRuleId,
    TimedInterval,
)
```

with:

```python
    SyncRule,
    SyncRuleId,
    SyncRuleState,
    TimedInterval,
)
```

Then find the end of `test_rules_round_trip_and_list_by_identifier`:

```python
        with harness.unit_of_work() as uow:
            assert uow.rules.list() == (OTHER_RULE, stopped)
            assert uow.rules.get(RULE.id) == stopped
```

and add this method right after it, inside `class PersistenceContract`:

```python
    def test_a_draft_keeps_its_place_through_its_preview_until_it_starts(
        self, harness: PersistenceHarness
    ) -> None:
        draft = replace(RULE, state=SyncRuleState.DRAFT, keeps_place=True)
        with harness.unit_of_work() as uow:
            uow.rules.add(draft)
            uow.commit()
        with harness.unit_of_work() as uow:
            added = uow.rules.get(RULE.id)
            uow.rules.save(draft.mark_previewed())
            uow.commit()
        with harness.unit_of_work() as uow:
            previewed = uow.rules.list()
            uow.rules.save(draft.mark_previewed().enable())
            uow.commit()
        with harness.unit_of_work() as uow:
            started = uow.rules.get(RULE.id)

        assert added == draft
        assert previewed == (replace(draft, state=SyncRuleState.PREVIEWED),)
        assert previewed[0].keeps_place
        assert started is not None
        assert not started.keeps_place
        assert started == RULE
```

Then find the end of `test_status_records_hold_each_users_rules_in_the_order_they_were_created`:

```python
        assert records[OTHER_USER].rules == (RecordedRule(theirs, None, None),)
```

and add these two methods right after it. They go inside `class PersistenceContract`; the
`class` line below only shows where, so do not add it again:

```python
class PersistenceContract:
    def test_a_replacement_ranks_where_the_rule_it_replaced_ranked(
        self, harness: PersistenceHarness
    ) -> None:
        successor = replace(
            RULE,
            id=SyncRuleId("rule-9"),
            destination=endpoint("work-account", "replacement-calendar"),
            state=SyncRuleState.DRAFT,
        )
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.rules.add(OTHER_RULE)
            uow.commit()
        with harness.unit_of_work() as uow:
            # As a Rule Replacement moves a place: in the step that begins the old rule's removal.
            uow.rules.save(RULE.begin_removal())
            uow.rules.add(successor.take_place_of(RULE))
            uow.rules.inherit_place(successor.id, of=RULE.id)
            uow.commit()
        with harness.unit_of_work() as uow:
            uow.rules.remove(RULE.id)
            uow.commit()

        with harness.installation() as installation:
            records = installation.status_records([USER])[USER]
        with harness.unit_of_work() as uow:
            listed = uow.rules.list()

        # Created after OTHER_RULE and sorting after it by identifier, it ranks first all the same.
        assert [recorded.rule.id for recorded in records.rules] == [successor.id, OTHER_RULE.id]
        assert records.rules[0].rule.keeps_place
        # Listing keeps its order by identifier, so the Rules page does not change.
        assert [each.id for each in listed] == [OTHER_RULE.id, successor.id]

    def test_a_place_passes_only_between_rules_of_one_user(
        self, harness: PersistenceHarness
    ) -> None:
        for account in (THEIR_SOURCE, THEIR_DESTINATION):
            harness.connect_account(account.connected_account_id, OTHER_USER)
        their_first = replace(
            RULE, id=SyncRuleId("their-b"), source=THEIR_SOURCE, destination=THEIR_DESTINATION
        )
        their_second = replace(
            their_first,
            id=SyncRuleId("their-a"),
            destination=endpoint(THEIR_DESTINATION.connected_account_id.value, "other-calendar"),
        )
        # Created in turns, so the two Users' rules interleave, and each User's identifiers sort
        # against the order they were created in.
        _commit_as(harness, OTHER_USER, lambda uow: uow.rules.add(their_first))
        _commit_as(harness, USER, lambda uow: uow.rules.add(RULE))
        _commit_as(harness, OTHER_USER, lambda uow: uow.rules.add(their_second))
        _commit_as(harness, USER, lambda uow: uow.rules.add(OTHER_RULE))

        with harness.unit_of_work() as uow:
            uow.rules.inherit_place(OTHER_RULE.id, of=their_first.id)
            uow.rules.inherit_place(their_first.id, of=OTHER_RULE.id)
            uow.commit()
        with harness.installation() as installation:
            records = installation.status_records([USER, OTHER_USER])

        assert [recorded.rule.id for recorded in records[USER].rules] == [RULE.id, OTHER_RULE.id]
        assert [recorded.rule.id for recorded in records[OTHER_USER].rules] == [
            their_first.id,
            their_second.id,
        ]
```

- [ ] **Step 3: Write the failing users store test, and list `plans` as an installation table**

In `tests/adapters/test_users_store.py`, replace the first imports:

```python
import sqlite3
from dataclasses import dataclass, replace
```

with:

```python
import logging
import sqlite3
from dataclasses import dataclass, replace
```

and replace:

```python
    UserState,
)
from calendar_sync.infrastructure.persistence.migrations import initialize_database
```

with:

```python
    UserState,
)
from calendar_sync.domain.plans import PlanKey
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.persistence.migrations import initialize_database
```

Then add this test right after `test_a_new_user_wants_instant_sync`:

```python
def test_a_users_own_plan_is_read_and_a_key_this_release_cannot_read_names_none(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    users = _users(tmp_path)
    later = replace(SECOND, id=UserId("later"), email="later@example.test")
    for user in (FIRST, SECOND, later):
        users.add(user, "hash")
    with transaction(tmp_path / "test.db") as connection:
        # A later release may write a key this one refuses; the foreign key still needs its Plan.
        for key in ("family", "Later Key"):
            connection.execute(
                """
                INSERT INTO plans (key, name, sync_interval, created_at, updated_at)
                VALUES (?, 'Family', 'instant', ?, ?)
                """,
                (key, NOW.isoformat(), NOW.isoformat()),
            )
        connection.execute("UPDATE users SET plan_key = 'family' WHERE id = ?", (SECOND.id.value,))
        connection.execute(
            "UPDATE users SET plan_key = 'Later Key' WHERE id = ?", (later.id.value,)
        )

    with caplog.at_level(logging.WARNING, logger="calendar_sync.infrastructure.persistence"):
        found = users.get(later.id)
        listed = users.list()

    assert users.get(FIRST.id) == FIRST
    assert users.get(SECOND.id) == replace(SECOND, plan=PlanKey("family"))
    assert found == later
    assert listed == (FIRST, replace(SECOND, plan=PlanKey("family")), later)
    assert [record.getMessage() for record in caplog.records] == [
        "User later names a plan this release cannot read; the Default Plan applies"
    ] * 2
```

In `tests/adapters/test_user_isolation_schema.py`, replace:

```python
# Tables that hold no User's records: the migration ledger, the Users themselves, the
# installation's settings, Invitations, which belong to nobody until they are used, and Delivery
# Evidence, which says whether providers reach the installation's own address.
INSTALLATION_TABLES = {
    "schema_migrations",
    "users",
    "installation_settings",
    "invitations",
    "delivery_evidence",
}
```

with:

```python
# Tables that hold no User's records: the migration ledger, the Users themselves, the
# installation's settings, Invitations, which belong to nobody until they are used, Delivery
# Evidence, which says whether providers reach the installation's own address, and the Plans an
# Installation Administrator defines, which a User names through their own row (ADR 0038).
INSTALLATION_TABLES = {
    "schema_migrations",
    "users",
    "installation_settings",
    "invitations",
    "delivery_evidence",
    "plans",
}
```

(`plans` carries no `user_id`, so once migration 33 creates it,
`test_every_owned_table_carries_its_user_and_a_reference_through_it` fails unless it is listed
here.)

- [ ] **Step 4: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/adapters/test_plans_schema.py tests/adapters/test_users_store.py tests/adapters/test_persistence_contract.py tests/adapters/test_user_isolation_schema.py`

Expected: 10 failed. The four schema tests fail with `sqlite3.OperationalError` (`no such column: plans_enabled`, `no such table: plans`, `no such column: keeps_place`); the users store test with `sqlite3.OperationalError: no such table: plans`; `test_a_replacement_ranks_where_the_rule_it_replaced_ranked` and `test_a_place_passes_only_between_rules_of_one_user` on both `TestInMemoryUnitOfWork` and `TestSqliteUnitOfWork` with `AttributeError: ... object has no attribute 'inherit_place'`; and `TestSqliteUnitOfWork::test_a_draft_keeps_its_place_through_its_preview_until_it_starts` with an `AssertionError` (SQLite does not keep `keeps_place` yet). The in-memory draft test already passes, because memory keeps the rule object itself.

- [ ] **Step 5: Implement migration 33**

Create `src/calendar_sync/infrastructure/persistence/0033_plans.sql`:

```sql
-- Plans (ADR 0028, ADR 0038): named limits an Installation Administrator defines and assigns.
-- Installation data, no User's records: a User names their own Plan through users.plan_key, and
-- NULL there means the Default Plan. Nothing is backfilled: Plans start off and limit nobody. A
-- Rule Replacement draft may keep the place of the rule it replaced under its User's rule limit.
-- The foreign keys keep NO ACTION, so the database refuses to delete a Plan that a User or the
-- default still names. Earlier releases ignore the table and the columns and limit nobody, so
-- rolling back works with the same database; after upgrading again, Plans are as the
-- administrator left them. Phase 4 rebuilds installation_settings and must carry plans_enabled
-- and default_plan_key.
CREATE TABLE plans (
    key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    rule_limit INTEGER,
    account_limit INTEGER,
    token_limit INTEGER,
    sync_interval TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
ALTER TABLE installation_settings ADD COLUMN plans_enabled INTEGER NOT NULL DEFAULT 0;
ALTER TABLE installation_settings ADD COLUMN default_plan_key TEXT REFERENCES plans(key);
ALTER TABLE users ADD COLUMN plan_key TEXT REFERENCES plans(key);
ALTER TABLE users ADD COLUMN plan_assigned_by TEXT;
ALTER TABLE users ADD COLUMN plan_assigner_id TEXT REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE users ADD COLUMN plan_assigned_at TEXT;
ALTER TABLE sync_rules ADD COLUMN keeps_place INTEGER NOT NULL DEFAULT 0;
```

`NULL` limits mean unlimited; `sync_interval` has no CHECK, so later releases can add intervals
without rebuilding the table; `plan_assigned_by` holds `administrator` or `billing`. There is no
index on `users.plan_key` (the spec's SQL has none).

In `src/calendar_sync/infrastructure/persistence/migrations.py`, replace the end of
`_FORWARD_MIGRATIONS`:

```python
    (31, "0031_instant_sync.sql"),
    (32, "0032_audit_entry_provenance.sql"),
)
```

with:

```python
    (31, "0031_instant_sync.sql"),
    (32, "0032_audit_entry_provenance.sql"),
    (33, "0033_plans.sql"),
)
```

`_CHECKED_FROM = 21` runs `PRAGMA foreign_key_check` after the migration; it passes because every
new value is `NULL` or `0`.

- [ ] **Step 6: Implement the `inherit_place` port and the SQLite rule repository**

In `src/calendar_sync/application/sync/ports.py`, class `SyncRuleRepository`, replace:

```python
    def purge(self, rule_id: SyncRuleId) -> None:
        """Delete the rule like `remove`, and its audit entries and incidents with it."""


class EventMappingRepository(Protocol):
```

with:

```python
    def purge(self, rule_id: SyncRuleId) -> None:
        """Delete the rule like `remove`, and its audit entries and incidents with it."""

    def inherit_place(self, rule: SyncRuleId, of: SyncRuleId) -> None:
        """Give `rule` the creation order of `of`, so it ranks where `of` ranked; both are this
        User's. Called only in the transaction that moves a Rule Replacement's place."""


class EventMappingRepository(Protocol):
```

In `src/calendar_sync/infrastructure/persistence/sqlite.py`, class `SqliteSyncRuleRepository`,
replace the whole `add` method with:

```python
    def add(self, rule: SyncRule) -> None:
        with refusals(), _rule_refusals():
            self._connection.execute(
                """
                INSERT INTO sync_rules (
                    id, source_account_id, source_calendar_id,
                    destination_account_id, destination_calendar_id,
                    privacy_policy, all_day_policy, busy_title,
                    tentative_policy, unanswered_policy, birthday_policy,
                    initial_lookback_days, state, reprojection_required,
                    awaiting_reauthorization, keeps_place, user_id, creation_order
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    (SELECT COALESCE(MAX(creation_order), 0) + 1 FROM sync_rules)
                )
                """,
                (*_rule_values(rule), self._user),
            )
```

replace the whole `_update` method with:

```python
    def _update(self, rule: SyncRule) -> sqlite3.Cursor:
        return self._connection.execute(
            """
            UPDATE sync_rules SET
                source_account_id = ?, source_calendar_id = ?,
                destination_account_id = ?, destination_calendar_id = ?,
                privacy_policy = ?, all_day_policy = ?, busy_title = ?,
                tentative_policy = ?, unanswered_policy = ?, birthday_policy = ?,
                initial_lookback_days = ?, state = ?, reprojection_required = ?,
                awaiting_reauthorization = ?, keeps_place = ?
            WHERE id = ? AND user_id = ?
            """,
            (*_rule_values(rule)[1:], rule.id.value, self._user),
        )
```

and replace the end of `purge` and the head of `relationship_exists`:

```python
        self._connection.execute("DELETE FROM sync_rules WHERE id = ? AND user_id = ?", owned)

    def relationship_exists(self, source: CalendarEndpoint, destination: CalendarEndpoint) -> bool:
```

with:

```python
        self._connection.execute("DELETE FROM sync_rules WHERE id = ? AND user_id = ?", owned)

    def inherit_place(self, rule: SyncRuleId, of: SyncRuleId) -> None:
        # creation_order is not unique: until `of` is removed, the two rank together, by id.
        self._connection.execute(
            """
            UPDATE sync_rules SET creation_order = (
                SELECT creation_order FROM sync_rules WHERE id = :of AND user_id = :user
            )
            WHERE id = :rule AND user_id = :user
                AND EXISTS (SELECT 1 FROM sync_rules WHERE id = :of AND user_id = :user)
            """,
            {"rule": rule.value, "of": of.value, "user": self._user},
        )

    def relationship_exists(self, source: CalendarEndpoint, destination: CalendarEndpoint) -> bool:
```

Near the end of the same file, replace the whole of `_rule_values` and `rule_from_row` with:

```python
def _rule_values(rule: SyncRule) -> tuple[object, ...]:
    return (
        rule.id.value,
        rule.source.connected_account_id.value,
        rule.source.calendar_id.value,
        rule.destination.connected_account_id.value,
        rule.destination.calendar_id.value,
        rule.transformation.content.value,
        rule.transformation.all_day.value,
        rule.transformation.busy_title,
        rule.transformation.tentative.value,
        rule.transformation.unanswered.value,
        rule.transformation.birthdays.value,
        rule.initial_lookback_days,
        rule.state.value,
        int(rule.reprojection_required),
        int(rule.awaiting_reauthorization),
        int(rule.keeps_place),
    )


_KEEPS_PLACE = frozenset({SyncRuleState.DRAFT, SyncRuleState.PREVIEWED})
"""The states a rule may keep a place in; a mark left on any other row reads as none."""


def rule_from_row(row: sqlite3.Row) -> SyncRule:
    state = SyncRuleState(str(row["state"]))
    return SyncRule(
        id=SyncRuleId(str(row["id"])),
        source=CalendarEndpoint(
            ConnectedAccountId(str(row["source_account_id"])),
            CalendarId(str(row["source_calendar_id"])),
        ),
        destination=CalendarEndpoint(
            ConnectedAccountId(str(row["destination_account_id"])),
            CalendarId(str(row["destination_calendar_id"])),
        ),
        transformation=TransformationPolicy(
            content=ProjectionContent(str(row["privacy_policy"])),
            all_day=AllDaySyncPolicy(str(row["all_day_policy"])),
            busy_title=str(row["busy_title"]),
            tentative=TentativeEventPolicy(str(row["tentative_policy"])),
            unanswered=UnansweredInvitationPolicy(str(row["unanswered_policy"])),
            birthdays=BirthdayPolicy(str(row["birthday_policy"])),
        ),
        initial_lookback_days=int(row["initial_lookback_days"]),
        state=state,
        reprojection_required=bool(row["reprojection_required"]),
        awaiting_reauthorization=bool(row["awaiting_reauthorization"]),
        keeps_place=bool(row["keeps_place"]) and state in _KEEPS_PLACE,
    )
```

Every caller of `rule_from_row` (`get` and `list` here, and `scheduled_rules`,
`pending_instant_runs`, and `_recorded_rules` in `installation.py`) selects `sync_rules.*`, so the
row always carries `keeps_place`. `list()` keeps `ORDER BY id`.

- [ ] **Step 7: Implement the in-memory rule order**

In `src/calendar_sync/infrastructure/persistence/memory.py`, class `MemoryState`, replace:

```python
    rules: dict[SyncRuleId, SyncRule] = field(default_factory=dict)
    mappings: dict[tuple[SyncRuleId, EventRef], EventMapping] = field(default_factory=dict)
```

with:

```python
    rules: dict[SyncRuleId, SyncRule] = field(default_factory=dict)
    rule_order: dict[SyncRuleId, int] = field(default_factory=dict)
    """Each rule's creation order, as SQLite's `creation_order` keeps it. A rule a test seeded
    into `rules` directly has none and ranks as 0."""
    mappings: dict[tuple[SyncRuleId, EventRef], EventMapping] = field(default_factory=dict)
```

(`InMemoryUnitOfWork.commit` copies every field of `MemoryState`, so the order commits and rolls
back with the rules.)

In class `InMemorySyncRuleRepository`, replace the whole `add` method with:

```python
    def add(self, rule: SyncRule) -> None:
        # Mirror SQLite's primary key and its unique source-and-destination constraint.
        if rule.id in self._state.rules or self._others.hold_rule(rule.id):
            raise IdentityCollision(f"sync rule {rule.id.value} already exists")
        if self.relationship_exists(rule.source, rule.destination):
            raise _duplicate_relationship()
        self._state.rules[rule.id] = rule
        self._state.rule_order[rule.id] = max(self._state.rule_order.values(), default=0) + 1
```

replace the first lines of `remove`:

```python
    def remove(self, rule_id: SyncRuleId) -> None:
        self._incidents.resolve_rule(rule_id, self._clock.now())
        self._state.rules.pop(rule_id, None)
```

with:

```python
    def remove(self, rule_id: SyncRuleId) -> None:
        self._incidents.resolve_rule(rule_id, self._clock.now())
        self._state.rules.pop(rule_id, None)
        self._state.rule_order.pop(rule_id, None)
```

(the rest of `remove` is unchanged; `purge` calls `remove`, so it drops the order too), and
replace the end of `purge` and the head of `relationship_exists`:

```python
        self._state.audit = [entry for entry in self._state.audit if entry.rule_id != rule_id]
        self._incidents.delete_rule(rule_id)

    def relationship_exists(self, source: CalendarEndpoint, destination: CalendarEndpoint) -> bool:
```

with:

```python
        self._state.audit = [entry for entry in self._state.audit if entry.rule_id != rule_id]
        self._incidents.delete_rule(rule_id)

    def inherit_place(self, rule: SyncRuleId, of: SyncRuleId) -> None:
        # Both must be this User's, as SQLite's update requires.
        if rule in self._state.rules and of in self._state.rules:
            self._state.rule_order[rule] = self._state.rule_order.get(of, 0)

    def relationship_exists(self, source: CalendarEndpoint, destination: CalendarEndpoint) -> bool:
```

In `src/calendar_sync/infrastructure/persistence/memory_installation.py`, replace the whole
`_status_records` function with this version. Only the `rules=` argument and its comment change:
it used to list `state.rules.values()` in insertion order, under the comment "Rules keep the order
they were added in, as a dictionary keeps its keys'."

```python
def _status_records(database: MemoryDatabase, user: UserId) -> StatusRecords:
    """A User's records as Installation Status reads them. This store keeps no daily block
    checks, so every block still the latest decision about its event is open. It knows an
    account's provider only when a test recorded one, so an account without one counts but has no
    standing."""
    state = database.partitions.get(user) or MemoryState()
    incidents = sorted(
        (
            _incident_summary(key, incident, state)
            for key, incident in database.incidents.get(user, {}).items()
            if incident.open
        ),
        key=lambda summary: (summary.updated_at, summary.id),
        reverse=True,
    )
    accounts = tuple(
        AccountStanding(
            account.value,
            standing,
            state.providers[account],
            lapsed=standing is ConnectedAccountState.CONNECTED and account in state.lapsed,
        )
        for account, standing in sorted(state.accounts.items(), key=lambda item: item[0].value)
        if account in state.providers
    )
    standings = state.accounts.values()
    succeeded = [
        outcome.last_succeeded_at
        for (_, kind), outcome in state.outcomes.items()
        if kind is RunKind.SYNC and outcome.last_succeeded_at is not None
    ]
    return StatusRecords(
        # Rules in the order they were created, then by identifier, as SQLite lists them.
        rules=tuple(
            RecordedRule(
                rule, state.outcomes.get((rule.id, RunKind.SYNC)), state.previews.get(rule.id)
            )
            for rule in sorted(
                state.rules.values(),
                key=lambda rule: (state.rule_order.get(rule.id, 0), rule.id.value),
            )
        ),
        overview=OperationsOverview(
            connected_accounts=sum(s is ConnectedAccountState.CONNECTED for s in standings),
            disconnected_accounts=sum(s is ConnectedAccountState.DISCONNECTED for s in standings),
            open_incidents=len(incidents),
            last_synced_at=max(succeeded) if succeeded else None,
            open_blocks=_open_blocks(state),
            accounts=accounts,
        ),
        incidents=tuple(incidents),
    )
```

While a replacement's old rule still exists (REMOVING), the two share one order and both stores
break the tie by identifier, which is why the contract test compares positions after the old rule
is removed.

- [ ] **Step 8: Implement reading each User's own Plan**

In `src/calendar_sync/infrastructure/persistence/users.py`, replace:

```python
from __future__ import annotations

import secrets
import sqlite3
```

with:

```python
from __future__ import annotations

import logging
import secrets
import sqlite3
```

replace:

```python
from calendar_sync.domain.access import Role, User, UserId, UserState, require_administrator_remains
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.security import token_hash

SESSION_LIFETIME = timedelta(days=7)
_COLUMNS = (
    "id, email, role, state, language, notify_by_email, instant_sync, created_at, last_sign_in_at"
)
```

with:

```python
from calendar_sync.domain.access import Role, User, UserId, UserState, require_administrator_remains
from calendar_sync.domain.plans import InvalidPlan, PlanKey
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.security import token_hash

logger = logging.getLogger(__name__)

SESSION_LIFETIME = timedelta(days=7)
_COLUMNS = (
    "id, email, role, state, language, notify_by_email, instant_sync, created_at, "
    "last_sign_in_at, plan_key"
)
```

and replace the whole `_user` function with `_user` and the new `_own_plan`:

```python
def _user(row: sqlite3.Row) -> User:
    signed_in = row["last_sign_in_at"]
    user_id = UserId(str(row["id"]))
    return User(
        id=user_id,
        email=str(row["email"]) if row["email"] is not None else None,
        role=Role(str(row["role"])),
        state=UserState(str(row["state"])),
        created_at=datetime.fromisoformat(str(row["created_at"])),
        last_sign_in_at=datetime.fromisoformat(str(signed_in)) if signed_in else None,
        language=str(row["language"]) if row["language"] is not None else None,
        notify_by_email=bool(row["notify_by_email"]),
        instant_sync=bool(row["instant_sync"]),
        plan=_own_plan(user_id, row["plan_key"]),
    )


def _own_plan(user_id: UserId, stored: object) -> PlanKey | None:
    """The User's own Plan, or None for the Default Plan. A key this release cannot read names
    no Plan, so a key a later release wrote never stops anyone from signing in."""
    if stored is None:
        return None
    try:
        return PlanKey(str(stored))
    except InvalidPlan:
        logger.warning(
            "User %s names a plan this release cannot read; the Default Plan applies",
            user_id.value,
        )
        return None
```

`insert_user` does not change: a new User's `plan_key` is `NULL`, the Default Plan, for setup,
Invitations, and later sign-up alike.

- [ ] **Step 9: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/adapters/test_plans_schema.py tests/adapters/test_users_store.py tests/adapters/test_persistence_contract.py tests/adapters/test_user_isolation_schema.py tests/adapters/test_sqlite.py`

Expected: all pass (no failures).

The in-memory `status_records` now orders rules as SQLite does, so run the whole backend gate:

```sh
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy
.venv/bin/lint-imports
.venv/bin/pytest --cov --cov-report=term-missing --cov-fail-under=80
```

Expected: `ruff format` reports every file already formatted; `ruff check` says
`All checks passed!`; mypy says `Success: no issues found`; lint-imports reports
`Contracts: 10 kept, 0 broken.`; pytest passes with coverage at or above 80%.

- [ ] **Step 10: Document migration 33 for operators**

In `docs/deployment.md`, find the end of the "Migration 32" paragraph:

```markdown
Earlier entries keep `NULL`. Rolling back works with the same database: earlier releases ignore the
columns, and record the repeated skips the newer release leaves out.
```

and add this paragraph after it, separated by one blank line (the next paragraph, "Sign-in
failures are counted...", stays after it):

```markdown
Migration 33 adds Plans ([ADR 0028](adr/0028-plans-apart-from-commercial-mode.md),
[ADR 0038](adr/0038-plans-allowances-and-limits.md)): the installation table `plans`; the columns
`installation_settings.plans_enabled` (default `0`, off) and
`installation_settings.default_plan_key`; each User's own Plan in `users.plan_key`, with who
assigned it and when (`plan_assigned_by`, `plan_assigner_id`, `plan_assigned_at`); and
`sync_rules.keeps_place`, which marks a Rule Replacement draft that keeps the place of the rule it
replaced under its User's rule limit. Nothing is backfilled: Plans start off and limit nobody, and
a User with no Plan of their own has the Default Plan once one exists. The database refuses to
delete a Plan that a User or the default still names. Once an administrator turns Plans on, a
lowered rule limit refuses new Starts and stops nothing. Rolling back works with the same
database: earlier releases ignore the table and the columns, and limit nobody. After upgrading
again, Plans are as the administrator left them.
```

ADR 0038 is written in task 19; until then the link points at the file that task creates.

Run: `.venv/bin/pytest tests/test_no_em_dashes.py tests/test_ubiquitous_language.py`

Expected: all pass.

- [ ] **Step 11: Commit**

```sh
git add src/calendar_sync/infrastructure/persistence/0033_plans.sql \
  src/calendar_sync/infrastructure/persistence/migrations.py \
  src/calendar_sync/application/sync/ports.py \
  src/calendar_sync/infrastructure/persistence/sqlite.py \
  src/calendar_sync/infrastructure/persistence/memory.py \
  src/calendar_sync/infrastructure/persistence/memory_installation.py \
  src/calendar_sync/infrastructure/persistence/users.py \
  docs/deployment.md \
  tests/adapters/test_plans_schema.py \
  tests/contracts/persistence.py \
  tests/adapters/test_user_isolation_schema.py \
  tests/adapters/test_users_store.py
git commit -m "$(cat <<'EOF'
Keep Plans and each User's own Plan in the database, and let a replacement draft keep its place

Migration 33 adds the plans table, the Plans setting, each User's own
Plan with who set it and when, and sync_rules.keeps_place. Plans start
off and limit nobody, and rolling back works with the same database.
Rules keep keeps_place through each save, a Rule Replacement draft can
take the creation order of the rule it replaces, and Users are read
with their own Plan, a key this release cannot read naming none.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Plans ports, SqlitePlans, MemoryPlans, return to setup

**Files:**
- Modify: `src/calendar_sync/application/sync/ports.py` (import; new `Allowances` protocol after `UnitOfWorkFactory`)
- Modify: `src/calendar_sync/application/identity/errors.py` (new `PlanNotFound`, `PlanKeyTaken` at the end)
- Modify: `src/calendar_sync/application/identity/ports.py` (module docstring; import; `RegistrationSettings.return_to_setup` docstring; new `PlansSetting`, `PlanListing`, `PlanCatalog`, `AssignmentChange`, `PlanAssignments` at the end)
- Create: `src/calendar_sync/infrastructure/persistence/plans.py`
- Modify: `src/calendar_sync/infrastructure/persistence/connections.py` (new `USERS_PER_QUERY`)
- Modify: `src/calendar_sync/infrastructure/persistence/installation.py` (import `USERS_PER_QUERY`; drop `_USERS_PER_QUERY`)
- Modify: `src/calendar_sync/infrastructure/persistence/registration.py` (`SqliteRegistrationSettings.return_to_setup`)
- Modify: `src/calendar_sync/bootstrap/container.py` (imports; three `Adapters` fields after `watch_inbox`; one `SqlitePlans` in `build_adapters`)
- Modify: `tests/identity_fakes.py` (imports; `MemoryRegistration.plans`; new `MemoryPlans`, `BrokenAllowances` at the end)
- Modify: `tests/users.py` (new `limited_user` before `add_account`)
- Create: `tests/plans.py`
- Create: `tests/adapters/test_plans_store.py`
- Modify: `tests/adapters/test_users_store.py` (imports; one helper and one test after `test_returning_to_setup_chooses_only_me_and_revokes_every_invitation_in_one_step`)
- Test: `tests/adapters/test_plans_store.py`, `tests/adapters/test_users_store.py`

**Interfaces:**
- Consumes:
  - Task 1, `calendar_sync.domain.plans`: `Allowance(basis, plan=None, on_default=False, assigned=None)`, `AllowanceBasis` (`PLANS_OFF`, `ADMINISTRATOR`, `PLAN`), `UNLIMITED = Allowance(AllowanceBasis.PLANS_OFF)`, `allowance_for(*, plans_on: bool, administers: bool, own: Plan | None, default: Plan | None) -> Allowance`, `Plan(key, name, limits)`, `PlanKey(value)`, `PlanLimits(rules, connected_accounts, integration_tokens, sync_interval)`, `SyncInterval` (`INSTANT`, `EVERY_5_MINUTES`, ...), `AssignmentSource` (`ADMINISTRATOR`, `BILLING`), `InvalidPlan`, `PlansNeedDefault`, `PlanIsDefault`, `PlanInUse(people: int)` (attribute `people`), `require_plans_setting(enabled: bool, default: PlanKey | None) -> None`, `require_removable(key: PlanKey, default: PlanKey | None, people: int) -> None`.
  - Task 1, `User.plan: PlanKey | None`; `User.administers` (role only, state ignored).
  - Task 3: migration 33's table and columns; `SqliteUserDirectory` reads `User.plan`.
- Produces:
  - `calendar_sync.application.sync.ports.Allowances` (Protocol): `of(self, user: UserId) -> Allowance`; `of_users(self, users: Collection[UserId]) -> Mapping[UserId, Allowance]`. A User not found reads as `UNLIMITED`; a read that cannot be made raises.
  - `calendar_sync.application.identity.ports`: `PlansSetting(enabled: bool, default: PlanKey | None)`; `PlanListing(plan: Plan, is_default: bool, people: int, limited_people: int)`; `PlanCatalog` (Protocol: `settings() -> PlansSetting`, `change_settings(enabled: bool, default: PlanKey | None) -> PlansSetting`, `plans() -> Sequence[PlanListing]`, `any_plans() -> bool`, `get(key: PlanKey) -> Plan | None`, `add(plan: Plan, at: datetime) -> None`, `change(plan: Plan, at: datetime) -> None`, `remove(key: PlanKey) -> None`); `AssignmentChange(source: AssignmentSource, actor: UserId | None, at: datetime)`; `PlanAssignments` (Protocol: `assign(user: UserId, plan: PlanKey | None, change: AssignmentChange) -> bool`).
  - `calendar_sync.application.identity.errors`: `PlanNotFound(ApplicationError)`, `PlanKeyTaken(ApplicationError)`.
  - `calendar_sync.infrastructure.persistence.plans.SqlitePlans(database_path: Path)`: implements all three ports.
  - `calendar_sync.infrastructure.persistence.connections.USERS_PER_QUERY = 500`.
  - `Adapters.allowances: Allowances`, `Adapters.plan_catalog: PlanCatalog`, `Adapters.plan_assignments: PlanAssignments` (required fields after `watch_inbox`); `build_adapters` makes one local `plans = SqlitePlans(database)` and passes it as all three.
  - `SqliteRegistrationSettings.return_to_setup` also sets `plans_enabled = 0`, keeping every Plan and the default.
  - `tests.identity_fakes.MemoryPlans(users: MemoryUsers = MemoryUsers(), enabled: bool = False, default: PlanKey | None = None, catalog: dict[PlanKey, Plan] = {}, changes: dict[UserId, AssignmentChange] = {})`, implementing the three ports; `assign` rewrites `users.users[user]` with `replace(user, plan=key)` and records `changes[user]`.
  - `tests.identity_fakes.BrokenAllowances()`: `of` and `of_users` raise `RuntimeError("database is locked")`.
  - `tests.identity_fakes.MemoryRegistration(..., plans: MemoryPlans | None = None)`: `return_to_setup` sets `plans.enabled = False`.
  - `tests.users.limited_user(database: Path, user: UserId = OTHER_USER, *, plan: str | None = None, email: str | None = None) -> UserId`.
  - `tests.plans.FREE`, `tests.plans.FAMILY`, `tests.plans.plans_on(catalog: PlanCatalog, default: Plan = FREE, *others: Plan) -> None`.

- [ ] **Step 1: Write the test Plans and the failing store tests**

Create `tests/plans.py`:

```python
"""Plans for tests: a small free Plan and a larger family Plan (ADR 0038)."""

from calendar_sync.application.identity.ports import PlanCatalog
from calendar_sync.domain.plans import Plan, PlanKey, PlanLimits, SyncInterval
from tests.helpers import NOW

FREE = Plan(PlanKey("free"), "Free", PlanLimits(1, 1, 0, SyncInterval.EVERY_5_MINUTES))
"""One rule, one calendar account, no Integration Tokens, and no Instant Sync."""
FAMILY = Plan(PlanKey("family"), "Family", PlanLimits(5, 3, 2, SyncInterval.INSTANT))
"""Five rules, three calendar accounts, two Integration Tokens, and Instant Sync."""


def plans_on(catalog: PlanCatalog, default: Plan = FREE, *others: Plan) -> None:
    """Define `default` and `others`, and turn Plans on with `default` as the Default Plan."""
    for plan in (default, *others):
        catalog.add(plan, NOW)
    catalog.change_settings(True, default.key)
```

Create `tests/adapters/test_plans_store.py`. The fixture runs every shared test on SQLite and on
`MemoryPlans`, as the `directory` fixture in `tests/adapters/test_users_store.py` does for Users;
the tests after `_sqlite` are SQLite only.

```python
"""Plans as the installation stores them (ADR 0038). SQLite and the in-memory stand-in that
application tests use pass the same tests, so a use case tested in memory meets SQLite's refusals
and counts."""

import logging
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from calendar_sync.application.identity.errors import PlanKeyTaken, PlanNotFound
from calendar_sync.application.identity.ports import (
    AssignmentChange,
    PlanListing,
    PlansSetting,
    UserDirectory,
)
from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import build_adapters
from calendar_sync.domain.access import Role, User, UserId, UserState
from calendar_sync.domain.plans import (
    UNLIMITED,
    Allowance,
    AllowanceBasis,
    AssignmentSource,
    Plan,
    PlanInUse,
    PlanIsDefault,
    PlanKey,
    PlanLimits,
    PlansNeedDefault,
    SyncInterval,
)
from calendar_sync.infrastructure.persistence import plans as plans_store
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.persistence.migrations import initialize_database
from calendar_sync.infrastructure.persistence.plans import SqlitePlans
from calendar_sync.infrastructure.persistence.users import SqliteUserDirectory
from tests.helpers import NOW
from tests.identity_fakes import MemoryPlans, MemoryUsers
from tests.plans import FAMILY, FREE, plans_on
from tests.users import limited_user

ADMIN = User(
    UserId("admin"), "admin@example.test", Role.INSTALLATION_ADMINISTRATOR, UserState.ACTIVE, NOW
)
MEMBER = User(UserId("member"), "member@example.test", Role.USER, UserState.ACTIVE, NOW)
NEWCOMER = User(UserId("newcomer"), "newcomer@example.test", Role.USER, UserState.ACTIVE, NOW)
AWAY = User(UserId("away"), "away@example.test", Role.USER, UserState.DISABLED, NOW)
NOBODY = UserId("nobody")
LATER = NOW + timedelta(hours=1)
BY_ADMIN = AssignmentChange(AssignmentSource.ADMINISTRATOR, ADMIN.id, NOW)


@dataclass(frozen=True)
class PlansStore:
    plans: SqlitePlans | MemoryPlans
    users: UserDirectory
    recorded: Callable[[UserId], AssignmentChange | None]
    """How a User's own Plan was last set, as the store records it."""

    def people(self, *users: User) -> None:
        for user in users:
            self.users.add(user, "hash")


def _recorded(database: Path, user: UserId) -> AssignmentChange | None:
    with transaction(database) as connection:
        row = connection.execute(
            "SELECT plan_assigned_by, plan_assigner_id, plan_assigned_at FROM users WHERE id = ?",
            (user.value,),
        ).fetchone()
    if row is None or row["plan_assigned_by"] is None:
        return None
    actor = row["plan_assigner_id"]
    return AssignmentChange(
        AssignmentSource(str(row["plan_assigned_by"])),
        UserId(str(actor)) if actor is not None else None,
        datetime.fromisoformat(str(row["plan_assigned_at"])),
    )


@pytest.fixture(params=["sqlite", "memory"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> PlansStore:
    """Both Plans stores, so the application tests' stand-in keeps SQLite's rules."""
    if request.param == "memory":
        users = MemoryUsers()
        memory = MemoryPlans(users)
        return PlansStore(memory, users, memory.changes.get)
    database = tmp_path / "test.db"
    initialize_database(database)
    return PlansStore(
        SqlitePlans(database), SqliteUserDirectory(database), lambda user: _recorded(database, user)
    )


def test_plans_start_off_with_no_default_and_no_plans_so_nobody_is_limited(
    store: PlansStore,
) -> None:
    store.people(ADMIN, MEMBER)

    assert store.plans.settings() == PlansSetting(enabled=False, default=None)
    assert store.plans.plans() == ()
    assert not store.plans.any_plans()
    assert store.plans.of(MEMBER.id) == UNLIMITED
    assert store.plans.of_users([ADMIN.id, MEMBER.id]) == {
        ADMIN.id: UNLIMITED,
        MEMBER.id: UNLIMITED,
    }


def test_plans_are_defined_changed_and_listed_by_name_then_key(store: PlansStore) -> None:
    team_b = Plan(PlanKey("team-b"), "Team", PlanLimits(10, 5, 5, SyncInterval.INSTANT))
    team_a = replace(team_b, key=PlanKey("team-a"))
    for plan in (FREE, team_b, FAMILY, team_a):
        store.plans.add(plan, NOW)
    starter = replace(FREE, name="Starter", limits=PlanLimits(2, None, None, SyncInterval.INSTANT))

    store.plans.change(starter, LATER)

    assert store.plans.any_plans()
    assert store.plans.get(FREE.key) == starter
    assert store.plans.get(PlanKey("missing")) is None
    assert store.plans.plans() == (
        PlanListing(FAMILY, is_default=False, people=0, limited_people=0),
        PlanListing(starter, is_default=False, people=0, limited_people=0),
        PlanListing(team_a, is_default=False, people=0, limited_people=0),
        PlanListing(team_b, is_default=False, people=0, limited_people=0),
    )


def test_a_key_another_plan_has_is_refused(store: PlansStore) -> None:
    store.plans.add(FREE, NOW)

    with pytest.raises(PlanKeyTaken):
        store.plans.add(replace(FREE, name="Another free plan"), LATER)

    assert store.plans.get(FREE.key) == FREE


def test_changing_a_plan_that_does_not_exist_is_refused(store: PlansStore) -> None:
    with pytest.raises(PlanNotFound):
        store.plans.change(FREE, NOW)

    assert not store.plans.any_plans()


def test_plans_turn_on_only_with_a_default_that_exists_and_turn_off_at_any_time(
    store: PlansStore,
) -> None:
    store.plans.add(FREE, NOW)

    with pytest.raises(PlansNeedDefault):
        store.plans.change_settings(True, None)
    with pytest.raises(PlanNotFound):
        store.plans.change_settings(True, FAMILY.key)
    refused = store.plans.settings()
    turned_on = store.plans.change_settings(True, FREE.key)
    with pytest.raises(PlansNeedDefault):
        store.plans.change_settings(True, None)
    turned_off = store.plans.change_settings(False, FREE.key)
    cleared = store.plans.change_settings(False, None)

    assert refused == PlansSetting(enabled=False, default=None)
    assert turned_on == PlansSetting(enabled=True, default=FREE.key)
    assert turned_off == PlansSetting(enabled=False, default=FREE.key)
    assert cleared == PlansSetting(enabled=False, default=None)
    assert store.plans.settings() == cleared


def test_a_plan_is_removed_only_when_it_is_not_the_default_and_nobody_has_it(
    store: PlansStore,
) -> None:
    store.people(ADMIN, MEMBER)
    plans_on(store.plans, FREE, FAMILY)
    starter = replace(FREE, key=PlanKey("starter"), name="Starter")
    store.plans.add(starter, NOW)
    store.plans.assign(MEMBER.id, FAMILY.key, BY_ADMIN)

    # The default is refused first, even though ADMIN has it too.
    with pytest.raises(PlanIsDefault):
        store.plans.remove(FREE.key)
    with pytest.raises(PlanInUse) as in_use:
        store.plans.remove(FAMILY.key)
    with pytest.raises(PlanNotFound):
        store.plans.remove(PlanKey("missing"))
    store.plans.remove(starter.key)

    assert in_use.value.people == 1
    assert [listing.plan for listing in store.plans.plans()] == [FAMILY, FREE]


def test_assigning_a_plan_records_how_who_and_when(store: PlansStore) -> None:
    store.people(ADMIN, MEMBER)
    store.plans.add(FAMILY, NOW)
    by_billing = AssignmentChange(AssignmentSource.BILLING, None, LATER)

    assigned = store.plans.assign(MEMBER.id, FAMILY.key, BY_ADMIN)
    with pytest.raises(PlanNotFound):
        store.plans.assign(MEMBER.id, PlanKey("missing"), by_billing)
    kept = (store.users.get(MEMBER.id), store.recorded(MEMBER.id))
    unknown = store.plans.assign(NOBODY, FAMILY.key, by_billing)
    returned = store.plans.assign(MEMBER.id, None, by_billing)

    assert assigned
    assert kept == (replace(MEMBER, plan=FAMILY.key), BY_ADMIN)
    assert not unknown
    assert returned
    assert store.users.get(MEMBER.id) == MEMBER
    assert store.recorded(MEMBER.id) == by_billing


def test_each_users_allowance_follows_the_setting_their_role_and_their_own_plan(
    store: PlansStore,
) -> None:
    store.people(ADMIN, MEMBER, NEWCOMER)
    plans_on(store.plans, FREE, FAMILY)
    for user in (ADMIN, MEMBER):
        store.plans.assign(user.id, FAMILY.key, BY_ADMIN)
    everyone = [ADMIN.id, MEMBER.id, NEWCOMER.id, NOBODY]

    on = store.plans.of_users(everyone)
    store.plans.change_settings(False, FREE.key)
    off = store.plans.of_users(everyone)

    assert on == {
        ADMIN.id: Allowance(AllowanceBasis.ADMINISTRATOR, assigned=FAMILY),
        MEMBER.id: Allowance(AllowanceBasis.PLAN, plan=FAMILY, assigned=FAMILY),
        NEWCOMER.id: Allowance(AllowanceBasis.PLAN, plan=FREE, on_default=True),
        NOBODY: UNLIMITED,
    }
    # With Plans off nobody is limited, and each User's own Plan is still shown as assigned.
    assert off == {
        ADMIN.id: Allowance(AllowanceBasis.PLANS_OFF, assigned=FAMILY),
        MEMBER.id: Allowance(AllowanceBasis.PLANS_OFF, assigned=FAMILY),
        NEWCOMER.id: UNLIMITED,
        NOBODY: UNLIMITED,
    }
    assert store.plans.of(MEMBER.id) == off[MEMBER.id]
    assert store.plans.of(NOBODY) == UNLIMITED


def test_everyone_without_a_plan_of_their_own_follows_a_new_default_at_once(
    store: PlansStore,
) -> None:
    store.people(ADMIN, MEMBER, NEWCOMER)
    plans_on(store.plans, FREE, FAMILY)
    store.plans.assign(MEMBER.id, FREE.key, BY_ADMIN)

    store.plans.change_settings(True, FAMILY.key)
    joined_later = User(UserId("joined"), "joined@example.test", Role.USER, UserState.ACTIVE, LATER)
    store.people(joined_later)

    assert store.plans.of_users([MEMBER.id, NEWCOMER.id, joined_later.id]) == {
        MEMBER.id: Allowance(AllowanceBasis.PLAN, plan=FREE, assigned=FREE),
        NEWCOMER.id: Allowance(AllowanceBasis.PLAN, plan=FAMILY, on_default=True),
        joined_later.id: Allowance(AllowanceBasis.PLAN, plan=FAMILY, on_default=True),
    }
    # Nothing was written for the Users who follow the default.
    assert store.recorded(NEWCOMER.id) is None


def test_a_plan_counts_everyone_who_has_it_and_the_people_it_limits(store: PlansStore) -> None:
    other_admin = replace(ADMIN, id=UserId("other-admin"), email="other-admin@example.test")
    store.people(ADMIN, other_admin, MEMBER, NEWCOMER, AWAY)
    for plan in (FREE, FAMILY):
        store.plans.add(plan, NOW)
    for user in (MEMBER, other_admin):
        store.plans.assign(user.id, FAMILY.key, BY_ADMIN)

    without_default = store.plans.plans()
    store.plans.change_settings(False, FREE.key)
    while_off = store.plans.plans()
    store.plans.change_settings(True, FREE.key)
    while_on = store.plans.plans()

    assert without_default == (
        PlanListing(FAMILY, is_default=False, people=2, limited_people=1),
        PlanListing(FREE, is_default=False, people=0, limited_people=0),
    )
    # The default counts everyone with no Plan of their own. Only active Users who do not
    # administer are limited, and they are counted whether or not Plans are on.
    expected = (
        PlanListing(FAMILY, is_default=False, people=2, limited_people=1),
        PlanListing(FREE, is_default=True, people=3, limited_people=1),
    )
    assert while_off == expected
    assert while_on == expected


def _sqlite(tmp_path: Path) -> tuple[Path, SqlitePlans]:
    database = tmp_path / "test.db"
    initialize_database(database)
    return database, SqlitePlans(database)


def test_the_allowances_of_many_users_are_read_in_chunks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, plans = _sqlite(tmp_path)
    plans_on(plans, FREE, FAMILY)
    users = [UserId(f"user-{number:04}") for number in range(1200)]
    with transaction(database) as connection:
        connection.executemany(
            """
            INSERT INTO users (id, email, password_hash, role, state, created_at, plan_key)
            VALUES (?, ?, 'scrypt$unusable', 'user', 'active', ?, ?)
            """,
            [
                (
                    user.value,
                    f"{user.value}@example.test",
                    NOW.isoformat(),
                    FAMILY.key.value if number % 2 else None,
                )
                for number, user in enumerate(users)
            ],
        )

    chunks: list[int] = []
    read_rows = plans_store._allowance_rows

    def counted(connection: sqlite3.Connection, chunk: Sequence[str]) -> list[sqlite3.Row]:
        chunks.append(len(chunk))
        return read_rows(connection, chunk)

    monkeypatch.setattr(plans_store, "_allowance_rows", counted)

    allowances = plans.of_users(users)

    # One read for each USERS_PER_QUERY (500) Users, so no statement passes SQLite's bound values.
    assert chunks == [500, 500, 200]
    assert len(allowances) == 1200
    assert allowances[users[0]] == Allowance(AllowanceBasis.PLAN, plan=FREE, on_default=True)
    assert allowances[users[1199]] == Allowance(AllowanceBasis.PLAN, plan=FAMILY, assigned=FAMILY)
    assert sum(allowance.on_default for allowance in allowances.values()) == 600


def test_a_sync_interval_this_release_does_not_know_reads_as_instant(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    database, plans = _sqlite(tmp_path)
    plans_on(plans, FREE)
    member = limited_user(database, plan=FREE.key.value)
    with transaction(database) as connection:
        connection.execute("UPDATE plans SET sync_interval = '2_minutes' WHERE key = 'free'")

    with caplog.at_level(logging.WARNING, logger="calendar_sync.infrastructure.persistence"):
        stored = plans.get(FREE.key)
        allowance = plans.of(member)
        listed = plans.plans()

    instant = replace(FREE, limits=replace(FREE.limits, sync_interval=SyncInterval.INSTANT))
    assert stored == instant
    assert allowance == Allowance(AllowanceBasis.PLAN, plan=instant, assigned=instant)
    assert [listing.plan for listing in listed] == [instant]
    assert set(caplog.messages) == {
        "Plan free has a sync interval this release does not know; it syncs instantly"
    }


def test_a_plan_key_this_release_cannot_read_is_left_out_and_never_breaks_a_read(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    database, plans = _sqlite(tmp_path)
    plans_on(plans, FREE)
    member = limited_user(database)
    with transaction(database) as connection:
        # A later release may write a key this one refuses.
        connection.execute(
            """
            INSERT INTO plans (key, name, sync_interval, created_at, updated_at)
            VALUES ('Later_Key', 'Later', 'instant', ?, ?)
            """,
            (NOW.isoformat(), NOW.isoformat()),
        )
        connection.execute("UPDATE users SET plan_key = 'Later_Key' WHERE id = ?", (member.value,))

    with caplog.at_level(logging.WARNING, logger="calendar_sync.infrastructure.persistence"):
        allowance = plans.of(member)
        listed = plans.plans()

    assert allowance == Allowance(AllowanceBasis.PLAN, plan=FREE, on_default=True)
    assert [listing.plan for listing in listed] == [FREE]
    assert (
        "Plan Later_Key is stored in a form this release cannot read; it is left out"
        in caplog.messages
    )


def test_a_default_this_release_cannot_read_limits_nobody(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    database, plans = _sqlite(tmp_path)
    plans_on(plans, FREE)
    member = limited_user(database)
    with transaction(database) as connection:
        connection.execute(
            """
            INSERT INTO plans (key, name, sync_interval, created_at, updated_at)
            VALUES ('Later_Key', 'Later', 'instant', ?, ?)
            """,
            (NOW.isoformat(), NOW.isoformat()),
        )
        connection.execute("UPDATE installation_settings SET default_plan_key = 'Later_Key'")

    with caplog.at_level(logging.WARNING, logger="calendar_sync.infrastructure.persistence"):
        allowance = plans.of(member)
        setting = plans.settings()

    # Plans on with no Plan found reads as Plans off: a fault in Plans never limits anyone.
    assert allowance == UNLIMITED
    assert setting == PlansSetting(enabled=True, default=None)
    assert (
        f"Plans are on, but User {member.value} has no Plan; nothing limits them" in caplog.messages
    )


def test_the_installation_reads_and_changes_plans_through_one_store(tmp_path: Path) -> None:
    adapters = build_adapters(Settings(tmp_path / "test.db"))

    assert isinstance(adapters.allowances, SqlitePlans)
    assert adapters.plan_catalog is adapters.allowances
    assert adapters.plan_assignments is adapters.allowances
```

- [ ] **Step 2: Run the store tests to verify they fail**

Run: `.venv/bin/pytest tests/adapters/test_plans_store.py`

Expected: a collection error, `ImportError: cannot import name 'PlanKeyTaken' from 'calendar_sync.application.identity.errors'`.

- [ ] **Step 3: Implement the Plans errors**

In `src/calendar_sync/application/identity/errors.py`, add at the end of the file, after
`InvalidIntegrationTokenName`:

```python
class PlanNotFound(ApplicationError):
    """No Plan has this key."""


class PlanKeyTaken(ApplicationError):
    """Another Plan already has this key."""
```

Raise sites pass the message: `PlanNotFound(f"plan {key.value} does not exist")` and
`PlanKeyTaken(f"a plan with the key {plan.key.value} already exists")`.

- [ ] **Step 4: Implement the identity Plans ports**

In `src/calendar_sync/application/identity/ports.py`, replace the module docstring:

```python
"""Ports of identity and access: Users, sessions, links, and Integration Tokens."""
```

with:

```python
"""Ports of identity and access: Users, sessions, links, Integration Tokens, and Plans."""
```

replace:

```python
from calendar_sync.domain.access import RegistrationPolicy, Role, User, UserId, UserState
```

with:

```python
from calendar_sync.domain.access import RegistrationPolicy, Role, User, UserId, UserState
from calendar_sync.domain.plans import AssignmentSource, Plan, PlanKey
```

and add at the end of the file, after `class IntegrationTokenAuthentication`:

```python
@dataclass(frozen=True, slots=True)
class PlansSetting:
    """Whether Plans limit anyone, and the Default Plan of everyone with no Plan of their own."""

    enabled: bool
    default: PlanKey | None


@dataclass(frozen=True, slots=True)
class PlanListing:
    """A Plan as Administration lists it."""

    plan: Plan
    is_default: bool
    people: int
    """Everyone who has it: their own Plan, plus, for the default, everyone with none."""
    limited_people: int
    """Active Users who do not administer and have it, whom it limits while Plans are on."""


class PlanCatalog(Protocol):
    """The Plans an Installation Administrator defines, and whether they are on (ADR 0038)."""

    def settings(self) -> PlansSetting: ...

    def change_settings(self, enabled: bool, default: PlanKey | None) -> PlansSetting:
        """One step: raises PlanNotFound when `default` names no Plan, PlansNeedDefault when
        turning Plans on without a default."""
        ...

    def plans(self) -> Sequence[PlanListing]:
        """Every Plan, by name then key."""
        ...

    def any_plans(self) -> bool: ...

    def get(self, key: PlanKey) -> Plan | None: ...

    def add(self, plan: Plan, at: datetime) -> None:
        """Raises PlanKeyTaken."""
        ...

    def change(self, plan: Plan, at: datetime) -> None:
        """The key never changes; raises PlanNotFound."""
        ...

    def remove(self, key: PlanKey) -> None:
        """One step: raises PlanNotFound, PlanIsDefault, or PlanInUse(people)."""
        ...


@dataclass(frozen=True, slots=True)
class AssignmentChange:
    """How a User's own Plan was last set: by an administrator now, by billing later."""

    source: AssignmentSource
    actor: UserId | None
    """The administrator who set it; None when billing set it."""
    at: datetime


class PlanAssignments(Protocol):
    """The one way a User's own Plan changes; administrators now, billing later (ADR 0038)."""

    def assign(self, user: UserId, plan: PlanKey | None, change: AssignmentChange) -> bool:
        """Set the User's own Plan, None for the Default Plan, recording the change; False when
        no such User. Raises PlanNotFound."""
        ...
```

- [ ] **Step 5: Implement the `Allowances` port**

In `src/calendar_sync/application/sync/ports.py`, replace:

```python
from calendar_sync.domain.providers import ProviderFailureKind
from calendar_sync.domain.runs import RuleRunOutcome, RunKind
```

with:

```python
from calendar_sync.domain.plans import Allowance
from calendar_sync.domain.providers import ProviderFailureKind
from calendar_sync.domain.runs import RuleRunOutcome, RunKind
```

and replace:

```python
    def __call__(self) -> UnitOfWork: ...


@dataclass(frozen=True, slots=True)
class ScheduledRule:
```

with:

```python
    def __call__(self) -> UnitOfWork: ...


class Allowances(Protocol):
    """What each User may use now, as their Plan allows (ADR 0038). Declared here so sync
    enforces limits without importing identity; SqlitePlans implements it."""

    def of(self, user: UserId) -> Allowance:
        """The User's Allowance, read now. Raises when it cannot be read, so a limit check
        fails closed; a User not found reads as UNLIMITED."""
        ...

    def of_users(self, users: Collection[UserId]) -> Mapping[UserId, Allowance]:
        """Each User's Allowance, in one read per 500 Users. A User not found reads as
        UNLIMITED."""
        ...


@dataclass(frozen=True, slots=True)
class ScheduledRule:
```

(`Collection` and `Mapping` are already imported from `collections.abc` in this module.)

- [ ] **Step 6: Move the chunk size beside the connection settings**

In `src/calendar_sync/infrastructure/persistence/connections.py`, replace:

```python
BUSY_TIMEOUT_SECONDS = 5.0
```

with:

```python
BUSY_TIMEOUT_SECONDS = 5.0
USERS_PER_QUERY = 500
"""Users read together, well under SQLite's limit on bound values in one statement."""
```

In `src/calendar_sync/infrastructure/persistence/installation.py`, replace:

```python
from calendar_sync.infrastructure.persistence.connections import open_connection
```

with:

```python
from calendar_sync.infrastructure.persistence.connections import USERS_PER_QUERY, open_connection
```

delete these lines (they sit after `pending_instant_runs`, before `_upkeep_due`), with the two
blank lines that follow them:

```python
_USERS_PER_QUERY = 500
"""Users read together, well under SQLite's limit on bound values in one statement."""
```

and rename the four remaining uses of `_USERS_PER_QUERY` to `USERS_PER_QUERY` (two in
`resource_use`, two in `status_records`), so each reads:

```python
        for start in range(0, len(ordered), USERS_PER_QUERY):
            chunk = ordered[start : start + USERS_PER_QUERY]
```

- [ ] **Step 7: Implement `SqlitePlans`**

Create `src/calendar_sync/infrastructure/persistence/plans.py`:

```python
"""Plans, the Plans setting, and each User's own Plan (ADR 0038)."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Collection, Mapping, Sequence
from datetime import datetime
from pathlib import Path

from calendar_sync.application.identity.errors import PlanKeyTaken, PlanNotFound
from calendar_sync.application.identity.ports import AssignmentChange, PlanListing, PlansSetting
from calendar_sync.domain.access import Role, UserId
from calendar_sync.domain.plans import (
    UNLIMITED,
    Allowance,
    InvalidPlan,
    Plan,
    PlanInUse,
    PlanKey,
    PlanLimits,
    SyncInterval,
    allowance_for,
    require_plans_setting,
    require_removable,
)
from calendar_sync.infrastructure.persistence.connections import USERS_PER_QUERY, transaction

logger = logging.getLogger(__name__)


class SqlitePlans:
    """Plans, the Plans setting, and each User's own Plan (ADR 0038). Implements Allowances,
    PlanCatalog, and PlanAssignments; each client depends only on the port it uses.

    Reads never catch a database error: a limit check fails closed on it, and every other caller
    decides to fail open. Writes hold the write lock from their first read, so a limit check that
    already holds it either sees the change or makes it wait.
    """

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path

    # Allowances

    def of(self, user: UserId) -> Allowance:
        return self.of_users([user])[user]

    def of_users(self, users: Collection[UserId]) -> Mapping[UserId, Allowance]:
        allowances = dict.fromkeys(users, UNLIMITED)
        ordered = sorted({user.value for user in users})
        with transaction(self._database_path) as connection:
            for start in range(0, len(ordered), USERS_PER_QUERY):
                for row in _allowance_rows(connection, ordered[start : start + USERS_PER_QUERY]):
                    allowances[UserId(str(row["id"]))] = _allowance(row)
        return allowances

    # PlanCatalog

    def settings(self) -> PlansSetting:
        with transaction(self._database_path) as connection:
            return _setting(connection)

    def change_settings(self, enabled: bool, default: PlanKey | None) -> PlansSetting:
        with transaction(self._database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            if default is not None:
                _require_plan(connection, default)
            require_plans_setting(enabled, default)
            # Migration 22 creates the one row.
            connection.execute(
                """
                UPDATE installation_settings SET plans_enabled = ?, default_plan_key = ?
                WHERE singleton = 1
                """,
                (int(enabled), default.value if default is not None else None),
            )
            return _setting(connection)

    def plans(self) -> Sequence[PlanListing]:
        with transaction(self._database_path) as connection:
            rows = connection.execute(
                """
                SELECT plans.*, plans.key IS setting.default_plan_key AS is_default,
                    COUNT(holder.id) AS people,
                    COUNT(CASE WHEN holder.role = 'user' AND holder.state = 'active'
                        THEN holder.id END) AS limited_people
                FROM plans
                LEFT JOIN installation_settings setting ON setting.singleton = 1
                LEFT JOIN users holder ON holder.plan_key = plans.key
                    OR (holder.plan_key IS NULL AND plans.key IS setting.default_plan_key)
                GROUP BY plans.key
                ORDER BY plans.name, plans.key
                """
            ).fetchall()
        listings = (_listing(row) for row in rows)
        return tuple(listing for listing in listings if listing is not None)

    def any_plans(self) -> bool:
        with transaction(self._database_path) as connection:
            return connection.execute("SELECT 1 FROM plans LIMIT 1").fetchone() is not None

    def get(self, key: PlanKey) -> Plan | None:
        with transaction(self._database_path) as connection:
            row = connection.execute("SELECT * FROM plans WHERE key = ?", (key.value,)).fetchone()
        return _plan(row) if row is not None else None

    def add(self, plan: Plan, at: datetime) -> None:
        try:
            with transaction(self._database_path) as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    INSERT INTO plans (
                        key, name, rule_limit, account_limit, token_limit, sync_interval,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (*_plan_values(plan), at.isoformat(), at.isoformat()),
                )
        except sqlite3.IntegrityError as error:
            if "plans.key" not in str(error):
                raise
            raise PlanKeyTaken(f"a plan with the key {plan.key.value} already exists") from error

    def change(self, plan: Plan, at: datetime) -> None:
        with transaction(self._database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            changed = connection.execute(
                """
                UPDATE plans SET name = ?, rule_limit = ?, account_limit = ?, token_limit = ?,
                    sync_interval = ?, updated_at = ?
                WHERE key = ?
                """,
                (*_plan_values(plan)[1:], at.isoformat(), plan.key.value),
            ).rowcount
            if changed == 0:
                raise PlanNotFound(f"plan {plan.key.value} does not exist")

    def remove(self, key: PlanKey) -> None:
        with transaction(self._database_path) as connection:
            # Held from the counts to the delete, so nobody is given the Plan meanwhile.
            connection.execute("BEGIN IMMEDIATE")
            _require_plan(connection, key)
            people = int(
                connection.execute(
                    "SELECT COUNT(*) FROM users WHERE plan_key = ?", (key.value,)
                ).fetchone()[0]
            )
            require_removable(key, _setting(connection).default, people)
            try:
                connection.execute("DELETE FROM plans WHERE key = ?", (key.value,))
            except sqlite3.IntegrityError as error:
                # A reference this release cannot read, such as a default a later one wrote.
                raise PlanInUse(people) from error

    # PlanAssignments

    def assign(self, user: UserId, plan: PlanKey | None, change: AssignmentChange) -> bool:
        with transaction(self._database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            if plan is not None:
                _require_plan(connection, plan)
            assigned = connection.execute(
                """
                UPDATE users SET plan_key = ?, plan_assigned_by = ?, plan_assigner_id = ?,
                    plan_assigned_at = ?
                WHERE id = ?
                """,
                (
                    plan.value if plan is not None else None,
                    change.source.value,
                    change.actor.value if change.actor is not None else None,
                    change.at.isoformat(),
                    user.value,
                ),
            ).rowcount
        return assigned == 1


def _allowance_rows(connection: sqlite3.Connection, users: Sequence[str]) -> list[sqlite3.Row]:
    """Each of `users` with the setting, their own Plan, and the Default Plan, in one row."""
    marks = ", ".join("?" * len(users))
    # Interpolates only `?` placeholders; values stay bound.
    return connection.execute(
        f"""
        SELECT users.id, users.role, COALESCE(setting.plans_enabled, 0) AS plans_enabled,
            own.key AS own_key, own.name AS own_name, own.rule_limit AS own_rule_limit,
            own.account_limit AS own_account_limit, own.token_limit AS own_token_limit,
            own.sync_interval AS own_sync_interval,
            default_plan.key AS default_key, default_plan.name AS default_name,
            default_plan.rule_limit AS default_rule_limit,
            default_plan.account_limit AS default_account_limit,
            default_plan.token_limit AS default_token_limit,
            default_plan.sync_interval AS default_sync_interval
        FROM users
        LEFT JOIN installation_settings setting ON setting.singleton = 1
        LEFT JOIN plans own ON own.key = users.plan_key
        LEFT JOIN plans default_plan ON default_plan.key = setting.default_plan_key
        WHERE users.id IN ({marks})
        """,  # noqa: S608
        users,
    ).fetchall()


def _allowance(row: sqlite3.Row) -> Allowance:
    plans_on = bool(row["plans_enabled"])
    administers = row["role"] == Role.INSTALLATION_ADMINISTRATOR.value
    own, default = _plan(row, "own_"), _plan(row, "default_")
    if plans_on and not administers and own is None and default is None:
        # Turning Plans on needs a default, so this cannot happen; a fault never limits anyone.
        logger.warning("Plans are on, but User %s has no Plan; nothing limits them", row["id"])
    return allowance_for(plans_on=plans_on, administers=administers, own=own, default=default)


def _setting(connection: sqlite3.Connection) -> PlansSetting:
    row = connection.execute(
        "SELECT plans_enabled, default_plan_key FROM installation_settings WHERE singleton = 1"
    ).fetchone()
    if row is None:
        return PlansSetting(enabled=False, default=None)
    return PlansSetting(bool(row["plans_enabled"]), _stored_key(row["default_plan_key"]))


def _require_plan(connection: sqlite3.Connection, key: PlanKey) -> None:
    if connection.execute("SELECT 1 FROM plans WHERE key = ?", (key.value,)).fetchone() is None:
        raise PlanNotFound(f"plan {key.value} does not exist")


def _listing(row: sqlite3.Row) -> PlanListing | None:
    plan = _plan(row)
    if plan is None:
        return None
    return PlanListing(
        plan, bool(row["is_default"]), int(row["people"]), int(row["limited_people"])
    )


def _plan(row: sqlite3.Row, prefix: str = "") -> Plan | None:
    """The Plan in `row`'s columns named with `prefix`. None when there is none, or when a later
    release stored it in a form this one cannot read, so a stored Plan never breaks a read."""
    key = row[f"{prefix}key"]
    if key is None:
        return None
    try:
        return Plan(
            PlanKey(str(key)),
            str(row[f"{prefix}name"]),
            PlanLimits(
                _count(row[f"{prefix}rule_limit"]),
                _count(row[f"{prefix}account_limit"]),
                _count(row[f"{prefix}token_limit"]),
                _interval(str(key), str(row[f"{prefix}sync_interval"])),
            ),
        )
    except InvalidPlan:
        logger.warning("Plan %s is stored in a form this release cannot read; it is left out", key)
        return None


def _stored_key(stored: str | None) -> PlanKey | None:
    if stored is None:
        return None
    try:
        return PlanKey(stored)
    except InvalidPlan:
        logger.warning(
            "Plan %s is stored in a form this release cannot read; it is left out", stored
        )
        return None


def _count(stored: int | None) -> int | None:
    """A stored limit; NULL is unlimited."""
    return None if stored is None else int(stored)


def _interval(key: str, stored: str) -> SyncInterval:
    try:
        return SyncInterval(stored)
    except ValueError:
        logger.warning(
            "Plan %s has a sync interval this release does not know; it syncs instantly", key
        )
        return SyncInterval.INSTANT


def _plan_values(plan: Plan) -> tuple[object, ...]:
    limits = plan.limits
    return (
        plan.key.value,
        plan.name,
        limits.rules,
        limits.connected_accounts,
        limits.integration_tokens,
        limits.sync_interval.value,
    )
```

Notes for the reader of this module: `of_users` answers every User asked for, `UNLIMITED` for one
the database does not have; `administers` reads the role only, so a disabled administrator is
still unlimited; `assign` raises `sqlite3.IntegrityError` when `change.actor` names no User (the
foreign key on `plan_assigner_id`), which the use cases never do, because the actor is the
administrator making the request.

- [ ] **Step 8: Implement the in-memory Plans store and the test helpers**

In `tests/identity_fakes.py`, replace the imports:

```python
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from calendar_sync.application.identity.errors import EmailTaken
from calendar_sync.application.identity.ports import (
    IssuedLink,
    PendingInvitation,
    Session,
    UserPage,
    UserQuery,
    UserSort,
)
```

with:

```python
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from calendar_sync.application.identity.errors import EmailTaken, PlanKeyTaken, PlanNotFound
from calendar_sync.application.identity.ports import (
    AssignmentChange,
    IssuedLink,
    PendingInvitation,
    PlanListing,
    PlansSetting,
    Session,
    UserPage,
    UserQuery,
    UserSort,
)
```

and replace:

```python
    require_administrator_remains,
    require_registration_change,
)
```

with:

```python
    require_administrator_remains,
    require_registration_change,
)
from calendar_sync.domain.plans import (
    UNLIMITED,
    Allowance,
    Plan,
    PlanKey,
    allowance_for,
    require_plans_setting,
    require_removable,
)
```

Then add at the end of the file, after `class MemoryResetLinks`:

```python
@dataclass
class MemoryPlans:
    """Plans as SqlitePlans keeps them; each User's role and own Plan come from `users`."""

    users: MemoryUsers = field(default_factory=MemoryUsers)
    enabled: bool = False
    default: PlanKey | None = None
    catalog: dict[PlanKey, Plan] = field(default_factory=dict)
    changes: dict[UserId, AssignmentChange] = field(default_factory=dict)
    """How each User's own Plan was last set, as SQLite's users table records it."""

    def of(self, user: UserId) -> Allowance:
        found = self.users.get(user)
        if found is None:
            return UNLIMITED
        return allowance_for(
            plans_on=self.enabled,
            administers=found.administers,
            own=self.catalog.get(found.plan) if found.plan is not None else None,
            default=self.catalog.get(self.default) if self.default is not None else None,
        )

    def of_users(self, users: Collection[UserId]) -> dict[UserId, Allowance]:
        return {user: self.of(user) for user in users}

    def settings(self) -> PlansSetting:
        return PlansSetting(self.enabled, self.default)

    def change_settings(self, enabled: bool, default: PlanKey | None) -> PlansSetting:
        if default is not None:
            self._require(default)
        require_plans_setting(enabled, default)
        self.enabled, self.default = enabled, default
        return self.settings()

    def plans(self) -> tuple[PlanListing, ...]:
        ordered = sorted(self.catalog.values(), key=lambda plan: (plan.name, plan.key.value))
        return tuple(self._listing(plan) for plan in ordered)

    def any_plans(self) -> bool:
        return bool(self.catalog)

    def get(self, key: PlanKey) -> Plan | None:
        return self.catalog.get(key)

    def add(self, plan: Plan, at: datetime) -> None:
        if plan.key in self.catalog:
            raise PlanKeyTaken(f"a plan with the key {plan.key.value} already exists")
        self.catalog[plan.key] = plan

    def change(self, plan: Plan, at: datetime) -> None:
        self._require(plan.key)
        self.catalog[plan.key] = plan

    def remove(self, key: PlanKey) -> None:
        self._require(key)
        people = sum(user.plan == key for user in self.users.users.values())
        require_removable(key, self.default, people)
        del self.catalog[key]

    def assign(self, user: UserId, plan: PlanKey | None, change: AssignmentChange) -> bool:
        if plan is not None:
            self._require(plan)
        found = self.users.get(user)
        if found is None:
            return False
        self.users.users[user] = replace(found, plan=plan)
        self.changes[user] = change
        return True

    def _require(self, key: PlanKey) -> None:
        if key not in self.catalog:
            raise PlanNotFound(f"plan {key.value} does not exist")

    def _listing(self, plan: Plan) -> PlanListing:
        holders = [
            user
            for user in self.users.users.values()
            if user.plan == plan.key or (user.plan is None and plan.key == self.default)
        ]
        limited = [
            user for user in holders if not user.administers and user.state is UserState.ACTIVE
        ]
        return PlanListing(plan, plan.key == self.default, len(holders), len(limited))


@dataclass
class BrokenAllowances:
    """An Allowances whose every read raises, as a locked or failing database would."""

    def of(self, user: UserId) -> Allowance:
        raise RuntimeError("database is locked")

    def of_users(self, users: Collection[UserId]) -> Mapping[UserId, Allowance]:
        raise RuntimeError("database is locked")
```

Both sort Plans by name, then key, in code point order, as SQLite's default `BINARY` collation
does, so the two stores list Plans alike.

In `tests/users.py`, add `limited_user` right before `add_account` (after `add_user`):

```python
def limited_user(
    database: Path, user: UserId = OTHER_USER, *, plan: str | None = None, email: str | None = None
) -> UserId:
    """A User Plans can limit: role `user`, with `plan` as their own Plan when given (it must
    exist). `add_user` records an Installation Administrator, whom no Plan limits."""
    add_user(database, user, email=email, role="user")
    if plan is not None:
        with transaction(database) as connection:
            connection.execute("UPDATE users SET plan_key = ? WHERE id = ?", (plan, user.value))
    return user
```

Like `add_user`, it records nobody when a User with this identifier exists already, so call it
before anything else adds that User. `plan` is a Plan key, such as `FREE.key.value`, of a Plan
already defined (the foreign key refuses any other).

- [ ] **Step 9: Compose one Plans store for the installation**

In `src/calendar_sync/bootstrap/container.py`, replace the import statement:

```python
from calendar_sync.application.identity.ports import (
    IntegrationTokenAuthentication,
    IntegrationTokens,
    Invitations,
    PasswordHasher,
    PasswordResetLinks,
    RegistrationSettings,
    Sessions,
    SignInThrottle,
    UserDirectory,
)
```

with:

```python
from calendar_sync.application.identity.ports import (
    IntegrationTokenAuthentication,
    IntegrationTokens,
    Invitations,
    PasswordHasher,
    PasswordResetLinks,
    PlanAssignments,
    PlanCatalog,
    RegistrationSettings,
    Sessions,
    SignInThrottle,
    UserDirectory,
)
```

replace the import statement:

```python
from calendar_sync.application.sync.ports import (
    AccountCalendars,
    CalendarProvider,
    ConnectedAccountRepository,
    IncidentNotifications,
    IncidentRepository,
    ProviderCallStats,
    RuleHealthRecords,
    RunIdGenerator,
    UnitOfWorkFactory,
)
```

with:

```python
from calendar_sync.application.sync.ports import (
    AccountCalendars,
    Allowances,
    CalendarProvider,
    ConnectedAccountRepository,
    IncidentNotifications,
    IncidentRepository,
    ProviderCallStats,
    RuleHealthRecords,
    RunIdGenerator,
    UnitOfWorkFactory,
)
```

replace:

```python
from calendar_sync.infrastructure.persistence.migrations import initialize_database
from calendar_sync.infrastructure.persistence.registration import (
```

with:

```python
from calendar_sync.infrastructure.persistence.migrations import initialize_database
from calendar_sync.infrastructure.persistence.plans import SqlitePlans
from calendar_sync.infrastructure.persistence.registration import (
```

In `class Adapters`, replace:

```python
    watch_inbox: WatchNoticeInbox
    notifications: Callable[[UserId], IncidentNotifications | None] = lambda _owner: None
```

with:

```python
    watch_inbox: WatchNoticeInbox
    allowances: Allowances
    """What each User may use now, as their Plan allows (ADR 0038)."""
    plan_catalog: PlanCatalog
    plan_assignments: PlanAssignments
    """The one way a User's own Plan changes: administrators now, billing later."""
    notifications: Callable[[UserId], IncidentNotifications | None] = lambda _owner: None
```

In `build_adapters`, replace:

```python
    users = SqliteUserDirectory(database)
    mail = _mail_server(settings)
```

with:

```python
    users = SqliteUserDirectory(database)
    plans = SqlitePlans(database)
    mail = _mail_server(settings)
```

and replace:

```python
        watch_inbox=SqliteWatchNoticeInbox(database),
        notifications=lambda owner: (
```

with:

```python
        watch_inbox=SqliteWatchNoticeInbox(database),
        allowances=plans,
        plan_catalog=plans,
        plan_assignments=plans,
        notifications=lambda owner: (
```

`build_adapters` is the only place that constructs `Adapters`; tests and `scripts/dev_preview.py`
take theirs from it, so no other call site changes. Tasks 5 and 11 later pass the same `plans` to
`PlanCadence` and to `SqliteConnectedAccountStore`.

- [ ] **Step 10: Run the store tests to verify they pass**

Run: `.venv/bin/pytest tests/adapters/test_plans_store.py tests/adapters/test_composition.py`

Expected: all pass (the shared store tests run twice, as `[sqlite]` and `[memory]`).

- [ ] **Step 11: Write the failing return to setup test**

In `tests/adapters/test_users_store.py`, replace:

```python
from calendar_sync.application.identity.ports import IssuedLink, UserPage, UserQuery, UserSort
```

with:

```python
from calendar_sync.application.identity.ports import (
    IssuedLink,
    PlansSetting,
    RegistrationSettings,
    UserDirectory,
    UserPage,
    UserQuery,
    UserSort,
)
```

replace (task 3 added the first line):

```python
from calendar_sync.domain.plans import PlanKey
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.persistence.migrations import initialize_database
```

with:

```python
from calendar_sync.domain.plans import UNLIMITED, PlanKey
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.persistence.migrations import initialize_database
from calendar_sync.infrastructure.persistence.plans import SqlitePlans
```

and replace:

```python
from tests.identity_fakes import MemoryUsers
```

with:

```python
from tests.identity_fakes import MemoryPlans, MemoryRegistration, MemoryUsers
from tests.plans import FAMILY, FREE, plans_on
```

Then add this helper and test right after
`test_returning_to_setup_chooses_only_me_and_revokes_every_invitation_in_one_step`:

```python
def _setup_with_plans(
    kind: str, tmp_path: Path
) -> tuple[UserDirectory, RegistrationSettings, SqlitePlans | MemoryPlans]:
    if kind == "memory":
        users = MemoryUsers()
        plans = MemoryPlans(users)
        return users, MemoryRegistration(users, plans=plans), plans
    database = _database(tmp_path)
    return (
        SqliteUserDirectory(database),
        SqliteRegistrationSettings(database),
        SqlitePlans(database),
    )


@pytest.mark.parametrize("kind", ["sqlite", "memory"])
def test_returning_to_setup_turns_plans_off_and_keeps_them_for_the_next_administrator(
    kind: str, tmp_path: Path
) -> None:
    users, registration, plans = _setup_with_plans(kind, tmp_path)
    users.add(FIRST, "hash-1")
    plans_on(plans, FREE, FAMILY)
    # The last User deletes their account, and the installation returns to setup.
    users.delete(FIRST.id)

    registration.return_to_setup(NOW)
    new_first = replace(FIRST, id=UserId("new-first"), email="new-first@example.test")
    assert users.add_first(new_first, "hash-2")
    users.add(SECOND, "hash-3")

    assert plans.settings() == PlansSetting(enabled=False, default=FREE.key)
    assert [listing.plan for listing in plans.plans()] == [FAMILY, FREE]
    # Nobody inherits a limit the earlier installation set: neither the new first User nor
    # anyone who joins later, until an administrator turns Plans on again.
    assert plans.of_users([new_first.id, SECOND.id]) == {
        new_first.id: UNLIMITED,
        SECOND.id: UNLIMITED,
    }
```

- [ ] **Step 12: Run it to verify it fails**

Run: `.venv/bin/pytest tests/adapters/test_users_store.py -k returning_to_setup_turns_plans_off`

Expected: 2 failed. `[sqlite]` fails with `AssertionError` (`enabled: True != False`: Plans are
still on); `[memory]` fails with
`TypeError: MemoryRegistration.__init__() got an unexpected keyword argument 'plans'`.

- [ ] **Step 13: Turn Plans off when the installation returns to setup**

In `src/calendar_sync/infrastructure/persistence/registration.py`, replace the whole
`SqliteRegistrationSettings.return_to_setup` method with:

```python
    def return_to_setup(self, at: datetime) -> None:
        with transaction(self._database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            users = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            require_registration_change(RegistrationPolicy.ONLY_ME, int(users))
            # Plans turn off and keep their definitions, so a new first User inherits no limit.
            connection.execute(
                """
                UPDATE installation_settings SET registration_policy = ?, plans_enabled = 0
                WHERE singleton = 1
                """,
                (RegistrationPolicy.ONLY_ME.value,),
            )
            connection.execute(
                f"UPDATE invitations SET revoked_at = ? WHERE {_INVITATION_USABLE}",  # noqa: S608
                (at.isoformat(), at.isoformat()),
            )
```

In `src/calendar_sync/application/identity/ports.py`, class `RegistrationSettings`, replace:

```python
    def return_to_setup(self, at: datetime) -> None:
        """Choose Only Me and revoke every Invitation still usable at `at`, in one step, so a
        failure between them cannot leave an old Invitation for the next setup. Raises
        OnlyMeNeedsOneUser, changing nothing, while another User exists."""
        ...
```

with:

```python
    def return_to_setup(self, at: datetime) -> None:
        """Choose Only Me, revoke every Invitation still usable at `at`, and turn Plans off,
        keeping their definitions, in one step, so a failure between them cannot leave an old
        Invitation or a hidden limit for the next setup. Raises OnlyMeNeedsOneUser, changing
        nothing, while another User exists."""
        ...
```

In `tests/identity_fakes.py`, replace the whole `class MemoryRegistration` with:

```python
@dataclass
class MemoryRegistration:
    users: MemoryUsers
    current: RegistrationPolicy = RegistrationPolicy.ONLY_ME
    links: list[_Link] = field(default_factory=list)
    """The Invitations' links, shared with MemoryInvitations as SQLite shares one database."""
    plans: MemoryPlans | None = None
    """The installation's Plans, which returning to setup turns off as SQLite's does."""

    def policy(self) -> RegistrationPolicy:
        return self.current

    def set_policy(self, policy: RegistrationPolicy) -> None:
        require_registration_change(policy, self.users.count())
        self.current = policy

    def return_to_setup(self, at: datetime) -> None:
        require_registration_change(RegistrationPolicy.ONLY_ME, self.users.count())
        self.current = RegistrationPolicy.ONLY_ME
        for link in self.links:
            if link.usable(at):
                link.revoked_at = at
        if self.plans is not None:
            self.plans.enabled = False
```

(`MemoryPlans` is defined later in the module; the module has `from __future__ import
annotations`, so the annotation resolves.)

- [ ] **Step 14: Run the tests and the backend gate**

Run: `.venv/bin/pytest tests/adapters/test_plans_store.py tests/adapters/test_users_store.py tests/adapters/test_persistence_contract.py tests/adapters/test_composition.py tests/test_dev_preview.py`

Expected: all pass.

Then the whole backend gate:

```sh
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy
.venv/bin/lint-imports
.venv/bin/pytest --cov --cov-report=term-missing --cov-fail-under=80
```

Expected: `ruff format` reports every file already formatted; `ruff check` says
`All checks passed!`; mypy says `Success: no issues found`; lint-imports reports
`Contracts: 10 kept, 0 broken.` (identity and infrastructure import `domain.plans`, sync declares
`Allowances` without importing identity); pytest passes with coverage at or above 80%.

- [ ] **Step 15: Commit**

```sh
git add src/calendar_sync/application/sync/ports.py \
  src/calendar_sync/application/identity/errors.py \
  src/calendar_sync/application/identity/ports.py \
  src/calendar_sync/infrastructure/persistence/plans.py \
  src/calendar_sync/infrastructure/persistence/connections.py \
  src/calendar_sync/infrastructure/persistence/installation.py \
  src/calendar_sync/infrastructure/persistence/registration.py \
  src/calendar_sync/bootstrap/container.py \
  tests/identity_fakes.py \
  tests/users.py \
  tests/plans.py \
  tests/adapters/test_plans_store.py \
  tests/adapters/test_users_store.py
git commit -m "$(cat <<'EOF'
Store Plans and each User's own Plan, and turn Plans off when the installation returns to setup

SqlitePlans keeps the Plans an administrator defines, whether they are
on, the Default Plan, and who set each User's own Plan and when. It
answers each User's Allowance, and never fails a read on a key or sync
interval a later release stored. Every write holds the write lock from
its first read. MemoryPlans keeps the same rules for application tests.
Returning to setup turns Plans off and keeps them, so a new first User
inherits no limit.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
)"
```

## Part 3: Sync Cadence and problem codes (Tasks 5 and 6)

### Task 5: PlanCadence and fail-open cadence readers

Each User's Sync Cadence now comes from their Allowance (`PlanCadence`). Every reader that is not a
limit check fails open: Instant Sync dispatch never drops a request, watch upkeep never retires a
watch, Installation Hints count the User as wanting Instant Sync, and the account switch and the
rules API show the default cadence when Plans cannot be read (contract section 3.9).

Before you start: tasks 1 and 4 are merged. This task uses `Allowance.cadence`,
`AllowanceBasis`, `AssignmentSource`, `UNLIMITED` (task 1), the `Allowances` port in
`application/sync/ports.py`, `AssignmentChange` in `application/identity/ports.py`,
`MemoryPlans` and `BrokenAllowances` in `tests/identity_fakes.py`, `FREE`, `FAMILY`, `plans_on`
in `tests/plans.py`, `limited_user` in `tests/users.py`, and `Adapters.allowances`,
`Adapters.plan_catalog`, and `plans = SqlitePlans(database)` in `build_adapters` (task 4).

**Files:**
- Modify: `src/calendar_sync/application/sync/watch_ports.py` (imports, `logger`, `SyncCadencePolicy`, `EveryUserInstant`; new `PlanCadence`, `cadences_of`, `_cadence_alone`)
- Modify: `src/calendar_sync/application/operations/instant_sync.py` (imports; `WatchUpkeep` docstring, `run`, `_keep`, `_allowed`; `InstantDispatch` docstring, `_instant_users`; new `_may_sync_instantly`; `InstantSyncStatus.poll_every`, `_availability`, new `_cadence`)
- Modify: `src/calendar_sync/application/operations/installation_hints.py` (import; `instant_sync_signals` body; `_wants_instant_sync` becomes `_wanting_instant_sync`)
- Modify: `src/calendar_sync/bootstrap/container.py` (import `PlanCadence`; `Adapters.sync_cadence` docstring; `build_adapters` passes `sync_cadence=PlanCadence(plans)`)
- Create: `tests/application/test_plan_cadence.py`
- Test: `tests/application/test_watch_ports.py`, `tests/application/test_instant_dispatch.py`, `tests/application/test_watch_upkeep.py`, `tests/application/test_installation_hints.py`, `tests/application/test_instant_sync_status.py`, `tests/adapters/test_api.py`

**Interfaces:**
- Consumes:
  - `Allowances.of(user: UserId) -> Allowance` and `Allowances.of_users(users: Collection[UserId]) -> Mapping[UserId, Allowance]` (task 4, `application/sync/ports.py`)
  - `Allowance.cadence -> SyncCadence`, `Allowance(basis, plan=None, on_default=False, assigned=None)`, `AllowanceBasis.PLAN`, `UNLIMITED`, `AssignmentSource.ADMINISTRATOR` (task 1, `domain/plans.py`)
  - `AssignmentChange(source, actor, at)` (task 4, `application/identity/ports.py`)
  - `MemoryPlans(users=MemoryUsers)` with `assign`, `change_settings`; `BrokenAllowances()` whose `of` and `of_users` raise `RuntimeError("database is locked")` (task 4, `tests/identity_fakes.py`)
  - `FREE` (`5_minutes`), `FAMILY` (`instant`), `plans_on(catalog, default=FREE, *others)` (task 4, `tests/plans.py`)
  - `limited_user(database, user=OTHER_USER, *, plan=None, email=None) -> UserId` (task 4, `tests/users.py`)
  - `Adapters.allowances`, `Adapters.plan_catalog`, and the local `plans = SqlitePlans(database)` in `build_adapters` (task 4)
- Produces:
  - `SyncCadencePolicy.cadences(self, users: Collection[UserId]) -> Mapping[UserId, SyncCadence]`
  - `EveryUserInstant.cadences(self, users: Collection[UserId]) -> Mapping[UserId, SyncCadence]`
  - `PlanCadence(allowances: Allowances)` with `cadence(user) -> SyncCadence` and `cadences(users) -> Mapping[UserId, SyncCadence]`
  - `cadences_of(policy: SyncCadencePolicy, users: Collection[UserId]) -> dict[UserId, SyncCadence | None]`
  - `InstantSyncStatus._cadence(self, user: UserId) -> SyncCadence` (private; falls back to `DEFAULT_CADENCE`)
  - `Adapters.sync_cadence` is `PlanCadence(plans)` in `build_adapters`
  - Every test fake of `SyncCadencePolicy` implements `cadences`

- [ ] **Step 1: Write the failing tests for the port**

Create `tests/application/test_plan_cadence.py`:

```python
"""Each User's Sync Cadence as their Allowance says, and the batch read that falls back to one
User at a time when Plans cannot be read (ADR 0038)."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field

import pytest

from calendar_sync.application.identity.ports import AssignmentChange
from calendar_sync.application.sync.watch_ports import EveryUserInstant, PlanCadence, cadences_of
from calendar_sync.domain.access import Role, User, UserId, UserState
from calendar_sync.domain.cadence import DEFAULT_CADENCE, SCHEDULED_EVERY, SyncCadence
from calendar_sync.domain.plans import UNLIMITED, Allowance, AllowanceBasis, AssignmentSource
from tests.helpers import NOW
from tests.identity_fakes import BrokenAllowances, MemoryPlans, MemoryUsers
from tests.plans import FAMILY, FREE, plans_on

ADMIN, MEMBER, OTHER, GONE = UserId("admin"), UserId("member"), UserId("other"), UserId("gone")
SCHEDULED_ONLY = SyncCadence(instant=False, poll_every=SCHEDULED_EVERY)
"""A `5_minutes` Plan's cadence in slice 1: no Instant Sync, and a poll every five minutes."""
LOGGER = "calendar_sync.application.sync.watch_ports"


def _person(user: UserId, role: Role = Role.USER) -> User:
    return User(user, f"{user.value}@example.test", role, UserState.ACTIVE, NOW)


def _plans(*, on: bool) -> MemoryPlans:
    """An administrator; MEMBER, whose own Plan is FAMILY (instant); and OTHER, on the Default
    Plan FREE (every five minutes)."""
    users = MemoryUsers()
    users.add(_person(ADMIN, Role.INSTALLATION_ADMINISTRATOR), "hashed:synthetic")
    users.add(_person(MEMBER), "hashed:synthetic")
    users.add(_person(OTHER), "hashed:synthetic")
    plans = MemoryPlans(users=users)
    plans_on(plans, FREE, FAMILY)
    change = AssignmentChange(AssignmentSource.ADMINISTRATOR, ADMIN, NOW)
    plans.assign(MEMBER, FAMILY.key, change)
    if not on:
        plans.change_settings(False, FREE.key)
    return plans


@pytest.mark.parametrize(
    ("on", "user", "expected"),
    [
        (False, OTHER, DEFAULT_CADENCE),
        (True, ADMIN, DEFAULT_CADENCE),
        (True, MEMBER, DEFAULT_CADENCE),
        (True, OTHER, SCHEDULED_ONLY),
    ],
    ids=["plans off", "administrator", "an instant plan", "a 5-minute plan"],
)
def test_a_users_cadence_is_the_one_their_allowance_gives(
    on: bool, user: UserId, expected: SyncCadence
) -> None:
    assert PlanCadence(_plans(on=on)).cadence(user) == expected


def test_reading_many_users_answers_as_reading_each_does() -> None:
    policy = PlanCadence(_plans(on=True))
    users = (ADMIN, MEMBER, OTHER)

    assert policy.cadences(users) == {user: policy.cadence(user) for user in users}
    assert policy.cadences(users) == {
        ADMIN: DEFAULT_CADENCE,
        MEMBER: DEFAULT_CADENCE,
        OTHER: SCHEDULED_ONLY,
    }


@dataclass
class Answering:
    """Allowances whose batch read answers only the Users it knows, counting each batch."""

    known: Mapping[UserId, Allowance]
    batches: int = 0

    def of(self, user: UserId) -> Allowance:
        return self.known.get(user, UNLIMITED)

    def of_users(self, users: Collection[UserId]) -> Mapping[UserId, Allowance]:
        self.batches += 1
        return {user: self.known[user] for user in users if user in self.known}


def test_reading_many_users_takes_one_read_and_gives_a_missing_user_the_default() -> None:
    allowances = Answering({OTHER: Allowance(AllowanceBasis.PLAN, plan=FREE)})

    cadences = PlanCadence(allowances).cadences([OTHER, GONE])

    assert cadences == {OTHER: SCHEDULED_ONLY, GONE: DEFAULT_CADENCE}
    assert allowances.batches == 1


def test_the_policy_never_hides_a_failed_read() -> None:
    # Each reader decides how to fail open, through cadences_of or a fallback of its own.
    policy = PlanCadence(BrokenAllowances())

    with pytest.raises(RuntimeError, match="database is locked"):
        policy.cadence(MEMBER)
    with pytest.raises(RuntimeError, match="database is locked"):
        policy.cadences([MEMBER])


@dataclass
class Unsteady:
    """A cadence policy whose batch read answers `batch`, or fails when it is None, and whose
    read of each `unreadable` User fails too, as a locked database would."""

    batch: Mapping[UserId, SyncCadence] | None = None
    unreadable: frozenset[UserId] = frozenset()
    read_alone: list[UserId] = field(default_factory=list)

    def cadence(self, user: UserId) -> SyncCadence:
        self.read_alone.append(user)
        if user in self.unreadable:
            raise RuntimeError("database is locked")
        return SCHEDULED_ONLY

    def cadences(self, users: Collection[UserId]) -> Mapping[UserId, SyncCadence]:
        if self.batch is None:
            raise RuntimeError("database is locked")
        return self.batch


def test_cadences_of_takes_the_batch_when_it_can_be_read() -> None:
    policy = Unsteady(batch={MEMBER: DEFAULT_CADENCE})

    # A User the batch leaves out reads as unread, which every reader counts as instant.
    assert cadences_of(policy, [MEMBER, OTHER]) == {MEMBER: DEFAULT_CADENCE, OTHER: None}
    assert policy.read_alone == []


def test_cadences_of_reads_each_user_alone_when_the_batch_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    policy = Unsteady(unreadable=frozenset({MEMBER}))

    with caplog.at_level("WARNING", logger=LOGGER):
        cadences = cadences_of(policy, [MEMBER, OTHER])

    assert cadences == {MEMBER: None, OTHER: SCHEDULED_ONLY}
    assert policy.read_alone == [MEMBER, OTHER]
    # Only the error's class: its text could quote the database's own words.
    assert "RuntimeError" in caplog.text
    assert "database is locked" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_with_plans_unreadable_every_user_reads_as_unread() -> None:
    assert cadences_of(PlanCadence(BrokenAllowances()), [MEMBER, OTHER]) == {
        MEMBER: None,
        OTHER: None,
    }


def test_with_plans_off_everyone_may_sync_instantly_in_one_read() -> None:
    assert cadences_of(EveryUserInstant(), [MEMBER, OTHER]) == {
        MEMBER: DEFAULT_CADENCE,
        OTHER: DEFAULT_CADENCE,
    }
```

In `tests/application/test_watch_ports.py`, replace `test_with_plans_off_every_user_may_sync_instantly` with:

```python
def test_with_plans_off_every_user_may_sync_instantly() -> None:
    policy = EveryUserInstant()

    assert policy.cadence(USER) == DEFAULT_CADENCE
    assert policy.cadence(OTHER_USER) == DEFAULT_CADENCE
    assert policy.cadences([USER, OTHER_USER]) == {
        USER: DEFAULT_CADENCE,
        OTHER_USER: DEFAULT_CADENCE,
    }
    assert policy.cadences([]) == {}
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/pytest tests/application/test_plan_cadence.py tests/application/test_watch_ports.py -q`

Expected: collection of `test_plan_cadence.py` errors with
`ImportError: cannot import name 'PlanCadence' from 'calendar_sync.application.sync.watch_ports'`;
run alone, `test_watch_ports.py` fails with
`AttributeError: 'EveryUserInstant' object has no attribute 'cadences'`.

- [ ] **Step 3: Implement `cadences`, `PlanCadence`, and `cadences_of` in `watch_ports.py`**

In `src/calendar_sync/application/sync/watch_ports.py`, replace the import block at the top of the
module (from `from __future__ import annotations` to the line before `NOTICE_PATH`) with:

```python
from __future__ import annotations

import logging
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from calendar_sync.application.shared.errors import ApplicationError
from calendar_sync.application.sync.errors import ProviderFailure
from calendar_sync.domain.access import UserId
from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.cadence import DEFAULT_CADENCE, SyncCadence
from calendar_sync.domain.model import CalendarEndpoint, CalendarId, ConnectedAccountId, SyncRuleId
from calendar_sync.domain.watches import (
    CalendarWatch,
    CalendarWatchId,
    DeliveryEvidence,
    WatchRegistration,
    WatchRegistrationId,
    WatchScope,
)

if TYPE_CHECKING:
    # ports.py imports this module, so the Allowances port is named here for type checking only.
    from calendar_sync.application.sync.ports import Allowances

logger = logging.getLogger(__name__)

NOTICE_PATH = "/api/v1/watch-notices"
"""Where providers deliver notices, below the installation's public address."""
```

Replace `SyncCadencePolicy` and `EveryUserInstant` (the two classes just above `notice_address`)
with:

```python
class SyncCadencePolicy(Protocol):
    """Each User's Sync Cadence, as their Plan allows (ADR 0028, ADR 0038).

    Both reads raise when the cadence cannot be read; readers that must not fail read through
    `cadences_of`, or fall back to `DEFAULT_CADENCE` themselves.
    """

    def cadence(self, user: UserId) -> SyncCadence:
        """One User's cadence."""
        ...

    def cadences(self, users: Collection[UserId]) -> Mapping[UserId, SyncCadence]:
        """Each User's cadence, in one read."""
        ...


@dataclass(frozen=True, slots=True)
class EveryUserInstant:
    """Every User may sync instantly, as while Plans are off (ADR 0028): the default of
    `Adapters.sync_cadence`, and a policy for tests."""

    # The port names the User so Plans can tell Users apart; this policy tells none apart.
    def cadence(self, user: UserId) -> SyncCadence:  # noqa: ARG002
        return DEFAULT_CADENCE

    def cadences(self, users: Collection[UserId]) -> Mapping[UserId, SyncCadence]:
        return dict.fromkeys(users, DEFAULT_CADENCE)


@dataclass(frozen=True, slots=True)
class PlanCadence:
    """Each User's Sync Cadence, as their Allowance says (ADR 0038).

    A failed read raises here: each reader decides how to fail open.
    """

    allowances: Allowances

    def cadence(self, user: UserId) -> SyncCadence:
        return self.allowances.of(user).cadence

    def cadences(self, users: Collection[UserId]) -> Mapping[UserId, SyncCadence]:
        """Every User's cadence in one Allowances read; a User missing from its answer gets
        the default cadence."""
        allowances = self.allowances.of_users(users)
        return {
            user: allowances[user].cadence if user in allowances else DEFAULT_CADENCE
            for user in users
        }


def cadences_of(
    policy: SyncCadencePolicy, users: Collection[UserId]
) -> dict[UserId, SyncCadence | None]:
    """Each User's cadence in one batch read; when the batch raises, each User read alone; None
    for a User whose own read raises too, or whom the batch left out. Logs only the error's class.

    Readers count None as instant, so a Plans fault never drops an Instant Sync Request,
    retires a watch, or hides Instant Sync from Installation Hints (ADR 0038).
    """
    try:
        batch = policy.cadences(users)
    except Exception as error:
        logger.warning(
            "Could not read Sync Cadences in one batch; reading each User alone (%s)",
            error.__class__.__name__,
        )
        return {user: _cadence_alone(policy, user) for user in users}
    return {user: batch.get(user) for user in users}


def _cadence_alone(policy: SyncCadencePolicy, user: UserId) -> SyncCadence | None:
    try:
        return policy.cadence(user)
    except Exception as error:
        logger.warning(
            "Could not read a User's Sync Cadence; they count as instant (%s)",
            error.__class__.__name__,
        )
        return None
```

`notice_address` stays as it is, below them.

- [ ] **Step 4: Give every existing cadence fake `cadences`**

The port gained a method, so mypy refuses each fake until it has one. Each fake takes its final
form here; Step 6 uses the `unreadable` and `batch_fails` switches.

In `tests/application/test_instant_dispatch.py`, change the first import to
`from collections.abc import Callable, Collection, Mapping`, and replace `class Cadences` with:

```python
class Cadences:
    """Each User's Sync Cadence. The batch read fails when told to or once any User is
    unreadable, and reading an unreadable User alone fails too, as a locked database would."""

    def __init__(self) -> None:
        self.scheduled_only: set[UserId] = set()
        self.unreadable: set[UserId] = set()
        self.batch_fails = False

    def cadence(self, user: UserId) -> SyncCadence:
        if user in self.unreadable:
            raise RuntimeError("database is locked")
        return SyncCadence(instant=user not in self.scheduled_only, poll_every=SCHEDULED_EVERY)

    def cadences(self, users: Collection[UserId]) -> Mapping[UserId, SyncCadence]:
        if self.batch_fails or self.unreadable:
            raise RuntimeError("database is locked")
        return {user: self.cadence(user) for user in users}
```

In `tests/application/test_watch_upkeep.py`, add `from collections.abc import Collection, Mapping`
above `from datetime import datetime, timedelta`, and replace `class Cadences` with:

```python
class Cadences:
    """Each User's Sync Cadence; Users named here have no Instant Sync in their Plan. Once any
    User is unreadable, the batch read fails, and so does reading that User alone, as a locked
    database would."""

    def __init__(
        self, *scheduled_only: UserId, unreadable: frozenset[UserId] = frozenset()
    ) -> None:
        self.scheduled_only = set(scheduled_only)
        self.unreadable = unreadable
        self.batches = 0

    def cadence(self, user: UserId) -> SyncCadence:
        if user in self.unreadable:
            raise RuntimeError("database is locked")
        return SyncCadence(instant=user not in self.scheduled_only, poll_every=SCHEDULED_EVERY)

    def cadences(self, users: Collection[UserId]) -> Mapping[UserId, SyncCadence]:
        self.batches += 1
        if self.unreadable:
            raise RuntimeError("database is locked")
        return {user: self.cadence(user) for user in users}
```

In `tests/application/test_installation_hints.py`, add `from collections.abc import Collection, Mapping`
above `from dataclasses import dataclass`, and replace the `Cadences` dataclass with:

```python
@dataclass(frozen=True)
class Cadences:
    """A Sync Cadence Policy that gives Instant Sync to everyone but some Users. Once any User is
    unreadable, the batch read fails, and so does reading that User alone, as a locked database
    would."""

    without_instant: frozenset[UserId] = frozenset()
    unreadable: frozenset[UserId] = frozenset()

    def cadence(self, user: UserId) -> SyncCadence:
        if user in self.unreadable:
            raise RuntimeError("database is locked")
        return SyncCadence(instant=user not in self.without_instant, poll_every=SCHEDULED_EVERY)

    def cadences(self, users: Collection[UserId]) -> Mapping[UserId, SyncCadence]:
        if self.unreadable:
            raise RuntimeError("database is locked")
        return {user: self.cadence(user) for user in users}
```

In `tests/application/test_instant_sync_status.py`, change the first import to
`from collections.abc import Callable, Collection, Mapping`, and replace `class Plan` with:

```python
class Plan:
    def __init__(self, *, instant: bool = True, poll_every: timedelta = SCHEDULED_EVERY) -> None:
        self.allowed = SyncCadence(instant=instant, poll_every=poll_every)

    def cadence(self, user: UserId) -> SyncCadence:
        return self.allowed

    def cadences(self, users: Collection[UserId]) -> Mapping[UserId, SyncCadence]:
        return dict.fromkeys(users, self.allowed)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run:

```sh
.venv/bin/pytest tests/application/test_plan_cadence.py tests/application/test_watch_ports.py tests/application/test_instant_dispatch.py tests/application/test_watch_upkeep.py tests/application/test_installation_hints.py tests/application/test_instant_sync_status.py -q
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy
.venv/bin/lint-imports
```

Expected: all tests pass; ruff reports no changes and no errors; mypy reports
`Success: no issues found`; lint-imports reports `Contracts: 10 kept, 0 broken.` (the
`TYPE_CHECKING` import stays inside `application.sync`).

- [ ] **Step 6: Write the failing tests for the fail-open readers**

In `tests/application/test_instant_dispatch.py`, add after
`test_a_drop_storage_refuses_logs_only_the_class_of_its_error`:

```python
def test_a_user_whose_cadence_cannot_be_read_keeps_their_requests_and_runs_them(
    caplog: pytest.LogCaptureFixture,
) -> None:
    world = World((USER, rule()))
    world.requests.notice(USER, rule().id, NOW - QUIET)
    world.cadences.unreadable.add(USER)

    with caplog.at_level("WARNING", logger="calendar_sync.application.sync.watch_ports"):
        (item,), _ = world.dispatch.due(frozenset())
        world.dispatch.run(item)

    # A Plans fault never drops an Instant Sync Request: the rule runs as for an instant User.
    assert world.runs.ran == [("rule-1", False)]
    assert not world.requests.waiting(USER, rule().id)
    assert "RuntimeError" in caplog.text
    assert "database is locked" not in caplog.text


def test_when_the_batch_read_fails_each_user_is_read_alone() -> None:
    world = World((USER, rule()), (OTHER_USER, _rule("rule-4")))
    world.requests.notice(USER, rule().id, NOW - QUIET)
    world.requests.notice(OTHER_USER, SyncRuleId("rule-4"), NOW - QUIET)
    world.cadences.batch_fails = True
    world.cadences.scheduled_only.add(OTHER_USER)

    runs, _ = world.dispatch.due(frozenset())

    # OTHER_USER's Plan, read alone, has no Instant Sync, so only their request is dropped.
    assert _ids(runs) == ["rule-1"]
    assert world.requests.waiting(USER, rule().id)
    assert not world.requests.waiting(OTHER_USER, SyncRuleId("rule-4"))
```

At the end of `tests/application/test_watch_upkeep.py`, add:

```python
def test_a_cycle_reads_every_users_cadence_at_once() -> None:
    cadence = Cadences()
    owners = Owners(_owner(USER), _owner(OTHER_USER), _owner(THIRD_USER))

    _upkeep(owners, [], cadence=cadence).run()

    assert cadence.batches == 1


def test_a_user_whose_cadence_cannot_be_read_keeps_their_watches(
    caplog: pytest.LogCaptureFixture,
) -> None:
    visits: list[Visit] = []
    # The batch read fails, so each User is read alone: USER's read fails too, and OTHER_USER's
    # Plan has no Instant Sync.
    cadence = Cadences(OTHER_USER, unreadable=frozenset({USER}))
    owners = Owners(_owner(USER), _owner(OTHER_USER), _owner(THIRD_USER, wanted=False))

    with caplog.at_level("WARNING"):
        _upkeep(owners, visits, cadence=cadence).run()

    # USER counts as instant, so upkeep keeps their watches instead of retiring them.
    assert visits == [
        (USER, True, ADDRESS),
        (OTHER_USER, False, ADDRESS),
        (THIRD_USER, False, ADDRESS),
    ]
    assert "RuntimeError" in caplog.text
    assert "database is locked" not in caplog.text


def test_an_unreadable_cadence_never_allows_watches_without_an_address_or_the_wish() -> None:
    visits: list[Visit] = []
    cadence = Cadences(unreadable=frozenset({USER, OTHER_USER}))
    owners = Owners(_owner(USER), _owner(OTHER_USER, wanted=False))

    _upkeep(owners, visits, cadence=cadence, address=None).run()

    assert visits == [(USER, False, None), (OTHER_USER, False, None)]
```

In `tests/application/test_installation_hints.py`, add after
`test_only_users_who_may_sign_in_want_it_and_may_use_it_count`:

```python
def test_a_user_whose_cadence_cannot_be_read_counts_as_wanting_instant_sync(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # The batch read fails, so each User is read alone: ROBIN's read fails too, and KIM's Plan
    # has no Instant Sync.
    cadences = Cadences(frozenset({KIM}), unreadable=frozenset({ROBIN}))
    owners = [owner(ROBIN), owner(SAM), owner(KIM)]

    with caplog.at_level("WARNING"):
        signals = instant_sync_signals(owners, cadences, HTTPS, {})

    assert signals == InstantSyncSignals(wanting=2)
    assert "database is locked" not in caplog.text
```

In `tests/application/test_instant_sync_status.py`, replace the `watch_ports` import and the
`identity_fakes` import with:

```python
from calendar_sync.application.sync.watch_ports import (
    EveryUserInstant,
    PlanCadence,
    Receipt,
    SyncCadencePolicy,
    notice_address,
)
```

```python
from tests.identity_fakes import BrokenAllowances, MemoryPlans, MemoryUsers
from tests.plans import FREE, plans_on
```

and add at the end of the file:

```python
def test_a_plans_fault_shows_the_default_cadence(caplog: pytest.LogCaptureFixture) -> None:
    database = InMemoryUnitOfWorkFactory()
    _watched(_with_rule(database), confirmed=True)
    status = _status(database, plan=PlanCadence(BrokenAllowances()))

    with caplog.at_level("WARNING", logger="calendar_sync.application.operations.instant_sync"):
        availability = status.availability(USER)
        reasons = status.cadences(USER)
        poll_every = status.poll_every(USER)

    # Sign-in and the rules API keep working: a Plans fault never takes Instant Sync away.
    assert availability is Availability.ON
    assert reasons == {rule().id: CadenceReason.INSTANT}
    assert poll_every == SCHEDULED_EVERY
    assert "RuntimeError" in caplog.text
    assert "database is locked" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_a_plan_without_instant_sync_makes_it_not_in_plan() -> None:
    database = InMemoryUnitOfWorkFactory()
    _watched(_with_rule(database), confirmed=True)
    users = MemoryUsers()
    users.add(_user(), "hashed:synthetic")
    plans = MemoryPlans(users=users)
    plans_on(plans, FREE)

    status = _status(database, plan=PlanCadence(plans))

    # FREE syncs every 5 minutes: the User keeps their own wish, but their Plan rules it out.
    assert status.availability(USER) is Availability.NOT_IN_PLAN
    assert status.cadences(USER) == {rule().id: CadenceReason.NOT_IN_PLAN}
    assert status.poll_every(USER) == SCHEDULED_EVERY
```

In `tests/adapters/test_api.py`, add the import
`from calendar_sync.application.sync.watch_ports import PlanCadence` right after
`from calendar_sync.application.sync.synchronization import ExecuteSyncRule, SyncRunResult`, and
`from tests.identity_fakes import BrokenAllowances` right after the closing parenthesis of the
`from tests.helpers import (...)` block. Then add at the end of the file:

```python
def test_a_plans_fault_never_breaks_sign_in_or_the_rules_api(tmp_path: Path) -> None:
    container, adapters = _installation(
        Settings(tmp_path / "test.db"), sync_cadence=PlanCadence(BrokenAllowances())
    )
    with _units(adapters)() as uow:
        uow.rules.add(rule())
        uow.commit()

    with TestClient(create_app(container)) as client:
        sign_in(client)
        session = client.get("/api/v1/session")
        listed = client.get("/api/v1/rules")
        detail = client.get(f"/api/v1/rules/{rule().id.value}")

    # Each answer reads the default cadence; without a master key there is no public address.
    assert (session.status_code, listed.status_code, detail.status_code) == (200, 200, 200)
    assert session.json()["user"]["instant_sync_availability"] == "no_public_address"
    assert [item["poll_every_minutes"] for item in listed.json()] == [5]
    assert (detail.json()["effective_cadence"], detail.json()["poll_every_minutes"]) == (
        "no_public_address",
        5,
    )
```

- [ ] **Step 7: Run them to verify they fail**

Run:

```sh
.venv/bin/pytest tests/application/test_instant_dispatch.py tests/application/test_watch_upkeep.py tests/application/test_installation_hints.py tests/application/test_instant_sync_status.py tests/adapters/test_api.py -q -k "cadence or plans_fault or batch_read or not_in_plan"
```

Expected failures, each from `RuntimeError("database is locked")` reaching a reader:
- `test_a_user_whose_cadence_cannot_be_read_keeps_their_requests_and_runs_them`: `RuntimeError` raised from `InstantDispatch.due`
- `test_a_cycle_reads_every_users_cadence_at_once`: `assert 0 == 1`
- `test_a_user_whose_cadence_cannot_be_read_keeps_their_watches`: USER's visit is missing (upkeep logs "Upkeep of a User's watches failed")
- `test_a_user_whose_cadence_cannot_be_read_counts_as_wanting_instant_sync`: `RuntimeError`
- `test_a_plans_fault_shows_the_default_cadence`: `RuntimeError`
- `test_a_plans_fault_never_breaks_sign_in_or_the_rules_api`: `RuntimeError: database is locked` during `sign_in(client)`

Already passing, and they must keep passing: `test_when_the_batch_read_fails_each_user_is_read_alone`
and `test_an_unreadable_cadence_never_allows_watches_without_an_address_or_the_wish` (today's
readers read one User at a time), and `test_a_plan_without_instant_sync_makes_it_not_in_plan`
(`PlanCadence` exists since Step 3).

- [ ] **Step 8: Make the Instant Sync readers fail open**

In `src/calendar_sync/application/operations/instant_sync.py`, replace the `watch_ports` import
and the two `domain` imports that follow it with:

```python
from calendar_sync.application.sync.watch_ports import (
    DeliveryEvidenceLog,
    PendingRequest,
    SyncCadencePolicy,
    cadences_of,
)
from calendar_sync.domain.access import UserId
from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.cadence import DEFAULT_CADENCE, SyncCadence
```

Replace the `WatchUpkeep` docstring, `run`, `_keep`, and `_allowed` (keep the fields and
`_in_turn` as they are) so the class reads:

```python
@dataclass(slots=True)
class WatchUpkeep:
    """Keeps every User's Calendar Watches as their rules, preference, and Plan want them.

    Each cycle visits Users with nothing planned yet first, then the others in order of their
    earliest due work, so what waited longest goes first. Disabled Users are visited too: nothing
    is wanted for them, so their watches stop. A User whose Sync Cadence cannot be read counts
    as instant, so a Plans fault never retires their watches (ADR 0038).
    """

    installation: InstallationUnitOfWorkFactory
    upkeep_for: Callable[[UserId], UpkeepWatches | None]
    """A User's own upkeep; None where no provider can watch, as without the master key."""
    cadence: SyncCadencePolicy
    address: str | None
    """The installation's public https address; None when it has none."""
    clock: Clock
    _carried: tuple[UserId, ...] = ()
    """The Users the last cycle never reached, then the User it stopped on; they go first."""

    def run(self, budget: int = UPKEEP_BUDGET) -> None:
        calls = CallBudget(budget)
        with self.installation() as installation:
            owners = self._in_turn(installation.instant_sync_owners())
        # One read of every listed User's cadence per cycle, outside any unit of work.
        cadences = cadences_of(self.cadence, [owner.user for owner in owners])
        self._carried = ()
        for position, owner in enumerate(owners):
            self._keep(owner, cadences.get(owner.user), calls)
            if calls.exhausted:
                # The Users it never reached go first next cycle, then this one, whose upkeep
                # the budget may have cut short. So a User with a large backlog never stays
                # first forever, and two such Users take turns.
                unreached = owners[position + 1 :]
                self._carried = (*(each.user for each in unreached), owner.user)
                logger.info("Watch upkeep spent its provider call budget; the rest waits a cycle")
                return

    def _in_turn(self, owners: Sequence[InstantSyncOwner]) -> list[InstantSyncOwner]:
        """The Users the last cycle never reached, then the User it stopped on, then those with
        nothing planned yet, whose coverage is missing, then the rest by earliest due work."""
        now = self.clock.now()
        carried = {user: turn for turn, user in enumerate(self._carried)}

        def turn(owner: InstantSyncOwner) -> tuple[int, int, datetime, str]:
            if owner.user in carried:
                return 0, carried[owner.user], now, owner.user.value
            if owner.next_due is None:
                return 1, 0, now, owner.user.value
            return 2, 0, owner.next_due, owner.user.value

        return sorted(owners, key=turn)

    def _keep(
        self, owner: InstantSyncOwner, cadence: SyncCadence | None, calls: CallBudget
    ) -> None:
        """One User's upkeep; a failure waits for the next cycle and holds up nobody else."""
        try:
            upkeep = self.upkeep_for(owner.user)
            if upkeep is not None:
                upkeep.execute(
                    allowed=self._allowed(owner, cadence), address=self.address, budget=calls
                )
        except Exception as error:
            # Only the class: a provider's text, which the error may carry along, can quote a
            # token or a registration address.
            logger.error(
                "Upkeep of a User's watches failed; trying again next cycle (%s)",
                error.__class__.__name__,
            )

    def _allowed(self, owner: InstantSyncOwner, cadence: SyncCadence | None) -> bool:
        """Whether the User may have watches: the installation can be reached, the User is
        active and wants Instant Sync, and their Plan includes it, or could not be read."""
        return (
            self.address is not None
            and not owner.disabled
            and owner.wanted
            and _may_sync_instantly(cadence)
        )
```

Replace the `InstantDispatch` class docstring with:

```python
    """Chooses which rules run now for their Instant Sync Requests, and runs them.

    A request whose rule may no longer run instantly is acknowledged and dropped: its owner turned
    Instant Sync off, their Plan no longer includes it, or the rule's last run failed, which
    Scheduled Sync retries with its own backoff. Requests of a paused rule or a disabled User are
    not listed, so they wait, and run or are dropped once the rule or User is active again.
    Delivery Evidence never holds a run back: an authenticated notice proves delivery works. A
    User whose Sync Cadence cannot be read counts as instant, so a Plans fault drops nothing.
    """
```

Replace `InstantDispatch._instant_users` with:

```python
    def _instant_users(self, owners: Sequence[InstantSyncOwner]) -> frozenset[UserId]:
        """The Users whose rules may run instantly now, their cadences read in one batch."""
        wanting = [owner.user for owner in owners if owner.wanted and not owner.disabled]
        cadences = cadences_of(self.cadence, wanting)
        return frozenset(user for user in wanting if _may_sync_instantly(cadences.get(user)))
```

Add this module function directly above `def _eligible(`:

```python
def _may_sync_instantly(cadence: SyncCadence | None) -> bool:
    """Whether a User's cadence allows Instant Sync; one that could not be read does, so a Plans
    fault never drops a request or retires a watch (ADR 0038)."""
    return cadence is None or cadence.instant
```

In `InstantSyncStatus`, replace `poll_every` and `_availability`, and add `_cadence` after them
(before `_delivery`). The block opens with the class line only to place the three methods; the
decorator, the docstring, the seven fields, `availability`, `cadences`, and `_delivery` stay as
they are:

```python
class InstantSyncStatus:
    def poll_every(self, user: UserId) -> timedelta:
        """How often Scheduled Sync runs the User's rules, as their Plan says."""
        return self._cadence(user).poll_every

    def _availability(self, user: UserId, watches: Sequence[CalendarWatch]) -> Availability:
        found = self.users.get(user)
        return instant_sync_availability(
            address_is_https=self.address is not None,
            cadence=self._cadence(user),
            wanted=found is not None and found.instant_sync,
            delivery=self._delivery(watches),
        )

    def _cadence(self, user: UserId) -> SyncCadence:
        """The User's cadence, or the default one when it cannot be read, so a Plans fault never
        breaks sign-in or the rules API (ADR 0038)."""
        try:
            return self.cadence.cadence(user)
        except Exception as error:
            # Only the class: the error's text could quote the database's own words.
            logger.warning(
                "Could not read a User's Sync Cadence; showing the default one (%s)",
                error.__class__.__name__,
            )
            return DEFAULT_CADENCE
```

`InstantSyncStatus` keeps its seven fields; `availability` and `cadences` reach `_cadence`
through `_availability`.

- [ ] **Step 9: Make Installation Hints fail open**

In `src/calendar_sync/application/operations/installation_hints.py`, replace
`from calendar_sync.application.sync.watch_ports import SyncCadencePolicy` with:

```python
from calendar_sync.application.sync.watch_ports import SyncCadencePolicy, cadences_of
```

Replace `instant_sync_signals` (signature unchanged) with:

```python
def instant_sync_signals(
    owners: Iterable[InstantSyncOwner],
    cadence: SyncCadencePolicy,
    address: str | None,
    evidence: Mapping[ProviderKind, DeliveryEvidence],
) -> InstantSyncSignals:
    """Who wants Instant Sync, and what keeps providers from the installation's public address.

    Plain http on this machine or a home network is the homelab norm and signals nothing: each
    User's switch already says Instant Sync needs a public address.
    """
    wanting = _wanting_instant_sync(owners, cadence)
    if not wanting or address is None:
        return InstantSyncSignals(wanting)
    if urlsplit(address).scheme == "http":
        return InstantSyncSignals(wanting, plain_http=_internet_host(address))
    failing = frozenset(
        kind for kind, seen in evidence.items() if seen.state is DeliveryState.FAILING
    )
    return InstantSyncSignals(wanting, failing=failing)
```

Replace `_wants_instant_sync` with:

```python
def _wanting_instant_sync(owners: Iterable[InstantSyncOwner], cadence: SyncCadencePolicy) -> int:
    """How many Users may sign in, want Instant Sync, and whose cadence allows it, read in one
    batch. A User whose cadence cannot be read counts, as dispatch and upkeep treat them."""
    users = [owner.user for owner in owners if owner.wanted and not owner.disabled]
    cadences = cadences_of(cadence, users)
    return sum(1 for user in users if (found := cadences.get(user)) is None or found.instant)
```

- [ ] **Step 10: Run the tests to verify they pass**

Run:

```sh
.venv/bin/pytest tests/application/test_plan_cadence.py tests/application/test_watch_ports.py tests/application/test_instant_dispatch.py tests/application/test_watch_upkeep.py tests/application/test_installation_hints.py tests/application/test_instant_sync_status.py tests/application/test_instant_sync_upkeep.py tests/adapters/test_api.py tests/adapters/test_instant_sync_api.py tests/adapters/test_instant_sync_loops.py tests/adapters/test_installation_health_api.py -q
```

Expected: every test passes, the six fail-open tests of Step 6 included.

- [ ] **Step 11: Write the failing test for the composition**

In `tests/adapters/test_api.py`, add these imports:
- `from calendar_sync.domain.cadence import SCHEDULED_EVERY, SyncCadence` right after `from calendar_sync.domain.audit import AuditAction, AuditEntry, AuditOutcome, RecordedEvent`;
- `from tests.plans import plans_on` right after `from tests.identity_fakes import BrokenAllowances`;
- `limited_user,` inside `from tests.users import (...)`, between `first_user,` and `session_for,`.

Add at the end of the file:

```python
def test_the_installation_reads_each_users_cadence_from_their_plan(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    adapters = build_adapters(Settings(database))
    member = limited_user(database)
    plans_on(adapters.plan_catalog)

    cadence = adapters.sync_cadence

    assert isinstance(cadence, PlanCadence)
    assert cadence.allowances is adapters.allowances
    # FREE, the Default Plan, syncs every 5 minutes without Instant Sync.
    assert cadence.cadence(member) == SyncCadence(instant=False, poll_every=SCHEDULED_EVERY)
```

- [ ] **Step 12: Run it to verify it fails**

Run: `.venv/bin/pytest tests/adapters/test_api.py -q -k test_the_installation_reads_each_users_cadence_from_their_plan`

Expected: FAIL at `assert isinstance(cadence, PlanCadence)`: `build_adapters` still leaves the
`EveryUserInstant()` default.

- [ ] **Step 13: Compose `PlanCadence` in `build_adapters`**

In `src/calendar_sync/bootstrap/container.py`, replace the `watch_ports` import with:

```python
from calendar_sync.application.sync.watch_ports import (
    DeliveryEvidenceLog,
    EveryUserInstant,
    NoticeReader,
    PlanCadence,
    SyncCadencePolicy,
)
```

In `class Adapters`, replace the `sync_cadence` field and its docstring with:

```python
    sync_cadence: SyncCadencePolicy = field(default_factory=EveryUserInstant)
    """Each User's Sync Cadence. `build_adapters` reads it from each User's Plan (`PlanCadence`,
    ADR 0038); this default gives every User Instant Sync, as Plans off does (ADR 0028)."""
```

In `build_adapters`, add `sync_cadence=PlanCadence(plans),` as the last keyword argument of the
`Adapters(...)` call, so the call that task 4 left reads (task 4's `plans = SqlitePlans(database)`
line and its three `allowances`, `plan_catalog`, `plan_assignments` arguments stay where task 4 put
them; keyword order does not matter):

```python
    tokens = SqliteIntegrationTokens(database, clock, ids)
    users = SqliteUserDirectory(database)
    plans = SqlitePlans(database)
    mail = _mail_server(settings)
    adapters = Adapters(
        unit_of_work=SqliteUnitOfWorkFactory(database, clock, history).for_user,
        installation_units=SqliteInstallationUnitOfWorkFactory(database),
        locks=RuleLocks(),
        clock=clock,
        ids=ids,
        run_ids=UuidRunIdGenerator(),
        users=users,
        sessions=SqliteSessions(database, clock),
        passwords=ScryptPasswords(),
        sign_in_throttle=MemorySignInThrottle(clock),
        link_throttle=MemorySignInThrottle(clock),
        registration=SqliteRegistrationSettings(database),
        invitations=SqliteInvitations(database, ids),
        password_resets=SqlitePasswordResetLinks(database, ids),
        activity=lambda user: SqliteActivityQueries(database, user, history),
        operations=lambda user: SqliteOperationsQueries(database, user),
        health_records=lambda user: SqliteRuleHealthRecords(database, user),
        incidents=lambda user: SqliteIncidentRepository(database, user, ids),
        database_storage=SqliteStorage(database),
        integration_tokens=tokens.for_user,
        token_authentication=tokens,
        delivery_evidence=SqliteDeliveryEvidenceLog(database),
        watch_inbox=SqliteWatchNoticeInbox(database),
        allowances=plans,
        plan_catalog=plans,
        plan_assignments=plans,
        notifications=lambda owner: (
            OwnerNotifier(users, owner, mail, public_address(settings)) if mail else None
        ),
        installation_notifications=_installation_notifier(settings, mail),
        sends_email=mail is not None,
        sync_cadence=PlanCadence(plans),
    )
```

`compose` needs no change: `InstantSyncStatus`, `WatchUpkeep`, `InstantDispatch`, and
`_instant_sync_signals` already read `adapters.sync_cadence`.

- [ ] **Step 14: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/adapters/test_api.py tests/adapters/test_composition.py tests/test_dev_preview.py -q`

Expected: all pass.

- [ ] **Step 15: Run the backend quality gate**

Run:

```sh
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy
.venv/bin/lint-imports
.venv/bin/pytest --cov --cov-report=term-missing --cov-fail-under=80
```

Expected: ruff reports no changes and `All checks passed!`; mypy `Success: no issues found`;
lint-imports `Contracts: 10 kept, 0 broken.`; every test passes and coverage stays at or above 80%.
With Plans off (every existing test's database), `PlanCadence` answers `DEFAULT_CADENCE` for
everyone, so no existing Instant Sync test changes its expectations.

- [ ] **Step 16: Commit**

```sh
git add src/calendar_sync/application/sync/watch_ports.py src/calendar_sync/application/operations/instant_sync.py src/calendar_sync/application/operations/installation_hints.py src/calendar_sync/bootstrap/container.py tests/application/test_plan_cadence.py tests/application/test_watch_ports.py tests/application/test_instant_dispatch.py tests/application/test_watch_upkeep.py tests/application/test_installation_hints.py tests/application/test_instant_sync_status.py tests/adapters/test_api.py
git commit -F - <<'EOF'
Sync each person as often as their plan allows, and keep syncing when plans cannot be read

Each User's Sync Cadence now comes from their Allowance through
PlanCadence, read for many Users at once. When Plans cannot be read,
Instant Sync dispatch keeps every request, watch upkeep keeps every
watch, Installation Hints count the User as wanting Instant Sync, and
sign-in and the rules API show the default cadence. Only the error's
class is logged.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
```

### Task 6: Problem codes and messages

Every Plan refusal reaches API clients with a stable code and reaches the Web UI as an English
message, with `count` beside each number so the right plural form shows (contract section 3.17).

Before you start: tasks 1 and 4 are merged. This task imports `PlanLimitReached`,
`LimitedResource`, `PlanInUse`, `InvalidPlan`, `InvalidPlanReason`, `PlansNeedDefault`,
`PlanIsDefault`, `PlanKey`, `require_plans_setting`, `require_removable` from
`calendar_sync.domain.plans`, and `PlanNotFound`, `PlanKeyTaken` from
`calendar_sync.application.identity.errors`.

**Files:**
- Modify: `src/calendar_sync/interfaces/api/problems.py` (imports, `_CODES`, `_params`; new `_plan_params`)
- Modify: `web/src/i18n/locales/en/common.json` (`apiError.*` only)
- Modify: `src/calendar_sync/interfaces/api/static/` (rebuilt bundle)
- Test: `tests/adapters/test_api_problems.py`
- Test: `web/src/i18n/api-errors.test.ts`

**Interfaces:**
- Consumes:
  - `PlanLimitReached(resource: LimitedResource, limit: int)` with `.resource`, `.limit`; `PlanInUse(people: int)` with `.people`; `InvalidPlan(reason: InvalidPlanReason, message: str)` with `.reason`; `PlansNeedDefault`, `PlanIsDefault` as `require_plans_setting(enabled, default)` and `require_removable(key, default, people)` raise them (task 1)
  - `PlanNotFound(message)`, `PlanKeyTaken(message)` (task 4)
- Produces:
  - Codes: `plan_limit_reached` (params `reason`, `limit`, `count`), `plans_need_default`, `plan_not_found`, `plan_key_taken`, `plan_in_use` (params `people`, `count`), `plan_is_default`, `invalid_plan` (param `reason`)
  - English messages `common.apiError.plan_limit_reached`, `plan_limit_reached_rules`, `plan_limit_reached_integration_tokens`, `plans_need_default`, `plan_not_found`, `plan_key_taken`, `plan_in_use`, `plan_is_default`, `invalid_plan`, `invalid_plan_key`, `invalid_plan_name`, `invalid_plan_limit`, `invalid_plan_interval`
  - Routes raise these with `problem_from(<status>, error)`: 409 for `PlanLimitReached`, `PlansNeedDefault`, `PlanKeyTaken`, `PlanInUse`, `PlanIsDefault`; 404 for `PlanNotFound`; 422 for `InvalidPlan` (tasks 8, 9, 13)

- [ ] **Step 1: Write the failing tests for the codes**

In `tests/adapters/test_api_problems.py`, replace the imports above `REPOSITORY = ...` with:

```python
import ast
import json
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from calendar_sync.application.identity.errors import (
    InvalidIntegrationTokenName,
    PlanKeyTaken,
    PlanNotFound,
)
from calendar_sync.application.sync.errors import (
    ProviderFailure,
    RemovalInterrupted,
    ReplacementInterrupted,
    RuleNotFound,
)
from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.errors import DomainError, DomainValidationError, InvalidStateTransition
from calendar_sync.domain.model import SyncRuleId
from calendar_sync.domain.plans import (
    InvalidPlan,
    InvalidPlanReason,
    LimitedResource,
    PlanInUse,
    PlanKey,
    PlanLimitReached,
    require_plans_setting,
    require_removable,
)
from calendar_sync.domain.providers import ProviderFailureKind
from calendar_sync.interfaces.api import problems
from calendar_sync.interfaces.api.problems import install_problem_handlers, problem, problem_from
```

Replace the block from `GOOGLE_LIMIT = ...` to the end of `test_problem_from_maps_exceptions` with:

```python
GOOGLE_LIMIT = ProviderFailure(ProviderFailureKind.RATE_LIMIT, "429", provider=ProviderKind.GOOGLE)


def _refusal(check: Callable[[], object]) -> DomainError:
    """The error a domain policy raises, built as the policy builds it."""
    try:
        check()
    except DomainError as error:
        return error
    raise AssertionError("the policy refused nothing")


FAMILY_KEY = PlanKey("family")


@pytest.mark.parametrize(
    ("error", "code", "params"),
    [
        (RuleNotFound("rule r1 does not exist"), "rule_not_found", {}),
        (GOOGLE_LIMIT, "provider_failed", {"provider": "google", "kind": "rate_limit"}),
        (
            RemovalInterrupted(2, 3, GOOGLE_LIMIT),
            "removal_interrupted",
            {
                "processed": 2,
                "remaining": 3,
                "total": 5,
                "provider": "google",
                "kind": "rate_limit",
            },
        ),
        (
            ReplacementInterrupted(SyncRuleId("r2"), RemovalInterrupted(1, 1, GOOGLE_LIMIT)),
            "replacement_interrupted",
            {
                "replacement_rule_id": "r2",
                "processed": 1,
                "remaining": 1,
                "total": 2,
                "provider": "google",
                "kind": "rate_limit",
            },
        ),
        (DomainValidationError("name must not be empty"), "invalid_rule", {}),
        (InvalidStateTransition("cannot enable"), "invalid_state_transition", {}),
        (
            InvalidIntegrationTokenName("name must be 1 to 80 printable characters"),
            "invalid_integration_token_name",
            {},
        ),
        (
            PlanLimitReached(LimitedResource.RULES, 3),
            "plan_limit_reached",
            {"reason": "rules", "limit": 3, "count": 3},
        ),
        (
            PlanLimitReached(LimitedResource.INTEGRATION_TOKENS, 0),
            "plan_limit_reached",
            {"reason": "integration_tokens", "limit": 0, "count": 0},
        ),
        (PlanInUse(2), "plan_in_use", {"people": 2, "count": 2}),
        # A DomainValidationError, but never "invalid_rule": its own code comes first.
        (
            InvalidPlan(InvalidPlanReason.KEY, "a plan key is 1 to 32 lower-case letters"),
            "invalid_plan",
            {"reason": "key"},
        ),
        (
            InvalidPlan(InvalidPlanReason.INTERVAL, "choose one of the offered sync intervals"),
            "invalid_plan",
            {"reason": "interval"},
        ),
        (_refusal(lambda: require_plans_setting(True, None)), "plans_need_default", {}),
        (_refusal(lambda: require_removable(FAMILY_KEY, FAMILY_KEY, 0)), "plan_is_default", {}),
        (PlanNotFound("plan family does not exist"), "plan_not_found", {}),
        (PlanKeyTaken("a plan with the key family already exists"), "plan_key_taken", {}),
    ],
)
def test_problem_from_maps_exceptions(
    error: Exception, code: str, params: dict[str, object]
) -> None:
    mapped = problem_from(422, error)
    assert (mapped.status_code, mapped.code, mapped.params, mapped.detail) == (
        422,
        code,
        params,
        str(error),
    )
```

(`_refusal` builds `PlansNeedDefault` and `PlanIsDefault` through the policies that raise them, so
the test does not depend on how task 1 words or constructs them.)

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/pytest tests/adapters/test_api_problems.py -q`

Expected: the new `test_problem_from_maps_exceptions` cases fail:
`TypeError: no error code for PlanLimitReached` (and for `PlanInUse`, `PlansNeedDefault`,
`PlanIsDefault`, `PlanNotFound`, `PlanKeyTaken`), and both `InvalidPlan` cases with
`'invalid_rule' == 'invalid_plan'`, since `InvalidPlan` is a `DomainValidationError`.

- [ ] **Step 3: Map the Plan errors to codes and params**

In `src/calendar_sync/interfaces/api/problems.py`, replace the `identity.errors` import with:

```python
from calendar_sync.application.identity.errors import (
    AdminAlreadyConfigured,
    EmailRequired,
    EmailTaken,
    IncorrectCredentials,
    IncorrectPassword,
    InvalidIntegrationTokenName,
    PasswordPolicyViolation,
    PlanKeyTaken,
    PlanNotFound,
    SignInThrottled,
    UserDisabled,
)
```

and add, right after `from calendar_sync.domain.errors import DomainValidationError, InvalidStateTransition`:

```python
from calendar_sync.domain.plans import (
    InvalidPlan,
    PlanInUse,
    PlanIsDefault,
    PlanLimitReached,
    PlansNeedDefault,
)
```

In `_CODES`, replace the last five entries (from `UserDeletionInterrupted` to the closing brace)
with:

```python
    UserDeletionInterrupted: "user_deletion_interrupted",
    # Plans (ADR 0038).
    PlanLimitReached: "plan_limit_reached",
    PlansNeedDefault: "plans_need_default",
    PlanNotFound: "plan_not_found",
    PlanKeyTaken: "plan_key_taken",
    PlanInUse: "plan_in_use",
    PlanIsDefault: "plan_is_default",
    # A DomainValidationError too; the MRO reaches this code before "invalid_rule".
    InvalidPlan: "invalid_plan",
    DomainValidationError: "invalid_rule",
    # Every rejected lifecycle change (enable, pause, policy edit) with a message naming the state.
    InvalidStateTransition: "invalid_state_transition",
}
```

Replace `_params` with the version below, and add `_plan_params` after it (a separate function
keeps `_params` within Ruff's complexity bound):

```python
def _params(error: Exception) -> dict[str, ParamValue]:
    if isinstance(error, ReplacementInterrupted):
        return {
            "replacement_rule_id": error.replacement_rule_id.value,
            **_removal_params(error.removal),
        }
    if isinstance(error, RemovalInterrupted):
        return _removal_params(error)
    if isinstance(error, ProviderFailure):
        return failure_params(error)
    if isinstance(error, AccountAccessCheckFailed):
        return {
            "reason": error.kind.value,
            "provider": error.provider.value if error.provider else None,
        }
    if isinstance(error, SignInThrottled):
        return {"retry_after": error.retry_after}
    if isinstance(error, UserDeletionInterrupted):
        return {"removed": error.removed, "remaining": error.remaining}
    return _plan_params(error)


def _plan_params(error: Exception) -> dict[str, ParamValue]:
    """What a Plan's refusal names; `count` beside each number picks the message's plural form."""
    if isinstance(error, PlanLimitReached):
        return {"reason": error.resource.value, "limit": error.limit, "count": error.limit}
    if isinstance(error, PlanInUse):
        return {"people": error.people, "count": error.people}
    if isinstance(error, InvalidPlan):
        return {"reason": error.reason.value}
    return {}
```

- [ ] **Step 4: Run the tests to see the catalog check fail**

Run: `.venv/bin/pytest tests/adapters/test_api_problems.py -q`

Expected: every `test_problem_from_maps_exceptions` case passes; one test still fails:
`test_every_code_the_server_sends_has_an_english_message`, listing the seven new codes
(`invalid_plan`, `plan_in_use`, `plan_is_default`, `plan_key_taken`, `plan_limit_reached`,
`plan_not_found`, `plans_need_default`) as codes with no English message.

- [ ] **Step 5: Write the failing Web UI test for the messages**

In `web/src/i18n/api-errors.test.ts`, inside `describe("apiErrorMessage", ...)`, add this test
right before `it("shows the server's detail for an unknown code or a missing param, then a generic message", ...)`:

```ts
  it("words a plan's refusals with the numbers the server sends", () => {
    const rules = (limit: number) => coded("plan_limit_reached", { reason: "rules", limit, count: limit })
    expect(apiErrorMessage(i18n, rules(1))).toBe("Your plan lets 1 rule sync. Pause or remove it to start this rule.")
    expect(apiErrorMessage(i18n, rules(3))).toBe("Your plan lets 3 rules sync. Pause or remove one to start this rule.")
    const tokens = coded("plan_limit_reached", { reason: "integration_tokens", limit: 0, count: 0 })
    expect(apiErrorMessage(i18n, tokens)).toBe("Your plan allows at most 0 Integration Tokens. Revoked tokens do not count.")
    const later = coded("plan_limit_reached", { reason: "a_later_resource", limit: 2, count: 2 })
    expect(apiErrorMessage(i18n, later)).toBe(
      "Your plan's limit is reached. Settings, Your account, Your plan shows what it allows.",
    )
    expect(apiErrorMessage(i18n, coded("plan_in_use", { people: 1, count: 1 }))).toBe(
      "1 person has this plan. Give them another plan before you remove it.",
    )
    expect(apiErrorMessage(i18n, coded("plan_in_use", { people: 2, count: 2 }))).toBe(
      "2 people have this plan. Give them another plan before you remove it.",
    )
    expect(apiErrorMessage(i18n, coded("invalid_plan", { reason: "key" }))).toBe(
      "Use 1 to 32 lower-case letters, digits, and hyphens for the key, starting with a letter or digit.",
    )
    expect(apiErrorMessage(i18n, coded("plans_need_default"))).toBe("Choose a default plan before you turn plans on.")
  })

```

- [ ] **Step 6: Run it to verify it fails**

Run: `cd web && pnpm exec vitest run src/i18n/api-errors.test.ts`

Expected: FAIL, `expected 'English detail' to be 'Your plan lets 1 rule sync. Pause or remove it to start this rule.'`
(no message exists, so the server's detail shows).

- [ ] **Step 7: Add the English messages**

In `web/src/i18n/locales/en/common.json`, inside `"apiError"`, add these five lines right after the
`"invalid_integration_token_name"` line:

```json
    "invalid_plan": "This plan is not valid. Check its key, name, and limits.",
    "invalid_plan_interval": "Choose one of the offered sync intervals.",
    "invalid_plan_key": "Use 1 to 32 lower-case letters, digits, and hyphens for the key, starting with a letter or digit.",
    "invalid_plan_limit": "Enter each limit as a whole number up to 10000, at least 1 for rules and calendar accounts, or choose Unlimited.",
    "invalid_plan_name": "Give the plan a name of 1 to 60 characters, without line breaks or other control characters.",
```

and these entries right after the `"password_policy"` line:

```json
    "plan_in_use": {
      "one": "{count} person has this plan. Give them another plan before you remove it.",
      "other": "{count} people have this plan. Give them another plan before you remove it."
    },
    "plan_is_default": "This is the default plan. Choose another default before you remove it.",
    "plan_key_taken": "Another plan already uses this key. Choose a different key.",
    "plan_limit_reached": "Your plan's limit is reached. Settings, Your account, Your plan shows what it allows.",
    "plan_limit_reached_integration_tokens": {
      "one": "Your plan allows at most {count} Integration Token. Revoked tokens do not count.",
      "other": "Your plan allows at most {count} Integration Tokens. Revoked tokens do not count."
    },
    "plan_limit_reached_rules": {
      "one": "Your plan lets {count} rule sync. Pause or remove it to start this rule.",
      "other": "Your plan lets {count} rules sync. Pause or remove one to start this rule."
    },
    "plan_not_found": "This plan no longer exists. Reload to see the current plans.",
    "plans_need_default": "Choose a default plan before you turn plans on.",
```

`apiErrorMessage` tries `common.apiError.<code>_<reason>` first, so `plan_limit_reached` with
reason `rules` or `integration_tokens`, and `invalid_plan` with reason `key`, `name`, `limit`, or
`interval`, show their own message; any other reason shows the general one. With 0 tokens the
English `other` form reads "at most 0 Integration Tokens".

- [ ] **Step 8: Run the tests to verify they pass**

Run:

```sh
.venv/bin/pytest tests/adapters/test_api_problems.py tests/test_no_em_dashes.py -q
cd web && pnpm exec vitest run src/i18n/api-errors.test.ts src/i18n/catalog.test.ts && cd ..
```

Expected: all pass. The catalog test accepts the new keys through
`"common.apiError.*": "server"` and `"common.apiError.*_*": "server"`, and
`test_every_english_error_message_names_a_code_the_server_sends` accepts each `<code>_<reason>`
message.

- [ ] **Step 9: Rebuild the static bundle and run the gates**

Run:

```sh
cd web && pnpm run typecheck && pnpm run lint && pnpm run knip && pnpm run build && cd ..
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy
.venv/bin/lint-imports
.venv/bin/pytest --cov --cov-report=term-missing --cov-fail-under=80
git status --short src/calendar_sync/interfaces/api/static
```

Expected: every command passes; `git status` shows the rebuilt bundle (a new hashed asset that
carries the catalog, and `index.html`), which changed because `common.json` changed.

- [ ] **Step 10: Commit**

```sh
git add src/calendar_sync/interfaces/api/problems.py tests/adapters/test_api_problems.py web/src/i18n/locales/en/common.json web/src/i18n/api-errors.test.ts src/calendar_sync/interfaces/api/static
git commit -F - <<'EOF'
Explain each plan refusal with a stable code and a message that names the limit

A reached limit, a plan in use, the default plan, a taken or unknown
key, an invalid plan, and turning plans on without a default now answer
with their own codes. Each number travels with a count, so the Web UI
picks the right plural form, including a plan that allows 0 tokens.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
```

## Part 4: Identity Plan use cases and the token limit (Tasks 7 and 8)

### Task 7: Identity Plan use cases

Installation Administrators define, change, and remove Plans, turn Plans on or off with a Default
Plan, and give a User their own Plan (spec sections 9 and 11; contract section 3.11). Each use case
checks first that the actor is an active Installation Administrator, and each change logs one line
that names only ids.

**Files:**
- Create: `src/calendar_sync/application/identity/plans.py`
- Modify: `src/calendar_sync/bootstrap/container.py` (imports; `AdministrationServices` gains `assign_plan`; new `PlanServices`; `Container.plans`; `compose()` passes `plans=`; `_administration()` builds `AssignPlan`; new `_plan_services()`)
- Test: `tests/application/test_plans.py` (new)
- Test: `tests/adapters/test_composition.py` (module docstring, imports, one new test)

**Interfaces:**
- Consumes (task 1, `calendar_sync.domain.plans`): `Plan`, `PlanKey`, `PlanLimits`, `SyncInterval`, `OFFERED_INTERVALS`, `NO_LIMITS`, `Allowance`, `AllowanceBasis`, `AssignmentSource`, `InvalidPlan`, `InvalidPlanReason`, `PlansNeedDefault`, `PlanIsDefault`, `PlanInUse` (`.people`), `require_offered(interval: SyncInterval) -> None`; `User.plan: PlanKey | None`.
- Consumes (task 4): `Allowances` (`calendar_sync.application.sync.ports`, `of(user) -> Allowance`); `PlansSetting(enabled, default)`, `PlanListing(plan, is_default, people, limited_people)`, `PlanCatalog` (`settings()`, `change_settings(enabled, default) -> PlansSetting`, `plans() -> Sequence[PlanListing]`, `any_plans()`, `get(key) -> Plan | None`, `add(plan, at)`, `change(plan, at)`, `remove(key)`), `AssignmentChange(source, actor, at)`, `PlanAssignments.assign(user, plan, change) -> bool` (all `calendar_sync.application.identity.ports`); `PlanNotFound`, `PlanKeyTaken` (`calendar_sync.application.identity.errors`); `Adapters.allowances`, `Adapters.plan_catalog`, `Adapters.plan_assignments`; test helpers `MemoryPlans(users: MemoryUsers, enabled, default, catalog, changes)` (`tests.identity_fakes`), `FREE`, `FAMILY`, `plans_on(catalog, default=FREE, *others)` (`tests.plans`), `limited_user(database, user=OTHER_USER, *, plan=None, email=None)` (`tests.users`).
- Consumes (existing): `require_administrator(users, actor) -> User`, `AdministratorRequired`, `UserNotFound` (`calendar_sync.application.identity.administration`); `Clock`; `UserDirectory`.
- Produces (`calendar_sync.application.identity.plans`):
  - `PlansOverview(setting: PlansSetting, plans: tuple[PlanListing, ...], offered: tuple[SyncInterval, ...])`
  - `ShowPlans(users, catalog).execute(actor: UserId) -> PlansOverview`
  - `DefinePlan(users, catalog, clock).execute(actor: UserId, plan: Plan) -> PlanListing`
  - `ChangePlan(users, catalog, clock).execute(actor: UserId, plan: Plan) -> PlanListing`
  - `RemovePlan(users, catalog).execute(actor: UserId, key: PlanKey) -> None`
  - `SetPlansSetting(users, catalog).execute(actor: UserId, enabled: bool, default: PlanKey | None) -> PlansOverview`
  - `AssignPlan(users, assignments, allowances, clock).execute(actor: UserId, user: UserId, plan: PlanKey | None) -> Allowance`
- Produces (`calendar_sync.bootstrap.container`): `PlanServices(show_plans, define_plan, change_plan, remove_plan, set_plans_setting)`; `Container.plans: PlanServices` (right after `administration`); `AdministrationServices.assign_plan: AssignPlan`. Task 13's `PlanAdministration`, `PlansApiServices`, and `users.Administration.assign_plan` protocols read these.
- Log lines (exact): `plan defined key=<key> by=<actor id>`, `plan changed key=<key> by=<actor id>`, `plan removed key=<key> by=<actor id>`, `plans setting changed enabled=<True|False> default=<key|None> by=<actor id>`, `plan assigned user=<user id> plan=<key|None> by=<actor id>`, all at INFO on logger `calendar_sync.application.identity.plans`.

- [ ] **Step 1: Write the failing test**

Create `tests/application/test_plans.py`. It covers every task-7 line of the contract task map and
Review Focus 5 at the use-case level: refusals for a member, a disabled administrator, and an
unknown actor with nothing changed; offered intervals; `DefinePlan` and `ChangePlan` interval and
key rules; `RemovePlan` refusals; `SetPlansSetting` refusals and turning Plans off; `AssignPlan`
provenance, Plans off, `None`, unknown User, unknown Plan, an administrator's own Plan; a default
change reaching every User without a Plan of their own at once (someone who joins later too) while
Users with their own Plan keep it; the default never removed nor cleared while Plans are on; log
lines with ids only.

```python
"""What Installation Administrators do with Plans (ADR 0038), over the in-memory Plans store."""

import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime

import pytest

from calendar_sync.application.identity.administration import AdministratorRequired, UserNotFound
from calendar_sync.application.identity.errors import PlanKeyTaken, PlanNotFound
from calendar_sync.application.identity.plans import (
    AssignPlan,
    ChangePlan,
    DefinePlan,
    PlansOverview,
    RemovePlan,
    SetPlansSetting,
    ShowPlans,
)
from calendar_sync.application.identity.ports import AssignmentChange, PlanListing, PlansSetting
from calendar_sync.domain.access import Role, User, UserId, UserState
from calendar_sync.domain.plans import (
    NO_LIMITS,
    OFFERED_INTERVALS,
    Allowance,
    AllowanceBasis,
    AssignmentSource,
    InvalidPlan,
    InvalidPlanReason,
    Plan,
    PlanInUse,
    PlanIsDefault,
    PlanKey,
    PlanLimits,
    PlansNeedDefault,
    SyncInterval,
)
from tests.helpers import NOW
from tests.identity_fakes import MemoryPlans, MemoryUsers
from tests.plans import FAMILY, FREE, plans_on

PLANS_LOGGER = "calendar_sync.application.identity.plans"
ADMIN = User(
    UserId("admin"), "admin@example.test", Role.INSTALLATION_ADMINISTRATOR, UserState.ACTIVE, NOW
)
MEMBER = User(UserId("member"), "member@example.test", Role.USER, UserState.ACTIVE, NOW)
NEIGHBOUR = User(UserId("neighbour"), "neighbour@example.test", Role.USER, UserState.ACTIVE, NOW)
LATECOMER = User(UserId("latecomer"), "latecomer@example.test", Role.USER, UserState.ACTIVE, NOW)
RETIRED = User(
    UserId("retired"),
    "retired@example.test",
    Role.INSTALLATION_ADMINISTRATOR,
    UserState.DISABLED,
    NOW,
)
SOLO = Plan(PlanKey("solo"), "Solo", PlanLimits(2, 2, 1, SyncInterval.INSTANT))
HOURLY = Plan(
    PlanKey("hourly"), "Hourly", PlanLimits(None, None, None, SyncInterval.EVERY_60_MINUTES)
)


@dataclass(frozen=True)
class _Clock:
    def now(self) -> datetime:
        return NOW


CLOCK = _Clock()


class _DeletedMeanwhile:
    """PlanAssignments as the store answers once the User was deleted after the check."""

    def assign(self, user: UserId, plan: PlanKey | None, change: AssignmentChange) -> bool:
        return False


def _plans(*others: User) -> MemoryPlans:
    """An installation with an administrator and a member, Plans off, and no Plan yet."""
    users = MemoryUsers()
    for user in (ADMIN, MEMBER, *others):
        users.add(user, "hashed:password")
    return MemoryPlans(users)


def _define(plans: MemoryPlans) -> DefinePlan:
    return DefinePlan(plans.users, plans, CLOCK)


def _change(plans: MemoryPlans) -> ChangePlan:
    return ChangePlan(plans.users, plans, CLOCK)


def _remove(plans: MemoryPlans) -> RemovePlan:
    return RemovePlan(plans.users, plans)


def _setting(plans: MemoryPlans) -> SetPlansSetting:
    return SetPlansSetting(plans.users, plans)


def _assign(plans: MemoryPlans) -> AssignPlan:
    return AssignPlan(plans.users, plans, plans, CLOCK)


def _own_plan(plans: MemoryPlans, user: UserId) -> PlanKey | None:
    stored = plans.users.get(user)
    assert stored is not None
    return stored.plan


def _snapshot(plans: MemoryPlans) -> tuple[object, ...]:
    return (
        plans.enabled,
        plans.default,
        dict(plans.catalog),
        dict(plans.changes),
        dict(plans.users.users),
    )


# Each would succeed for an active administrator, on Plans turned on with FREE and FAMILY.
ATTEMPTS: dict[str, Callable[[MemoryPlans, UserId], object]] = {
    "show plans": lambda plans, actor: ShowPlans(plans.users, plans).execute(actor),
    "define a plan": lambda plans, actor: _define(plans).execute(actor, SOLO),
    "change a plan": lambda plans, actor: _change(plans).execute(
        actor, replace(FREE, name="Starter")
    ),
    "remove a plan": lambda plans, actor: _remove(plans).execute(actor, FAMILY.key),
    "turn plans off": lambda plans, actor: _setting(plans).execute(actor, False, FREE.key),
    "assign a plan": lambda plans, actor: _assign(plans).execute(actor, MEMBER.id, FAMILY.key),
}


@pytest.mark.parametrize("attempt", list(ATTEMPTS.values()), ids=list(ATTEMPTS))
@pytest.mark.parametrize(
    "actor",
    [MEMBER.id, RETIRED.id, UserId("nobody")],
    ids=["member", "disabled administrator", "unknown"],
)
def test_only_an_active_administrator_manages_plans(
    attempt: Callable[[MemoryPlans, UserId], object], actor: UserId
) -> None:
    plans = _plans(RETIRED)
    plans_on(plans, FREE, FAMILY)
    before = _snapshot(plans)

    with pytest.raises(AdministratorRequired):
        attempt(plans, actor)

    assert _snapshot(plans) == before
    # The same request goes through for an active administrator.
    attempt(plans, ADMIN.id)


# Showing Plans


def test_show_plans_answers_each_plan_who_has_it_the_setting_and_the_offered_intervals() -> None:
    plans = _plans(NEIGHBOUR)
    plans_on(plans, FREE, FAMILY)
    _assign(plans).execute(ADMIN.id, NEIGHBOUR.id, FAMILY.key)

    overview = ShowPlans(plans.users, plans).execute(ADMIN.id)

    # FREE is the default, so the administrator and the member have it; it limits the member.
    assert overview == PlansOverview(
        PlansSetting(True, FREE.key),
        (PlanListing(FAMILY, False, 1, 1), PlanListing(FREE, True, 2, 1)),
        (SyncInterval.INSTANT, SyncInterval.EVERY_5_MINUTES),
    )


def test_a_new_installation_shows_no_plans_and_plans_off() -> None:
    plans = _plans()

    overview = ShowPlans(plans.users, plans).execute(ADMIN.id)

    assert overview == PlansOverview(PlansSetting(False, None), (), OFFERED_INTERVALS)


# Defining and changing Plans


def test_an_administrator_defines_a_plan_with_an_offered_interval() -> None:
    plans = _plans()

    listing = _define(plans).execute(ADMIN.id, SOLO)

    assert listing == PlanListing(SOLO, False, 0, 0)
    assert plans.get(SOLO.key) == SOLO


def test_a_new_plan_whose_interval_is_not_offered_is_refused() -> None:
    plans = _plans()

    with pytest.raises(InvalidPlan) as refused:
        _define(plans).execute(ADMIN.id, HOURLY)

    assert refused.value.reason is InvalidPlanReason.INTERVAL
    assert plans.any_plans() is False


def test_a_taken_key_is_refused_and_the_plan_with_it_is_kept() -> None:
    plans = _plans()
    plans.add(FREE, NOW)

    with pytest.raises(PlanKeyTaken):
        _define(plans).execute(ADMIN.id, replace(FREE, name="Another free plan"))

    assert plans.get(FREE.key) == FREE


def test_changing_a_plan_keeps_its_key_and_its_new_limits_apply_at_once() -> None:
    plans = _plans()
    plans_on(plans, FREE)
    roomier = Plan(FREE.key, "Starter", PlanLimits(2, 2, 1, SyncInterval.INSTANT))

    listing = _change(plans).execute(ADMIN.id, roomier)

    assert listing == PlanListing(roomier, True, 2, 1)
    assert list(plans.catalog) == [FREE.key]
    assert plans.of(MEMBER.id) == Allowance(AllowanceBasis.PLAN, plan=roomier, on_default=True)


def test_a_newly_chosen_interval_must_be_offered() -> None:
    plans = _plans()
    plans.add(FREE, NOW)
    hourly = replace(FREE, limits=replace(FREE.limits, sync_interval=SyncInterval.EVERY_60_MINUTES))

    with pytest.raises(InvalidPlan) as refused:
        _change(plans).execute(ADMIN.id, hourly)

    assert refused.value.reason is InvalidPlanReason.INTERVAL
    assert plans.get(FREE.key) == FREE


def test_an_interval_a_later_release_stored_may_be_kept() -> None:
    plans = _plans()
    # As a release offering every interval stored it, before a rollback to this one.
    plans.catalog[HOURLY.key] = HOURLY
    renamed = replace(HOURLY, name="Every hour")

    listing = _change(plans).execute(ADMIN.id, renamed)

    assert listing.plan == renamed
    assert plans.get(HOURLY.key) == renamed


def test_changing_a_plan_that_does_not_exist_is_plan_not_found() -> None:
    plans = _plans()

    with pytest.raises(PlanNotFound):
        _change(plans).execute(ADMIN.id, FREE)

    assert plans.any_plans() is False


# Removing Plans


def test_a_plan_nobody_has_is_removed() -> None:
    plans = _plans()
    plans_on(plans, FREE, FAMILY)

    _remove(plans).execute(ADMIN.id, FAMILY.key)

    assert plans.get(FAMILY.key) is None
    assert plans.get(FREE.key) == FREE


def test_a_plan_someone_has_is_kept_and_the_refusal_says_how_many_have_it() -> None:
    plans = _plans(NEIGHBOUR)
    plans_on(plans, FREE, FAMILY)
    for user in (MEMBER, NEIGHBOUR):
        _assign(plans).execute(ADMIN.id, user.id, FAMILY.key)

    with pytest.raises(PlanInUse) as in_use:
        _remove(plans).execute(ADMIN.id, FAMILY.key)

    assert in_use.value.people == 2
    assert plans.get(FAMILY.key) == FAMILY


def test_removing_a_plan_that_does_not_exist_is_plan_not_found() -> None:
    plans = _plans()
    plans_on(plans, FREE)

    with pytest.raises(PlanNotFound):
        _remove(plans).execute(ADMIN.id, FAMILY.key)

    assert plans.get(FREE.key) == FREE


# The Plans setting and the Default Plan


def test_turning_plans_on_with_a_default_answers_the_overview_and_limits_members() -> None:
    plans = _plans()
    plans.add(FREE, NOW)

    overview = _setting(plans).execute(ADMIN.id, True, FREE.key)

    assert overview == PlansOverview(
        PlansSetting(True, FREE.key), (PlanListing(FREE, True, 2, 1),), OFFERED_INTERVALS
    )
    assert plans.of(MEMBER.id) == Allowance(AllowanceBasis.PLAN, plan=FREE, on_default=True)


def test_plans_turn_on_only_with_a_default() -> None:
    plans = _plans()
    plans.add(FREE, NOW)

    with pytest.raises(PlansNeedDefault):
        _setting(plans).execute(ADMIN.id, True, None)

    assert plans.settings() == PlansSetting(False, None)


def test_a_default_that_names_no_plan_is_plan_not_found() -> None:
    plans = _plans()
    plans.add(FREE, NOW)

    with pytest.raises(PlanNotFound):
        _setting(plans).execute(ADMIN.id, True, PlanKey("missing"))

    assert plans.settings() == PlansSetting(False, None)


@pytest.mark.parametrize("default", [FREE.key, None], ids=["keeping the default", "clearing it"])
def test_turning_plans_off_is_always_allowed_and_keeps_every_plan(default: PlanKey | None) -> None:
    plans = _plans()
    plans_on(plans, FREE, FAMILY)
    _assign(plans).execute(ADMIN.id, MEMBER.id, FAMILY.key)

    overview = _setting(plans).execute(ADMIN.id, False, default)

    assert overview.setting == PlansSetting(False, default)
    assert [listing.plan for listing in overview.plans] == [FAMILY, FREE]
    assert plans.of(MEMBER.id) == Allowance(AllowanceBasis.PLANS_OFF, assigned=FAMILY)


def test_a_new_default_applies_at_once_to_everyone_without_a_plan_of_their_own() -> None:
    plans = _plans(NEIGHBOUR)
    plans_on(plans, FREE, FAMILY)
    _assign(plans).execute(ADMIN.id, NEIGHBOUR.id, FREE.key)

    _setting(plans).execute(ADMIN.id, True, FAMILY.key)
    # Someone who joins later has no Plan of their own either.
    plans.users.add(LATECOMER, "hashed:password")

    on_default = Allowance(AllowanceBasis.PLAN, plan=FAMILY, on_default=True)
    assert plans.of(MEMBER.id) == on_default
    assert plans.of(LATECOMER.id) == on_default
    assert plans.of(NEIGHBOUR.id) == Allowance(AllowanceBasis.PLAN, plan=FREE, assigned=FREE)
    assert set(plans.changes) == {NEIGHBOUR.id}


def test_the_default_is_never_removed_nor_cleared_while_plans_are_on() -> None:
    plans = _plans()
    plans_on(plans, FREE, FAMILY)

    with pytest.raises(PlanIsDefault):
        _remove(plans).execute(ADMIN.id, FREE.key)
    with pytest.raises(PlansNeedDefault):
        _setting(plans).execute(ADMIN.id, True, None)

    assert plans.settings() == PlansSetting(True, FREE.key)
    assert plans.get(FREE.key) == FREE


# Assigning a Plan


def test_assigning_a_plan_records_the_administrator_and_when() -> None:
    plans = _plans()
    plans_on(plans, FREE, FAMILY)

    allowance = _assign(plans).execute(ADMIN.id, MEMBER.id, FAMILY.key)

    assert allowance == Allowance(AllowanceBasis.PLAN, plan=FAMILY, assigned=FAMILY)
    assert _own_plan(plans, MEMBER.id) == FAMILY.key
    assert plans.changes[MEMBER.id] == AssignmentChange(
        AssignmentSource.ADMINISTRATOR, ADMIN.id, NOW
    )


def test_a_plan_assigned_while_plans_are_off_applies_once_they_are_on() -> None:
    plans = _plans()
    plans.add(FREE, NOW)
    plans.add(FAMILY, NOW)

    allowance = _assign(plans).execute(ADMIN.id, MEMBER.id, FAMILY.key)
    _setting(plans).execute(ADMIN.id, True, FREE.key)

    assert allowance == Allowance(AllowanceBasis.PLANS_OFF, assigned=FAMILY)
    assert plans.of(MEMBER.id) == Allowance(AllowanceBasis.PLAN, plan=FAMILY, assigned=FAMILY)


def test_assigning_none_returns_the_user_to_the_default_plan() -> None:
    plans = _plans()
    plans_on(plans, FREE, FAMILY)
    _assign(plans).execute(ADMIN.id, MEMBER.id, FAMILY.key)

    allowance = _assign(plans).execute(ADMIN.id, MEMBER.id, None)

    assert allowance == Allowance(AllowanceBasis.PLAN, plan=FREE, on_default=True)
    assert _own_plan(plans, MEMBER.id) is None
    assert plans.changes[MEMBER.id] == AssignmentChange(
        AssignmentSource.ADMINISTRATOR, ADMIN.id, NOW
    )


def test_an_administrators_own_plan_is_stored_and_limits_them_not_at_all() -> None:
    plans = _plans()
    plans_on(plans, FREE, FAMILY)

    allowance = _assign(plans).execute(ADMIN.id, ADMIN.id, FAMILY.key)

    assert allowance == Allowance(AllowanceBasis.ADMINISTRATOR, assigned=FAMILY)
    assert allowance.limits == NO_LIMITS
    assert _own_plan(plans, ADMIN.id) == FAMILY.key


def test_assigning_to_an_unknown_user_is_user_not_found() -> None:
    plans = _plans()
    plans_on(plans, FREE, FAMILY)

    with pytest.raises(UserNotFound):
        _assign(plans).execute(ADMIN.id, UserId("nobody"), FAMILY.key)

    assert plans.changes == {}


def test_a_user_deleted_before_the_assignment_is_user_not_found() -> None:
    plans = _plans()
    plans_on(plans, FREE, FAMILY)
    assigning = AssignPlan(plans.users, _DeletedMeanwhile(), plans, CLOCK)

    with pytest.raises(UserNotFound):
        assigning.execute(ADMIN.id, MEMBER.id, FAMILY.key)


def test_assigning_an_unknown_plan_is_plan_not_found_and_changes_nothing() -> None:
    plans = _plans()
    plans_on(plans, FREE)

    with pytest.raises(PlanNotFound):
        _assign(plans).execute(ADMIN.id, MEMBER.id, PlanKey("missing"))

    assert _own_plan(plans, MEMBER.id) is None
    assert plans.changes == {}


# Log lines


def test_each_change_logs_one_line_naming_only_ids(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=PLANS_LOGGER)
    plans = _plans()
    plans.add(FREE, NOW)

    _define(plans).execute(ADMIN.id, SOLO)
    _change(plans).execute(ADMIN.id, replace(SOLO, name="Solo, renamed"))
    _assign(plans).execute(ADMIN.id, MEMBER.id, SOLO.key)
    _setting(plans).execute(ADMIN.id, True, FREE.key)
    _assign(plans).execute(ADMIN.id, MEMBER.id, None)
    _remove(plans).execute(ADMIN.id, SOLO.key)
    ShowPlans(plans.users, plans).execute(ADMIN.id)

    lines = [record.getMessage() for record in caplog.records if record.name == PLANS_LOGGER]
    assert lines == [
        "plan defined key=solo by=admin",
        "plan changed key=solo by=admin",
        "plan assigned user=member plan=solo by=admin",
        "plans setting changed enabled=True default=free by=admin",
        "plan assigned user=member plan=None by=admin",
        "plan removed key=solo by=admin",
    ]
    logged = "\n".join(lines)
    assert "Solo" not in logged
    assert "Free" not in logged
    assert "@example.test" not in logged
```

- [ ] **Step 2: Run it to verify it fails**

```sh
.venv/bin/pytest tests/application/test_plans.py -q
```

Expected: the module fails to collect with
`ModuleNotFoundError: No module named 'calendar_sync.application.identity.plans'`.

- [ ] **Step 3: Implement the use cases**

Create `src/calendar_sync/application/identity/plans.py`. `identity` may import `sync`
(`Allowances`), so no import-linter contract changes. `AssignPlan` has 4 fields and every other
use case 2 or 3, under the 7-field bound of `tests/test_architecture.py`.

```python
"""What Installation Administrators do with Plans (ADR 0038): define, change, and remove them,
choose the Default Plan, turn Plans on or off, and give a User their own Plan.

Each use case checks first that the actor is an active Installation Administrator. Each change
logs one line that names only ids: a Plan's key and Users' identifiers, never a name or email.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from calendar_sync.application.identity.administration import UserNotFound, require_administrator
from calendar_sync.application.identity.errors import PlanNotFound
from calendar_sync.application.identity.ports import (
    AssignmentChange,
    PlanAssignments,
    PlanCatalog,
    PlanListing,
    PlansSetting,
    UserDirectory,
)
from calendar_sync.application.shared.ports import Clock
from calendar_sync.application.sync.ports import Allowances
from calendar_sync.domain.access import UserId
from calendar_sync.domain.plans import (
    OFFERED_INTERVALS,
    Allowance,
    AssignmentSource,
    Plan,
    PlanKey,
    SyncInterval,
    require_offered,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PlansOverview:
    """Every Plan with who has it, the Plans setting, and the sync intervals a Plan may offer."""

    setting: PlansSetting
    plans: tuple[PlanListing, ...]
    offered: tuple[SyncInterval, ...]


def _overview(catalog: PlanCatalog, setting: PlansSetting) -> PlansOverview:
    return PlansOverview(setting, tuple(catalog.plans()), OFFERED_INTERVALS)


def _listing(catalog: PlanCatalog, key: PlanKey) -> PlanListing:
    """The Plan as listed now; PlanNotFound when another administrator removed it meanwhile."""
    listing = next((each for each in catalog.plans() if each.plan.key == key), None)
    if listing is None:
        raise PlanNotFound(f"plan {key.value} does not exist")
    return listing


def _logged(key: PlanKey | None) -> str | None:
    """A Plan key for a log line; None stands for the Default Plan."""
    return key.value if key is not None else None


@dataclass(slots=True)
class ShowPlans:
    """Every Plan, who has it, and the Plans setting, for Administration."""

    users: UserDirectory
    catalog: PlanCatalog

    def execute(self, actor: UserId) -> PlansOverview:
        require_administrator(self.users, actor)
        return _overview(self.catalog, self.catalog.settings())


@dataclass(slots=True)
class DefinePlan:
    """Add a Plan. Its key is chosen now and never changes."""

    users: UserDirectory
    catalog: PlanCatalog
    clock: Clock

    def execute(self, actor: UserId, plan: Plan) -> PlanListing:
        require_administrator(self.users, actor)
        require_offered(plan.limits.sync_interval)
        # Raises PlanKeyTaken.
        self.catalog.add(plan, self.clock.now())
        logger.info("plan defined key=%s by=%s", plan.key.value, actor.value)
        return _listing(self.catalog, plan.key)


@dataclass(slots=True)
class ChangePlan:
    """Change a Plan's name and limits, keeping its key. New limits apply at once to new rules,
    accounts, and tokens, and stop nothing a User already has."""

    users: UserDirectory
    catalog: PlanCatalog
    clock: Clock

    def execute(self, actor: UserId, plan: Plan) -> PlanListing:
        require_administrator(self.users, actor)
        current = self.catalog.get(plan.key)
        if current is None:
            raise PlanNotFound(f"plan {plan.key.value} does not exist")
        if plan.limits.sync_interval != current.limits.sync_interval:
            # A Plan may keep an interval a later release stored; a new choice must be offered.
            require_offered(plan.limits.sync_interval)
        # Raises PlanNotFound when the Plan was removed since it was read.
        self.catalog.change(plan, self.clock.now())
        logger.info("plan changed key=%s by=%s", plan.key.value, actor.value)
        return _listing(self.catalog, plan.key)


@dataclass(slots=True)
class RemovePlan:
    """Remove a Plan that is not the default and that nobody has."""

    users: UserDirectory
    catalog: PlanCatalog

    def execute(self, actor: UserId, key: PlanKey) -> None:
        require_administrator(self.users, actor)
        # Raises PlanNotFound, PlanIsDefault, or PlanInUse, decided in one step with the delete.
        self.catalog.remove(key)
        logger.info("plan removed key=%s by=%s", key.value, actor.value)


@dataclass(slots=True)
class SetPlansSetting:
    """Turn Plans on or off and choose the Default Plan. Turning Plans off is always allowed and
    keeps every Plan and every User's own Plan."""

    users: UserDirectory
    catalog: PlanCatalog

    def execute(self, actor: UserId, enabled: bool, default: PlanKey | None) -> PlansOverview:
        require_administrator(self.users, actor)
        # Raises PlanNotFound for a default that names no Plan, and PlansNeedDefault when
        # turning Plans on without one.
        setting = self.catalog.change_settings(enabled, default)
        logger.info(
            "plans setting changed enabled=%s default=%s by=%s",
            enabled,
            _logged(default),
            actor.value,
        )
        return _overview(self.catalog, setting)


@dataclass(slots=True)
class AssignPlan:
    """Give a User their own Plan, or None to return them to the Default Plan.

    Allowed while Plans are off, so an administrator can prepare them. An administrator's own
    Plan is stored and limits them only once they stop administering.
    """

    users: UserDirectory
    assignments: PlanAssignments
    allowances: Allowances
    clock: Clock

    def execute(self, actor: UserId, user: UserId, plan: PlanKey | None) -> Allowance:
        require_administrator(self.users, actor)
        if self.users.get(user) is None:
            raise UserNotFound(f"user {user.value} does not exist")
        change = AssignmentChange(AssignmentSource.ADMINISTRATOR, actor, self.clock.now())
        # Raises PlanNotFound; False when the User was deleted since the check above.
        if not self.assignments.assign(user, plan, change):
            raise UserNotFound(f"user {user.value} does not exist")
        logger.info("plan assigned user=%s plan=%s by=%s", user.value, _logged(plan), actor.value)
        return self.allowances.of(user)
```

- [ ] **Step 4: Run the tests to verify they pass**

```sh
.venv/bin/pytest tests/application/test_plans.py tests/test_architecture.py -q
```

Expected: `tests/application/test_plans.py` reports 45 passed (27 test functions; the refusal test
runs 6 use cases for 3 actors), and the architecture tests pass.

- [ ] **Step 5: Write the failing composition test**

In `tests/adapters/test_composition.py`, replace the module docstring:

```python
"""The composed installation shares one rule lock registry across every use case, and one
Plans store across every Plan use case.

Rule execution is serialized only when every use case that runs, previews, reconciles, removes,
or changes a rule holds the same `RuleLocks`. No use case creates a registry of its own, so the
container is the one place a registry is made.
"""
```

Replace its import block with:

```python
from collections.abc import Iterator
from pathlib import Path

from calendar_sync.application.identity.ports import PlanListing
from calendar_sync.application.sync.locking import RuleLocks
from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import build_adapters, compose
from calendar_sync.domain.plans import Allowance, AllowanceBasis
from calendar_sync.infrastructure.security import CredentialCipher
from tests.plans import FAMILY
from tests.users import OTHER_USER, USER, administrator, limited_user
```

Append this test at the end of the file:

```python
def test_the_plan_use_cases_share_the_installations_one_plans_store(tmp_path: Path) -> None:
    settings = Settings(tmp_path / "test.db")
    adapters = build_adapters(settings)
    container = compose(settings, adapters)
    admin = administrator(adapters)
    member = limited_user(settings.database_path)

    container.plans.define_plan.execute(admin, FAMILY)
    assigned = container.administration.assign_plan.execute(admin, member, FAMILY.key)
    overview = container.plans.set_plans_setting.execute(admin, True, FAMILY.key)

    assert assigned == Allowance(AllowanceBasis.PLANS_OFF, assigned=FAMILY)
    # FAMILY is the default and the member's own: both have it, and it limits the member.
    assert overview.plans == (PlanListing(FAMILY, True, 2, 1),)
    assert container.plans.show_plans.execute(admin) == overview
    assert adapters.allowances.of(member) == Allowance(
        AllowanceBasis.PLAN, plan=FAMILY, assigned=FAMILY
    )
```

- [ ] **Step 6: Run it to verify it fails**

```sh
.venv/bin/pytest tests/adapters/test_composition.py -q
```

Expected: `test_the_plan_use_cases_share_the_installations_one_plans_store` fails with
`AttributeError: 'Container' object has no attribute 'plans'`; the rule-lock test still passes.

- [ ] **Step 7: Compose the use cases**

In `src/calendar_sync/bootstrap/container.py`, add this import right after the
`from calendar_sync.application.identity.administration import (...)` block and before
`from calendar_sync.application.identity.ports import (`:

```python
from calendar_sync.application.identity.plans import (
    AssignPlan,
    ChangePlan,
    DefinePlan,
    RemovePlan,
    SetPlansSetting,
    ShowPlans,
)
```

Replace the `AdministrationServices` class with this version, and add `PlanServices` right after
it (before `class Container`):

```python
@dataclass(frozen=True, slots=True)
class AdministrationServices:
    """What Installation Administrators do with Users, and the links people use to join or to
    choose a new password."""

    show_registration: ShowRegistration
    set_registration_policy: SetRegistrationPolicy
    invite_user: InviteUser
    list_invitations: ListInvitations
    revoke_invitation: RevokeInvitation
    check_invitation: CheckInvitation
    accept_invitation: AcceptInvitation
    issue_password_reset: IssuePasswordReset
    check_password_reset: CheckPasswordReset
    reset_password: ResetPassword
    change_role: ChangeRole
    change_user_state: ChangeUserState
    delete_user: DeleteUser
    delete_own_account: DeleteOwnAccount
    show_own_account_deletion: ShowOwnAccountDeletion
    assign_plan: AssignPlan
    """Gives a User their own Plan, or returns them to the Default Plan (ADR 0038)."""


@dataclass(frozen=True, slots=True)
class PlanServices:
    """What Installation Administrators do with Plans and the Plans setting (ADR 0038)."""

    show_plans: ShowPlans
    define_plan: DefinePlan
    change_plan: ChangePlan
    remove_plan: RemovePlan
    set_plans_setting: SetPlansSetting
```

In `class Container`, add `plans: PlanServices` right after `administration`:

```diff
     identity: IdentityServices
     administration: AdministrationServices
+    plans: PlanServices
     token_authentication: IntegrationTokenAuthentication
```

In `compose()`, pass it in the `Container(...)` call right after `administration=`:

```diff
         administration=_administration(
             adapters, lambda owner: _owned_rules(owner, adapters, user_services(owner))
         ),
+        plans=_plan_services(adapters),
         token_authentication=adapters.token_authentication,
```

Replace `_administration` with this version, and add `_plan_services` right after it (before
`def _scheduled_services`):

```python
def _administration(
    adapters: Adapters, owned: Callable[[UserId], OwnedRules]
) -> AdministrationServices:
    users, clock, sessions = adapters.users, adapters.clock, adapters.sessions
    settings, invitations, resets = (
        adapters.registration,
        adapters.invitations,
        adapters.password_resets,
    )
    passwords = adapters.passwords
    attempts = LinkAttempts(adapters.link_throttle)
    return AdministrationServices(
        show_registration=ShowRegistration(users, settings),
        set_registration_policy=SetRegistrationPolicy(users, settings),
        invite_user=InviteUser(users, settings, invitations, clock),
        list_invitations=ListInvitations(users, invitations, clock),
        revoke_invitation=RevokeInvitation(users, invitations, clock),
        check_invitation=CheckInvitation(settings, invitations, clock, attempts),
        accept_invitation=AcceptInvitation(
            users, settings, invitations, passwords, sessions, adapters.ids, clock, attempts
        ),
        issue_password_reset=IssuePasswordReset(users, resets, clock),
        check_password_reset=CheckPasswordReset(resets, clock, attempts),
        reset_password=ResetPassword(resets, passwords, sessions, clock, attempts),
        change_role=ChangeRole(users),
        change_user_state=ChangeUserState(users, sessions),
        delete_user=DeleteUser(users, sessions, owned),
        delete_own_account=DeleteOwnAccount(users, passwords, sessions, owned, settings, clock),
        show_own_account_deletion=ShowOwnAccountDeletion(users),
        assign_plan=AssignPlan(users, adapters.plan_assignments, adapters.allowances, clock),
    )


def _plan_services(adapters: Adapters) -> PlanServices:
    """Every Plan use case reads and writes the installation's one Plans store."""
    users, catalog, clock = adapters.users, adapters.plan_catalog, adapters.clock
    return PlanServices(
        show_plans=ShowPlans(users, catalog),
        define_plan=DefinePlan(users, catalog, clock),
        change_plan=ChangePlan(users, catalog, clock),
        remove_plan=RemovePlan(users, catalog),
        set_plans_setting=SetPlansSetting(users, catalog),
    )
```

- [ ] **Step 8: Run the tests and the backend gates**

```sh
.venv/bin/pytest tests/application/test_plans.py tests/adapters/test_composition.py tests/test_architecture.py tests/test_dev_preview.py -q
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy
.venv/bin/lint-imports
.venv/bin/pytest -q
```

Expected: every test passes (the composition file reports 2 passed); Ruff reports no change and
no error; mypy reports `Success: no issues found`; lint-imports reports every contract kept and
none broken.

- [ ] **Step 9: Commit**

```sh
git add src/calendar_sync/application/identity/plans.py src/calendar_sync/bootstrap/container.py tests/application/test_plans.py tests/adapters/test_composition.py
git commit -F - <<'EOF'
Let administrators define Plans, choose the default, and give each person their own

Adds the identity use cases behind Plans administration (ADR 0038): show,
define, change, and remove Plans, turn Plans on or off with a Default
Plan, and assign a User's own Plan, also while Plans are off. Each checks
first that the actor is an active Installation Administrator, and each
change logs one line with ids only. The container offers them as
Container.plans and AdministrationServices.assign_plan.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 8: IssueIntegrationToken and the token limit

`IssueIntegrationToken` issues every Integration Token: it refuses `installation:read` to a User
who does not administer before it reads their Plan, and the token store reads the Plan's token
limit once it holds SQLite's writer lock (spec sections 3.6 and 4; contract sections 3.7, 3.11,
and 3.12). The route answers 409 `plan_limit_reached` with `reason`, `limit`, and `count`.

**Files:**
- Modify: `src/calendar_sync/application/identity/ports.py` (`collections.abc` import; `IntegrationTokens.issue`)
- Modify: `src/calendar_sync/application/identity/integration_tokens.py` (module docstring, imports, new `IssueIntegrationToken`)
- Modify: `src/calendar_sync/infrastructure/integration_tokens.py` (imports; `SqliteUserIntegrationTokens.issue`; new `SqliteUserIntegrationTokens._require_room`)
- Modify: `src/calendar_sync/interfaces/api/routes/integrations.py` (`IntegrationServices`, `StatusServices`, `issue_integration_token`, imports)
- Modify: `src/calendar_sync/bootstrap/container.py` (import; `UserServices.issue_integration_token`; `_compose_user`)
- Test: `tests/adapters/test_integration_tokens.py` (imports; new tests at the end)
- Test: `tests/application/test_integration_tokens.py` (full new version)
- Test: `tests/adapters/test_plan_races.py` (new; the token part)
- Test: `tests/adapters/test_status_api.py` (imports, `ONE_TOKEN`, two route tests)
- Test: `tests/adapters/test_installation_health_api.py` (imports, one route test; the existing 403 tests stay unchanged)

**Interfaces:**
- Consumes (task 1): `PlanLimitReached` (`.resource`, `.limit`), `LimitedResource.INTEGRATION_TOKENS`, `require_room(resource, in_use, limit) -> None`, `Allowance.limits.integration_tokens`, `Plan`, `PlanKey`, `PlanLimits`, `SyncInterval`.
- Consumes (task 4): `Allowances.of(user) -> Allowance`; `SqlitePlans(database_path)` (`calendar_sync.infrastructure.persistence.plans`, with `add(plan, at)`, `change(plan, at)`); `Adapters.allowances`, `Adapters.plan_catalog`; `BrokenAllowances` (`tests.identity_fakes`, every read raises `RuntimeError("database is locked")`); `FREE` (0 tokens), `FAMILY` (2 tokens), `plans_on`; `limited_user`.
- Consumes (task 6): `problem_from` maps `PlanLimitReached` to code `plan_limit_reached` with params `{"reason": "integration_tokens", "limit": n, "count": n}`.
- Consumes (task 7): `container.py` as task 7 left it (the `calendar_sync.application.identity.plans` import block).
- Produces:
  - `IntegrationTokens.issue(name, scopes=frozenset({STATUS_READ}), *, within: Callable[[], int | None] | None = None) -> IssuedIntegrationToken` (port) and the same signature on `SqliteUserIntegrationTokens.issue`, which always runs `BEGIN IMMEDIATE` and calls `within()` once inside it.
  - `IssueIntegrationToken(user: UserId, users: UserDirectory, tokens: IntegrationTokens, allowances: Allowances)` with `execute(name: str, scopes: frozenset[IntegrationTokenScope]) -> IssuedIntegrationToken`; raises `AdministratorRequired`, `InvalidIntegrationTokenName`, `PlanLimitReached`, or whatever a raising Allowance read raises.
  - `UserServices.issue_integration_token: IssueIntegrationToken` (right after `integration_tokens`); in `_compose_user`, the local `tokens = adapters.integration_tokens(user_id)` is made once and shared, so task 12 passes the same `tokens` to `ShowOwnPlan`.
  - `routes/integrations.py` `IntegrationServices.issue_integration_token`; `StatusServices` keeps `for_user` and `installation_health` only.
  - `tests/adapters/test_plan_races.py` with reusable `HeldAllowances(inner)` (`.reading`, `.released` events; every read waits until released), `released(inner) -> HeldAllowances`, `WAIT = 0.5`, and `STATUS`. Tasks 9 and 11 append their races to this file and reuse them.

- [ ] **Step 1: Write the failing store tests**

In `tests/adapters/test_integration_tokens.py`, change two import lines. After
`from calendar_sync.application.identity.ports import IntegrationTokenScope, IntegrationTokenSummary`
add:

```python
from calendar_sync.domain.plans import LimitedResource, PlanLimitReached
```

and replace `from tests.users import USER, add_user` with:

```python
from tests.users import OTHER_USER, USER, add_user
```

Append at the end of the file:

```python
# The token limit (ADR 0038): `within` reads it once the store holds SQLite's write lock.


@pytest.mark.parametrize(("limit", "allowed"), [(None, 3), (2, 2), (1, 1), (0, 0)])
def test_the_limit_bounds_how_many_unrevoked_tokens_the_user_holds(
    tmp_path: Path, limit: int | None, allowed: int
) -> None:
    tokens, _, _ = _tokens(tmp_path)
    store = tokens.for_user(USER)
    for name in ("First", "Second", "Third")[:allowed]:
        store.issue(name, within=lambda: limit)

    if limit is not None:
        with pytest.raises(PlanLimitReached) as refused:
            store.issue("One more", within=lambda: limit)
        assert (refused.value.resource, refused.value.limit) == (
            LimitedResource.INTEGRATION_TOKENS,
            limit,
        )
    assert len(store.list()) == allowed


def test_only_the_users_own_unrevoked_tokens_count(tmp_path: Path) -> None:
    tokens, _, database = _tokens(tmp_path)
    add_user(database, OTHER_USER)
    tokens.for_user(OTHER_USER).issue("Theirs")
    old = tokens.for_user(USER).issue("Old monitor")
    tokens.for_user(USER).revoke(old.summary.id)

    tokens.for_user(USER).issue("Uptime Kuma", within=lambda: 1)
    with pytest.raises(PlanLimitReached):
        tokens.for_user(USER).issue("Homepage", within=lambda: 1)

    assert [token.name for token in tokens.for_user(USER).list()] == ["Uptime Kuma", "Old monitor"]


def test_the_limit_is_read_once_while_the_store_holds_the_write_lock(tmp_path: Path) -> None:
    tokens, _, database = _tokens(tmp_path)
    locked: list[bool] = []

    def limit() -> int | None:
        # Another writer gives up at once while this issue holds SQLite's write lock.
        other = sqlite3.connect(database, timeout=0, isolation_level=None)
        try:
            other.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError:
            locked.append(True)
        else:
            other.execute("ROLLBACK")
            locked.append(False)
        finally:
            other.close()
        return 5

    tokens.for_user(USER).issue("Uptime Kuma", within=limit)

    assert locked == [True]


def test_a_limit_that_cannot_be_read_issues_nothing(tmp_path: Path) -> None:
    tokens, _, _ = _tokens(tmp_path)

    def unreadable() -> int | None:
        raise RuntimeError("database is locked")

    with pytest.raises(RuntimeError, match="database is locked"):
        tokens.for_user(USER).issue("Uptime Kuma", within=unreadable)

    assert tokens.for_user(USER).list() == []


def test_an_invalid_name_is_refused_before_the_limit_is_read(tmp_path: Path) -> None:
    tokens, _, _ = _tokens(tmp_path)
    reads: list[str] = []

    def limit() -> int | None:
        reads.append("read")
        return 5

    with pytest.raises(InvalidIntegrationTokenName):
        tokens.for_user(USER).issue("Kuma\nadmin", within=limit)

    assert reads == []
```

- [ ] **Step 2: Run them to verify they fail**

```sh
.venv/bin/pytest tests/adapters/test_integration_tokens.py -q
```

Expected: the 8 new tests fail with
`TypeError: SqliteUserIntegrationTokens.issue() got an unexpected keyword argument 'within'`; the
existing tests pass.

- [ ] **Step 3: Implement `within` in the port and the SQLite store**

In `src/calendar_sync/application/identity/ports.py`, make the `collections.abc` import read as
below (if task 4 added names to this line, keep them and add `Callable`):

```python
from collections.abc import Callable, Sequence
```

Replace the `IntegrationTokens` class with:

```python
class IntegrationTokens(Protocol):
    """One User's named credentials, issued so monitors and agents can read their status."""

    def issue(
        self,
        name: str,
        scopes: frozenset[IntegrationTokenScope] = frozenset({IntegrationTokenScope.STATUS_READ}),
        *,
        within: Callable[[], int | None] | None = None,
    ) -> IssuedIntegrationToken:
        """Issue a token; raises InvalidIntegrationTokenName before anything is stored.

        `within`, when given, reads the token limit once this store holds the write lock;
        raises PlanLimitReached(INTEGRATION_TOKENS, limit), issuing nothing, when the User's
        unrevoked tokens already reach it. A `within` that raises fails the issue.
        """
        ...

    def list(self) -> Sequence[IntegrationTokenSummary]:
        """Every token, newest first, revoked ones last."""
        ...

    def revoke(self, token_id: str) -> bool:
        """Whether a token of this User's that was not yet revoked is revoked now."""
        ...
```

In `src/calendar_sync/infrastructure/integration_tokens.py`, replace
`from collections.abc import Sequence` with:

```python
from collections.abc import Callable, Sequence
```

and add, right after `from calendar_sync.domain.access import UserId`:

```python
from calendar_sync.domain.plans import LimitedResource, require_room
```

Replace the `SqliteUserIntegrationTokens` class with this version (`issue` gains `within` and
`BEGIN IMMEDIATE`; `_require_room` is new; `list` and `revoke` are unchanged):

```python
class SqliteUserIntegrationTokens:
    """One User's Integration Tokens; another User's are neither listed nor revoked."""

    def __init__(
        self, database_path: Path, user_id: UserId, clock: Clock, ids: IdGenerator
    ) -> None:
        self._database_path = database_path
        self._user = user_id
        self._clock = clock
        self._ids = ids

    def issue(
        self,
        name: str,
        scopes: frozenset[IntegrationTokenScope] = frozenset({IntegrationTokenScope.STATUS_READ}),
        *,
        within: Callable[[], int | None] | None = None,
    ) -> IssuedIntegrationToken:
        cleaned = token_name(name)
        token = TOKEN_PREFIX + secrets.token_urlsafe(32)
        summary = IntegrationTokenSummary(
            self._ids.new(),
            cleaned,
            scopes,
            self._clock.now(),
            None,
            None,
            owner=self._user,
        )
        with transaction(self._database_path) as connection:
            # Held from reading the limit to the insert, so two issues cannot both take the last
            # place, and a lower limit cannot commit between the read and the insert (ADR 0038).
            connection.execute("BEGIN IMMEDIATE")
            if within is not None:
                self._require_room(connection, within())
            connection.execute(
                """
                INSERT INTO integration_tokens (id, user_id, name, token_hash, scopes, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    summary.id,
                    self._user.value,
                    summary.name,
                    token_hash(token),
                    " ".join(sorted(scope.value for scope in scopes)),
                    summary.created_at.isoformat(),
                ),
            )
        return IssuedIntegrationToken(summary, token)

    def _require_room(self, connection: sqlite3.Connection, limit: int | None) -> None:
        """Refuse when the User's unrevoked tokens already reach `limit`; revoked ones never
        count, and neither do another User's."""
        unrevoked = connection.execute(
            "SELECT COUNT(*) FROM integration_tokens WHERE user_id = ? AND revoked_at IS NULL",
            (self._user.value,),
        ).fetchone()[0]
        require_room(LimitedResource.INTEGRATION_TOKENS, int(unrevoked), limit)

    def list(self) -> Sequence[IntegrationTokenSummary]:
        with transaction(self._database_path) as connection:
            rows = connection.execute(
                f"""
                SELECT {_COLUMNS} FROM integration_tokens WHERE user_id = ?
                ORDER BY revoked_at IS NOT NULL, created_at DESC, id
                """,  # noqa: S608
                (self._user.value,),
            ).fetchall()
        return [_summary(row) for row in rows]

    def revoke(self, token_id: str) -> bool:
        with transaction(self._database_path) as connection:
            cursor = connection.execute(
                """
                UPDATE integration_tokens SET revoked_at = ?
                WHERE id = ? AND user_id = ? AND revoked_at IS NULL
                """,
                (self._clock.now().isoformat(), token_id, self._user.value),
            )
        return cursor.rowcount == 1
```

- [ ] **Step 4: Run the store tests to verify they pass**

```sh
.venv/bin/pytest tests/adapters/test_integration_tokens.py tests/adapters/test_api_authorization.py -q
.venv/bin/mypy
```

Expected: every test passes; mypy reports `Success: no issues found` (the store still satisfies
the `IntegrationTokens` protocol, and existing callers that pass no `within` are unchanged).

- [ ] **Step 5: Write the failing use-case and race tests**

There is no in-memory `IntegrationTokens`, so these tests run on SQLite: `SqliteUserDirectory`,
`SqlitePlans`, and `SqliteIntegrationTokens` over one `tmp_path` database. Replace
`tests/application/test_integration_tokens.py` with this full version (its first three tests are
the existing ones, unchanged). It covers: within the limit; at the limit, nothing stored; revoked
tokens give their place back; a Plan offering 0 tokens refuses the first; administrators and
Plans off unlimited; a raising Allowance read fails the issue and stores nothing (fail closed);
`installation:read` refused to a member with and without room, and before the limit is read;
existing tokens keep authenticating after the limit is lowered; and Review Focus 2 (an
administrator demoted past the limit keeps their tokens, gets `PlanLimitReached` for a new one and
`AdministratorRequired` for `installation:read`, and issues again once promoted).

```python
"""Integration Tokens: their format and names, and issuing one within the User's Plan.

There is no in-memory Integration Token store, so issuing runs on SQLite: its Users, Plans, and
tokens share one database, as they do in the installation.
"""

from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from calendar_sync.application.identity.administration import AdministratorRequired
from calendar_sync.application.identity.errors import InvalidIntegrationTokenName
from calendar_sync.application.identity.integration_tokens import (
    IssueIntegrationToken,
    is_well_formed,
    token_name,
)
from calendar_sync.application.identity.ports import IntegrationTokenScope
from calendar_sync.application.sync.ports import Allowances
from calendar_sync.domain.access import Role, UserId
from calendar_sync.domain.plans import LimitedResource, Plan, PlanLimitReached
from calendar_sync.infrastructure.clock import SystemClock
from calendar_sync.infrastructure.identifiers import UuidIdGenerator
from calendar_sync.infrastructure.integration_tokens import SqliteIntegrationTokens
from calendar_sync.infrastructure.persistence.migrations import initialize_database
from calendar_sync.infrastructure.persistence.plans import SqlitePlans
from calendar_sync.infrastructure.persistence.users import SqliteUserDirectory
from tests.helpers import NOW
from tests.identity_fakes import BrokenAllowances
from tests.plans import FAMILY, FREE, plans_on
from tests.users import OTHER_USER, USER, add_user, limited_user

VALID = "cgs_" + "A" * 43
STATUS = frozenset({IntegrationTokenScope.STATUS_READ})
BOTH = frozenset({IntegrationTokenScope.STATUS_READ, IntegrationTokenScope.INSTALLATION_READ})


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        (VALID, True),
        ("cgs_" + "a-_9" * 10 + "abc", True),
        ("cgs_" + "A" * 42, False),
        ("cgs_" + "A" * 44, False),
        ("cgx_" + "A" * 43, False),
        ("cgs_" + "A" * 42 + "=", False),
        ("cgs_" + "A" * 42 + "\n", False),
        ("", False),
        ("x" * 10_000, False),
    ],
)
def test_only_the_exact_token_format_is_well_formed(token: str, expected: bool) -> None:
    assert is_well_formed(token) is expected


def test_names_are_trimmed() -> None:
    assert token_name("  Uptime Kuma  ") == "Uptime Kuma"


@pytest.mark.parametrize(
    "name",
    ["", "   ", "x" * 81, "Kuma\nadmin", "Kuma\x1b[31m", "Kuma\u2028admin", "Kuma\u2029admin"],
)
def test_names_must_be_short_printable_text(name: str) -> None:
    with pytest.raises(InvalidIntegrationTokenName):
        token_name(name)


# Issuing a token within the User's Plan (ADR 0038)


@dataclass
class _Installation:
    """One SQLite installation; USER is its Installation Administrator."""

    database: Path
    users: SqliteUserDirectory
    plans: SqlitePlans
    tokens: SqliteIntegrationTokens

    def issuing(self, user: UserId, allowances: Allowances | None = None) -> IssueIntegrationToken:
        """The use case one request of `user` gets, reading `allowances` or the stored Plans."""
        return IssueIntegrationToken(
            user,
            self.users,
            self.tokens.for_user(user),
            self.plans if allowances is None else allowances,
        )

    def names(self, user: UserId) -> list[str]:
        """The User's unrevoked tokens, by name."""
        return sorted(
            token.name for token in self.tokens.for_user(user).list() if token.revoked_at is None
        )


def _installation(tmp_path: Path) -> _Installation:
    database = tmp_path / "test.db"
    initialize_database(database)
    add_user(database, USER)
    return _Installation(
        database,
        SqliteUserDirectory(database),
        SqlitePlans(database),
        SqliteIntegrationTokens(database, SystemClock(), UuidIdGenerator()),
    )


def test_a_member_issues_tokens_while_their_plan_has_room(tmp_path: Path) -> None:
    installation = _installation(tmp_path)
    plans_on(installation.plans, FAMILY)
    member = limited_user(installation.database)

    installation.issuing(member).execute("Uptime Kuma", STATUS)
    installation.issuing(member).execute("Homepage", STATUS)

    assert installation.names(member) == ["Homepage", "Uptime Kuma"]


def test_a_token_past_the_plans_limit_is_refused_and_nothing_is_stored(tmp_path: Path) -> None:
    installation = _installation(tmp_path)
    plans_on(installation.plans, FAMILY)
    member = limited_user(installation.database)
    for name in ("Uptime Kuma", "Homepage"):
        installation.issuing(member).execute(name, STATUS)

    with pytest.raises(PlanLimitReached) as refused:
        installation.issuing(member).execute("Claude Code", STATUS)

    assert (refused.value.resource, refused.value.limit) == (LimitedResource.INTEGRATION_TOKENS, 2)
    assert installation.names(member) == ["Homepage", "Uptime Kuma"]


def test_a_revoked_token_gives_its_place_back(tmp_path: Path) -> None:
    installation = _installation(tmp_path)
    plans_on(installation.plans, FAMILY)
    member = limited_user(installation.database)
    old = installation.issuing(member).execute("Old monitor", STATUS)
    installation.issuing(member).execute("Homepage", STATUS)
    assert installation.tokens.for_user(member).revoke(old.summary.id)

    installation.issuing(member).execute("Uptime Kuma", STATUS)

    assert installation.names(member) == ["Homepage", "Uptime Kuma"]


def test_a_plan_offering_no_tokens_refuses_the_first(tmp_path: Path) -> None:
    installation = _installation(tmp_path)
    plans_on(installation.plans, FREE)
    member = limited_user(installation.database)

    with pytest.raises(PlanLimitReached) as refused:
        installation.issuing(member).execute("Uptime Kuma", STATUS)

    assert (refused.value.resource, refused.value.limit) == (LimitedResource.INTEGRATION_TOKENS, 0)
    assert installation.names(member) == []


def test_administrators_are_never_limited(tmp_path: Path) -> None:
    installation = _installation(tmp_path)
    plans_on(installation.plans, FREE)

    for name in ("Uptime Kuma", "Homepage", "Claude Code"):
        installation.issuing(USER).execute(name, STATUS)

    assert installation.names(USER) == ["Claude Code", "Homepage", "Uptime Kuma"]


def test_with_plans_off_nobody_is_limited_even_with_a_plan_of_their_own(tmp_path: Path) -> None:
    installation = _installation(tmp_path)
    installation.plans.add(FREE, NOW)
    member = limited_user(installation.database, plan=FREE.key.value)

    for name in ("Uptime Kuma", "Homepage", "Claude Code"):
        installation.issuing(member).execute(name, STATUS)

    assert installation.names(member) == ["Claude Code", "Homepage", "Uptime Kuma"]


def test_an_allowance_that_cannot_be_read_fails_the_issue_and_stores_nothing(
    tmp_path: Path,
) -> None:
    installation = _installation(tmp_path)
    plans_on(installation.plans, FAMILY)
    member = limited_user(installation.database)

    with pytest.raises(RuntimeError, match="database is locked"):
        installation.issuing(member, BrokenAllowances()).execute("Uptime Kuma", STATUS)

    assert installation.names(member) == []


@pytest.mark.parametrize("plan", [FAMILY, FREE], ids=["room left", "no room"])
def test_installation_read_needs_an_administrator_whatever_the_plan_allows(
    tmp_path: Path, plan: Plan
) -> None:
    installation = _installation(tmp_path)
    plans_on(installation.plans, plan)
    member = limited_user(installation.database)

    with pytest.raises(AdministratorRequired):
        installation.issuing(member).execute("Uptime Kuma", BOTH)

    assert installation.names(member) == []


def test_installation_read_is_refused_before_the_plan_is_read(tmp_path: Path) -> None:
    installation = _installation(tmp_path)
    member = limited_user(installation.database)

    # Reading the Allowance would raise; the refusal comes first, so it is never read.
    with pytest.raises(AdministratorRequired):
        installation.issuing(member, BrokenAllowances()).execute("Uptime Kuma", BOTH)


def test_an_administrator_issues_an_installation_read_token(tmp_path: Path) -> None:
    installation = _installation(tmp_path)
    plans_on(installation.plans, FREE)

    issued = installation.issuing(USER).execute("Uptime Kuma", BOTH)

    assert issued.summary.scopes == BOTH


def test_existing_tokens_keep_working_after_the_limit_is_lowered(tmp_path: Path) -> None:
    installation = _installation(tmp_path)
    plans_on(installation.plans, FAMILY)
    member = limited_user(installation.database)
    issued = [
        installation.issuing(member).execute(name, STATUS) for name in ("Uptime Kuma", "Homepage")
    ]
    lowered = replace(FAMILY, limits=replace(FAMILY.limits, integration_tokens=0))
    installation.plans.change(lowered, NOW)

    with pytest.raises(PlanLimitReached) as refused:
        installation.issuing(member).execute("Claude Code", STATUS)

    assert refused.value.limit == 0
    assert [installation.tokens.authenticate(each.token) is not None for each in issued] == [
        True,
        True,
    ]


def test_an_administrator_demoted_past_the_limit_keeps_their_tokens_but_issues_no_more(
    tmp_path: Path,
) -> None:
    installation = _installation(tmp_path)
    plans_on(installation.plans, FREE)
    other = add_user(installation.database, OTHER_USER)
    kept = [
        installation.issuing(other).execute("Uptime Kuma", STATUS),
        installation.issuing(other).execute("Health monitor", BOTH),
    ]

    installation.users.set_role(other, Role.USER)
    with pytest.raises(PlanLimitReached) as refused:
        installation.issuing(other).execute("Homepage", STATUS)
    with pytest.raises(AdministratorRequired):
        installation.issuing(other).execute("Homepage", BOTH)
    working = [installation.tokens.authenticate(each.token) is not None for each in kept]
    installation.users.set_role(other, Role.INSTALLATION_ADMINISTRATOR)
    promoted = installation.issuing(other).execute("Homepage", STATUS)

    assert refused.value.limit == 0
    assert working == [True, True]
    assert promoted.summary.name == "Homepage"
    assert installation.names(other) == ["Health monitor", "Homepage", "Uptime Kuma"]
```

Create `tests/adapters/test_plan_races.py` (Review Focus 3, token part: two issues for the last
place, and a Plan lowering that must wait for an issue holding the writer lock). `HeldAllowances`
holds a check at its Allowance read, after its write lock is taken; a second request that must
wait is given `WAIT` seconds to show that it does not go ahead.

```python
"""Plan limits hold when requests race on one SQLite database (ADR 0038).

Each limit check reads the User's Allowance once its own write holds SQLite's writer lock, so two
requests cannot both take the last place, and a lower limit cannot commit between a check and
its write. `HeldAllowances` holds a check at its read, so a test can show what another request
does meanwhile.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from threading import Event, Thread

import pytest

from calendar_sync.application.identity.integration_tokens import IssueIntegrationToken
from calendar_sync.application.identity.ports import IntegrationTokenScope, IssuedIntegrationToken
from calendar_sync.application.sync.ports import Allowances
from calendar_sync.domain.access import UserId
from calendar_sync.domain.plans import Allowance, LimitedResource, PlanLimitReached
from calendar_sync.infrastructure.clock import SystemClock
from calendar_sync.infrastructure.identifiers import UuidIdGenerator
from calendar_sync.infrastructure.integration_tokens import SqliteIntegrationTokens
from calendar_sync.infrastructure.persistence.migrations import initialize_database
from calendar_sync.infrastructure.persistence.plans import SqlitePlans
from calendar_sync.infrastructure.persistence.users import SqliteUserDirectory
from tests.helpers import NOW
from tests.plans import FAMILY, plans_on
from tests.users import add_user, limited_user

STATUS = frozenset({IntegrationTokenScope.STATUS_READ})
WAIT = 0.5
"""How long a test gives a request that must wait to show that it does not go ahead."""


@dataclass
class HeldAllowances:
    """Allowances whose reads say when they start and answer only once released. A check that
    reads them holds its write lock meanwhile, as a slow read would."""

    inner: Allowances
    reading: Event = field(default_factory=Event)
    released: Event = field(default_factory=Event)

    def of(self, user: UserId) -> Allowance:
        self.reading.set()
        assert self.released.wait(5)
        return self.inner.of(user)

    def of_users(self, users: Collection[UserId]) -> Mapping[UserId, Allowance]:
        self.reading.set()
        assert self.released.wait(5)
        return self.inner.of_users(users)


def released(inner: Allowances) -> HeldAllowances:
    """Allowances that answer at once, and still say when they are read."""
    held = HeldAllowances(inner)
    held.released.set()
    return held


# Integration Tokens


@dataclass
class _Tokens:
    database: Path
    plans: SqlitePlans
    tokens: SqliteIntegrationTokens

    def issuing(self, user: UserId, allowances: Allowances) -> IssueIntegrationToken:
        """One request's use case, composed for it as the Web API composes each request's."""
        return IssueIntegrationToken(
            user, SqliteUserDirectory(self.database), self.tokens.for_user(user), allowances
        )

    def unrevoked(self, user: UserId) -> int:
        return sum(token.revoked_at is None for token in self.tokens.for_user(user).list())


def _tokens(tmp_path: Path) -> _Tokens:
    database = tmp_path / "test.db"
    initialize_database(database)
    add_user(database)
    return _Tokens(
        database,
        SqlitePlans(database),
        SqliteIntegrationTokens(database, SystemClock(), UuidIdGenerator()),
    )


def _issue_in_thread(issuing: IssueIntegrationToken, name: str, outcomes: list[object]) -> Thread:
    def issue() -> None:
        try:
            outcomes.append(issuing.execute(name, STATUS))
        except PlanLimitReached as refused:
            outcomes.append(refused)

    thread = Thread(target=issue)
    thread.start()
    return thread


def test_two_issues_for_the_last_token_place_store_exactly_one(tmp_path: Path) -> None:
    installation = _tokens(tmp_path)
    plans_on(installation.plans, FAMILY)
    member = limited_user(installation.database)
    installation.issuing(member, installation.plans).execute("Homepage", STATUS)
    first = HeldAllowances(installation.plans)
    second = released(installation.plans)
    outcomes: list[object] = []

    holding = _issue_in_thread(installation.issuing(member, first), "Uptime Kuma", outcomes)
    assert first.reading.wait(5)
    waiting = _issue_in_thread(installation.issuing(member, second), "Claude Code", outcomes)
    try:
        # The second issue waits for the first one's write lock, so it cannot read the limit
        # while the first holds the last place.
        assert not second.reading.wait(WAIT)
    finally:
        first.released.set()
        holding.join()
        waiting.join()

    issued = [each for each in outcomes if isinstance(each, IssuedIntegrationToken)]
    refused = [each for each in outcomes if isinstance(each, PlanLimitReached)]
    assert (len(issued), len(refused)) == (1, 1)
    assert (refused[0].resource, refused[0].limit) == (LimitedResource.INTEGRATION_TOKENS, 2)
    assert installation.unrevoked(member) == 2


def test_a_plan_lowering_waits_for_an_issue_that_holds_the_write_lock(tmp_path: Path) -> None:
    installation = _tokens(tmp_path)
    plans_on(installation.plans, FAMILY)
    member = limited_user(installation.database)
    installation.issuing(member, installation.plans).execute("Homepage", STATUS)
    held = HeldAllowances(installation.plans)
    lowered = Event()
    one_token = replace(FAMILY, limits=replace(FAMILY.limits, integration_tokens=1))
    outcomes: list[object] = []

    def lower() -> None:
        # The administrator's ChangePlan, through its own store as its own request.
        SqlitePlans(installation.database).change(one_token, NOW)
        lowered.set()

    holding = _issue_in_thread(installation.issuing(member, held), "Uptime Kuma", outcomes)
    assert held.reading.wait(5)
    lowering = Thread(target=lower)
    lowering.start()
    try:
        # The lowering waits until the issue, which reads the limit under its write lock, has
        # committed; it never lands between that read and the insert.
        assert not lowered.wait(WAIT)
    finally:
        held.released.set()
        holding.join()
        lowering.join()

    assert lowered.is_set()
    assert [type(each) for each in outcomes] == [IssuedIntegrationToken]
    with pytest.raises(PlanLimitReached) as refused:
        installation.issuing(member, installation.plans).execute("Claude Code", STATUS)
    assert refused.value.limit == 1
    assert installation.unrevoked(member) == 2
```

- [ ] **Step 6: Run them to verify they fail**

```sh
.venv/bin/pytest tests/application/test_integration_tokens.py tests/adapters/test_plan_races.py -q
```

Expected: both files fail to collect with
`ImportError: cannot import name 'IssueIntegrationToken' from 'calendar_sync.application.identity.integration_tokens'`.

- [ ] **Step 7: Implement `IssueIntegrationToken`**

Replace `src/calendar_sync/application/identity/integration_tokens.py` with this full version
(`is_well_formed` and `token_name` are unchanged; the module docstring, three imports, and
`IssueIntegrationToken` are new). It imports `AdministratorRequired` from
`administration.py`, which never imports this module, so there is no import cycle.

```python
"""What an Integration Token and its name may look like, checked before any lookup, and issuing
one within the User's Plan (ADR 0038)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from calendar_sync.application.identity.administration import AdministratorRequired
from calendar_sync.application.identity.errors import InvalidIntegrationTokenName
from calendar_sync.application.identity.ports import (
    IntegrationTokens,
    IntegrationTokenScope,
    IssuedIntegrationToken,
    UserDirectory,
)
from calendar_sync.application.sync.ports import Allowances
from calendar_sync.domain.access import UserId

TOKEN_PREFIX = "cgs_"  # noqa: S105
# The prefix and 32 random bytes in unpadded URL-safe base64.
_TOKEN = re.compile(r"cgs_[A-Za-z0-9_-]{43}")
NAME_LIMIT = 80
# Control and format characters, and the line and paragraph separators that break a line.
_REFUSED_CATEGORIES = ("C", "Zl", "Zp")


def is_well_formed(token: str) -> bool:
    return _TOKEN.fullmatch(token) is not None


def token_name(raw: str) -> str:
    name = raw.strip()
    if not 1 <= len(name) <= NAME_LIMIT or any(
        unicodedata.category(character).startswith(_REFUSED_CATEGORIES) for character in name
    ):
        raise InvalidIntegrationTokenName("name must be 1 to 80 printable characters")
    return name


@dataclass(slots=True)
class IssueIntegrationToken:
    """Issue one of the User's Integration Tokens, within their Plan's token limit (ADR 0038)."""

    user: UserId
    users: UserDirectory
    tokens: IntegrationTokens
    allowances: Allowances

    def execute(
        self, name: str, scopes: frozenset[IntegrationTokenScope]
    ) -> IssuedIntegrationToken:
        if IntegrationTokenScope.INSTALLATION_READ in scopes:
            # Checked before the limit is read: Installation Health is for administrators only
            # (ADR 0030), whatever their Plan allows.
            issuer = self.users.get(self.user)
            if issuer is None or not issuer.administers:
                raise AdministratorRequired(
                    "only an Installation Administrator may read Installation Health"
                )
        # The store reads the limit once it holds its write lock. A read that raises fails the
        # issue, so a fault never admits a token past the limit.
        return self.tokens.issue(name, scopes, within=self._token_limit)

    def _token_limit(self) -> int | None:
        return self.allowances.of(self.user).limits.integration_tokens
```

- [ ] **Step 8: Run the tests to verify they pass**

```sh
.venv/bin/pytest tests/application/test_integration_tokens.py tests/adapters/test_plan_races.py tests/adapters/test_integration_tokens.py -q
```

Expected: every test passes. Each race test waits about `WAIT` (0.5 s) on purpose.

- [ ] **Step 9: Write the failing route tests**

In `tests/adapters/test_status_api.py`, replace the import block from
`from calendar_sync.bootstrap.config import Settings` to the `tests.users` import with:

```python
from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import Adapters, Container, build_adapters, compose
from calendar_sync.domain.access import Role
from calendar_sync.domain.audit import AuditAction, AuditEntry, AuditOutcome, RecordedEvent
from calendar_sync.domain.model import (
    CalendarEndpoint,
    CalendarId,
    ConnectedAccountId,
    SyncRule,
    SyncRuleId,
    SyncRuleState,
)
from calendar_sync.domain.plans import Plan, PlanKey, PlanLimits, SyncInterval
from calendar_sync.interfaces.access import StatusAccess, StatusPrincipal
from calendar_sync.interfaces.api import dependencies
from calendar_sync.interfaces.api.app import create_app
from calendar_sync.interfaces.api.dependencies import (
    SESSION_COOKIE,
    StatusReaderServices,
    status_reader,
)
from tests.helpers import endpoint, rule
from tests.plans import FREE, plans_on
from tests.users import (
    OTHER_USER,
    add_account,
    add_user,
    administrator,
    limited_user,
    session_for,
    sign_in,
)
```

Add this constant right after the `SECRETS = {...}` dictionary:

```python
ONE_TOKEN = Plan(PlanKey("one-token"), "One token", PlanLimits(None, None, 1, SyncInterval.INSTANT))
```

Insert these two tests right after `test_tokens_are_managed_only_with_an_administrator_session`
(before `class _RefusingSessions:`):

```python
def test_a_member_at_their_plans_token_limit_is_refused_with_the_limit(tmp_path: Path) -> None:
    container, adapters = _installation(tmp_path)
    database = tmp_path / "test.db"
    member = limited_user(database)
    plans_on(adapters.plan_catalog, ONE_TOKEN)
    with TestClient(create_app(container)) as client:
        client.cookies.set(SESSION_COOKIE, session_for(database, member))
        _issue(client)
        refused = client.post("/api/v1/integration-tokens", json={"name": "Homepage"})
        listed = client.get("/api/v1/integration-tokens").json()

    assert (refused.status_code, refused.json()["code"], refused.json()["params"]) == (
        409,
        "plan_limit_reached",
        {"reason": "integration_tokens", "limit": 1, "count": 1},
    )
    assert [token["name"] for token in listed] == ["Uptime Kuma"]


def test_a_demoted_administrator_keeps_their_tokens_but_issues_none_past_the_limit(
    tmp_path: Path,
) -> None:
    container, adapters = _installation(tmp_path)
    database = tmp_path / "test.db"
    other = add_user(database, OTHER_USER)
    plans_on(adapters.plan_catalog, FREE)
    with TestClient(create_app(container)) as client:
        client.cookies.set(SESSION_COOKIE, session_for(database, other))
        kept = _issue(client)
        adapters.users.set_role(other, Role.USER)
        refused = client.post("/api/v1/integration-tokens", json={"name": "Homepage"})
        health = client.post(
            "/api/v1/integration-tokens",
            json={"name": "Health monitor", "scopes": ["status:read", "installation:read"]},
        )
        still_reads = client.get("/api/v1/status", headers={"Authorization": f"Bearer {kept}"})
        adapters.users.set_role(other, Role.INSTALLATION_ADMINISTRATOR)
        promoted = client.post("/api/v1/integration-tokens", json={"name": "Homepage"})

    assert (refused.status_code, refused.json()["code"], refused.json()["params"]) == (
        409,
        "plan_limit_reached",
        {"reason": "integration_tokens", "limit": 0, "count": 0},
    )
    assert (health.status_code, health.json()["code"]) == (403, "administrator_required")
    assert still_reads.status_code == 200
    assert promoted.status_code == 201
```

In `tests/adapters/test_installation_health_api.py`, add `from dataclasses import replace` as the
first import (above `from datetime import ...`), and replace the first-party imports with:

```python
from calendar_sync.application.operations.installation_health import InstallationHealth
from calendar_sync.application.operations.installation_hints import (
    PLAIN_HTTP_ANCHOR,
    HintKind,
    InstallationHint,
)
from calendar_sync.application.operations.status import StatusVerdict
from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import build_container
from calendar_sync.infrastructure.persistence.plans import SqlitePlans
from calendar_sync.interfaces.api.app import create_app
from calendar_sync.interfaces.api.status_payload import installation_health_response
from tests.adapters.test_mcp import JSON_HEADERS
from tests.helpers import NOW
from tests.plans import FAMILY, plans_on
from tests.users import ADMIN_EMAIL, ADMIN_PASSWORD
```

Insert this test right after
`test_only_installation_read_tokens_and_administrators_read_installation_health` (before
`test_a_token_stops_reading_installation_health_when_its_user_stops_administering`):

```python
def test_installation_read_is_refused_to_a_member_before_their_plans_token_limit(
    tmp_path: Path,
) -> None:
    plans = SqlitePlans(tmp_path / "test.db")
    no_tokens = replace(FAMILY, limits=replace(FAMILY.limits, integration_tokens=0))
    with _client(tmp_path) as admin, _client(tmp_path) as member:
        _join(admin, member)
        plans_on(plans, FAMILY)
        with_room = _issue(member, BOTH)
        plans.change(no_tokens, NOW)
        without_room = _issue(member, BOTH)
        status_only = _issue(member)

    # Installation Health is for administrators whatever their Plan allows, and that is said
    # before the limit is.
    assert (with_room.status_code, with_room.json()["code"]) == (403, "administrator_required")
    assert (without_room.status_code, without_room.json()["code"]) == (
        403,
        "administrator_required",
    )
    assert (status_only.status_code, status_only.json()["code"]) == (409, "plan_limit_reached")
```

- [ ] **Step 10: Run them to verify they fail**

```sh
.venv/bin/pytest tests/adapters/test_status_api.py tests/adapters/test_installation_health_api.py -q
```

Expected: `test_a_member_at_their_plans_token_limit_is_refused_with_the_limit`,
`test_a_demoted_administrator_keeps_their_tokens_but_issues_none_past_the_limit`, and
`test_installation_read_is_refused_to_a_member_before_their_plans_token_limit` fail with
`KeyError: 'code'`: the route still issues the token with no limit (201), and a 201 body has no
`code`. Every existing test passes.

- [ ] **Step 11: Route the issue through the use case, and compose it**

Replace `src/calendar_sync/interfaces/api/routes/integrations.py` with this full version. The
route drops its `installation` and `user` parameters and its inline administrator check; the
`StatusServices.identity` property, the `SignedIn` alias, and the `Identity` import go too,
because nothing reads them any more (`ApiServices` declares its own `identity`). The route keeps
no docstring and the same parameters, so the OpenAPI schema does not change.

```python
from __future__ import annotations

from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, Response, status

from calendar_sync.application.identity.administration import AdministratorRequired
from calendar_sync.application.identity.errors import InvalidIntegrationTokenName
from calendar_sync.application.identity.integration_tokens import IssueIntegrationToken
from calendar_sync.application.identity.ports import (
    IntegrationTokens,
    IntegrationTokenScope,
    IntegrationTokenSummary,
)
from calendar_sync.application.operations.installation_health import GetInstallationHealth
from calendar_sync.application.operations.status import GetInstallationStatus
from calendar_sync.domain.access import UserId
from calendar_sync.domain.plans import PlanLimitReached
from calendar_sync.interfaces.api.dependencies import (
    app_services,
    current_user,
    installation_reader,
    status_reader,
    user_services,
)
from calendar_sync.interfaces.api.problems import problem, problem_from
from calendar_sync.interfaces.api.schemas import (
    InstallationHealthResponse,
    IntegrationTokenResponse,
    IssuedIntegrationTokenResponse,
    IssueIntegrationTokenRequest,
    StatusResponse,
)
from calendar_sync.interfaces.api.status_payload import (
    installation_health_response,
    status_response,
)


class IntegrationServices(Protocol):
    """One User's tokens and Installation Status."""

    @property
    def integration_tokens(self) -> IntegrationTokens: ...
    @property
    def issue_integration_token(self) -> IssueIntegrationToken: ...
    @property
    def get_installation_status(self) -> GetInstallationStatus: ...


class StatusServices(Protocol):
    def for_user(self, user_id: UserId) -> IntegrationServices: ...
    @property
    def installation_health(self) -> GetInstallationHealth: ...


Services = Annotated[IntegrationServices, Depends(user_services)]
Installation = Annotated[StatusServices, Depends(app_services)]
Reader = Annotated[UserId, Depends(status_reader)]
HealthReader = Annotated[UserId, Depends(installation_reader)]
ADMIN = [Depends(current_user)]
router = APIRouter()


@router.get("/api/v1/status", response_model=StatusResponse)
def installation_status(
    installation: Installation, reader: Reader, response: Response
) -> StatusResponse:
    """The Installation Status of the User the token or session belongs to (ADR 0030)."""
    response.headers["Cache-Control"] = "no-store"
    return status_response(installation.for_user(reader).get_installation_status.execute())


@router.get("/api/v1/installation/health", response_model=InstallationHealthResponse)
def installation_health(
    installation: Installation, _reader: HealthReader, response: Response
) -> InstallationHealthResponse:
    """Installation Health, for an Installation Administrator's session or installation:read
    token; it names no rule, calendar, or User (ADR 0030)."""
    response.headers["Cache-Control"] = "no-store"
    return installation_health_response(installation.installation_health.execute())


@router.get(
    "/api/v1/integration-tokens",
    response_model=list[IntegrationTokenResponse],
    dependencies=ADMIN,
)
def list_integration_tokens(services: Services) -> list[IntegrationTokenResponse]:
    return [_token(summary) for summary in services.integration_tokens.list()]


@router.post(
    "/api/v1/integration-tokens",
    response_model=IssuedIntegrationTokenResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=ADMIN,
)
def issue_integration_token(
    payload: IssueIntegrationTokenRequest, services: Services, response: Response
) -> IssuedIntegrationTokenResponse:
    response.headers["Cache-Control"] = "no-store"
    scopes = frozenset(IntegrationTokenScope(scope) for scope in payload.scopes)
    # The use case refuses installation:read to a User who does not administer before it reads
    # the User's Plan, and refuses a token past the Plan's limit (ADR 0030, ADR 0038).
    try:
        issued = services.issue_integration_token.execute(payload.name, scopes)
    except AdministratorRequired as error:
        raise problem_from(status.HTTP_403_FORBIDDEN, error) from error
    except InvalidIntegrationTokenName as error:
        raise problem_from(status.HTTP_422_UNPROCESSABLE_CONTENT, error) from error
    except PlanLimitReached as error:
        raise problem_from(status.HTTP_409_CONFLICT, error) from error
    return IssuedIntegrationTokenResponse(**_token(issued.summary).model_dump(), token=issued.token)


@router.delete(
    "/api/v1/integration-tokens/{token_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=ADMIN,
)
def revoke_integration_token(token_id: str, services: Services) -> None:
    if not services.integration_tokens.revoke(token_id):
        raise problem(
            status.HTTP_404_NOT_FOUND, "integration_token_not_found", "integration token not found"
        )


def _token(summary: IntegrationTokenSummary) -> IntegrationTokenResponse:
    return IntegrationTokenResponse(
        id=summary.id,
        name=summary.name,
        scopes=sorted(scope.value for scope in summary.scopes),
        created_at=summary.created_at.isoformat(),
        last_used_at=summary.last_used_at.isoformat() if summary.last_used_at else None,
        revoked_at=summary.revoked_at.isoformat() if summary.revoked_at else None,
    )
```

In `src/calendar_sync/bootstrap/container.py`, add this import right before the
`from calendar_sync.application.identity.plans import (` block that task 7 added:

```python
from calendar_sync.application.identity.integration_tokens import IssueIntegrationToken
```

In `class UserServices`, add the field right after `integration_tokens`:

```diff
     get_installation_status: GetInstallationStatus
     integration_tokens: IntegrationTokens
+    issue_integration_token: IssueIntegrationToken
+    """Issues a token within the User's Plan; installation:read only for administrators."""
     inspect_activity_event: InspectActivityEvent
```

In `_compose_user`, make the User's token store once, right after `operations`:

```diff
     operations = adapters.operations(user_id)
+    tokens = adapters.integration_tokens(user_id)
     create_sync_rule = CreateSyncRule(unit_of_work)
```

and in its `UserServices(...)` call, use it for both fields:

```diff
         get_installation_status=GetInstallationStatus(
             list_sync_rules, operations, clock, heartbeat
         ),
-        integration_tokens=adapters.integration_tokens(user_id),
+        integration_tokens=tokens,
+        issue_integration_token=IssueIntegrationToken(
+            user_id, adapters.users, tokens, adapters.allowances
+        ),
         inspect_activity_event=InspectActivityEvent(
```

- [ ] **Step 12: Run the tests and the backend gates**

```sh
.venv/bin/pytest tests/adapters/test_status_api.py tests/adapters/test_installation_health_api.py tests/adapters/test_integration_tokens.py tests/application/test_integration_tokens.py tests/adapters/test_plan_races.py tests/adapters/test_mcp.py tests/adapters/test_api_authorization.py tests/adapters/test_api_problems.py tests/test_openapi_contract.py tests/test_architecture.py tests/test_dev_preview.py -q
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy
.venv/bin/lint-imports
.venv/bin/pytest --cov --cov-report=term-missing --cov-fail-under=80
```

Expected: every test passes, including the unchanged 403 tests in
`tests/adapters/test_installation_health_api.py` and `tests/test_openapi_contract.py` (no request
or response model changed, so `web/openapi.json` and `web/src/lib/api-schema.ts` need no
regeneration and nothing under `web/` changes); Ruff reports no change and no error; mypy reports
`Success: no issues found`; lint-imports reports every contract kept; coverage stays at or above
80%.

- [ ] **Step 13: Commit**

```sh
git add src/calendar_sync/application/identity/ports.py src/calendar_sync/application/identity/integration_tokens.py src/calendar_sync/infrastructure/integration_tokens.py src/calendar_sync/interfaces/api/routes/integrations.py src/calendar_sync/bootstrap/container.py tests/adapters/test_integration_tokens.py tests/application/test_integration_tokens.py tests/adapters/test_plan_races.py tests/adapters/test_status_api.py tests/adapters/test_installation_health_api.py
git commit -F - <<'EOF'
Keep new Integration Tokens within each person's plan

IssueIntegrationToken now issues every token. It refuses installation:read
to a User who does not administer before it reads their Plan, and the
token store reads the Plan's token limit once it holds SQLite's write
lock, so two requests cannot both take the last place and a lower limit
cannot slip in between. Revoked tokens give their place back, existing
tokens keep working when a limit is lowered, and administrators and
installations with Plans off are never limited. The route answers 409
plan_limit_reached with the limit.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
```

## Part 5: The Start check and the Rule Replacement successor (Tasks 9 and 10)

Tasks 9 and 10 of `.context/plans-slice1-contract.md`. Both run after tasks 1 to 8 are committed:
task 9 reads `Allowances`, `MemoryPlans`, `BrokenAllowances`, `limited_user`, `tests/plans.py`,
`SqlitePlans`, `ChangePlan`, `Adapters.allowances`, `Adapters.plan_catalog`, and the
`plan_limit_reached` problem code; task 10 reads `SyncRule.take_place_of`,
`SyncRuleRepository.inherit_place`, `MemoryState.rule_order`, and task 9's `EnableSyncRule`.

Every code block below was run against stand-ins for tasks 1 to 8 built to the contract's
signatures: the tests pass, and `ruff format --check`, `ruff check`, `mypy`, and `lint-imports`
are clean.

### Task 9: Start check and `can_start`

**Files:**
- Modify: `src/calendar_sync/application/sync/rules.py` (import block, `EnableSyncRule`, new private `_counted`, `SyncRuleDetails`, `GetSyncRuleDetails`)
- Modify: `src/calendar_sync/interfaces/api/routes/rules.py` (import block, `rule_details`, `_lifecycle_change`)
- Modify: `src/calendar_sync/interfaces/api/schemas.py` (`RuleDetailResponse`)
- Modify: `src/calendar_sync/bootstrap/container.py` (`_compose_user`: `enable_sync_rule=`, `get_sync_rule_details=`)
- Modify (regenerated, never by hand): `web/openapi.json`, `web/src/lib/api-schema.ts`
- Modify: `web/src/features/rule-preview.test.tsx` (`previewedRule`), `web/src/features/calendar-replacement.test.tsx` (`detail`), `web/src/features/rule-details.test.tsx` (`enabledRule`)
- Modify: `tests/application/test_rules.py` (constructor changes)
- Create: `tests/application/test_plan_limits.py`
- Modify: `tests/adapters/test_plan_races.py` (append the Start part; task 8 created the file)
- Create: `tests/adapters/test_rule_limit_api.py`
- Test: `tests/application/test_plan_limits.py`, `tests/application/test_rules.py`, `tests/adapters/test_plan_races.py`, `tests/adapters/test_rule_limit_api.py`, `tests/test_openapi_contract.py`

**Interfaces:**
- Consumes: `Allowances.of(user: UserId) -> Allowance` (`application/sync/ports.py`, task 4); `Allowance.limits.rules: int | None` (task 1); `may_start(before: SyncRule, counting_after: int, limit: int | None) -> bool`, `PlanLimitReached(resource: LimitedResource, limit: int)`, `LimitedResource.RULES` (`domain/plans.py`, tasks 1 and 2); `SyncRule.counts_toward_plan`, `SyncRule.keeps_place` (task 2); `MemoryPlans`, `BrokenAllowances`, `MemoryUsers` (`tests/identity_fakes.py`, task 4); `FREE`, `FAMILY`, `plans_on(catalog, default=FREE, *others)` (`tests/plans.py`, task 4); `limited_user(database, user=OTHER_USER, *, plan=None, email=None) -> UserId` (`tests/users.py`, task 4); `SqlitePlans(database_path)` (task 4); `ChangePlan(users, catalog, clock).execute(actor, plan) -> PlanListing` (task 7); `Adapters.allowances`, `Adapters.plan_catalog` (task 4); problem code `plan_limit_reached` with params `reason`, `limit`, `count` (task 6).
- Produces: `EnableSyncRule(unit_of_work: UnitOfWorkFactory, locks: RuleLocks, allowances: Allowances, owner: UserId)`; `GetSyncRuleDetails(unit_of_work: UnitOfWorkFactory, locks: RuleLocks, allowances: Allowances, owner: UserId)`; `SyncRuleDetails.can_start: bool = True`; `SyncRuleDetails.rule_limit: int | None = None`; `RuleDetailResponse.can_start: bool`; `RuleDetailResponse.rule_limit: int | None`; in the Web UI types, `RuleDetail["can_start"]: boolean` and `RuleDetail["rule_limit"]: number | null`. `POST /api/v1/rules/{rule_id}/enable` answers 409 `plan_limit_reached` with `{"reason": "rules", "limit": n, "count": n}`.

- [ ] **Step 1: Write the failing test: constructor changes in `tests/application/test_rules.py`**

Replace the import block at the top of the file (everything from `from __future__ import
annotations` through `from tests.users import memory_units`) with:

```python
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from threading import Thread

import pytest

from calendar_sync.application.sync.errors import ConnectedAccountRequired, RuleNotFound
from calendar_sync.application.sync.locking import RuleLocks, RuleWork, RuleWorkKind
from calendar_sync.application.sync.rules import (
    ChangeSyncRulePolicy,
    CreateDraftSyncRule,
    CreateSyncRule,
    EnableSyncRule,
    GetSyncRuleDetails,
    ListSyncRules,
    PauseSyncRule,
)
from calendar_sync.domain.accounts import ConnectedAccountState
from calendar_sync.domain.errors import InvalidStateTransition
from calendar_sync.domain.model import (
    AllDaySyncPolicy,
    BirthdayPolicy,
    ProjectionContent,
    SyncRule,
    SyncRuleId,
    SyncRuleState,
    TentativeEventPolicy,
    TransformationPolicy,
    UnansweredInvitationPolicy,
)
from calendar_sync.domain.runs import RuleRunOutcome, RunKind
from tests.application.test_execute_sync_rule import FixedClock
from tests.helpers import rule
from tests.identity_fakes import MemoryPlans
from tests.users import USER, memory_units
```

Replace `test_details_report_mapping_count_and_latest_outcomes` with:

```python
def test_details_report_mapping_count_and_latest_outcomes() -> None:
    unit_of_work = memory_units()
    unit_of_work.state.rules[rule().id] = rule()
    synced = RuleRunOutcome(rule().id, RunKind.SYNC, datetime(2026, 9, 1, tzinfo=UTC), True)
    unit_of_work.state.outcomes[(rule().id, RunKind.SYNC)] = synced

    get_details = GetSyncRuleDetails(unit_of_work, RuleLocks(), MemoryPlans(), USER)

    details = get_details.execute(rule().id)

    assert details.rule == rule()
    assert details.mapping_count == 0
    assert details.last_sync == synced
    assert details.last_reconciliation is None
    # Plans are off, so nothing limits a Start.
    assert (details.can_start, details.rule_limit) == (True, None)
    with pytest.raises(RuleNotFound):
        get_details.execute(SyncRuleId("missing"))
```

Replace `test_enabling_a_previewed_rule_saves_it_enabled` and
`test_enabling_is_blocked_for_missing_or_unpreviewed_rules` with:

```python
def test_enabling_a_previewed_rule_saves_it_enabled() -> None:
    unit_of_work = memory_units()
    unit_of_work.state.rules[rule().id] = rule(state=SyncRuleState.PREVIEWED)

    enabled = EnableSyncRule(unit_of_work, RuleLocks(), MemoryPlans(), USER).execute(rule().id)

    assert enabled.state is SyncRuleState.ENABLED
    assert unit_of_work.state.rules[rule().id] == enabled


def test_enabling_is_blocked_for_missing_or_unpreviewed_rules() -> None:
    unit_of_work = memory_units()
    unit_of_work.state.rules[rule().id] = rule(state=SyncRuleState.DRAFT)
    enable = EnableSyncRule(unit_of_work, RuleLocks(), MemoryPlans(), USER)

    with pytest.raises(RuleNotFound):
        enable.execute(SyncRuleId("missing"))
    with pytest.raises(InvalidStateTransition):
        enable.execute(rule().id)
    assert unit_of_work.state.rules[rule().id].state is SyncRuleState.DRAFT
```

Replace `test_lifecycle_changes_wait_for_an_in_flight_provider_write` (with its `parametrize`
line) with:

```python
@pytest.mark.parametrize("change", ["enable", "pause"])
def test_lifecycle_changes_wait_for_an_in_flight_provider_write(change: str) -> None:
    unit_of_work = memory_units()
    starting = SyncRuleState.PREVIEWED if change == "enable" else SyncRuleState.ENABLED
    unit_of_work.state.rules[rule().id] = rule(state=starting)
    locks = RuleLocks()
    execute: Callable[[SyncRuleId], SyncRule] = (
        EnableSyncRule(unit_of_work, locks, MemoryPlans(), USER).execute
        if change == "enable"
        else PauseSyncRule(unit_of_work, locks).execute
    )
    writing = locks.for_writes(rule().id)
    writing.acquire()
    worker = Thread(target=execute, args=(rule().id,))
    worker.start()
    worker.join(0.1)
    blocked_while_writing = worker.is_alive()
    writing.release()
    worker.join(2)

    assert blocked_while_writing
    assert unit_of_work.state.rules[rule().id].state is not starting
```

Replace `test_listing_reports_each_rule_with_its_latest_outcomes_and_running_work` with:

```python
def test_listing_reports_each_rule_with_its_latest_outcomes_and_running_work() -> None:
    unit_of_work = memory_units()
    unit_of_work.state.rules[rule().id] = rule()
    synced = RuleRunOutcome(rule().id, RunKind.SYNC, datetime(2026, 9, 1, tzinfo=UTC), True)
    unit_of_work.state.outcomes[(rule().id, RunKind.SYNC)] = synced
    locks = RuleLocks()
    work = RuleWork(RuleWorkKind.SYNC, datetime(2026, 9, 1, tzinfo=UTC))

    with locks.working(rule().id, work):
        (running,) = ListSyncRules(unit_of_work, locks).execute()
        details = GetSyncRuleDetails(unit_of_work, locks, MemoryPlans(), USER).execute(rule().id)
    (idle,) = ListSyncRules(unit_of_work, locks).execute()

    assert running.rule == rule()
    assert running.last_sync == synced
    assert running.latest_preview is None
    assert running.running is not None
    assert running.running.kind is RuleWorkKind.SYNC
    assert details.running is not None
    assert idle.running is None
```

- [ ] **Step 2: Write the failing test: `tests/application/test_plan_limits.py`**

Create the file. It pins the Start check, `can_start`, decision 4 end to end, administrators and
Plans off, fail closed at Start and fail open on the rule page, lowering, and Review Focus 2
(an administrator demoted while over the limit):

```python
"""The rule limit: Start checks it, and the rule page says whether Start would pass (ADR 0038)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace

import pytest

from calendar_sync.application.identity.plans import ChangePlan
from calendar_sync.application.sync.lapsed_authorization import LapsedAuthorizations
from calendar_sync.application.sync.locking import RuleLocks
from calendar_sync.application.sync.ports import Allowances
from calendar_sync.application.sync.rules import (
    ChangeSyncRulePolicy,
    EnableSyncRule,
    GetSyncRuleDetails,
)
from calendar_sync.domain.access import Role, User, UserId, UserState
from calendar_sync.domain.model import (
    AllDaySyncPolicy,
    BirthdayPolicy,
    ProjectionContent,
    SyncRule,
    SyncRuleId,
    SyncRuleState,
    TentativeEventPolicy,
    UnansweredInvitationPolicy,
)
from calendar_sync.domain.plans import LimitedResource, Plan, PlanLimitReached
from calendar_sync.infrastructure.persistence.memory import (
    InMemoryIncidentRepository,
    InMemoryUserUnitOfWorkFactory,
)
from tests.fake_calendar import FixedClock
from tests.helpers import NOW, endpoint, rule
from tests.identity_fakes import BrokenAllowances, MemoryPlans, MemoryUsers
from tests.plans import FAMILY, FREE, plans_on
from tests.users import USER, memory_units

ADMIN = UserId("admin-1")
NEXT = SyncRuleId("next")
LATER = SyncRuleId("later")


def _rule(rule_id: SyncRuleId, state: SyncRuleState = SyncRuleState.PREVIEWED) -> SyncRule:
    """Another rule of the User, from a calendar of its own, so each relationship is unique."""
    return SyncRule(
        rule_id,
        endpoint("personal-account", f"{rule_id.value}-calendar"),
        rule().destination,
        state=state,
    )


def _plans(role: Role = Role.USER, plan: Plan | None = None) -> MemoryPlans:
    """Plans on, Free (one rule) the Default Plan and Family defined. USER has `role`, and
    `plan` as their own Plan when given; ADMIN administers."""
    users = MemoryUsers()
    users.add(
        User(ADMIN, "admin@example.test", Role.INSTALLATION_ADMINISTRATOR, UserState.ACTIVE, NOW),
        "x",
    )
    own = plan.key if plan is not None else None
    users.add(User(USER, "member@example.test", role, UserState.ACTIVE, NOW, plan=own), "x")
    plans = MemoryPlans(users=users)
    plans_on(plans, FREE, FAMILY)
    return plans


def _plans_off() -> MemoryPlans:
    """Plans defined, with Free the default, but off: nobody is limited."""
    plans = _plans()
    plans.change_settings(False, FREE.key)
    return plans


def _units(*rules: SyncRule) -> InMemoryUserUnitOfWorkFactory:
    """USER's records, with `rules` added in order, as creating them would."""
    units = memory_units()
    with units() as uow:
        for each in rules:
            uow.rules.add(each)
        uow.commit()
    return units


def _start(
    units: InMemoryUserUnitOfWorkFactory, allowances: Allowances, rule_id: SyncRuleId
) -> SyncRule:
    return EnableSyncRule(units, RuleLocks(), allowances, USER).execute(rule_id)


def _details(
    units: InMemoryUserUnitOfWorkFactory, allowances: Allowances, rule_id: SyncRuleId
) -> tuple[bool, int | None]:
    details = GetSyncRuleDetails(units, RuleLocks(), allowances, USER).execute(rule_id)
    return details.can_start, details.rule_limit


def _change(
    units: InMemoryUserUnitOfWorkFactory,
    rule_id: SyncRuleId,
    transition: Callable[[SyncRule], SyncRule],
) -> None:
    """Apply what a run or a preview would do to the rule, in a unit of its own."""
    with units() as uow:
        stored = uow.rules.get(rule_id)
        assert stored is not None
        uow.rules.save(transition(stored))
        uow.commit()


def _state(units: InMemoryUserUnitOfWorkFactory, rule_id: SyncRuleId) -> SyncRuleState:
    return units.state.rules[rule_id].state


def _counted(units: InMemoryUserUnitOfWorkFactory) -> int:
    return sum(each.counts_toward_plan for each in units.state.rules.values())


def test_a_start_within_the_rule_limit_enables_the_rule() -> None:
    units = _units(_rule(NEXT))

    started = _start(units, _plans(), NEXT)

    assert started.state is SyncRuleState.ENABLED
    assert units.state.rules[NEXT] == started


def test_a_start_past_the_rule_limit_is_refused_and_the_rule_stays_previewed() -> None:
    units = _units(rule(), _rule(NEXT))

    with pytest.raises(PlanLimitReached) as refused:
        _start(units, _plans(), NEXT)

    assert (refused.value.resource, refused.value.limit) == (LimitedResource.RULES, 1)
    assert _state(units, NEXT) is SyncRuleState.PREVIEWED
    assert _state(units, rule().id) is SyncRuleState.ENABLED


def test_a_start_counts_against_the_users_own_plan() -> None:
    four = [_rule(SyncRuleId(f"rule-{index}"), SyncRuleState.ENABLED) for index in range(2, 6)]
    units = _units(*four, _rule(NEXT), _rule(LATER))

    _start(units, _plans(plan=FAMILY), NEXT)
    with pytest.raises(PlanLimitReached) as refused:
        _start(units, _plans(plan=FAMILY), LATER)

    assert refused.value.limit == 5
    assert _state(units, NEXT) is SyncRuleState.ENABLED
    assert _state(units, LATER) is SyncRuleState.PREVIEWED


def test_a_rule_that_keeps_a_place_starts_even_over_the_limit() -> None:
    successor = replace(_rule(NEXT), keeps_place=True)
    units = _units(rule(), successor)
    assert _counted(units) == 2

    started = _start(units, _plans(), NEXT)

    assert started.state is SyncRuleState.ENABLED
    assert started.keeps_place is False
    assert _counted(units) == 2


@pytest.mark.parametrize("who", ["administrator", "plans_off"])
def test_administrators_and_plans_off_are_never_refused(who: str) -> None:
    plans = _plans(role=Role.INSTALLATION_ADMINISTRATOR) if who == "administrator" else _plans_off()
    enabled = [_rule(SyncRuleId(f"rule-{index}"), SyncRuleState.ENABLED) for index in range(2, 5)]
    units = _units(*enabled, _rule(NEXT))

    started = _start(units, plans, NEXT)

    assert started.state is SyncRuleState.ENABLED
    assert _details(units, plans, NEXT) == (True, None)


def test_a_start_fails_closed_when_the_allowance_cannot_be_read() -> None:
    units = _units(_rule(NEXT))

    with pytest.raises(RuntimeError, match="database is locked"):
        _start(units, BrokenAllowances(), NEXT)

    assert _state(units, NEXT) is SyncRuleState.PREVIEWED


@pytest.mark.parametrize(
    ("who", "rules", "expected"),
    [
        ("member", (_rule(NEXT),), (True, 1)),
        ("member", (rule(), _rule(NEXT)), (False, 1)),
        ("member", (rule(), replace(_rule(NEXT), keeps_place=True)), (True, 1)),
        ("family", (rule(), _rule(NEXT)), (True, 5)),
        ("administrator", (rule(), _rule(NEXT)), (True, None)),
        ("plans_off", (rule(), _rule(NEXT)), (True, None)),
    ],
)
def test_details_say_whether_start_would_pass_and_name_the_rule_limit(
    who: str, rules: tuple[SyncRule, ...], expected: tuple[bool, int | None]
) -> None:
    plans = {
        "member": _plans,
        "family": lambda: _plans(plan=FAMILY),
        "administrator": lambda: _plans(role=Role.INSTALLATION_ADMINISTRATOR),
        "plans_off": _plans_off,
    }[who]()

    assert _details(_units(*rules), plans, NEXT) == expected


def test_details_fail_open_and_log_only_the_error_class(caplog: pytest.LogCaptureFixture) -> None:
    units = _units(rule(), _rule(NEXT))

    with caplog.at_level(logging.WARNING):
        answer = _details(units, BrokenAllowances(), NEXT)

    assert answer == (True, None)
    assert "RuntimeError" in caplog.text
    assert "database is locked" not in caplog.text
    # The Start itself still checks, and fails closed.
    with pytest.raises(RuntimeError):
        _start(units, BrokenAllowances(), NEXT)


def test_a_rule_a_provider_failure_stopped_is_checked_at_its_recovery_start() -> None:
    units = _units(rule(), _rule(NEXT))
    plans = _plans()
    # A failure that needs intervention stops the rule; it no longer counts.
    _change(units, rule().id, lambda stopped: stopped.degrade())
    _start(units, plans, NEXT)
    _change(units, rule().id, SyncRule.mark_previewed)

    with pytest.raises(PlanLimitReached):
        _start(units, plans, rule().id)

    assert _state(units, rule().id) is SyncRuleState.PREVIEWED
    assert _details(units, plans, rule().id) == (False, 1)


def test_a_rule_a_material_rule_change_paused_is_checked_at_its_start() -> None:
    units = _units(rule(), _rule(NEXT))
    plans = _plans()
    ChangeSyncRulePolicy(units, FixedClock(), RuleLocks()).execute(
        rule().id,
        ProjectionContent.DETAILS,
        AllDaySyncPolicy.INCLUDE,
        tentative=TentativeEventPolicy.MARK,
        unanswered=UnansweredInvitationPolicy.AS_TENTATIVE,
        birthdays=BirthdayPolicy.EXCLUDE,
    )
    assert _state(units, rule().id) is SyncRuleState.PAUSED
    _start(units, plans, NEXT)
    _change(units, rule().id, SyncRule.mark_previewed)

    with pytest.raises(PlanLimitReached):
        _start(units, plans, rule().id)

    assert _state(units, rule().id) is SyncRuleState.PREVIEWED


def test_a_lapse_stopped_rule_counts_until_it_is_previewed_and_is_then_checked() -> None:
    lapse_stopped = rule().degrade(awaiting_reauthorization=True)
    units = _units(lapse_stopped, _rule(NEXT))
    plans = _plans()

    with pytest.raises(PlanLimitReached):
        _start(units, plans, NEXT)
    _change(units, rule().id, SyncRule.mark_previewed)
    _start(units, plans, NEXT)

    with pytest.raises(PlanLimitReached):
        _start(units, plans, rule().id)
    assert _state(units, rule().id) is SyncRuleState.PREVIEWED
    assert _state(units, NEXT) is SyncRuleState.ENABLED


def test_a_lapse_resume_while_over_the_limit_needs_no_plan() -> None:
    lapse_stopped = rule().degrade(awaiting_reauthorization=True)
    units = _units(lapse_stopped, _rule(NEXT, SyncRuleState.ENABLED))
    plans = _plans()
    assert plans.of(USER).limits.rules == 1
    assert _counted(units) == 2
    lapses = LapsedAuthorizations(
        units, InMemoryIncidentRepository(units.database, USER), FixedClock(), RuleLocks()
    )

    resumed = lapses.finish_interrupted()

    assert resumed == 1
    assert _state(units, rule().id) is SyncRuleState.ENABLED
    assert _counted(units) == 2


def test_lowering_the_limit_stops_nothing_and_refuses_the_next_start() -> None:
    enabled = [_rule(SyncRuleId(f"rule-{index}"), SyncRuleState.ENABLED) for index in range(2, 5)]
    units = _units(*enabled, _rule(NEXT))
    plans = _plans(plan=FAMILY)
    lowered = replace(FAMILY, limits=replace(FAMILY.limits, rules=1))

    ChangePlan(plans.users, plans, FixedClock()).execute(ADMIN, lowered)

    assert [_state(units, each.id) for each in enabled] == [SyncRuleState.ENABLED] * 3
    assert _details(units, plans, NEXT) == (False, 1)
    with pytest.raises(PlanLimitReached):
        _start(units, plans, NEXT)
    assert [_state(units, each.id) for each in enabled] == [SyncRuleState.ENABLED] * 3


def test_an_administrator_demoted_over_the_limit_keeps_every_rule_but_starts_no_more() -> None:
    enabled = [_rule(SyncRuleId(f"rule-{index}"), SyncRuleState.ENABLED) for index in range(2, 4)]
    units = _units(*enabled, _rule(NEXT), _rule(LATER))
    plans = _plans(role=Role.INSTALLATION_ADMINISTRATOR)
    _start(units, plans, NEXT)

    plans.users.set_role(USER, Role.USER)

    assert _counted(units) == 3
    assert _details(units, plans, LATER) == (False, 1)
    with pytest.raises(PlanLimitReached):
        _start(units, plans, LATER)
    assert _state(units, NEXT) is SyncRuleState.ENABLED
    # Promoting them again lifts the limit at the next request.
    plans.users.set_role(USER, Role.INSTALLATION_ADMINISTRATOR)
    assert _start(units, plans, LATER).state is SyncRuleState.ENABLED
```

- [ ] **Step 3: Write the failing test: the Start part of `tests/adapters/test_plan_races.py`**

Task 8 created this file with the token races. Merge these imports into its import block, each
name once (keep what is already there; `.venv/bin/ruff check --fix tests/adapters/test_plan_races.py`
then sorts the block):

```python
import time
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from threading import Barrier, Event, Thread

import pytest

from calendar_sync.application.identity.plans import ChangePlan
from calendar_sync.application.sync.locking import RuleLocks
from calendar_sync.application.sync.ports import Allowances, UnitOfWorkFactory
from calendar_sync.application.sync.rules import EnableSyncRule
from calendar_sync.domain.access import UserId
from calendar_sync.domain.model import SyncRule, SyncRuleId, SyncRuleState
from calendar_sync.domain.plans import (
    Allowance,
    Plan,
    PlanKey,
    PlanLimitReached,
    PlanLimits,
    SyncInterval,
)
from calendar_sync.infrastructure.clock import SystemClock
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.persistence.migrations import initialize_database
from calendar_sync.infrastructure.persistence.plans import SqlitePlans
from calendar_sync.infrastructure.persistence.users import SqliteUserDirectory
from tests.helpers import endpoint, rule
from tests.plans import plans_on
from tests.users import USER, add_user, limited_user, sqlite_units
```

Then append to the end of the file (the names are chosen so they do not meet task 8's helpers;
if one does, rename the Start part's copy):

```python
TWO_RULES = Plan(PlanKey("two-rules"), "Two rules", PlanLimits(2, 2, 2, SyncInterval.INSTANT))
"""A Plan whose rule limit is two, so one enabled rule leaves one place."""
NEXT_RULE = SyncRuleId("next")
LATER_RULE = SyncRuleId("later")


def _previewed_rule(rule_id: SyncRuleId) -> SyncRule:
    return SyncRule(
        rule_id,
        endpoint("personal-account", f"{rule_id.value}-calendar"),
        rule().destination,
        state=SyncRuleState.PREVIEWED,
    )


def _member_with_rules(database: Path, *rules: SyncRule) -> tuple[SqlitePlans, UnitOfWorkFactory]:
    """Plans on with TWO_RULES the Default Plan, and USER, whom it limits, with `rules`."""
    initialize_database(database)
    plans = SqlitePlans(database)
    plans_on(plans, TWO_RULES)
    limited_user(database, USER)
    units = sqlite_units(database, user=USER)
    with units() as uow:
        for each in rules:
            uow.rules.add(each)
        uow.commit()
    return plans, units


def _rule_state(units: UnitOfWorkFactory, rule_id: SyncRuleId) -> SyncRuleState:
    with units() as uow:
        stored = uow.rules.get(rule_id)
    assert stored is not None
    return stored.state


@dataclass
class SlowAllowanceReads:
    """Reads the Allowance, then holds the Start a moment longer, writer lock and all, so the
    other Start reaches its own save meanwhile."""

    inner: Allowances

    def of(self, user: UserId) -> Allowance:
        allowance = self.inner.of(user)
        time.sleep(0.2)
        return allowance

    def of_users(self, users: Collection[UserId]) -> Mapping[UserId, Allowance]:
        return self.inner.of_users(users)


@dataclass
class GatedAllowanceReads:
    """Reads the Allowance, says so, then holds the Start, writer lock and all, until released."""

    inner: Allowances
    read: Event = field(default_factory=Event)
    release: Event = field(default_factory=Event)

    def of(self, user: UserId) -> Allowance:
        allowance = self.inner.of(user)
        self.read.set()
        assert self.release.wait(5)
        return allowance

    def of_users(self, users: Collection[UserId]) -> Mapping[UserId, Allowance]:
        return self.inner.of_users(users)


def test_two_starts_for_the_last_place_admit_exactly_one(tmp_path: Path) -> None:
    plans, units = _member_with_rules(
        tmp_path / "calendar-sync.db",
        rule(),
        _previewed_rule(NEXT_RULE),
        _previewed_rule(LATER_RULE),
    )
    enable = EnableSyncRule(units, RuleLocks(), SlowAllowanceReads(plans), USER)
    start = Barrier(2)
    started: list[SyncRuleId] = []
    refused: list[SyncRuleId] = []

    def start_rule(rule_id: SyncRuleId) -> None:
        start.wait()
        try:
            enable.execute(rule_id)
        except PlanLimitReached:
            refused.append(rule_id)
        else:
            started.append(rule_id)

    threads = [Thread(target=start_rule, args=(rule_id,)) for rule_id in (NEXT_RULE, LATER_RULE)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)

    assert len(started) == 1
    assert len(refused) == 1
    assert _rule_state(units, started[0]) is SyncRuleState.ENABLED
    assert _rule_state(units, refused[0]) is SyncRuleState.PREVIEWED


def test_a_plan_lowered_during_a_start_waits_for_the_start_to_commit(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    plans, units = _member_with_rules(
        database, rule(), _previewed_rule(NEXT_RULE), _previewed_rule(LATER_RULE)
    )
    actor = add_user(database, UserId("admin-1"))
    lowered = replace(TWO_RULES, limits=replace(TWO_RULES.limits, rules=1))
    gate = GatedAllowanceReads(plans)
    start = Thread(target=EnableSyncRule(units, RuleLocks(), gate, USER).execute, args=(NEXT_RULE,))
    lowering = Thread(
        target=ChangePlan(SqliteUserDirectory(database), plans, SystemClock()).execute,
        args=(actor, lowered),
    )

    start.start()
    assert gate.read.wait(5)
    lowering.start()
    lowering.join(0.3)
    lowered_during_the_start = not lowering.is_alive()
    gate.release.set()
    start.join(5)
    lowering.join(5)

    # The Start saw the limit of two and committed before the lowering could.
    assert not lowered_during_the_start
    assert _rule_state(units, NEXT_RULE) is SyncRuleState.ENABLED
    assert plans.get(TWO_RULES.key) == lowered
    # Nothing stopped, and the next Start meets the lowered limit.
    assert _rule_state(units, rule().id) is SyncRuleState.ENABLED
    with pytest.raises(PlanLimitReached):
        EnableSyncRule(units, RuleLocks(), plans, USER).execute(LATER_RULE)


def _start_behind(
    database: Path, plans: SqlitePlans, units: UnitOfWorkFactory, statement: str
) -> tuple[bool, list[str]]:
    """Start NEXT_RULE while another connection holds the writer lock for `statement`, as every
    SqlitePlans write does; whether the Start waited for it, and how the Start ended."""
    outcome: list[str] = []

    def start_rule() -> None:
        try:
            EnableSyncRule(units, RuleLocks(), plans, USER).execute(NEXT_RULE)
        except PlanLimitReached:
            outcome.append("refused")
        else:
            outcome.append("started")

    start = Thread(target=start_rule)
    with transaction(database) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(statement)
        start.start()
        start.join(0.3)
        waited = start.is_alive()
    start.join(5)
    return waited, outcome


def test_a_start_that_waits_for_a_lowering_reads_the_lowered_limit(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    plans, units = _member_with_rules(database, rule(), _previewed_rule(NEXT_RULE))

    waited, outcome = _start_behind(
        database, plans, units, "UPDATE plans SET rule_limit = 1 WHERE key = 'two-rules'"
    )

    # The Start's save waited for the lowering, and its limit read came after it.
    assert waited
    assert outcome == ["refused"]
    assert _rule_state(units, NEXT_RULE) is SyncRuleState.PREVIEWED


def test_a_start_that_waits_for_plans_to_turn_on_reads_the_limit(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    enabled = replace(_previewed_rule(LATER_RULE), state=SyncRuleState.ENABLED)
    plans, units = _member_with_rules(database, rule(), enabled, _previewed_rule(NEXT_RULE))
    plans.change_settings(False, TWO_RULES.key)

    waited, outcome = _start_behind(
        database,
        plans,
        units,
        "UPDATE installation_settings SET plans_enabled = 1 WHERE singleton = 1",
    )

    assert waited
    assert outcome == ["refused"]
    assert _rule_state(units, NEXT_RULE) is SyncRuleState.PREVIEWED
```

- [ ] **Step 4: Write the failing test: `tests/adapters/test_rule_limit_api.py`**

Create the file (the route tests for the enable and details routes):

```python
"""The rule limit through the Web API: a refused Start, and what the rule page reads (ADR 0038)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import build_adapters, compose
from calendar_sync.domain.model import SyncRule, SyncRuleId, SyncRuleState
from calendar_sync.interfaces.api.app import create_app
from calendar_sync.interfaces.api.dependencies import SESSION_COOKIE
from tests.helpers import endpoint, rule
from tests.plans import plans_on
from tests.users import OTHER_USER, administrator, limited_user, session_for, sqlite_units

NEXT = SyncRule(
    SyncRuleId("next"),
    endpoint("personal-account", "next-calendar"),
    rule().destination,
    state=SyncRuleState.PREVIEWED,
)


def _client(tmp_path: Path, *, plans: bool) -> TestClient:
    """A member with one enabled rule and one previewed, signed in; with `plans`, Plans are on
    and the Default Plan, Free, lets one rule sync."""
    database = tmp_path / "test.db"
    settings = Settings(database)
    adapters = build_adapters(settings)
    administrator(adapters)
    member = limited_user(database, OTHER_USER)
    if plans:
        plans_on(adapters.plan_catalog)
    with sqlite_units(database, user=member)() as uow:
        uow.rules.add(rule())
        uow.rules.add(NEXT)
        uow.commit()
    client = TestClient(create_app(replace(compose(settings, adapters), scheduler=None)))
    client.cookies.set(SESSION_COOKIE, session_for(database, member))
    return client


def test_a_start_past_the_rule_limit_answers_its_code_never_a_server_error(
    tmp_path: Path,
) -> None:
    with _client(tmp_path, plans=True) as client:
        refused = client.post("/api/v1/rules/next/enable")
        after = client.get("/api/v1/rules/next")

    assert refused.status_code == 409
    assert (refused.json()["code"], refused.json()["params"]) == (
        "plan_limit_reached",
        {"reason": "rules", "limit": 1, "count": 1},
    )
    assert after.json()["state"] == "dry_run_validated"


def test_rule_details_say_whether_start_would_pass_and_name_the_limit(tmp_path: Path) -> None:
    with _client(tmp_path, plans=True) as client:
        over = client.get("/api/v1/rules/next").json()
        enabled = client.get("/api/v1/rules/rule-1").json()

    assert (over["can_start"], over["rule_limit"]) == (False, 1)
    assert (enabled["can_start"], enabled["rule_limit"]) == (True, 1)


def test_with_plans_off_details_name_no_limit_and_start_passes(tmp_path: Path) -> None:
    with _client(tmp_path, plans=False) as client:
        details = client.get("/api/v1/rules/next").json()
        started = client.post("/api/v1/rules/next/enable")

    assert (details["can_start"], details["rule_limit"]) == (True, None)
    assert started.status_code == 200
    assert started.json()["state"] == "enabled"
```

- [ ] **Step 5: Run the tests to verify they fail**

```sh
.venv/bin/pytest tests/application/test_rules.py tests/application/test_plan_limits.py tests/adapters/test_plan_races.py tests/adapters/test_rule_limit_api.py -q
```

Expected: failures, the task 8 token races still passing. The application and race tests fail with
`TypeError: EnableSyncRule.__init__() takes 3 positional arguments but 5 were given` and
`TypeError: GetSyncRuleDetails.__init__() takes 3 positional arguments but 5 were given`;
`test_a_start_past_the_rule_limit_answers_its_code_never_a_server_error` fails on
`assert refused.status_code == 409` (the Start passes with 200); the two details route tests fail
with `KeyError: 'can_start'`.

- [ ] **Step 6: Implement the Start check and `can_start` in `src/calendar_sync/application/sync/rules.py`**

Replace the import block at the top of the file (from `from collections.abc import Callable,
Mapping` through `from calendar_sync.domain.runs import RuleRunOutcome, RunKind`) with this block,
which also adds the module's logger:

```python
import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace

from calendar_sync.application.shared.errors import ApplicationError
from calendar_sync.application.shared.ports import Clock, IdGenerator
from calendar_sync.application.sync.errors import (
    ConnectedAccountRequired,
    DuplicateDirectionalRelationship,
    NotACalendarChange,
    RemovalInterrupted,
    ReplacementInterrupted,
    RuleNotFound,
)
from calendar_sync.application.sync.locking import RuleLocks, RuleWork
from calendar_sync.application.sync.ports import (
    Allowances,
    RulePreviewSummary,
    UnitOfWork,
    UnitOfWorkFactory,
)
from calendar_sync.application.sync.removal import RemovalResult, RemoveSyncRule
from calendar_sync.domain.access import UserId
from calendar_sync.domain.audit import AuditAction, AuditEntry, AuditOutcome
from calendar_sync.domain.model import (
    AllDaySyncPolicy,
    BirthdayPolicy,
    CalendarEndpoint,
    ProjectionContent,
    ProjectionHandling,
    SyncRule,
    SyncRuleId,
    TentativeEventPolicy,
    TransformationPolicy,
    UnansweredInvitationPolicy,
)
from calendar_sync.domain.plans import LimitedResource, PlanLimitReached, may_start
from calendar_sync.domain.runs import RuleRunOutcome, RunKind

logger = logging.getLogger(__name__)
```

Replace `class EnableSyncRule` (with its decorator) with the class below and the new private
helper after it. `PauseSyncRule` keeps using `_transition`:

```python
@dataclass(slots=True)
class EnableSyncRule:
    """Enables a previewed rule within its User's rule limit (ADR 0038); its next run reconciles
    before scheduled synchronization."""

    unit_of_work: UnitOfWorkFactory
    locks: RuleLocks
    allowances: Allowances
    owner: UserId

    def execute(self, rule_id: SyncRuleId) -> SyncRule:
        with self.locks.for_writes(rule_id), self.unit_of_work() as uow:
            rule = uow.rules.get(rule_id)
            if rule is None:
                raise RuleNotFound(f"sync rule {rule_id.value} does not exist")
            enabled = rule.enable()
            # Saved first: the save takes SQLite's writer lock, so no Start and no change of Plan
            # can commit between the limit read next and this unit's commit (ADR 0038). A read
            # that raises fails the Start, so a fault never admits a rule past the limit.
            uow.rules.save(enabled)
            limit = self.allowances.of(self.owner).limits.rules
            if limit is not None and not may_start(rule, _counted(uow.rules.list()), limit):
                raise PlanLimitReached(LimitedResource.RULES, limit)
            uow.commit()
        return enabled


def _counted(rules: Iterable[SyncRule]) -> int:
    """How many of a User's rules count toward their Plan's rule limit (ADR 0038)."""
    return sum(rule.counts_toward_plan for rule in rules)
```

Replace `class SyncRuleDetails` and `class GetSyncRuleDetails` (with their decorators) with:

```python
@dataclass(frozen=True, slots=True)
class SyncRuleDetails:
    rule: SyncRule
    mapping_count: int
    last_sync: RuleRunOutcome | None
    last_reconciliation: RuleRunOutcome | None
    latest_preview: RulePreviewSummary | None = None
    running: RuleWork | None = None
    names: Mapping[CalendarEndpoint, str] = field(default_factory=dict)
    """The last name the provider gave each of the rule's calendars, when one was recorded."""
    can_start: bool = True
    """Whether Start would admit the rule now under its User's rule limit; Start checks again."""
    rule_limit: int | None = None
    """The rule limit that applies to the User; None when none does, or it could not be read."""


@dataclass(slots=True)
class GetSyncRuleDetails:
    unit_of_work: UnitOfWorkFactory
    locks: RuleLocks
    allowances: Allowances
    owner: UserId

    def execute(self, rule_id: SyncRuleId) -> SyncRuleDetails:
        with self.unit_of_work() as uow:
            rule = uow.rules.get(rule_id)
            if rule is None:
                raise RuleNotFound(f"sync rule {rule_id.value} does not exist")
            can_start, rule_limit = self._start_check(uow, rule)
            return SyncRuleDetails(
                rule=rule,
                mapping_count=uow.mappings.count_for_rule(rule_id),
                last_sync=uow.run_outcomes.latest(rule_id, RunKind.SYNC),
                last_reconciliation=uow.run_outcomes.latest(rule_id, RunKind.RECONCILIATION),
                latest_preview=uow.previews.latest(rule_id),
                running=self.locks.current_work(rule_id),
                names=uow.calendar_names.names((rule.source, rule.destination)),
                can_start=can_start,
                rule_limit=rule_limit,
            )

    def _start_check(self, uow: UnitOfWork, rule: SyncRule) -> tuple[bool, int | None]:
        """Whether Start would admit the rule now, and the rule limit it would apply.

        Fails open: when the User's Allowance cannot be read, Start shows as allowed with no
        limit, because Start reads it again and refuses then (ADR 0038).
        """
        try:
            limit = self.allowances.of(self.owner).limits.rules
        except Exception as error:
            # Only the class: the error's text could name more than the User.
            logger.warning(
                "Could not read the rule limit of User %s; Start checks it again (%s)",
                self.owner.value,
                error.__class__.__name__,
            )
            return True, None
        counting = _counted(uow.rules.list())
        after = counting if rule.counts_toward_plan else counting + 1
        return may_start(rule, after, limit), limit
```

- [ ] **Step 7: Implement the route changes in `src/calendar_sync/interfaces/api/routes/rules.py`**

Add the import after the `from calendar_sync.domain.model import (...)` block and before
`from calendar_sync.domain.runs import RuleRunOutcome`:

```python
from calendar_sync.domain.plans import PlanLimitReached
```

Replace `rule_details` (with its `@router.get` decorator) with:

```python
@router.get(
    "/api/v1/rules/{rule_id}",
    response_model=RuleDetailResponse,
    dependencies=[Depends(current_user)],
)
def rule_details(rule_id: str, services: Services) -> RuleDetailResponse:
    try:
        details = services.get_sync_rule_details.execute(SyncRuleId(rule_id))
    except RuleNotFound as error:
        raise problem_from(status.HTTP_404_NOT_FOUND, error) from error
    status_, user = services.instant_sync_status, services.user_id
    reasons, poll_every = status_.cadences(user), status_.poll_every(user)
    return RuleDetailResponse(
        **_named_rule_response(details.rule, details.names),
        **_cadence_fields(reasons.get(details.rule.id), poll_every),
        initial_lookback_days=details.rule.initial_lookback_days,
        mapping_count=details.mapping_count,
        last_sync=_outcome_response(details.last_sync),
        last_reconciliation=_outcome_response(details.last_reconciliation),
        latest_preview=_preview_response(details.latest_preview),
        running=_work_response(details.running),
        can_start=details.can_start,
        rule_limit=details.rule_limit,
    )
```

Replace `_lifecycle_change` with (pause never raises `PlanLimitReached`, so only Start meets it):

```python
def _lifecycle_change(change: Callable[[SyncRuleId], SyncRule], rule_id: str) -> SyncRule:
    try:
        return change(SyncRuleId(rule_id))
    except RuleNotFound as error:
        raise problem(
            status.HTTP_404_NOT_FOUND, "rule_not_found", "sync rule does not exist"
        ) from error
    except InvalidStateTransition as error:
        raise problem_from(status.HTTP_409_CONFLICT, error) from error
    except PlanLimitReached as error:
        # A Start the User's Plan refuses; the code names the limit, so it is never a 500.
        raise problem_from(status.HTTP_409_CONFLICT, error) from error
```

- [ ] **Step 8: Implement the schema fields in `src/calendar_sync/interfaces/api/schemas.py`**

Replace `class RuleDetailResponse` with (both fields are required in the schema, as every
`ApiResponse` field is):

```python
class RuleDetailResponse(RuleResponse):
    source: NamedCalendarEndpointResponse
    destination: NamedCalendarEndpointResponse
    effective_cadence: EffectiveCadenceValue
    poll_every_minutes: int
    """How often Scheduled Sync runs the rule, as the User's Plan says."""
    initial_lookback_days: int
    mapping_count: int
    last_sync: RunOutcomeResponse | None
    last_reconciliation: RunOutcomeResponse | None
    latest_preview: PreviewSummaryResponse | None
    running: RuleWorkResponse | None
    can_start: bool
    """Whether the rule may start now under its User's rule limit; Start checks again."""
    rule_limit: int | None
    """The rule limit that applies to the User; null when none does."""
```

- [ ] **Step 9: Implement the composition in `src/calendar_sync/bootstrap/container.py`**

In `_compose_user`, inside `return UserServices(...)`, change these two keyword arguments
(each stays on one line; `ruff format` keeps them there):

```diff
-        enable_sync_rule=EnableSyncRule(unit_of_work, locks),
+        enable_sync_rule=EnableSyncRule(unit_of_work, locks, adapters.allowances, user_id),
```

```diff
-        get_sync_rule_details=GetSyncRuleDetails(unit_of_work, locks),
+        get_sync_rule_details=GetSyncRuleDetails(unit_of_work, locks, adapters.allowances, user_id),
```

(The MCP server reads rule details through the same `get_sync_rule_details` service and keeps its
own payload, so it needs no change.)

- [ ] **Step 10: Run the backend tests to verify they pass**

```sh
.venv/bin/pytest tests/application/test_rules.py tests/application/test_plan_limits.py tests/adapters/test_plan_races.py tests/adapters/test_rule_limit_api.py -q
```

Expected: all pass (14 in `test_rules.py`, 20 in `test_plan_limits.py`, the 4 Start races beside
task 8's token races, 3 in `test_rule_limit_api.py`). Run the race file three times to see it is
steady: `for i in 1 2 3; do .venv/bin/pytest tests/adapters/test_plan_races.py -q; done`.

- [ ] **Step 11: Regenerate the OpenAPI schema and the Web UI types**

```sh
.venv/bin/python scripts/export_openapi.py
cd web && pnpm run api:types && cd ..
```

Expected: `web/openapi.json` gains `can_start` (boolean) and `rule_limit` (integer or null) in
`RuleDetailResponse`, both in its `required` list, and `web/src/lib/api-schema.ts` gains
`can_start: boolean;` and `rule_limit: number | null;` in `RuleDetailResponse`. Never edit either
file by hand.

- [ ] **Step 12: Give the Web UI fixtures typed `RuleDetail` the new fields**

In `web/src/features/rule-preview.test.tsx`, the end of `const previewedRule: RuleDetail = {` becomes:

```ts
  latest_preview: null,
  running: null,
  can_start: true,
  rule_limit: null,
}
```

In `web/src/features/calendar-replacement.test.tsx`, the end of the object `detail(...)` returns
becomes:

```ts
    latest_preview: null,
    running: null,
    can_start: true,
    rule_limit: null,
  }
}
```

In `web/src/features/rule-details.test.tsx`, the end of `const enabledRule: RuleDetail = {` becomes:

```ts
  effective_cadence: "instant",
  poll_every_minutes: 5,
  can_start: true,
  rule_limit: null,
}
```

- [ ] **Step 13: Run the Web UI checks, and build the static bundle**

```sh
cd web
pnpm run api:check
pnpm run typecheck
pnpm run lint
pnpm exec vitest run src/features/rule-preview.test.tsx src/features/calendar-replacement.test.tsx src/features/rule-details.test.tsx
pnpm run build
cd ..
git status --short src/calendar_sync/interfaces/api/static
```

Expected: `api:check`, `typecheck`, and `lint` clean; the three Vitest files pass (20 tests);
the build succeeds. This task changes no shipped Web UI code (only test fixtures and type
declarations, which compile away), so the rebuilt bundle differs from the committed one only by
the commit SHA embedded in its source link. Do not commit a SHA-only rebuild; restore it:

```sh
git checkout -- src/calendar_sync/interfaces/api/static
git clean -fd src/calendar_sync/interfaces/api/static
```

- [ ] **Step 14: Run the backend gate**

```sh
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy
.venv/bin/lint-imports
.venv/bin/pytest -q
```

Expected: all clean; the full suite passes, `tests/test_openapi_contract.py` included.

- [ ] **Step 15: Commit**

```sh
git add src/calendar_sync/application/sync/rules.py \
  src/calendar_sync/interfaces/api/routes/rules.py \
  src/calendar_sync/interfaces/api/schemas.py \
  src/calendar_sync/bootstrap/container.py \
  web/openapi.json web/src/lib/api-schema.ts \
  web/src/features/rule-preview.test.tsx \
  web/src/features/calendar-replacement.test.tsx \
  web/src/features/rule-details.test.tsx \
  tests/application/test_rules.py \
  tests/application/test_plan_limits.py \
  tests/adapters/test_plan_races.py \
  tests/adapters/test_rule_limit_api.py
git commit -F - <<'EOF'
Refuse a Start past the Plan's rule limit, and show it before Start

Start saves the enabled rule first, which takes the writer lock, then
reads the User's Allowance and counts the rules that count, so two Starts
or a Plan change cannot slip past the limit. A read that fails refuses the
Start. The rule page answers can_start and rule_limit, and shows Start as
allowed when Plans cannot be read, since Start checks again.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
```

### Task 10: Rule Replacement successor

**Files:**
- Create: `src/calendar_sync/application/sync/rule_insertion.py`
- Modify: `src/calendar_sync/application/sync/rules.py` (import block, `CreateSyncRule`, `RuleReplacement`, `ReplaceSyncRuleCalendars`)
- Modify: `src/calendar_sync/application/sync/removal.py` (import block, `RemovalResult`, `RemoveSyncRule.execute`, `RemoveSyncRule._execute_measured`, new private `_place_successor`)
- Modify: `src/calendar_sync/bootstrap/container.py` (`_compose_user`: `replace_sync_rule_calendars=`)
- Modify: `tests/application/test_remove_sync_rule.py` (import block, `_with_mappings`, new `_add_mappings`, the Rule Replacement tests)
- Modify: `tests/application/test_rules.py` (one `CreateSyncRule` test that pins its unchanged duplicate refusal)
- Modify: `CONTEXT.md` (**Rule Replacement**)
- Test: `tests/application/test_remove_sync_rule.py`, `tests/application/test_rules.py`

**Interfaces:**
- Consumes: `SyncRule.take_place_of(old: SyncRule) -> Self` (DRAFT or PREVIEWED only, else `InvalidStateTransition`), `SyncRule.keeps_place`, `SyncRule.counts_toward_plan` (task 2); `SyncRuleRepository.inherit_place(rule: SyncRuleId, of: SyncRuleId) -> None` and `MemoryState.rule_order: dict[SyncRuleId, int]` (task 3); `EnableSyncRule(unit_of_work, locks, allowances, owner)` (task 9); `MemoryPlans`, `MemoryUsers`, `FREE`, `plans_on` (task 4).
- Produces: `insert_rule(uow: UnitOfWork, rule: SyncRule) -> None` (`application/sync/rule_insertion.py`); `RemoveSyncRule.execute(rule_id: SyncRuleId, handling: ProjectionHandling, *, successor: SyncRule | None = None) -> RemovalResult`; `RemovalResult.successor: SyncRule | None = None`; `ReplaceSyncRuleCalendars(unit_of_work: UnitOfWorkFactory, remove_rule: RemoveSyncRule, ids: IdGenerator)`; `RuleReplacement.rule` is the successor as inserted.

- [ ] **Step 1: Write the failing test: imports and fixtures of `tests/application/test_remove_sync_rule.py`**

Replace the import block at the top of the file (from `from __future__ import annotations`
through `from tests.users import memory_units`) with:

```python
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from threading import Thread

import pytest

from calendar_sync.application.sync.errors import (
    ConnectedAccountDisconnected,
    ConnectedAccountRequired,
    DuplicateDirectionalRelationship,
    NotACalendarChange,
    ProjectionOwnershipMismatch,
    ProviderFailure,
    RemovalInterrupted,
    RemovalRequiresAuthorization,
    RemovalRequiresProvider,
    ReplacementInterrupted,
)
from calendar_sync.application.sync.locking import RuleLocks
from calendar_sync.application.sync.ports import (
    AccountAuthorizations,
    ProjectionDeleter,
    UnitOfWorkFactory,
)
from calendar_sync.application.sync.removal import RemoveSyncRule
from calendar_sync.application.sync.rules import EnableSyncRule, ReplaceSyncRuleCalendars
from calendar_sync.domain.access import Role, User, UserState
from calendar_sync.domain.accounts import ConnectedAccountState, ProviderKind
from calendar_sync.domain.errors import InvalidStateTransition
from calendar_sync.domain.model import (
    CalendarEvent,
    ConnectedAccountId,
    EventId,
    EventMapping,
    EventMappingId,
    EventRef,
    EventStatus,
    ManagedOrigin,
    ProjectionContent,
    ProjectionFingerprint,
    ProjectionHandling,
    SyncRule,
    SyncRuleId,
    SyncRuleState,
    TransformationPolicy,
)
from calendar_sync.domain.providers import ProviderFailureKind
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.persistence.memory import (
    InMemoryUserUnitOfWorkFactory,
)
from calendar_sync.infrastructure.persistence.migrations import initialize_database
from tests.application.test_execute_sync_rule import FakeCalendarProvider, FixedClock
from tests.fake_calendar import FakeCalendars, enabled_rule_factory, sync_use_case
from tests.helpers import NOW, endpoint, event, occurrence, rule, series, week_start
from tests.identity_fakes import MemoryPlans, MemoryUsers
from tests.plans import FREE, plans_on
from tests.users import USER, memory_units, sqlite_units
```

Replace `_with_mappings` with this version and the new `_add_mappings` after it:

```python
def _with_mappings(
    count: int, state: SyncRuleState = SyncRuleState.ENABLED
) -> InMemoryUserUnitOfWorkFactory:
    unit_of_work = memory_units()
    unit_of_work.state.rules[rule().id] = rule(state=state)
    # Rule Replacement creates its draft under the same Connected Accounts.
    for endpoint_ in (rule().source, rule().destination):
        unit_of_work.state.accounts[endpoint_.connected_account_id] = (
            ConnectedAccountState.CONNECTED
        )
    _add_mappings(unit_of_work, count)
    return unit_of_work


def _add_mappings(unit_of_work: InMemoryUserUnitOfWorkFactory, count: int) -> None:
    """`count` mappings of rule-1, each to a projection of its own."""
    for index in range(count):
        source = EventRef(rule().source, EventId(f"source-{index}"))
        unit_of_work.state.mappings[(rule().id, source)] = EventMapping(
            EventMappingId(f"mapping-{index}"),
            rule().id,
            source,
            EventRef(rule().destination, EventId(f"destination-{index}")),
            "revision-1",
            ProjectionFingerprint("fingerprint"),
        )
```

- [ ] **Step 2: Write the failing test: the Rule Replacement tests**

In the same file, replace everything from `def test_replacement_rejects_a_duplicate_relationship_before_removing_anything`
up to (not including) `def _synced_series` (that is, the old replacement tests and the
`CompetingCreate` class) with the block below. It keeps the earlier tests under the new
constructor, replaces `CompetingCreate` with `CompetingRemoval` (a duplicate created after the
checks), and adds the successor tests: no draft before the old rule's run lock is free, failed
checks at the begin step change nothing, the place moves in the commit that begins the removal,
only a counting rule passes on a place, a non-draft successor is refused, an interrupted or later
failing removal keeps the draft, a replacement over the limit starts, a replacement in flight
when Plans turn on keeps its place and starts (Review Focus 3), and the same on SQLite.

```python
REPLACEMENT = SyncRuleId("replacement-rule")
NEW_DESTINATION = endpoint("work-account", "other-calendar")


def _other(name: str) -> SyncRule:
    """Another enabled rule of the User, from a calendar of its own."""
    return SyncRule(
        SyncRuleId(name),
        endpoint("personal-account", f"{name}-calendar"),
        rule().destination,
        state=SyncRuleState.ENABLED,
    )


def _ordered(old: SyncRule) -> InMemoryUserUnitOfWorkFactory:
    """`old`, with two mappings, created between an older and a newer enabled rule."""
    unit_of_work = memory_units()
    with unit_of_work() as uow:
        for each in (_other("older"), old, _other("newer")):
            uow.rules.add(each)
        uow.commit()
    _add_mappings(unit_of_work, 2)
    return unit_of_work


def _counting(unit_of_work: InMemoryUserUnitOfWorkFactory) -> int:
    """How many of the User's rules count toward their Plan's rule limit."""
    return sum(each.counts_toward_plan for each in unit_of_work.state.rules.values())


def _replacer(
    unit_of_work: InMemoryUserUnitOfWorkFactory, remover: RemoveSyncRule | None = None
) -> ReplaceSyncRuleCalendars:
    return ReplaceSyncRuleCalendars(
        unit_of_work, remover if remover is not None else _remover(unit_of_work), Ids()
    )


def test_replacement_rejects_a_duplicate_relationship_before_removing_anything() -> None:
    unit_of_work = _with_mappings(1)
    unit_of_work.state.rules[SyncRuleId("existing")] = SyncRule(
        SyncRuleId("existing"), rule().source, NEW_DESTINATION
    )
    provider = RecordingProvider()

    with pytest.raises(DuplicateDirectionalRelationship):
        _replacer(unit_of_work, _remover(unit_of_work, provider)).execute(
            rule().id, rule().source, NEW_DESTINATION, ProjectionHandling.DELETE
        )

    assert provider.deleted_refs == []
    assert unit_of_work.state.rules[rule().id].state is SyncRuleState.ENABLED
    assert REPLACEMENT not in unit_of_work.state.rules


def test_replacement_rejects_unchanged_calendars() -> None:
    unit_of_work = _with_mappings(0)

    with pytest.raises(NotACalendarChange):
        _replacer(unit_of_work).execute(
            rule().id, rule().source, rule().destination, ProjectionHandling.DELETE
        )
    assert rule().id in unit_of_work.state.rules


def test_replacement_removes_the_rule_and_creates_a_draft_with_the_same_policy() -> None:
    unit_of_work = _with_mappings(1)
    details = TransformationPolicy(content=ProjectionContent.DETAILS)
    unit_of_work.state.rules[rule().id] = replace(rule(), transformation=details)

    replacement = _replacer(unit_of_work).execute(
        rule().id, rule().source, NEW_DESTINATION, ProjectionHandling.DETACH
    )

    assert replacement.removal.detached == 1
    assert list(unit_of_work.state.rules) == [REPLACEMENT]
    assert replacement.rule.state is SyncRuleState.DRAFT
    assert replacement.rule.transformation == details
    assert replacement.rule.destination == NEW_DESTINATION
    # The draft as inserted, with the place it took.
    assert replacement.rule == unit_of_work.state.rules[REPLACEMENT]
    assert replacement.removal.successor == replacement.rule


class CompetingRemoval(RemoveSyncRule):
    """Simulates another request creating the same relationship just after the checks pass."""

    def check(self, rule_id: SyncRuleId, handling: ProjectionHandling) -> None:
        RemoveSyncRule.check(self, rule_id, handling)
        with self.unit_of_work() as uow:
            uow.rules.add(SyncRule(SyncRuleId("competitor"), rule().source, NEW_DESTINATION))
            uow.commit()


def test_a_duplicate_that_appears_after_the_checks_is_refused_before_anything_changes() -> None:
    unit_of_work = _with_mappings(1)
    provider = RecordingProvider()
    remover = CompetingRemoval(unit_of_work, provider, Accounts(), FixedClock(), RuleLocks())

    with pytest.raises(DuplicateDirectionalRelationship):
        _replacer(unit_of_work, remover).execute(
            rule().id, rule().source, NEW_DESTINATION, ProjectionHandling.DELETE
        )

    assert provider.deleted_refs == []
    assert unit_of_work.state.rules[rule().id].state is SyncRuleState.ENABLED
    assert REPLACEMENT not in unit_of_work.state.rules
    assert len(unit_of_work.state.mappings) == 1


def test_replacement_creates_nothing_when_removal_cannot_start() -> None:
    unit_of_work = _with_mappings(1)
    remover = _remover(unit_of_work, accounts=Accounts(connected=False))

    with pytest.raises(RemovalRequiresAuthorization):
        _replacer(unit_of_work, remover).execute(
            rule().id, rule().source, NEW_DESTINATION, ProjectionHandling.DELETE
        )

    assert list(unit_of_work.state.rules) == [rule().id]


class LapsingAccounts:
    """Authorized for the replacement's own check, then lapsed when the removal begins."""

    def __init__(self) -> None:
        self.asked = 0

    def is_connected(self, account_id: ConnectedAccountId) -> bool:
        self.asked += 1
        return self.asked == 1


def test_a_check_that_fails_when_the_removal_begins_leaves_the_old_rule_and_no_draft() -> None:
    unit_of_work = _with_mappings(1)
    provider = RecordingProvider()
    remover = RemoveSyncRule(unit_of_work, provider, LapsingAccounts(), FixedClock(), RuleLocks())

    with pytest.raises(RemovalRequiresAuthorization):
        _replacer(unit_of_work, remover).execute(
            rule().id, rule().source, NEW_DESTINATION, ProjectionHandling.DELETE
        )

    assert provider.deleted_refs == []
    assert unit_of_work.state.rules == {rule().id: rule()}
    assert len(unit_of_work.state.mappings) == 1


def test_a_calendar_of_an_account_the_user_lacks_leaves_the_old_rule_and_no_draft() -> None:
    unit_of_work = _with_mappings(1)
    provider = RecordingProvider()

    with pytest.raises(ConnectedAccountRequired):
        _replacer(unit_of_work, _remover(unit_of_work, provider)).execute(
            rule().id,
            endpoint("someone-elses-account", "calendar"),
            rule().destination,
            ProjectionHandling.DELETE,
        )

    assert provider.deleted_refs == []
    assert unit_of_work.state.rules == {rule().id: rule()}
    assert len(unit_of_work.state.mappings) == 1


def test_no_draft_exists_before_the_old_rules_removal_begins() -> None:
    unit_of_work = _with_mappings(1)
    locks = RuleLocks()
    remover = RemoveSyncRule(unit_of_work, RecordingProvider(), Accounts(), FixedClock(), locks)
    running = locks.for_rule(rule().id)
    running.acquire()
    worker = Thread(
        target=_replacer(unit_of_work, remover).execute,
        args=(rule().id, rule().source, NEW_DESTINATION, ProjectionHandling.DETACH),
    )

    worker.start()
    worker.join(0.2)
    waited_for_the_run = worker.is_alive()
    rules_while_the_run_lasts = set(unit_of_work.state.rules)
    running.release()
    worker.join(5)

    assert waited_for_the_run
    assert rules_while_the_run_lasts == {rule().id}
    assert set(unit_of_work.state.rules) == {REPLACEMENT}


def test_the_draft_keeps_the_place_from_the_commit_that_begins_the_removal() -> None:
    unit_of_work = _ordered(rule())
    counting_before = _counting(unit_of_work)
    order = unit_of_work.state.rule_order[rule().id]
    seen: list[tuple[SyncRuleState, bool, int, int]] = []

    class ObservingProvider(RecordingProvider):
        def delete_projection(
            self, destination: EventRef, source: EventRef, rule_id: SyncRuleId, operation_key: str
        ) -> None:
            committed = unit_of_work.state
            seen.append(
                (
                    committed.rules[rule().id].state,
                    committed.rules[REPLACEMENT].keeps_place,
                    committed.rule_order[REPLACEMENT],
                    _counting(unit_of_work),
                )
            )
            super().delete_projection(destination, source, rule_id, operation_key)

    replacement = _replacer(unit_of_work, _remover(unit_of_work, ObservingProvider())).execute(
        rule().id, rule().source, NEW_DESTINATION, ProjectionHandling.DELETE
    )

    assert seen == [(SyncRuleState.REMOVING, True, order, counting_before)] * 2
    assert replacement.rule.keeps_place is True
    assert replacement.rule == unit_of_work.state.rules[REPLACEMENT]
    assert _counting(unit_of_work) == counting_before
    ranks = unit_of_work.state.rule_order
    assert ranks[SyncRuleId("older")] < ranks[REPLACEMENT] < ranks[SyncRuleId("newer")]


@pytest.mark.parametrize(
    ("old", "keeps_place"),
    [
        (rule(state=SyncRuleState.ENABLED), True),
        (rule().degrade(awaiting_reauthorization=True), True),
        (replace(rule(state=SyncRuleState.DRAFT), keeps_place=True), True),
        (rule(state=SyncRuleState.PAUSED), False),
        (rule(state=SyncRuleState.DEGRADED), False),
        (rule(state=SyncRuleState.DRAFT), False),
        (rule(state=SyncRuleState.PREVIEWED), False),
    ],
)
def test_the_draft_keeps_a_place_only_when_the_old_rule_counted(
    old: SyncRule, keeps_place: bool
) -> None:
    unit_of_work = _ordered(old)
    order = unit_of_work.state.rule_order[rule().id]

    replacement = _replacer(unit_of_work).execute(
        rule().id, rule().source, NEW_DESTINATION, ProjectionHandling.DETACH
    )

    assert replacement.rule.keeps_place is keeps_place
    ranks = unit_of_work.state.rule_order
    if keeps_place:
        assert ranks[REPLACEMENT] == order
    else:
        # It keeps its own new order, so it is the newest rule.
        assert ranks[REPLACEMENT] > ranks[SyncRuleId("newer")]


def test_a_successor_that_is_not_a_new_draft_is_refused_and_nothing_changes() -> None:
    unit_of_work = _with_mappings(1)
    enabled = SyncRule(REPLACEMENT, rule().source, NEW_DESTINATION, state=SyncRuleState.ENABLED)

    with pytest.raises(InvalidStateTransition):
        _remover(unit_of_work).execute(rule().id, ProjectionHandling.DETACH, successor=enabled)

    assert unit_of_work.state.rules == {rule().id: rule()}
    assert len(unit_of_work.state.mappings) == 1


def test_interrupted_replacement_keeps_the_new_draft_its_place_and_a_retryable_old_rule() -> None:
    unit_of_work = _with_mappings(2)

    with pytest.raises(ReplacementInterrupted) as interrupted:
        _replacer(unit_of_work, _remover(unit_of_work, RecordingProvider(fail_on_call=2))).execute(
            rule().id, rule().source, NEW_DESTINATION, ProjectionHandling.DELETE
        )

    assert interrupted.value.replacement_rule_id == REPLACEMENT
    assert "retry" in str(interrupted.value)
    draft = unit_of_work.state.rules[REPLACEMENT]
    assert (draft.state, draft.keeps_place) == (SyncRuleState.DRAFT, True)
    assert unit_of_work.state.rules[rule().id].state is SyncRuleState.REMOVING
    assert _counting(unit_of_work) == 1

    _remover(unit_of_work).execute(rule().id, ProjectionHandling.DETACH)

    assert unit_of_work.state.rules == {REPLACEMENT: draft}


class DisconnectedDestination(RecordingProvider):
    """The destination account lost its credentials once the removal began."""

    def delete_projection(
        self, destination: EventRef, source: EventRef, rule_id: SyncRuleId, operation_key: str
    ) -> None:
        raise ConnectedAccountDisconnected("reauthorize the account before using it")


def test_an_error_after_the_removal_began_keeps_the_draft() -> None:
    unit_of_work = _with_mappings(1)

    with pytest.raises(ConnectedAccountDisconnected):
        _replacer(unit_of_work, _remover(unit_of_work, DisconnectedDestination())).execute(
            rule().id, rule().source, NEW_DESTINATION, ProjectionHandling.DELETE
        )

    assert unit_of_work.state.rules[REPLACEMENT].keeps_place is True
    assert unit_of_work.state.rules[rule().id].state is SyncRuleState.REMOVING
    assert len(unit_of_work.state.mappings) == 1


def test_a_replacement_over_the_rule_limit_keeps_the_place_and_its_start_succeeds() -> None:
    users = MemoryUsers()
    users.add(User(USER, "member@example.test", Role.USER, UserState.ACTIVE, NOW), "x")
    plans = MemoryPlans(users=users)
    plans_on(plans, FREE)
    unit_of_work = _ordered(rule())
    assert plans.of(USER).limits.rules == 1
    assert _counting(unit_of_work) == 3

    _replacer(unit_of_work).execute(
        rule().id, rule().source, NEW_DESTINATION, ProjectionHandling.DETACH
    )
    with unit_of_work() as uow:
        draft = uow.rules.get(REPLACEMENT)
        assert draft is not None
        uow.rules.save(draft.mark_previewed())
        uow.commit()
    started = EnableSyncRule(unit_of_work, RuleLocks(), plans, USER).execute(REPLACEMENT)

    assert started.state is SyncRuleState.ENABLED
    assert started.keeps_place is False
    assert _counting(unit_of_work) == 3


def test_a_replacement_in_flight_keeps_its_place_when_plans_turn_on_during_the_removal() -> None:
    users = MemoryUsers()
    users.add(User(USER, "member@example.test", Role.USER, UserState.ACTIVE, NOW), "x")
    plans = MemoryPlans(users=users)
    unit_of_work = _ordered(rule())
    assert plans.of(USER).limits.rules is None

    class PlansTurnOn(RecordingProvider):
        """An administrator turns Plans on, with a one-rule default, while the removal runs."""

        def delete_projection(
            self, destination: EventRef, source: EventRef, rule_id: SyncRuleId, operation_key: str
        ) -> None:
            if not plans.enabled:
                plans_on(plans, FREE)
            super().delete_projection(destination, source, rule_id, operation_key)

    _replacer(unit_of_work, _remover(unit_of_work, PlansTurnOn())).execute(
        rule().id, rule().source, NEW_DESTINATION, ProjectionHandling.DELETE
    )
    with unit_of_work() as uow:
        draft = uow.rules.get(REPLACEMENT)
        assert draft is not None
        uow.rules.save(draft.mark_previewed())
        uow.commit()
    assert plans.of(USER).limits.rules == 1
    assert _counting(unit_of_work) == 3
    started = EnableSyncRule(unit_of_work, RuleLocks(), plans, USER).execute(REPLACEMENT)

    assert started.state is SyncRuleState.ENABLED
    assert _counting(unit_of_work) == 3


def _creation_orders(database: Path) -> dict[str, int]:
    """Each rule's creation order, which ranks the User's rules (ADR 0038)."""
    with transaction(database) as connection:
        rows = connection.execute("SELECT id, creation_order FROM sync_rules").fetchall()
    return {str(row["id"]): int(row["creation_order"]) for row in rows}


def _sqlite_replacer(units: UnitOfWorkFactory) -> ReplaceSyncRuleCalendars:
    return ReplaceSyncRuleCalendars(
        units, RemoveSyncRule(units, None, None, FixedClock(), RuleLocks()), Ids()
    )


def test_on_sqlite_the_draft_takes_the_place_and_rank_of_the_rule_it_replaces(
    tmp_path: Path,
) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    units = sqlite_units(database)
    with units() as uow:
        for each in (_other("older"), rule(), _other("newer")):
            uow.rules.add(each)
        uow.commit()
    order = _creation_orders(database)[rule().id.value]

    replacement = _sqlite_replacer(units).execute(
        rule().id, rule().source, NEW_DESTINATION, ProjectionHandling.DETACH
    )

    with units() as uow:
        stored = uow.rules.get(REPLACEMENT)
    assert stored == replacement.rule
    assert replacement.rule.keeps_place is True
    assert _creation_orders(database) == {
        "older": order - 1,
        REPLACEMENT.value: order,
        "newer": order + 1,
    }


def test_on_sqlite_a_refused_draft_rolls_back_the_start_of_the_removal(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    units = sqlite_units(database)
    with units() as uow:
        uow.rules.add(rule())
        uow.commit()

    with pytest.raises(ConnectedAccountRequired):
        _sqlite_replacer(units).execute(
            rule().id,
            endpoint("someone-elses-account", "calendar"),
            rule().destination,
            ProjectionHandling.DETACH,
        )

    with units() as uow:
        assert tuple(uow.rules.list()) == (rule(),)
```

- [ ] **Step 3: Write the test: `CreateSyncRule` still refuses a duplicate**

In `tests/application/test_rules.py`, replace

```python
from calendar_sync.application.sync.errors import ConnectedAccountRequired, RuleNotFound
```

with

```python
from calendar_sync.application.sync.errors import (
    ConnectedAccountRequired,
    DuplicateDirectionalRelationship,
    RuleNotFound,
)
```

and append to the end of the file:

```python
def test_new_rules_refuse_a_relationship_another_rule_has() -> None:
    unit_of_work = memory_units()
    unit_of_work.state.rules[rule().id] = rule()
    twin = SyncRule(SyncRuleId("twin"), rule().source, rule().destination)

    with pytest.raises(DuplicateDirectionalRelationship):
        CreateSyncRule(unit_of_work).execute(twin)

    assert unit_of_work.state.rules == {rule().id: rule()}
```

It passes before and after this task: it pins that moving the checks into `insert_rule` keeps
`CreateSyncRule`'s behavior.

- [ ] **Step 4: Run the tests to verify they fail**

```sh
.venv/bin/pytest tests/application/test_remove_sync_rule.py tests/application/test_rules.py -q
```

Expected: every Rule Replacement test fails with
`TypeError: ReplaceSyncRuleCalendars.__init__() missing 1 required positional argument: 'ids'`, and
`test_a_successor_that_is_not_a_new_draft_is_refused_and_nothing_changes` with
`TypeError: RemoveSyncRule.execute() got an unexpected keyword argument 'successor'`. The removal
tests that do not replace, and every `test_rules.py` test, pass.

- [ ] **Step 5: Implement `src/calendar_sync/application/sync/rule_insertion.py`**

Create the file:

```python
"""The checks every new Directional Sync Rule passes, inside the unit of work that adds it."""

from __future__ import annotations

from calendar_sync.application.sync.errors import (
    ConnectedAccountRequired,
    DuplicateDirectionalRelationship,
)
from calendar_sync.application.sync.ports import UnitOfWork
from calendar_sync.domain.model import SyncRule


def insert_rule(uow: UnitOfWork, rule: SyncRule) -> None:
    """Add a new rule inside an open unit of work, with the checks every new rule passes:
    raises DuplicateDirectionalRelationship before the insert, and ConnectedAccountRequired
    after it (the insert holds the write lock); the caller's unit then rolls back."""
    if uow.rules.relationship_exists(rule.source, rule.destination):
        raise DuplicateDirectionalRelationship(
            "a rule already exists for this source and destination"
        )
    uow.rules.add(rule)
    # Checked after the insert holds the write lock, so an account deleted meanwhile cannot be
    # left with a rule that names it. Raising rolls the insert back with the caller's unit.
    for endpoint in (rule.source, rule.destination):
        if uow.accounts.state(endpoint.connected_account_id) is None:
            raise ConnectedAccountRequired("connect both accounts before creating a rule")
```

- [ ] **Step 6: Implement the successor in `src/calendar_sync/application/sync/removal.py`**

Change the `dataclasses` import to

```python
from dataclasses import dataclass, field, replace
```

and add, after `from calendar_sync.application.sync.retry import with_retries`,

```python
from calendar_sync.application.sync.rule_insertion import insert_rule
```

Replace `class RemovalResult` with:

```python
@dataclass(frozen=True, slots=True)
class RemovalResult:
    deleted: int
    detached: int
    conflicts: int
    successor: SyncRule | None = None
    """A Rule Replacement's new draft, as inserted when the removal began."""
```

In `class RemoveSyncRule`, replace `execute` with (the fields stay as they are, so the class
stays in `WIDE_DATACLASSES` unchanged):

```python
    def execute(
        self,
        rule_id: SyncRuleId,
        handling: ProjectionHandling,
        *,
        successor: SyncRule | None = None,
    ) -> RemovalResult:
        """Remove the rule. A Rule Replacement passes its new draft as `successor`: it is
        inserted, holding the rule's place under its User's rule limit when the rule counted,
        in the transaction that begins the removal, so both happen or neither does (ADR 0010,
        ADR 0038). Once that commits, nothing removes the draft."""
        work = RuleWork(RuleWorkKind.REMOVAL, self.clock.now(), handling=handling)
        with (
            self.locks.for_rule(rule_id),
            self.locks.working(rule_id, work),
            self.call_stats.measure() as calls,
        ):
            try:
                return self._execute_measured(rule_id, handling, work, calls, successor)
            finally:
                # After the removal's unit of work closed, so the count never waits on it.
                record_provider_calls(self.unit_of_work, self.clock, calls)
```

and replace `_execute_measured` with:

```python
    def _execute_measured(
        self,
        rule_id: SyncRuleId,
        handling: ProjectionHandling,
        work: RuleWork,
        calls: ProviderCallTally,
        successor: SyncRule | None,
    ) -> RemovalResult:
        with self.unit_of_work() as uow:
            with self.locks.for_writes(rule_id):
                rule = self._require_possible(uow.rules.get(rule_id), rule_id, handling)
                # The save takes SQLite's writer lock, so the successor's checks below see
                # every committed rule and account, and any of them raising rolls both back.
                uow.rules.save(rule.begin_removal())
                placed = _place_successor(uow, successor, rule)
                uow.commit()
            mappings = uow.mappings.for_rule(rule.id)
            work.total = len(mappings)
            logger.info(
                "removal started rule=%s handling=%s mappings=%d",
                rule_id.value,
                handling.value,
                len(mappings),
            )
            try:
                result = self._remove(uow, rule, mappings, handling, work)
            except RemovalInterrupted as interrupted:
                logger.warning(
                    "removal interrupted rule=%s kind=%s after %s handled=%d remaining=%d %s",
                    rule_id.value,
                    interrupted.failure.kind.value,
                    duration(self.clock.now() - work.started_at),
                    interrupted.processed,
                    interrupted.remaining,
                    call_summary(calls),
                )
                raise
            logger.info(
                "removal finished rule=%s in %s deleted=%d detached=%d conflicts=%d %s",
                rule_id.value,
                duration(self.clock.now() - work.started_at),
                result.deleted,
                result.detached,
                result.conflicts,
                call_summary(calls),
            )
        return result if placed is None else replace(result, successor=placed)
```

Add the module-level helper just before `def _operation_key`:

```python
def _place_successor(uow: UnitOfWork, successor: SyncRule | None, old: SyncRule) -> SyncRule | None:
    """Insert a Rule Replacement's new draft in the unit that begins `old`'s removal; it keeps
    `old`'s place, and ranks where `old` ranked, when `old` counted toward its User's Plan."""
    if successor is None:
        return None
    placed = successor.take_place_of(old)
    insert_rule(uow, placed)
    if placed.keeps_place:
        uow.rules.inherit_place(placed.id, of=old.id)
    return placed
```

- [ ] **Step 7: Implement `CreateSyncRule` and `ReplaceSyncRuleCalendars` in `src/calendar_sync/application/sync/rules.py`**

Replace the import block at the top of the file (task 9's version, from `import logging` through
`logger = logging.getLogger(__name__)`) with this block: `ApplicationError` and
`ConnectedAccountRequired` are no longer used here, and `insert_rule` is:

```python
import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace

from calendar_sync.application.shared.ports import Clock, IdGenerator
from calendar_sync.application.sync.errors import (
    DuplicateDirectionalRelationship,
    NotACalendarChange,
    RemovalInterrupted,
    ReplacementInterrupted,
    RuleNotFound,
)
from calendar_sync.application.sync.locking import RuleLocks, RuleWork
from calendar_sync.application.sync.ports import (
    Allowances,
    RulePreviewSummary,
    UnitOfWork,
    UnitOfWorkFactory,
)
from calendar_sync.application.sync.removal import RemovalResult, RemoveSyncRule
from calendar_sync.application.sync.rule_insertion import insert_rule
from calendar_sync.domain.access import UserId
from calendar_sync.domain.audit import AuditAction, AuditEntry, AuditOutcome
from calendar_sync.domain.model import (
    AllDaySyncPolicy,
    BirthdayPolicy,
    CalendarEndpoint,
    ProjectionContent,
    ProjectionHandling,
    SyncRule,
    SyncRuleId,
    TentativeEventPolicy,
    TransformationPolicy,
    UnansweredInvitationPolicy,
)
from calendar_sync.domain.plans import LimitedResource, PlanLimitReached, may_start
from calendar_sync.domain.runs import RuleRunOutcome, RunKind

logger = logging.getLogger(__name__)
```

Replace `class CreateSyncRule` with:

```python
@dataclass(slots=True)
class CreateSyncRule:
    unit_of_work: UnitOfWorkFactory

    def execute(self, rule: SyncRule) -> SyncRule:
        with self.unit_of_work() as uow:
            insert_rule(uow, rule)
            uow.commit()
        return rule
```

Replace `class RuleReplacement` and `class ReplaceSyncRuleCalendars` (to the end of the file)
with the block below. The draft is no longer created first and never withdrawn: `RemoveSyncRule.execute` inserts it in
the transaction that begins the removal, and every error but `RemovalInterrupted` propagates with
no cleanup. The route's mapping does not change: `DuplicateDirectionalRelationship` and
`ConnectedAccountRequired` raised in that transaction are `ApplicationError`s, which
`_rule_change_problem` answers with 409.

```python
@dataclass(frozen=True, slots=True)
class RuleReplacement:
    rule: SyncRule
    """The new draft as inserted; it keeps the previous rule's place when that rule counted."""
    removal: RemovalResult


@dataclass(slots=True)
class ReplaceSyncRuleCalendars:
    """Rule Replacement: remove the old rule, inserting a new Draft with the same policy in the
    step that begins the removal (ADR 0010, ADR 0038)."""

    unit_of_work: UnitOfWorkFactory
    remove_rule: RemoveSyncRule
    ids: IdGenerator

    def execute(
        self,
        rule_id: SyncRuleId,
        source: CalendarEndpoint,
        destination: CalendarEndpoint,
        handling: ProjectionHandling,
    ) -> RuleReplacement:
        with self.unit_of_work() as uow:
            current = uow.rules.get(rule_id)
            if current is None:
                raise RuleNotFound(f"sync rule {rule_id.value} does not exist")
            duplicate = uow.rules.relationship_exists(source, destination)
        if (source, destination) == (current.source, current.destination):
            raise NotACalendarChange("the calendars are unchanged; edit the policy instead")
        replacement = SyncRule(
            id=SyncRuleId(self.ids.new()),
            source=source,
            destination=destination,
            transformation=current.transformation,
            initial_lookback_days=current.initial_lookback_days,
        )
        if duplicate:
            raise DuplicateDirectionalRelationship(
                "a rule already exists for this source and destination"
            )
        self.remove_rule.check(rule_id, handling)
        # The removal inserts the draft in the transaction that begins it, with the checks every
        # new rule passes: a duplicate that appeared meanwhile, or an account deleted meanwhile,
        # rolls both back before anything is removed, and no draft exists without its removal.
        try:
            removal = self.remove_rule.execute(rule_id, handling, successor=replacement)
        except RemovalInterrupted as interrupted:
            raise ReplacementInterrupted(replacement.id, interrupted) from interrupted
        assert removal.successor is not None
        return RuleReplacement(removal.successor, removal)
```

- [ ] **Step 8: Implement the composition in `src/calendar_sync/bootstrap/container.py`**

In `_compose_user`, inside `return UserServices(...)`, drop `create_sync_rule` from the
replacement's arguments:

```diff
         replace_sync_rule_calendars=ReplaceSyncRuleCalendars(
-            unit_of_work, remove_sync_rule, create_sync_rule, adapters.ids
+            unit_of_work, remove_sync_rule, adapters.ids
         ),
```

`create_sync_rule` stays: `CreateDraftSyncRule(create_sync_rule, adapters.ids)` still uses it.

- [ ] **Step 9: Update the glossary in `CONTEXT.md`**

Replace the paragraph under `**Rule Replacement**:` (keep the `_Avoid_: Calendar edit, rule
move` line under it) with:

```markdown
A change of a rule's source or destination calendar, performed as a new draft rule with the same transformation policy followed by Rule Removal of the previous rule. The new draft is created in the step that begins the previous rule's removal, so a duplicate relationship is refused before anything is removed, and no draft exists without that removal. When the previous rule counted toward its User's rule limit, the new draft keeps its place until it starts or is removed. If the removal is interrupted, the new draft remains with its place, and the previous rule's removal can be retried.
```

ADR 0010 still says the draft is created first; task 19 amends it, with the CHANGELOG entry.

- [ ] **Step 10: Run the tests to verify they pass, and the backend gate**

```sh
.venv/bin/pytest tests/application/test_remove_sync_rule.py tests/application/test_rules.py tests/application/test_plan_limits.py -q
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy
.venv/bin/lint-imports
.venv/bin/pytest -q
```

Expected: 41 tests in `test_remove_sync_rule.py` and 15 in `test_rules.py` pass, with
`test_plan_limits.py`; ruff, mypy, and lint-imports are clean (`tests/test_architecture.py`
still finds `RemoveSyncRule` as the only wide class this task touches); the full suite passes,
including the replace route tests in `tests/adapters/test_api.py`. No schema changed, so the
OpenAPI files and the static bundle stay as they are.

- [ ] **Step 11: Commit**

```sh
git add src/calendar_sync/application/sync/rule_insertion.py \
  src/calendar_sync/application/sync/rules.py \
  src/calendar_sync/application/sync/removal.py \
  src/calendar_sync/bootstrap/container.py \
  tests/application/test_remove_sync_rule.py \
  tests/application/test_rules.py \
  CONTEXT.md
git commit -F - <<'EOF'
Create a replacement draft when the old rule's removal begins, in its place

Rule Replacement no longer creates its draft first. The removal inserts it
in the transaction that saves the old rule as Removing, after the old
rule's run ends, with the checks every new rule passes, so a duplicate or
a missing account changes nothing and no draft is ever withdrawn. When the
old rule counted toward its User's rule limit, the draft keeps its place
and rank, so its Start succeeds even over the limit.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
```

## Part 6: The account limit, Your plan, and the Operator Overview (Tasks 11 and 12)

### Task 11: Account limit and its OAuth outcome

A new calendar account (a provider and email address the User has not connected) is refused at the
User's Plan's account limit, inside the existing `BEGIN IMMEDIATE` of
`SqliteUserConnectedAccounts.save`, and stores nothing. Disconnected Accounts count. Reauthorization
of an account the User has never reads Plans, so it always works and still resumes the rules a
lapse stopped. The OAuth callback answers the refusal with the outcome `account_limit_reached` and
the limit; Settings explains it and links to Your plan in place of "Try again". Spec sections 3.4,
3.6, and 4; contract sections 3.12 (account part) and 3.18; Review Focus 1 and 3 (connect part);
open question 10 (a raising Allowance read for a new address answers 500 at the callback).

No request or response model changes and no route is added: the callback is
`include_in_schema=False`, so OpenAPI is not regenerated (`tests/test_openapi_contract.py` proves
it).

**Files:**
- Modify: `src/calendar_sync/application/sync/errors.py` (new `AccountLimitReached` right after `CalendarPermissionRequired`)
- Modify: `src/calendar_sync/infrastructure/persistence/accounts.py` (imports; `SqliteConnectedAccountStore` docstring, `__init__`, `for_user`; `SqliteUserConnectedAccounts.__init__`, `save`; new private `SqliteUserConnectedAccounts._require_room_for`)
- Modify: `src/calendar_sync/infrastructure/oauth.py` (import block; `connect_account`)
- Modify: `src/calendar_sync/interfaces/api/routes/accounts.py` (imports; `OAuthOutcome`, `OAUTH_OUTCOMES` after `REFUSED`; the `try` block of `complete_oauth`; `_ReturnTo.outcome`)
- Modify: `src/calendar_sync/bootstrap/container.py` (`build_adapters`: the `accounts = (...)` block)
- Modify: `web/src/lib/oauth-redirect.ts` (`OAuthOutcome`, `OAUTH_OUTCOME_MESSAGES`)
- Modify: `web/src/lib/navigation.ts` (`SETTINGS_ARRIVAL_PARAMS`; new `yourPlanPath` after `appPathForSettingsTab`)
- Modify: `web/src/features/settings.tsx` (navigation import; `SettingsArrival`; `useSettingsArrival`; `ConnectionsTab`; `OAuthOutcomeNotice` and two new private components)
- Modify: `web/src/i18n/locales/en/settings.json` (`oauthOutcome.accountLimitReached`)
- Modify: `web/src/i18n/locales/en/common.json` (new `plan` group with `seeYourPlan`)
- Modify: `docs/troubleshooting.md` (new section before `## Microsoft sign-in stops with an error`)
- Regenerate: `src/calendar_sync/interfaces/api/static/` (`pnpm run build`)
- Test: `tests/adapters/test_account_limit.py` (new)
- Test: `tests/adapters/test_oauth_outcomes.py` (new)
- Test: `tests/adapters/test_plan_races.py` (task 8 created it; append the connect race)
- Test: `web/src/lib/oauth-redirect.test.ts`, `web/src/lib/navigation.test.ts`, `web/src/features/settings.test.tsx`

**Interfaces:**
- Consumes (task 1): `LimitedResource.CONNECTED_ACCOUNTS`, `require_room(resource, in_use, limit) -> None`, `PlanLimitReached` (`.resource`, `.limit`), `Allowance.limits.connected_accounts`.
- Consumes (task 4): `Allowances` (`calendar_sync.application.sync.ports`, `of(user) -> Allowance`); `SqlitePlans(database_path)` (`calendar_sync.infrastructure.persistence.plans`); the local `plans = SqlitePlans(database)` in `build_adapters`; `Adapters.plan_catalog`; `BrokenAllowances` (`tests.identity_fakes`, every read raises `RuntimeError("database is locked")`); `FREE` (1 rule, 1 account, 0 tokens), `FAMILY` (5 rules, 3 accounts, 2 tokens), `plans_on(catalog, default=FREE, *others)` (`tests.plans`); `limited_user(database, user=OTHER_USER, *, plan=None, email=None) -> UserId` (`tests.users`).
- Consumes (task 8): `tests/adapters/test_plan_races.py` with `HeldAllowances(inner)` (`.reading`, `.released` events; every read waits until released), `WAIT = 0.5`, and its imports.
- Produces:
  - `AccountLimitReached(AuthorizationFailed)` in `calendar_sync.application.sync.errors`: `AccountLimitReached(limit: int)`, `.limit`, message `f"the plan allows {limit} calendar accounts"`.
  - `SqliteConnectedAccountStore(database_path, cipher, clock=None, ids=None, allowances: Allowances | None = None)`; `SqliteUserConnectedAccounts(database_path, user_id, cipher, clock, ids, allowances: Allowances | None = None)`; `save(...)` raises `PlanLimitReached(CONNECTED_ACCOUNTS, limit)` for a new address at the limit, and whatever a raising Allowance read raises.
  - `connect_account(...)` raises `AccountLimitReached(limit)` in place of `PlanLimitReached`.
  - `OAuthOutcome = Literal["connected", "calendar_permission_required", "authorization_failed", "account_limit_reached"]` and `OAUTH_OUTCOMES: tuple[str, ...]` in `calendar_sync.interfaces.api.routes.accounts`; the callback redirect `/settings/connections?oauth=account_limit_reached&provider=<kind>&limit=<n>` (303).
  - Web: `OAuthOutcome` gains `"account_limit_reached"`; `OAUTH_OUTCOME_MESSAGES.account_limit_reached`; `SETTINGS_ARRIVAL_PARAMS` gains `"limit"`; `export function yourPlanPath(): string` returning `"/settings/account#your-plan"`; catalog keys `settings.oauthOutcome.accountLimitReached.title`, `settings.oauthOutcome.accountLimitReached.body` (plural), `common.plan.seeYourPlan`.
  - Docs anchors: `docs/troubleshooting.md#connect-is-unavailable-your-plans-calendar-accounts` and `#an-accounts-address-changed`.

- [ ] **Step 1: Write the failing adapter, callback, and race tests**

Create `tests/adapters/test_account_limit.py`:

```python
"""A new calendar account is refused at its User's Plan's account limit, after the provider's
consent; Reauthorization of an account the User has is never refused (ADR 0038)."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from calendar_sync.application.sync.errors import AccountLimitReached, AuthorizationFailed
from calendar_sync.application.sync.ports import Allowances, AuthorizedAccount
from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import Adapters, Container, build_adapters, compose
from calendar_sync.domain.access import Role, UserId
from calendar_sync.domain.accounts import ConnectedAccount, ConnectedAccountState, ProviderKind
from calendar_sync.domain.model import SyncRule, SyncRuleId, SyncRuleState
from calendar_sync.domain.plans import LimitedResource, PlanLimitReached
from calendar_sync.infrastructure.clock import SystemClock
from calendar_sync.infrastructure.google.oauth import GoogleOAuthService
from calendar_sync.infrastructure.oauth import connect_account
from calendar_sync.infrastructure.persistence.accounts import SqliteConnectedAccountStore
from calendar_sync.infrastructure.persistence.migrations import initialize_database
from calendar_sync.infrastructure.persistence.plans import SqlitePlans
from calendar_sync.infrastructure.persistence.sqlite import SqliteUnitOfWorkFactory
from calendar_sync.infrastructure.persistence.users import SqliteUserDirectory
from calendar_sync.infrastructure.security import CredentialCipher
from calendar_sync.interfaces.api.app import create_app
from calendar_sync.interfaces.api.dependencies import SESSION_COOKIE
from tests.helpers import endpoint
from tests.identity_fakes import BrokenAllowances
from tests.plans import FAMILY, FREE, plans_on
from tests.users import OTHER_USER, add_user, administrator, limited_user, session_for

CIPHER = CredentialCipher(CredentialCipher.generate_key())


@pytest.fixture
def database(tmp_path: Path) -> Path:
    path = tmp_path / "calendar-sync.db"
    initialize_database(path)
    return path


def _store(database: Path, allowances: Allowances | None) -> SqliteConnectedAccountStore:
    return SqliteConnectedAccountStore(database, CIPHER, allowances=allowances)


def _connect(store: SqliteConnectedAccountStore, user: UserId, email: str) -> ConnectedAccount:
    """Save an account as a provider's callback does once its consent is given."""
    return store.for_user(user).save("Synthetic", email, "{}", provider=ProviderKind.GOOGLE)


def _emails(store: SqliteConnectedAccountStore, user: UserId) -> list[str]:
    return [account.email for account in store.for_user(user).list()]


def _on_free(database: Path) -> tuple[SqliteConnectedAccountStore, UserId]:
    """A member on the Default Plan, Free, which allows one calendar account."""
    plans = SqlitePlans(database)
    plans_on(plans, FREE)
    return _store(database, plans), limited_user(database)


def test_a_new_address_at_the_limit_is_refused_and_nothing_is_stored(database: Path) -> None:
    store, member = _on_free(database)
    _connect(store, member, "first@example.test")

    with pytest.raises(PlanLimitReached) as refused:
        _connect(store, member, "second@example.test")

    assert (refused.value.resource, refused.value.limit) == (
        LimitedResource.CONNECTED_ACCOUNTS,
        1,
    )
    assert _emails(store, member) == ["first@example.test"]


def test_the_oauth_flow_reports_the_limit_it_met(database: Path) -> None:
    store, member = _on_free(database)
    _connect(store, member, "first@example.test")

    with pytest.raises(AccountLimitReached) as refused:
        connect_account(
            store,
            member,
            display_name="Second",
            email="second@example.test",
            credentials="{}",
            provider=ProviderKind.GOOGLE,
        )

    assert refused.value.limit == 1
    # An AuthorizationFailed, so any caller that knows no better still connects nothing.
    assert isinstance(refused.value, AuthorizationFailed)
    assert _emails(store, member) == ["first@example.test"]


def test_disconnected_accounts_count_so_disconnecting_one_makes_no_room(database: Path) -> None:
    store, member = _on_free(database)
    first = _connect(store, member, "first@example.test")
    store.for_user(member).disconnect(first.id)

    with pytest.raises(PlanLimitReached):
        _connect(store, member, "second@example.test")
    # Connecting the Disconnected Account again is Reauthorization, which is never refused.
    again = _connect(store, member, "first@example.test")

    assert (again.id, again.state) == (first.id, ConnectedAccountState.CONNECTED)
    assert _emails(store, member) == ["first@example.test"]


def test_reauthorization_over_the_limit_succeeds_without_reading_plans(database: Path) -> None:
    plans = SqlitePlans(database)
    member = limited_user(database)
    # Both connected while Plans were off; Free then allows only one.
    work = _connect(_store(database, plans), member, "work@example.test")
    _connect(_store(database, plans), member, "home@example.test")
    plans_on(plans, FREE)
    with SqliteUnitOfWorkFactory(database, SystemClock()).for_user(member)() as uow:
        uow.accounts.lapse(work.id, attempted_at=datetime.now(UTC))
        uow.commit()

    # Every read of Plans raises, so a Reauthorization that read them would fail.
    renewed = _connect(_store(database, BrokenAllowances()), member, "work@example.test")

    assert renewed.id == work.id
    assert (renewed.state, renewed.authorization_lapsed_at) == (
        ConnectedAccountState.CONNECTED,
        None,
    )
    assert _emails(_store(database, plans), member) == ["home@example.test", "work@example.test"]


def test_a_failing_plans_read_refuses_a_new_address(database: Path) -> None:
    store = _store(database, BrokenAllowances())
    member = limited_user(database)

    # Fail closed: like any database error, never an account admitted past the limit. Through
    # the OAuth callback this answers 500, and connecting again works once Plans can be read.
    with pytest.raises(RuntimeError, match="database is locked"):
        connect_account(
            store,
            member,
            display_name="New",
            email="new@example.test",
            credentials="{}",
            provider=ProviderKind.GOOGLE,
        )

    assert _emails(store, member) == []


def test_administrators_and_plans_off_are_never_limited(database: Path) -> None:
    plans = SqlitePlans(database)
    store = _store(database, plans)
    member = limited_user(database)
    for number in range(3):
        _connect(store, member, f"member-{number}@example.test")
    plans_on(plans, FREE)
    owner = add_user(database)

    for number in range(3):
        _connect(store, owner, f"owner-{number}@example.test")

    assert len(_emails(store, member)) == 3
    assert len(_emails(store, owner)) == 3


def test_an_administrator_demoted_over_the_limit_keeps_every_account_but_adds_no_new_one(
    database: Path,
) -> None:
    add_user(database)  # Another administrator, so the demotion leaves one.
    owner = add_user(database, OTHER_USER)
    plans = SqlitePlans(database)
    store = _store(database, plans)
    first = _connect(store, owner, "first@example.test")
    _connect(store, owner, "second@example.test")
    plans_on(plans, FREE)
    directory = SqliteUserDirectory(database)
    directory.set_role(owner, Role.USER)

    with pytest.raises(PlanLimitReached) as refused:
        _connect(store, owner, "third@example.test")
    renewed = _connect(store, owner, "first@example.test")

    assert refused.value.limit == 1
    assert renewed.id == first.id
    assert _emails(store, owner) == ["first@example.test", "second@example.test"]

    # Promoting them again lifts the limit.
    directory.set_role(owner, Role.INSTALLATION_ADMINISTRATOR)
    _connect(store, owner, "third@example.test")

    assert len(_emails(store, owner)) == 3


def test_a_users_own_plan_sets_their_limit(database: Path) -> None:
    plans = SqlitePlans(database)
    plans_on(plans, FREE, FAMILY)
    store = _store(database, plans)
    member = limited_user(database, plan=FAMILY.key.value)
    for number in range(3):
        _connect(store, member, f"member-{number}@example.test")

    with pytest.raises(PlanLimitReached) as refused:
        _connect(store, member, "member-3@example.test")

    assert refused.value.limit == 3


def test_a_store_without_allowances_limits_nobody(database: Path) -> None:
    plans_on(SqlitePlans(database), FREE)
    store = _store(database, None)
    member = limited_user(database)

    _connect(store, member, "first@example.test")
    _connect(store, member, "second@example.test")

    assert len(_emails(store, member)) == 2


# Through the OAuth callback, as both providers complete their flows.

CALLBACK = "/api/v1/oauth/google/callback?state=synthetic-state&code=synthetic-code"


def _installation(database: Path) -> tuple[Container, Adapters]:
    settings = Settings(database, master_key=CredentialCipher.generate_key())
    adapters = build_adapters(settings)
    return replace(compose(settings, adapters), scheduler=None), adapters


def _account_store(adapters: Adapters) -> SqliteConnectedAccountStore:
    """The store both providers' callbacks save accounts through."""
    store = getattr(adapters.accounts, "__self__", None)
    assert isinstance(store, SqliteConnectedAccountStore)
    return store


def _consent_returns(adapters: Adapters, email: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Google's consent completes for the signed-in User with `email` as the account's address,
    and Calendar Ghost saves it as the real callback does."""
    descriptor = adapters.providers.of(ProviderKind.GOOGLE)
    assert descriptor is not None
    assert isinstance(descriptor.calendars, GoogleOAuthService)
    store = _account_store(adapters)

    def complete(state: str, code: str, user: UserId) -> AuthorizedAccount:
        return connect_account(
            store,
            user,
            display_name="Synthetic",
            email=email,
            credentials="{}",
            provider=ProviderKind.GOOGLE,
        )

    monkeypatch.setattr(descriptor.calendars, "complete", Mock(side_effect=complete))


def _member_at_the_limit(database: Path, adapters: Adapters) -> tuple[UserId, ConnectedAccount]:
    """A member on Free with one account and an enabled rule between two of its calendars."""
    administrator(adapters)
    member = limited_user(database)
    account = _connect(_account_store(adapters), member, "first@example.test")
    plans_on(adapters.plan_catalog, FREE)
    rule = SyncRule(
        SyncRuleId("member-rule"),
        endpoint(account.id.value, "home"),
        endpoint(account.id.value, "work"),
        state=SyncRuleState.ENABLED,
    )
    with adapters.unit_of_work(member)() as uow:
        uow.rules.add(rule)
        uow.commit()
    return member, account


def test_the_callback_reports_the_account_limit_and_connects_nothing(
    database: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    container, adapters = _installation(database)
    member, account = _member_at_the_limit(database, adapters)
    # The provider now reports another address: a renamed account, or another one chosen.
    _consent_returns(adapters, "renamed@example.test", monkeypatch)

    with TestClient(create_app(container)) as client:
        client.cookies.set(SESSION_COOKIE, session_for(database, member))
        response = client.get(CALLBACK, follow_redirects=False)
        rules = client.get("/api/v1/rules").json()

    assert response.status_code == 303
    assert response.headers["location"] == (
        "/settings/connections?oauth=account_limit_reached&provider=google&limit=1"
    )
    assert _emails(_account_store(adapters), member) == ["first@example.test"]
    assert [(rule["id"], rule["state"]) for rule in rules] == [("member-rule", "enabled")]
    assert _account_store(adapters).for_user(member).get(account.id) == account


def test_reauthorizing_at_the_limit_resumes_the_rules_its_lapse_stopped(
    database: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    container, adapters = _installation(database)
    member, account = _member_at_the_limit(database, adapters)
    with adapters.unit_of_work(member)() as uow:
        stopped = uow.rules.get(SyncRuleId("member-rule"))
        assert stopped is not None
        uow.rules.save(stopped.degrade(awaiting_reauthorization=True))
        uow.accounts.lapse(account.id, attempted_at=datetime.now(UTC))
        uow.commit()
    _consent_returns(adapters, "first@example.test", monkeypatch)

    with TestClient(create_app(container)) as client:
        client.cookies.set(SESSION_COOKIE, session_for(database, member))
        response = client.get(CALLBACK, follow_redirects=False)
        rules = client.get("/api/v1/rules").json()

    assert response.status_code == 303
    assert response.headers["location"] == (
        "/settings/connections?oauth=connected&provider=google"
        f"&account={account.id.value}&resumed=1"
    )
    assert [(rule["id"], rule["state"]) for rule in rules] == [("member-rule", "enabled")]
```

Then append the connect race to `tests/adapters/test_plan_races.py` (Review Focus 3, connect part).
Task 8 created the file with `HeldAllowances`, `WAIT`, and most of the imports this needs. Add each
of these imports the file does not have yet (task 8 already imports `Path`, `Thread`,
`initialize_database`, `SqlitePlans`, `plans_on`, `limited_user`, and `PlanLimitReached`; add
`FREE` to its `from tests.plans import ...` line):

```python
from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.infrastructure.persistence.accounts import SqliteConnectedAccountStore
from calendar_sync.infrastructure.security import CredentialCipher
from tests.plans import FAMILY, FREE, plans_on
```

and append at the end of the file:

```python
# Connected Accounts


def test_two_connects_for_the_last_account_place_store_exactly_one(tmp_path: Path) -> None:
    """The account limit is read inside the save's BEGIN IMMEDIATE, so a second connect waits
    for the first to commit, then counts its account (Review Focus 3)."""
    database = tmp_path / "test.db"
    initialize_database(database)
    plans = SqlitePlans(database)
    plans_on(plans, FREE)
    member = limited_user(database)
    held = HeldAllowances(plans)
    store = SqliteConnectedAccountStore(
        database, CredentialCipher(CredentialCipher.generate_key()), allowances=held
    )
    outcomes: dict[str, str] = {}

    def connect(email: str) -> None:
        try:
            store.for_user(member).save("Synthetic", email, "{}", provider=ProviderKind.GOOGLE)
        except PlanLimitReached as refused:
            outcomes[email] = f"refused at {refused.limit}"
        else:
            outcomes[email] = "connected"

    first = Thread(target=connect, args=("first@example.test",))
    first.start()
    assert held.reading.wait(5)
    second = Thread(target=connect, args=("second@example.test",))
    second.start()
    second.join(WAIT)
    # The first connect holds the writer lock while it reads the limit, so the second waits.
    assert second.is_alive()
    held.released.set()
    first.join(5)
    second.join(5)

    assert outcomes == {
        "first@example.test": "connected",
        "second@example.test": "refused at 1",
    }
    assert [account.email for account in store.for_user(member).list()] == ["first@example.test"]
```

Then sort the imports: `.venv/bin/ruff check --fix tests/adapters/test_plan_races.py`.

- [ ] **Step 2: Run them to verify they fail**

```sh
.venv/bin/pytest tests/adapters/test_account_limit.py tests/adapters/test_plan_races.py -q
```

Expected: `tests/adapters/test_account_limit.py` fails to collect with
`ImportError: cannot import name 'AccountLimitReached' from 'calendar_sync.application.sync.errors'`;
`test_two_connects_for_the_last_account_place_store_exactly_one` fails with
`TypeError: SqliteConnectedAccountStore.__init__() got an unexpected keyword argument 'allowances'`.
Task 8's token races still pass.

- [ ] **Step 3: Implement the limit in the account store and in `connect_account`**

In `src/calendar_sync/application/sync/errors.py`, add right after `CalendarPermissionRequired`:

```python
class CalendarPermissionRequired(AuthorizationFailed):
    """An authorization was completed without the calendar permissions synchronization needs."""


class AccountLimitReached(AuthorizationFailed):
    """Connecting a new calendar account would pass the User's Plan's account limit (ADR 0038).

    The provider's consent is already given, because only then is the account's address known;
    nothing is stored, and the User's existing accounts and rules are unchanged.
    """

    def __init__(self, limit: int) -> None:
        super().__init__(f"the plan allows {limit} calendar accounts")
        self.limit = limit
        """How many calendar accounts the User's Plan allows."""


class AccountAccessCheckFailed(ApplicationError):
```

In `src/calendar_sync/infrastructure/persistence/accounts.py`, the import block becomes:

```python
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from calendar_sync.application.identity.errors import UserDisabled
from calendar_sync.application.shared.ports import Clock, IdGenerator
from calendar_sync.application.sync.errors import (
    ConnectedAccountDisconnected,
    ConnectedAccountNotFound,
)
from calendar_sync.application.sync.ports import Allowances
from calendar_sync.domain.access import UserId
from calendar_sync.domain.accounts import ConnectedAccount, ConnectedAccountState, ProviderKind
from calendar_sync.domain.model import ConnectedAccountId
from calendar_sync.domain.plans import LimitedResource, require_room
from calendar_sync.infrastructure.clock import SystemClock
from calendar_sync.infrastructure.identifiers import UuidIdGenerator
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.security import CredentialCipher
```

Replace the start of `SqliteConnectedAccountStore` (its docstring, `__init__`, and `for_user`; the
methods after `for_user` are unchanged):

```python
class SqliteConnectedAccountStore:
    """Connected Accounts with their provider credentials, encrypted by the Master Key.

    Provider adapters read and renew credentials by account; everything else about accounts goes
    through `for_user`, which sees only one User's (ADR 0029). Account identifiers are generated,
    so a provider adapter reached with one reads only that account's credentials. With
    `allowances`, connecting a new account stays within its User's Plan (ADR 0038); without, as
    in tests and the development preview, nobody is limited.
    """

    def __init__(
        self,
        database_path: Path,
        cipher: CredentialCipher,
        clock: Clock | None = None,
        ids: IdGenerator | None = None,
        allowances: Allowances | None = None,
    ) -> None:
        self._database_path = database_path
        self._cipher = cipher
        self._clock = clock or SystemClock()
        self._ids = ids or UuidIdGenerator()
        self._allowances = allowances

    def for_user(self, user_id: UserId) -> SqliteUserConnectedAccounts:
        return SqliteUserConnectedAccounts(
            self._database_path,
            user_id,
            self._cipher,
            self._clock,
            self._ids,
            allowances=self._allowances,
        )

    def provider_of(self, account_id: ConnectedAccountId) -> ProviderKind | None:
```

Replace `SqliteUserConnectedAccounts.__init__`:

```python
class SqliteUserConnectedAccounts:
    """One User's Connected Accounts; another User's are not found."""

    def __init__(
        self,
        database_path: Path,
        user_id: UserId,
        cipher: CredentialCipher,
        clock: Clock,
        ids: IdGenerator,
        allowances: Allowances | None = None,
    ) -> None:
        self._database_path = database_path
        self._owner = user_id
        self._user = user_id.value
        self._cipher = cipher
        self._clock = clock
        self._ids = ids
        self._allowances = allowances

    def list(self) -> tuple[ConnectedAccount, ...]:
```

Replace `save` in full, and add `_require_room_for` right after it (before `disconnect`):

```python
    def save(
        self,
        display_name: str,
        email: str,
        credential_json: str,
        *,
        provider: ProviderKind,
        avatar_url: str | None = None,
    ) -> ConnectedAccount:
        """Connect an account, or reauthorize this User's one with this provider and email.

        Reauthorizing clears Lapsed Authorization; resuming the rules it stopped is the
        application's to do (ADR 0027). A new account beyond the User's Plan's account limit
        raises PlanLimitReached and stores nothing; Reauthorization is never refused (ADR 0038).
        """
        # In UTC, so recording a lapse can compare it with a request's start as text.
        now = self._clock.now().astimezone(UTC).isoformat()
        account_id = self._ids.new()
        encrypted = self._cipher.encrypt(credential_json)
        with transaction(self._database_path) as connection:
            # Held from the checks to the save: a User disabled while the provider answered
            # connects nothing, and two connects never both take the last account place.
            connection.execute("BEGIN IMMEDIATE")
            active = connection.execute(
                "SELECT 1 FROM users WHERE id = ? AND state = 'active'", (self._user,)
            ).fetchone()
            if active is None:
                raise UserDisabled("this User can no longer connect accounts")
            self._require_room_for(connection, provider, email)
            connection.execute(
                """
                INSERT INTO connected_accounts (
                    id, user_id, provider, display_name, email, avatar_url,
                    encrypted_credentials, state, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'connected', ?, ?)
                ON CONFLICT(user_id, provider, email) DO UPDATE SET
                    display_name = excluded.display_name,
                    avatar_url = excluded.avatar_url,
                    encrypted_credentials = excluded.encrypted_credentials,
                    state = 'connected',
                    authorization_lapsed_at = NULL,
                    updated_at = excluded.updated_at
                """,
                (
                    account_id,
                    self._user,
                    provider.value,
                    display_name,
                    email,
                    avatar_url,
                    encrypted,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                f"SELECT {_ACCOUNT_COLUMNS} FROM connected_accounts "  # noqa: S608
                "WHERE user_id = ? AND provider = ? AND email = ?",
                (self._user, provider.value, email),
            ).fetchone()
        assert row is not None
        return _account_from_row(row)

    def _require_room_for(
        self, connection: sqlite3.Connection, provider: ProviderKind, email: str
    ) -> None:
        """Refuse a new account beyond the User's Plan's account limit, inside the save's lock.

        Only a new provider and email is counted against the limit: Reauthorization of an
        account this User has, Disconnected or not, never reads Plans. Disconnected Accounts
        count, because reconnecting one is Reauthorization. A raising read fails the save, so a
        fault never admits an account past the limit.
        """
        if self._allowances is None:
            return
        known = connection.execute(
            "SELECT 1 FROM connected_accounts WHERE user_id = ? AND provider = ? AND email = ?",
            (self._user, provider.value, email),
        ).fetchone()
        if known is not None:
            return
        limit = self._allowances.of(self._owner).limits.connected_accounts
        counted = connection.execute(
            "SELECT COUNT(*) FROM connected_accounts WHERE user_id = ?", (self._user,)
        ).fetchone()
        require_room(LimitedResource.CONNECTED_ACCOUNTS, int(counted[0]), limit)

    def disconnect(self, account_id: ConnectedAccountId) -> ConnectedAccount:
```

In `src/calendar_sync/infrastructure/oauth.py`, replace the application and domain imports:

```python
from calendar_sync.application.identity.errors import UserDisabled
from calendar_sync.application.sync.errors import (
    AccountLimitReached,
    AuthorizationFailed,
    InvalidAuthorizationState,
)
from calendar_sync.application.sync.ports import AuthorizedAccount
from calendar_sync.domain.access import UserId
from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.model import ConnectedAccountId
from calendar_sync.domain.plans import PlanLimitReached
from calendar_sync.infrastructure.persistence.accounts import SqliteConnectedAccountStore
```

and replace `connect_account` in full:

```python
def connect_account(
    accounts: SqliteConnectedAccountStore,
    owner: UserId,
    *,
    display_name: str,
    email: str,
    credentials: str,
    provider: ProviderKind,
    avatar_url: str | None = None,
) -> AuthorizedAccount:
    """Connect, or reauthorize, `owner`'s account; nothing when they were disabled meanwhile, or
    when a new account would pass their Plan's account limit (ADR 0038)."""
    try:
        account = accounts.for_user(owner).save(
            display_name, email, credentials, provider=provider, avatar_url=avatar_url
        )
    except UserDisabled as error:
        raise AuthorizationFailed("the User was disabled during authorization") from error
    except PlanLimitReached as error:
        raise AccountLimitReached(error.limit) from error
    return AuthorizedAccount(owner, account)
```

- [ ] **Step 4: Run the adapter tests to verify they pass, and the callback test still fails**

```sh
.venv/bin/pytest tests/adapters/test_account_limit.py tests/adapters/test_plan_races.py -q
```

Expected: everything passes except
`test_the_callback_reports_the_account_limit_and_connects_nothing`, which fails on the redirect:
the container's account store has no Allowances yet, so the callback connects
`renamed@example.test` and answers `oauth=connected`.

- [ ] **Step 5: Answer the refusal at the callback, and give the container's store its Plans**

In `src/calendar_sync/interfaces/api/routes/accounts.py`, change the `typing` import:

```python
from typing import Annotated, Literal, Protocol, get_args
```

add `AccountLimitReached` to the errors import:

```python
from calendar_sync.application.sync.errors import (
    AccountAccessCheckFailed,
    AccountLimitReached,
    AuthorizationFailed,
    AuthorizationNotConfigured,
    CalendarPermissionRequired,
    ConnectedAccountDisconnected,
    ConnectedAccountMustBeDisconnected,
    ConnectedAccountNotFound,
    InvalidAuthorizationState,
)
```

add the outcomes right after `REFUSED`:

```python
# OAuth errors that mean the person, or their organization, did not grant what was asked, rather
# than that the flow failed: RFC 6749 section 4.1.2.1 and OpenID Connect Core section 3.1.2.6.
REFUSED = frozenset({"access_denied", "consent_required"})
OAuthOutcome = Literal[
    "connected", "calendar_permission_required", "authorization_failed", "account_limit_reached"
]
"""How a provider's connection flow ended, as Settings reads it from `?oauth=`. The Web UI's
`OAuthOutcome` names the same values (`tests/adapters/test_oauth_outcomes.py`)."""
OAUTH_OUTCOMES: tuple[str, ...] = get_args(OAuthOutcome)
```

replace the code-exchange `try` block of `complete_oauth` (the rest of the function is unchanged;
`AccountLimitReached` is an `AuthorizationFailed`, so it must come before that handler):

```python
    try:
        authorized = authorization.complete(state, code, browser)
    except InvalidAuthorizationState as state_error:
        raise problem_from(status.HTTP_400_BAD_REQUEST, state_error) from state_error
    except CalendarPermissionRequired:
        return returned.outcome("calendar_permission_required")
    except AccountLimitReached as limited:
        # A new account at the Plan's limit: trying again cannot help, so Settings links to
        # Your plan, with the limit it names.
        return returned.outcome("account_limit_reached", limit=limited.limit)
    except AuthorizationFailed:
        return returned.outcome("authorization_failed")
    # The User who began the flow finished it; the account and its rules are theirs.
```

and type `_ReturnTo.outcome` with the Literal:

```python
class _ReturnTo:
    """Settings, told how a provider's connection flow ended."""

    def __init__(self, provider: str) -> None:
        self._provider = provider

    def outcome(self, outcome: OAuthOutcome, **details: str | int) -> RedirectResponse:
        query = urlencode({"oauth": outcome, "provider": self._provider, **details})
        return RedirectResponse(f"{CONNECTIONS}?{query}", status_code=303)
```

A raising Allowance read for a new address is not caught here: it fails the callback with 500, as
any database error does (open question 10; `docs/troubleshooting.md` says so in Step 11).

In `src/calendar_sync/bootstrap/container.py` `build_adapters`, replace the `accounts = (...)` block
(`plans` is the `SqlitePlans(database)` local task 4 made):

```python
    # Connecting a new account stays within its User's Plan (ADR 0038).
    accounts = (
        SqliteConnectedAccountStore(
            database, CredentialCipher(settings.master_key), clock, ids, allowances=plans
        )
        if settings.master_key
        else None
    )
    providers = calendar_providers(settings, accounts, clock)
```

- [ ] **Step 6: Run the tests and the backend gates**

```sh
.venv/bin/pytest tests/adapters/test_account_limit.py tests/adapters/test_plan_races.py -q
.venv/bin/pytest tests/adapters/test_api.py tests/adapters/google tests/adapters/microsoft tests/adapters/test_connected_account_providers.py tests/adapters/test_scheduling.py tests/adapters/test_api_authorization.py tests/adapters/test_api_problems.py tests/test_openapi_contract.py tests/test_architecture.py tests/test_dev_preview.py -q
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy
.venv/bin/lint-imports
```

Expected: all pass (`test_account_limit.py` 11 passed; the race file passes, task 8's races
included); every existing OAuth, provider, and scheduler test passes unchanged; the OpenAPI
contract is unchanged; Ruff, mypy ("Success: no issues found"), and lint-imports
("Contracts: 10 kept, 0 broken") are clean.

- [ ] **Step 7: Commit the server side**

```sh
git add src/calendar_sync/application/sync/errors.py src/calendar_sync/infrastructure/persistence/accounts.py src/calendar_sync/infrastructure/oauth.py src/calendar_sync/interfaces/api/routes/accounts.py src/calendar_sync/bootstrap/container.py tests/adapters/test_account_limit.py tests/adapters/test_plan_races.py
git commit -F - <<'EOF'
Refuse a new calendar account beyond its owner's plan, but never a reauthorization

Saving a new provider and address now reads the User's Allowance inside
the save's lock and stores nothing past their Plan's account limit, so two
connects never both take the last place. Disconnected Accounts count.
Reauthorization of an account the User has never reads Plans, so it always
works and still resumes the rules a lapse stopped. The OAuth callback
answers the refusal with the account_limit_reached outcome and the limit.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
```

- [ ] **Step 8: Write the failing outcome-parity and Web UI tests**

Create `tests/adapters/test_oauth_outcomes.py`:

```python
"""The OAuth callback reports only outcomes the Web UI names, and the Web UI names no other."""

import re
from pathlib import Path

from calendar_sync.interfaces.api.routes.accounts import OAUTH_OUTCOMES

OAUTH_REDIRECT = Path(__file__).resolve().parents[2] / "web" / "src" / "lib" / "oauth-redirect.ts"


def _web_outcomes() -> set[str]:
    """The values of the Web UI's `OAuthOutcome` union, from its declaration to the blank line
    that ends it."""
    source = OAUTH_REDIRECT.read_text()
    start = source.index("export type OAuthOutcome =")
    return set(re.findall(r'"([^"]+)"', source[start : source.index("\n\n", start)]))


def test_the_server_and_the_web_ui_name_the_same_oauth_outcomes() -> None:
    assert _web_outcomes() == set(OAUTH_OUTCOMES)
```

In `web/src/lib/oauth-redirect.test.ts`, replace the first and third `it` blocks of
`describe("oauthOutcome", ...)` and add a fourth (the second block, "ignores a missing or unknown
outcome", is unchanged):

```ts
  it("reads the outcome the OAuth callback adds to the Settings address", () => {
    expect(oauthOutcome("?oauth=connected&provider=google")).toBe("connected")
    expect(oauthOutcome("?oauth=calendar_permission_required")).toBe("calendar_permission_required")
    expect(oauthOutcome("?tab=x&oauth=authorization_failed")).toBe("authorization_failed")
    expect(oauthOutcome("?oauth=account_limit_reached&provider=google&limit=1")).toBe("account_limit_reached")
    expect(oauthProvider("?oauth=connected&provider=google")).toBe("google")
  })
```

```ts
  it("names each outcome in the catalog, with the provider it was for", () => {
    const { t } = testI18n()
    const names = { account: "Example account", provider: "Example" }
    expect(t(OAUTH_OUTCOME_MESSAGES.connected.title, names)).toBe("Example account connected")
    expect(t(OAUTH_OUTCOME_MESSAGES.calendar_permission_required.title, names)).toBe("Calendar access wasn’t granted")
    expect(t(OAUTH_OUTCOME_MESSAGES.authorization_failed.title, names)).toBe("Example authorization could not be completed")
    expect(t(OAUTH_OUTCOME_MESSAGES.account_limit_reached.title, names)).toBe("Your plan's calendar accounts are all in use")
  })

  it("names the plan's account limit, in the plural it needs", () => {
    const { t } = testI18n()
    const body = OAUTH_OUTCOME_MESSAGES.account_limit_reached.body
    expect(t(body, { count: 1 })).toBe(
      "No account was connected. Your plan allows 1 calendar account, and disconnected accounts count too. Delete one you no longer use, or ask your administrator for a larger plan.",
    )
    expect(t(body, { count: 3 })).toBe(
      "No account was connected. Your plan allows 3 calendar accounts, and disconnected accounts count too. Delete one you no longer use, or ask your administrator for a larger plan.",
    )
  })
```

In `web/src/lib/navigation.test.ts`, add `yourPlanPath` to the import:

```ts
import {
  SETTINGS_TABS,
  accountSearch,
  appLocationFromPathname,
  appLocationFromUrl,
  appPathForActivityTab,
  appPathForIncident,
  appPathForLocation,
  appPathForPeopleTab,
  appPathForPerson,
  appPathForRule,
  appPathForRulePreview,
  appPathForSettingsTab,
  appPathForView,
  connectionsPath,
  defaultSettingsTab,
  isKnownAppPath,
  isPlainLeftClick,
  isViewingRule,
  yourPlanPath,
} from "./navigation"
```

replace the arrival `it.each` in `describe("Settings tab URLs", ...)`:

```ts
  it.each([
    "?oauth=connected&provider=google&account=acct-a&resumed=0",
    "?oauth=authorization_failed",
    "?oauth=account_limit_reached&provider=google&limit=1",
    "?account=acct-a",
    "?resumed=2",
    "?limit=1",
  ])(
    "shows Connections when a provider returns or an account is named (%s)",
    (search) => {
      expect(defaultSettingsTab(search)).toBe("connections")
    },
  )
```

and add after `it("links calendar accounts to Connections", ...)`:

```ts
  it("links to Your plan on the Your account tab", () => {
    expect(yourPlanPath()).toBe("/settings/account#your-plan")
    expect(appLocationFromUrl("/settings/account", "")).toEqual({ view: "settings", ruleId: null, settingsTab: "account" })
  })
```

In `web/src/features/settings.test.tsx`, inside `describe("SettingsPage", ...)`, add right before
`it("keeps the English copy", ...)`:

```tsx
  it("says a new account met the plan's limit, and links to Your plan in place of Try again", async () => {
    window.history.replaceState(null, "", "/settings?oauth=account_limit_reached&provider=google&limit=1")
    await renderSettings(testI18n())

    const notice = container.querySelector(".oauth-feedback")!
    expect(notice.getAttribute("role")).toBe("alert")
    expect(notice.querySelector("h2")?.textContent).toBe("Your plan's calendar accounts are all in use")
    expect(notice.querySelector("p")?.textContent).toBe(
      "No account was connected. Your plan allows 1 calendar account, and disconnected accounts count too. Delete one you no longer use, or ask your administrator for a larger plan.",
    )
    const links = [...notice.querySelectorAll("a")].map((link) => [link.textContent, link.getAttribute("href")])
    expect(links).toEqual([["See your plan", "/settings/account#your-plan"]])
    // A reload does not announce the refusal again: every arrival parameter, `limit` too, is gone.
    expect(window.location.search).toBe("")
  })

  it("names a plan's limit of several calendar accounts", async () => {
    window.history.replaceState(null, "", "/settings?oauth=account_limit_reached&provider=google&limit=3")
    await renderSettings(testI18n())
    expect(container.querySelector(".oauth-feedback p")?.textContent).toContain("Your plan allows 3 calendar accounts,")
  })

  it("has no untranslated text when a new account met the plan's limit", async () => {
    window.history.replaceState(null, "", "/settings?oauth=account_limit_reached&provider=google&limit=2")
    await renderSettings(pseudoI18n())
    expect(container.querySelector(".oauth-feedback")).not.toBeNull()
    expect(untranslatedText(container, FIXTURE_TEXT)).toEqual([])
  })

  it("still offers to try again when authorization failed", async () => {
    window.history.replaceState(null, "", "/settings?oauth=authorization_failed&provider=google")
    await renderSettings(testI18n())
    const notice = container.querySelector(".oauth-feedback")!
    expect(notice.getAttribute("role")).toBe("alert")
    expect([...notice.querySelectorAll("a")].map((link) => link.textContent)).toEqual(["Try again"])
  })
```

- [ ] **Step 9: Run them to verify they fail**

```sh
.venv/bin/pytest tests/adapters/test_oauth_outcomes.py -q
cd web && pnpm exec vitest run src/lib/oauth-redirect.test.ts src/lib/navigation.test.ts src/features/settings.test.tsx; cd ..
```

Expected: the Python test fails with `Extra items in the right set: 'account_limit_reached'`.
Vitest: `oauthOutcome` answers `null` for `account_limit_reached`; `OAUTH_OUTCOME_MESSAGES.account_limit_reached`
is undefined (`TypeError: Cannot read properties of undefined (reading 'title')`); `yourPlanPath is
not a function`; the settings tests find no `.oauth-feedback` (`Cannot read properties of null`);
"still offers to try again when authorization failed" already passes.

- [ ] **Step 10: Implement the outcome in the Web UI**

In `web/src/lib/oauth-redirect.ts`, replace the `OAuthOutcome` type and `OAUTH_OUTCOME_MESSAGES`
(the blank line after the union ends what `tests/adapters/test_oauth_outcomes.py` reads):

```ts
/**
 * What the OAuth callback reports when it sends the browser back to Settings (`?oauth=`). The server
 * names the same values (`tests/adapters/test_oauth_outcomes.py` reads this union).
 */
export type OAuthOutcome =
  | "connected"
  | "calendar_permission_required"
  | "authorization_failed"
  | "account_limit_reached"

export const OAUTH_OUTCOME_MESSAGES: Record<OAuthOutcome, { title: MessageKey; body: MessageKey }> = {
  connected: { title: "settings.oauthOutcome.connected.title", body: "settings.oauthOutcome.connected.body" },
  calendar_permission_required: {
    title: "settings.oauthOutcome.calendarPermissionRequired.title",
    body: "settings.oauthOutcome.calendarPermissionRequired.body",
  },
  authorization_failed: {
    title: "settings.oauthOutcome.authorizationFailed.title",
    body: "settings.oauthOutcome.authorizationFailed.body",
  },
  account_limit_reached: {
    title: "settings.oauthOutcome.accountLimitReached.title",
    body: "settings.oauthOutcome.accountLimitReached.body",
  },
}
```

In `web/src/lib/navigation.ts`, replace `SETTINGS_ARRIVAL_PARAMS` and its comment:

```ts
/**
 * What a provider's return, or a link to one Connected Account, carries in the address; `limit` is
 * the plan's account limit a new account met.
 */
export const SETTINGS_ARRIVAL_PARAMS = ["oauth", "provider", "account", "resumed", "limit"] as const
```

and add right after `appPathForSettingsTab`:

```ts
export function appPathForSettingsTab(tab: SettingsTab): string {
  return `${APP_VIEW_PATHS.settings}/${tab}`
}

/** Settings → Your account, at Your plan: what the person's plan allows, and how much of it they have. */
export function yourPlanPath(): string {
  return `${appPathForSettingsTab("account")}#your-plan`
}
```

In `web/src/i18n/locales/en/settings.json`, inside `"oauthOutcome"`, add `accountLimitReached` between
`authorizationFailed` and `tryAgain`:

```json
    "authorizationFailed": {
      "title": "{provider} authorization could not be completed",
      "body": "The account was not connected. Try again, then use Check access to confirm permissions."
    },
    "accountLimitReached": {
      "title": "Your plan's calendar accounts are all in use",
      "body": {
        "one": "No account was connected. Your plan allows {count} calendar account, and disconnected accounts count too. Delete one you no longer use, or ask your administrator for a larger plan.",
        "other": "No account was connected. Your plan allows {count} calendar accounts, and disconnected accounts count too. Delete one you no longer use, or ask your administrator for a larger plan."
      }
    },
    "tryAgain": "Try again"
```

In `web/src/i18n/locales/en/common.json`, end the file with a new `plan` group (tasks 14 and 18
add `plan.accountLimit` and `plan.mayNotRestart` to it):

```json
  "learnWhy": "Learn why",
  "opensInNewTab": " (opens in a new tab)",
  "plan": {
    "seeYourPlan": "See your plan"
  }
}
```

In `web/src/features/settings.tsx`, add `yourPlanPath` to the navigation import:

```tsx
import {
  DEFAULT_SETTINGS_TAB,
  SETTINGS_ARRIVAL_PARAMS,
  type OpenSettingsTab,
  type SettingsTab,
  yourPlanPath,
} from "@/lib/navigation"
```

replace `SettingsArrival` and `useSettingsArrival`:

```tsx
type SettingsArrival = {
  outcome: OAuthOutcome | null
  /** The Provider Kind whose connection flow returned. */
  provider: string | null
  /** The account a provider returned with, or the one a stopped rule pointed to. */
  accountId: string | null
  /** Rules that resumed because the account was reauthorized. */
  resumed: number
  /** The plan's account limit a new account met, when it was refused. */
  limit: number
}

/** What brought the administrator here, read once; returning ends the authorization attempt. */
function useSettingsArrival(): SettingsArrival {
  const [arrival] = useState(() => {
    const params = new URLSearchParams(window.location.search)
    // Any outcome, even one this version cannot name, ends the attempt started here.
    if (params.get("oauth")) clearAuthorizationStart()
    return {
      outcome: oauthOutcome(window.location.search),
      provider: oauthProvider(window.location.search),
      accountId: params.get("account"),
      resumed: Number(params.get("resumed")) || 0,
      limit: Number(params.get("limit")) || 0,
    }
  })
  useEffect(() => {
    // A reload should not announce the same connection, or point at the same account, again.
    const url = new URL(window.location.href)
    if (!SETTINGS_ARRIVAL_PARAMS.some((name) => url.searchParams.has(name))) return
    for (const name of SETTINGS_ARRIVAL_PARAMS) url.searchParams.delete(name)
    window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}${url.hash}`)
  }, [])
  return arrival
}
```

replace `ConnectionsTab`:

```tsx
/** Calendar accounts, with what brought the User back from a provider above them, and Integrations. */
function ConnectionsTab({ providers, administrator }: { providers: CalendarProvider[]; administrator: boolean }) {
  const { outcome, provider, accountId, resumed, limit } = useSettingsArrival()
  const returnHelp = useOAuthReturn(providers)
  return (
    <>
      {outcome && (
        <OAuthOutcomeNotice outcome={outcome} provider={provider} resumed={resumed} limit={limit} providers={providers} />
      )}
      <AccountsSection
        providers={providers}
        justConnected={outcome === "connected"}
        focusAccountId={accountId}
        returnHelp={returnHelp}
      />
      <IntegrationsSection administrator={administrator} />
    </>
  )
}
```

and replace `OAuthOutcomeNotice` (to the end of the file) with the notice and its two parts, so each
stays within ESLint's complexity bound:

```tsx
/** Outcomes announced at once, because the person acts before connecting again. */
const ALERT_OUTCOMES: ReadonlySet<OAuthOutcome> = new Set<OAuthOutcome>(["authorization_failed", "account_limit_reached"])

/** The notice for the outcome the OAuth callback reported, with its one next step. */
function OAuthOutcomeNotice({
  outcome,
  provider,
  resumed,
  limit,
  providers,
}: {
  outcome: OAuthOutcome
  provider: string | null
  resumed: number
  limit: number
  providers: CalendarProvider[]
}) {
  const i18n = useI18n()
  const succeeded = outcome === "connected"
  const names = { account: accountNoun(i18n, provider, providers), provider: providerDisplayName(i18n, provider, providers) }
  return (
    <div
      className={cn("oauth-feedback", succeeded ? "oauth-feedback-success" : "oauth-feedback-warning")}
      role={ALERT_OUTCOMES.has(outcome) ? "alert" : "status"}
    >
      {succeeded ? <CheckCircle2 aria-hidden="true" /> : <ShieldAlert aria-hidden="true" />}
      <div>
        <h2>{i18n.t(OAUTH_OUTCOME_MESSAGES[outcome].title, names)}</h2>
        <OAuthOutcomeBody outcome={outcome} resumed={resumed} limit={limit} />
      </div>
      <OAuthOutcomeStep outcome={outcome} retry={providerOf(providers, provider)} />
    </div>
  )
}

/** What happened: how many rules a reauthorization restarted, or the plan's account limit. */
function OAuthOutcomeBody({ outcome, resumed, limit }: { outcome: OAuthOutcome; resumed: number; limit: number }) {
  const { t } = useI18n()
  const body = OAUTH_OUTCOME_MESSAGES[outcome].body
  if (outcome === "connected" && resumed > 0) return <p>{t("settings.oauthOutcome.connected.resumed", { count: resumed })}</p>
  return <p>{outcome === "account_limit_reached" ? t(body, { count: limit }) : t(body)}</p>
}

/**
 * The one next step after a failure: connecting again, or, at the plan's account limit, Your plan,
 * because connecting again would meet the same limit.
 */
function OAuthOutcomeStep({ outcome, retry }: { outcome: OAuthOutcome; retry: CalendarProvider | null }) {
  const { t } = useI18n()
  if (outcome === "account_limit_reached") {
    return (
      <Button variant="outline" asChild>
        <a href={yourPlanPath()}>{t("common.plan.seeYourPlan")}</a>
      </Button>
    )
  }
  if (outcome === "connected" || !retry) return null
  return (
    <Button variant="outline" asChild>
      <a {...connectLink(retry)}>{t("settings.oauthOutcome.tryAgain")}</a>
    </Button>
  )
}
```

"See your plan" is a full navigation to `/settings/account#your-plan`; task 17's `OwnPlanSection`
scrolls itself into view on that fragment.

- [ ] **Step 11: Document the account limit in troubleshooting**

In `docs/troubleshooting.md`, insert this section right before `## Microsoft sign-in stops with an
error` (after `## Calendar permission was not granted`):

```markdown
## Connect is unavailable: your plan's calendar accounts

When an administrator has turned Plans on, your Plan may limit how many calendar accounts you
have. Every account under **Settings → Connections → Connected accounts** counts, Disconnected
Accounts too: connecting one of them again is Reauthorization, which a Plan never refuses. At the
limit, **Connect an account** is unavailable and says why, while **Reauthorize account** stays
available on every account you have. **Settings → Your account → Your plan** shows how many
calendar accounts your Plan allows. Installation Administrators are never limited.

Calendar Ghost learns an account's address only after the provider's consent. So when you choose
an address you have not connected, and your Plan has no room for it, you return to Connections
with "Your plan's calendar accounts are all in use". No account was saved, and your existing
accounts and rules are unchanged. The provider may keep the consent you gave; you can remove
Calendar Ghost from your Google or Microsoft account's security settings.

To make room, delete an account you no longer use ([A calendar account was
disconnected](#a-calendar-account-was-disconnected) explains what deleting removes), or ask your
administrator for a larger Plan.

If connecting a new account ends on an error page instead of Connections while Plans are on,
Calendar Ghost could not read your Plan, for example because its database was busy. No account was
saved; connect again. Reauthorizing an account you already have never reads your Plan.

### An account's address changed

Calendar Ghost knows each account by its provider and email address. When the address of a
Microsoft or Google Workspace account changes, for example after a rename, the provider reports
the new address, so reauthorizing connects a new account and the old one stays. At the limit, the
new address is refused. To move every rule to the new address without losing one:

1. Free one account place: delete an account you no longer use, or ask your administrator to raise
   your Plan's account limit, or give you a larger Plan, for the move.
2. Connect the new address.
3. On each rule that uses the old account, choose **Replace calendars…** and choose the same
   calendar under the new address. Where the old account holds the rule's destination, keep its
   events as ordinary events: the old account may no longer be able to delete them.
4. Disconnect the old account, then delete it.

Delete the old account only after every rule has moved: deleting an account deletes the rules that
use it.
```

- [ ] **Step 12: Run the tests, the Web UI gates, and rebuild the static bundle**

```sh
.venv/bin/pytest tests/adapters/test_oauth_outcomes.py tests/adapters/test_account_limit.py tests/test_no_em_dashes.py tests/test_ubiquitous_language.py tests/test_troubleshooting_anchors.py tests/test_openapi_contract.py -q
.venv/bin/ruff format --check .
.venv/bin/ruff check .
cd web
pnpm run typecheck
pnpm run lint
pnpm exec vitest run src/lib/oauth-redirect.test.ts src/lib/navigation.test.ts src/features/settings.test.tsx src/i18n/catalog.test.ts
pnpm run test
pnpm run knip
pnpm run doctor
pnpm run build
cd ..
```

Expected: every Python test passes (the outcome test now matches four values on both sides); the
typecheck, ESLint (`--max-warnings 0`), knip, and React Doctor ("No issues found") are clean; the
four Vitest files pass and so does the whole suite (no fixture needs a new route: the notice reads
only the address); `pnpm run build` rewrites `src/calendar_sync/interfaces/api/static/`.

- [ ] **Step 13: Commit the Web UI and the guide**

```sh
git add tests/adapters/test_oauth_outcomes.py web/src/lib/oauth-redirect.ts web/src/lib/oauth-redirect.test.ts web/src/lib/navigation.ts web/src/lib/navigation.test.ts web/src/features/settings.tsx web/src/features/settings.test.tsx web/src/i18n/locales/en/settings.json web/src/i18n/locales/en/common.json docs/troubleshooting.md
git add -A src/calendar_sync/interfaces/api/static
git commit -F - <<'EOF'
Say when a plan has no room for another calendar account, and link to Your plan

Settings now explains the account_limit_reached outcome with the plan's
limit, and offers See your plan in place of Try again, which would meet the
same limit. A reload no longer repeats it. A test keeps the server's OAuth
outcomes and the Web UI's in step. The troubleshooting guide explains the
limit, the error page a failed Plans read leaves, and how to move every rule
to an account whose address changed.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 12: ShowOwnPlan and the Operator Overview Plan

`ShowOwnPlan` reads the signed-in User's Allowance beside what counts toward each of its limits,
for Your plan (task 13 serves it at `GET /api/v1/account/plan`, task 17 shows it). A raising
Allowance read fails it (open question 14). The Operator Overview reads every shown person's
Allowance in one `of_users` read once any Plan exists, Plans on or off, and shows none, with a
warning that names only the error's class, when Plans cannot be read, so People and the person page
never fail on a Plans fault. Contract section 3.13; Review Focus 2 (Your plan part).

No schema or route changes here (task 13 adds them), so OpenAPI is not regenerated.

**Files:**
- Create: `src/calendar_sync/application/operations/own_plan.py`
- Modify: `src/calendar_sync/application/operations/operator_overview.py` (imports; `logger`; `UserOverview.allowance`; `OperatorOverview` fields `allowances`, `plans`; `_overviews`; new private `_allowances`)
- Modify: `src/calendar_sync/bootstrap/container.py` (import; `UserServices.show_own_plan`; `_compose_user`; the `OperatorOverview(...)` call in `compose`)
- Modify: `scripts/dev_preview.py` (the `OperatorOverview(...)` call in `build_preview_container`)
- Test: `tests/application/test_own_plan.py` (new)
- Test: `tests/application/test_operator_overview.py` (imports; `_installation`; new tests at the end)

**Interfaces:**
- Consumes (task 1): `Allowance` (`basis`, `plan`, `on_default`, `assigned`, `limits`), `AllowanceBasis`, `AssignmentSource`, `Plan`, `PlanKey`, `PlanLimits`, `SyncInterval`, `has_room(in_use, limit) -> bool`, `exceeds(in_use, limit) -> bool`.
- Consumes (task 2): `SyncRule.keeps_place`, `SyncRule.counts_toward_plan`.
- Consumes (task 4): `Allowances` (`of`, `of_users`); `PlanCatalog.any_plans()`, `PlanCatalog.change_settings(enabled, default)`; `AssignmentChange(source, actor, at)`; `PlanAssignments.assign(user, plan, change)`; `Adapters.allowances`, `Adapters.plan_catalog`; `MemoryPlans(users=MemoryUsers)` and `BrokenAllowances` (`tests.identity_fakes`); `FREE`, `FAMILY`, `plans_on` (`tests.plans`).
- Consumes (task 8): `IntegrationTokens.issue(..., *, within=None)` (the test fake matches it); `UserServices.issue_integration_token` and the `_compose_user` local `tokens = adapters.integration_tokens(user_id)`.
- Produces:
  - `calendar_sync.application.operations.own_plan.OwnPlan(allowance: Allowance, rules_counted: int, connected_accounts: int, integration_tokens: int)` with properties `may_connect_account`, `may_issue_token`, `over_rule_limit`.
  - `ShowOwnPlan(allowances: Allowances, unit_of_work: UnitOfWorkFactory, accounts: ConnectedAccountRepository | None, tokens: IntegrationTokens, owner: UserId)` with `execute() -> OwnPlan`; raises whatever a raising Allowance read raises.
  - `UserOverview.allowance: Allowance | None = None` (trailing field).
  - `OperatorOverview(users, statuses, installation, clock, allowances: Allowances, plans: PlanCatalog)`.
  - `UserServices.show_own_plan: ShowOwnPlan`.

- [ ] **Step 1: Write the failing ShowOwnPlan tests**

Create `tests/application/test_own_plan.py`:

```python
"""Your plan: what the signed-in User's Plan allows them, and how much of it they have."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import pytest

from calendar_sync.application.identity.ports import (
    AssignmentChange,
    IntegrationTokenScope,
    IntegrationTokenSummary,
    IssuedIntegrationToken,
)
from calendar_sync.application.operations.own_plan import OwnPlan, ShowOwnPlan
from calendar_sync.domain.access import Role, User, UserId, UserState
from calendar_sync.domain.accounts import ConnectedAccount, ConnectedAccountState, ProviderKind
from calendar_sync.domain.model import ConnectedAccountId, SyncRule, SyncRuleId, SyncRuleState
from calendar_sync.domain.plans import (
    Allowance,
    AllowanceBasis,
    AssignmentSource,
    Plan,
    PlanKey,
    PlanLimits,
    SyncInterval,
)
from tests.application.test_accounts import RecordingAccounts
from tests.helpers import NOW, endpoint
from tests.identity_fakes import BrokenAllowances, MemoryPlans
from tests.plans import FAMILY, FREE, plans_on
from tests.users import memory_units

ADMIN = User(
    UserId("admin"), "admin@example.test", Role.INSTALLATION_ADMINISTRATOR, UserState.ACTIVE, NOW
)
ALICE = User(UserId("alice"), "alice@example.test", Role.USER, UserState.ACTIVE, NOW)


@dataclass
class ListedTokens:
    """One User's Integration Tokens, as Your plan lists them; it never issues or revokes one."""

    tokens: list[IntegrationTokenSummary] = field(default_factory=list)

    def issue(
        self,
        name: str,
        scopes: frozenset[IntegrationTokenScope] = frozenset({IntegrationTokenScope.STATUS_READ}),
        *,
        within: Callable[[], int | None] | None = None,
    ) -> IssuedIntegrationToken:
        raise AssertionError("Your plan never issues a token")

    def list(self) -> Sequence[IntegrationTokenSummary]:
        return self.tokens

    def revoke(self, token_id: str) -> bool:
        raise AssertionError("Your plan never revokes a token")


def _rule(
    name: str, state: SyncRuleState, *, lapsed: bool = False, keeps_place: bool = False
) -> SyncRule:
    return SyncRule(
        SyncRuleId(name),
        endpoint("personal-account", f"{name}-source"),
        endpoint("work-account", f"{name}-destination"),
        state=state,
        awaiting_reauthorization=lapsed,
        keeps_place=keeps_place,
    )


COUNTED = (
    _rule("enabled", SyncRuleState.ENABLED),
    _rule("lapse-stopped", SyncRuleState.DEGRADED, lapsed=True),
    _rule("replacement", SyncRuleState.DRAFT, keeps_place=True),
    _rule("previewed-replacement", SyncRuleState.PREVIEWED, keeps_place=True),
)
NOT_COUNTED = (
    _rule("draft", SyncRuleState.DRAFT),
    _rule("previewed", SyncRuleState.PREVIEWED),
    _rule("paused", SyncRuleState.PAUSED),
    _rule("stopped", SyncRuleState.DEGRADED),
    _rule("removing", SyncRuleState.REMOVING),
)


def _account(
    account_id: str, state: ConnectedAccountState = ConnectedAccountState.CONNECTED
) -> ConnectedAccount:
    return ConnectedAccount(
        ConnectedAccountId(account_id),
        account_id,
        f"{account_id}@example.test",
        state,
        provider=ProviderKind.GOOGLE,
    )


def _token(token_id: str, *, revoked: bool = False) -> IntegrationTokenSummary:
    return IntegrationTokenSummary(
        token_id,
        token_id,
        frozenset({IntegrationTokenScope.STATUS_READ}),
        NOW,
        None,
        NOW if revoked else None,
        owner=ALICE.id,
    )


def _plans(*, on: bool = True) -> MemoryPlans:
    """An administrator and Alice; with `on`, Plans are on, Free is the default, Family exists."""
    plans = MemoryPlans()
    plans.users.add(ADMIN, "hash")
    plans.users.add(ALICE, "hash")
    if on:
        plans_on(plans, FREE, FAMILY)
    return plans


def _show(
    plans: MemoryPlans,
    user: User = ALICE,
    *,
    rules: Sequence[SyncRule] = (),
    accounts: Sequence[ConnectedAccount] = (),
    tokens: Sequence[IntegrationTokenSummary] = (),
) -> ShowOwnPlan:
    units = memory_units(user=user.id)
    with units() as uow:
        for rule in rules:
            uow.rules.add(rule)
        uow.commit()
    return ShowOwnPlan(
        plans, units, RecordingAccounts(*accounts), ListedTokens(list(tokens)), user.id
    )


def test_only_rules_that_count_toward_the_plan_are_counted() -> None:
    own = _show(_plans(), rules=COUNTED + NOT_COUNTED).execute()

    assert own.rules_counted == len(COUNTED)


def test_disconnected_accounts_count_and_revoked_tokens_do_not() -> None:
    accounts = (_account("home"), _account("old", ConnectedAccountState.DISCONNECTED))
    tokens = (_token("monitor"), _token("retired", revoked=True))

    own = _show(_plans(), accounts=accounts, tokens=tokens).execute()

    assert (own.connected_accounts, own.integration_tokens) == (2, 1)


def test_without_the_master_key_no_account_counts() -> None:
    show = ShowOwnPlan(_plans(), memory_units(user=ALICE.id), None, ListedTokens(), ALICE.id)

    assert show.execute().connected_accounts == 0


def test_a_member_without_a_plan_of_their_own_has_the_default() -> None:
    own = _show(_plans()).execute()

    assert own.allowance == Allowance(AllowanceBasis.PLAN, plan=FREE, on_default=True)


def test_a_member_with_their_own_plan_has_it() -> None:
    plans = _plans()
    plans.assign(
        ALICE.id, FAMILY.key, AssignmentChange(AssignmentSource.ADMINISTRATOR, ADMIN.id, NOW)
    )

    own = _show(plans).execute()

    assert own.allowance == Allowance(AllowanceBasis.PLAN, plan=FAMILY, assigned=FAMILY)


SMALL = Plan(PlanKey("small"), "Small", PlanLimits(2, 2, 2, SyncInterval.INSTANT))


@pytest.mark.parametrize(
    ("used", "room", "over"),
    [(1, True, False), (2, False, False), (3, False, True)],
    ids=["below", "at", "above"],
)
def test_each_limit_has_room_only_below_it_and_is_passed_only_above_it(
    used: int, room: bool, over: bool
) -> None:
    own = OwnPlan(Allowance(AllowanceBasis.PLAN, plan=SMALL, assigned=SMALL), used, used, used)

    assert (own.may_connect_account, own.may_issue_token, own.over_rule_limit) == (
        room,
        room,
        over,
    )


def test_a_plan_without_tokens_has_no_room_for_the_first() -> None:
    own = OwnPlan(Allowance(AllowanceBasis.PLAN, plan=FREE, on_default=True), 0, 0, 0)

    assert (own.may_connect_account, own.may_issue_token) == (True, False)


def test_unlimited_values_always_have_room() -> None:
    unlimited = Plan(
        PlanKey("unlimited"), "Unlimited", PlanLimits(None, None, None, SyncInterval.INSTANT)
    )

    own = OwnPlan(Allowance(AllowanceBasis.PLAN, plan=unlimited), 500, 500, 500)

    assert (own.may_connect_account, own.may_issue_token, own.over_rule_limit) == (
        True,
        True,
        False,
    )


def test_an_administrator_is_never_limited() -> None:
    accounts = (_account("one"), _account("two"))

    own = _show(_plans(), ADMIN, rules=COUNTED, accounts=accounts, tokens=(_token("t"),)).execute()

    assert own.allowance.basis is AllowanceBasis.ADMINISTRATOR
    assert (own.may_connect_account, own.may_issue_token, own.over_rule_limit) == (
        True,
        True,
        False,
    )


def test_with_plans_off_nobody_is_limited() -> None:
    own = _show(
        _plans(on=False), rules=COUNTED, accounts=(_account("one"), _account("two"))
    ).execute()

    assert own.allowance.basis is AllowanceBasis.PLANS_OFF
    assert (own.may_connect_account, own.may_issue_token, own.over_rule_limit) == (
        True,
        True,
        False,
    )


def test_an_administrator_demoted_over_the_limit_is_limited_until_promoted_again() -> None:
    plans = _plans()
    plans.users.set_role(ALICE.id, Role.INSTALLATION_ADMINISTRATOR)
    show = _show(
        plans,
        rules=COUNTED,
        accounts=(_account("one"), _account("two")),
        tokens=(_token("monitor"),),
    )
    assert show.execute().allowance.basis is AllowanceBasis.ADMINISTRATOR

    plans.users.set_role(ALICE.id, Role.USER)
    demoted = show.execute()

    # Free allows one rule, one account, and no tokens: Your plan shows the over-limit line,
    # and Connect and issuing a token are unavailable. Nothing she has stops.
    assert demoted.allowance == Allowance(AllowanceBasis.PLAN, plan=FREE, on_default=True)
    assert (demoted.over_rule_limit, demoted.may_connect_account, demoted.may_issue_token) == (
        True,
        False,
        False,
    )
    plans.users.set_role(ALICE.id, Role.INSTALLATION_ADMINISTRATOR)
    promoted = show.execute()
    assert promoted.allowance.basis is AllowanceBasis.ADMINISTRATOR
    assert (promoted.over_rule_limit, promoted.may_connect_account, promoted.may_issue_token) == (
        False,
        True,
        True,
    )


def test_a_plans_fault_fails_your_plan() -> None:
    show = ShowOwnPlan(
        BrokenAllowances(), memory_units(user=ALICE.id), None, ListedTokens(), ALICE.id
    )

    # Never a made-up Allowance: the Web UI reads the failure as no hints, and the server
    # still checks every limit.
    with pytest.raises(RuntimeError, match="database is locked"):
        show.execute()
```

- [ ] **Step 2: Run it to verify it fails**

```sh
.venv/bin/pytest tests/application/test_own_plan.py -q
```

Expected: collection fails with
`ModuleNotFoundError: No module named 'calendar_sync.application.operations.own_plan'`.

- [ ] **Step 3: Implement `OwnPlan` and `ShowOwnPlan`**

Create `src/calendar_sync/application/operations/own_plan.py`:

```python
"""Your plan: what the signed-in User's Plan allows them, and how much of it they have (ADR 0038).

A read model across sync, which counts rules and accounts, and identity, which counts tokens. The
limits themselves are checked where each resource is added, inside its own transaction; this only
shows them, and lets the Web UI disable Connect and issuing a token before the server refuses.
"""

from __future__ import annotations

from dataclasses import dataclass

from calendar_sync.application.identity.ports import IntegrationTokens
from calendar_sync.application.sync.ports import (
    Allowances,
    ConnectedAccountRepository,
    UnitOfWorkFactory,
)
from calendar_sync.domain.access import UserId
from calendar_sync.domain.plans import Allowance, exceeds, has_room


@dataclass(frozen=True, slots=True)
class OwnPlan:
    """A User's Allowance beside what counts toward each of its limits."""

    allowance: Allowance
    rules_counted: int
    """Rules that count toward the rule limit: enabled, stopped only by Lapsed Authorization, or
    a Rule Replacement draft that keeps its place."""
    connected_accounts: int
    """Every Connected Account, Disconnected Accounts included."""
    integration_tokens: int
    """Integration Tokens not revoked."""

    @property
    def may_connect_account(self) -> bool:
        """Whether a new calendar account fits; Reauthorization always does."""
        return has_room(self.connected_accounts, self.allowance.limits.connected_accounts)

    @property
    def may_issue_token(self) -> bool:
        return has_room(self.integration_tokens, self.allowance.limits.integration_tokens)

    @property
    def over_rule_limit(self) -> bool:
        """Whether more rules count than the Plan allows, after the limit was lowered: nothing
        stops, but no rule may start until fewer count."""
        return exceeds(self.rules_counted, self.allowance.limits.rules)


@dataclass(slots=True)
class ShowOwnPlan:
    """What the signed-in User's Plan allows and how much of it they have, for Your plan."""

    allowances: Allowances
    unit_of_work: UnitOfWorkFactory
    accounts: ConnectedAccountRepository | None
    """None without the Installation Master Key, where no account is stored: none count."""
    tokens: IntegrationTokens
    owner: UserId

    def execute(self) -> OwnPlan:
        """Raises when the Allowance cannot be read: an Allowance made up here would show a
        Plan that is not theirs, and the Web UI reads a failure as no hints (ADR 0038)."""
        allowance = self.allowances.of(self.owner)
        with self.unit_of_work() as uow:
            rules = sum(1 for rule in uow.rules.list() if rule.counts_toward_plan)
        accounts = len(self.accounts.list()) if self.accounts is not None else 0
        tokens = sum(1 for token in self.tokens.list() if token.revoked_at is None)
        return OwnPlan(allowance, rules, accounts, tokens)
```

- [ ] **Step 4: Run it to verify it passes**

```sh
.venv/bin/pytest tests/application/test_own_plan.py -q
```

Expected: 14 passed.

- [ ] **Step 5: Write the failing Operator Overview tests**

In `tests/application/test_operator_overview.py`, replace the imports (the module already names a
calendar endpoint `FAMILY`, so the Plan is imported as `FAMILY_PLAN`):

```python
"""The Operator Overview shows each User's Installation Status with calendars by neutral labels."""

import logging
from collections.abc import Collection, Mapping
from dataclasses import replace
from datetime import date, datetime, timedelta

import pytest

from calendar_sync.application.identity.administration import AdministratorRequired, UserNotFound
from calendar_sync.application.identity.ports import AssignmentChange, UserQuery
from calendar_sync.application.operations.operator_overview import (
    OperatorOverview,
    OverviewQuery,
    UserStatuses,
    calendar_labels,
)
from calendar_sync.application.operations.ports import (
    InstallationUnitOfWork,
    InstallationUnitOfWorkFactory,
    ProviderCallUse,
    ResourceUse,
)
from calendar_sync.application.operations.status import StatusVerdict
from calendar_sync.application.sync.locking import RuleLocks
from calendar_sync.application.sync.ports import (
    Allowances,
    CalendarAccess,
    DiscoveredCalendar,
    ProviderCallCounts,
)
from calendar_sync.domain.access import Role, User, UserId, UserState
from calendar_sync.domain.accounts import ConnectedAccountState, ProviderKind
from calendar_sync.domain.model import ConnectedAccountId, SyncRuleId, SyncRuleState
from calendar_sync.domain.plans import Allowance, AllowanceBasis, AssignmentSource
from calendar_sync.domain.runs import RuleRunOutcome, RunKind
from calendar_sync.infrastructure.persistence.memory import InMemoryUnitOfWorkFactory
from tests.helpers import NOW, RecentSchedulerHeartbeat, endpoint, rule
from tests.identity_fakes import BrokenAllowances, MemoryPlans, MemoryUsers
from tests.plans import FAMILY as FAMILY_PLAN
from tests.plans import FREE, plans_on
from tests.users import OTHER_USER, USER, memory_units, rule_accounts
```

replace the end of `_installation` (from `clock = FixedClock()`):

```python
    clock = FixedClock()
    plans = MemoryPlans(users=users)
    return OperatorOverview(
        users,
        UserStatuses(units.installation(), RuleLocks(), clock, RecentSchedulerHeartbeat(clock)),
        units.installation(),
        clock,
        plans,
        plans,
    )
```

and append at the end of the file:

```python
def _plans(overview: OperatorOverview) -> MemoryPlans:
    """The installation's Plans, which `_installation` keeps in memory."""
    assert isinstance(overview.plans, MemoryPlans)
    return overview.plans


def _allowances(overview: OperatorOverview) -> dict[UserId, Allowance | None]:
    page = overview.page(ADMIN.id, OverviewQuery())
    return {entry.user.id: entry.allowance for entry in page.users}


def _bob_on_family(overview: OperatorOverview) -> None:
    """Free is the default, and Bob has Family as his own Plan."""
    plans = _plans(overview)
    plans_on(plans, FREE, FAMILY_PLAN)
    plans.assign(
        BOB.id, FAMILY_PLAN.key, AssignmentChange(AssignmentSource.ADMINISTRATOR, ADMIN.id, NOW)
    )


def test_no_plan_shows_while_no_plan_exists() -> None:
    overview = _installation()
    # Nothing reads Allowances while no Plan exists, so not even a failing read is noticed.
    overview.allowances = BrokenAllowances()

    assert _allowances(overview) == {ADMIN.id: None, ALICE.id: None, BOB.id: None}
    assert overview.of(ADMIN.id, ALICE.id).allowance is None


def test_every_person_shows_what_their_plan_allows_once_plans_are_on() -> None:
    overview = _installation()
    _bob_on_family(overview)

    assert _allowances(overview) == {
        ADMIN.id: Allowance(AllowanceBasis.ADMINISTRATOR),
        ALICE.id: Allowance(AllowanceBasis.PLAN, plan=FREE, on_default=True),
        BOB.id: Allowance(AllowanceBasis.PLAN, plan=FAMILY_PLAN, assigned=FAMILY_PLAN),
    }
    assert overview.of(ADMIN.id, BOB.id).allowance == Allowance(
        AllowanceBasis.PLAN, plan=FAMILY_PLAN, assigned=FAMILY_PLAN
    )


def test_every_person_shows_their_own_plan_while_plans_are_off() -> None:
    """An administrator can prepare Plans before turning them on."""
    overview = _installation()
    _bob_on_family(overview)
    _plans(overview).change_settings(False, FREE.key)

    assert _allowances(overview) == {
        ADMIN.id: Allowance(AllowanceBasis.PLANS_OFF),
        ALICE.id: Allowance(AllowanceBasis.PLANS_OFF),
        BOB.id: Allowance(AllowanceBasis.PLANS_OFF, assigned=FAMILY_PLAN),
    }


class CountedAllowances:
    """The installation's Allowances, recording each read."""

    def __init__(self, inner: Allowances) -> None:
        self.inner = inner
        self.read: list[list[UserId]] = []

    def of(self, user: UserId) -> Allowance:
        raise AssertionError("the overview reads a page of Users at once")

    def of_users(self, users: Collection[UserId]) -> Mapping[UserId, Allowance]:
        self.read.append(list(users))
        return self.inner.of_users(users)


def test_a_page_reads_its_peoples_allowances_at_once() -> None:
    overview = _installation()
    _bob_on_family(overview)
    counted = CountedAllowances(overview.allowances)
    overview.allowances = counted

    overview.page(ADMIN.id, OverviewQuery(UserQuery(limit=2)))

    assert counted.read == [[ADMIN.id, ALICE.id]]


class UnreadablePlans(MemoryPlans):
    """Plans whose catalog cannot be read, as a locked or failing database would."""

    def any_plans(self) -> bool:
        raise RuntimeError("database is locked")


@pytest.mark.parametrize("fault", ["allowances", "catalog"])
def test_a_plans_fault_shows_no_plan_and_never_fails_people(
    fault: str, caplog: pytest.LogCaptureFixture
) -> None:
    overview = _installation()
    _bob_on_family(overview)
    if fault == "allowances":
        overview.allowances = BrokenAllowances()
    else:
        overview.plans = UnreadablePlans(users=_plans(overview).users)

    with caplog.at_level(logging.WARNING):
        shown = _allowances(overview)
        person = overview.of(ADMIN.id, BOB.id)

    assert shown == {ADMIN.id: None, ALICE.id: None, BOB.id: None}
    assert (person.user.id, person.allowance) == (BOB.id, None)
    assert "could not read Plans" in caplog.text
    # Only the error's class: its text could say more than the overview may log.
    assert "RuntimeError" in caplog.text
    assert "database is locked" not in caplog.text
```

- [ ] **Step 6: Run them to verify they fail**

```sh
.venv/bin/pytest tests/application/test_operator_overview.py -q
```

Expected: every test that builds `_installation()` fails with
`TypeError: OperatorOverview.__init__() takes 5 positional arguments but 7 were given`; the three
`UserStatuses` and `calendar_labels` tests still pass.

- [ ] **Step 7: Implement the Plan in the Operator Overview, and compose both**

In `src/calendar_sync/application/operations/operator_overview.py`, replace the imports and the
lines before `CALENDAR_LABEL`:

```python
from __future__ import annotations

import logging
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime

from calendar_sync.application.identity.administration import (
    AdministratorRequired,
    UserNotFound,
    require_administrator,
)
from calendar_sync.application.identity.ports import PlanCatalog, UserDirectory, UserQuery
from calendar_sync.application.operations.ports import (
    InstallationUnitOfWorkFactory,
    ResourceUse,
    SchedulerHeartbeat,
    SchedulerProgress,
    StatusRecords,
)
from calendar_sync.application.operations.status import (
    InstallationStatus,
    StatusVerdict,
    assess_installation,
)
from calendar_sync.application.shared.ports import Clock
from calendar_sync.application.sync.locking import RuleLocks
from calendar_sync.application.sync.ports import Allowances
from calendar_sync.application.sync.resource_use import first_counted_day
from calendar_sync.application.sync.rules import SyncRuleSummary
from calendar_sync.domain.access import User, UserId
from calendar_sync.domain.model import CalendarEndpoint, SyncRule
from calendar_sync.domain.plans import Allowance

logger = logging.getLogger(__name__)

CALENDAR_LABEL = "Calendar {number}"
```

replace `UserOverview`:

```python
@dataclass(frozen=True, slots=True)
class UserOverview:
    """What the Operator Overview shows about one User, to an administrator and to that User."""

    user: User
    status: InstallationStatus
    resources: ResourceUse
    calls_since: date
    """The first UTC day the provider calls in `resources` count."""
    allowance: Allowance | None = None
    """What their Plan allows them now, and their own Plan; None while no Plan exists, or when
    Plans cannot be read (ADR 0038)."""
```

add the two fields to `OperatorOverview` (its `page`, `of`, and `_overview` are unchanged):

```python
@dataclass(slots=True)
class OperatorOverview:
    """The Installation Administrator's view of every User's health: the list under People and
    each person's page. Both come from `_overviews`, so they cannot differ."""

    users: UserDirectory
    statuses: UserStatuses
    installation: InstallationUnitOfWorkFactory
    clock: Clock
    allowances: Allowances
    plans: PlanCatalog
```

and replace `_overviews`, adding `_allowances` after it (the end of the class and the file). The
block opens with the class line only to place the two methods; the fields above stay as just shown,
and `page`, `of`, and `_overview` stay as they are:

```python
class OperatorOverview:
    def _overviews(
        self, users: Sequence[User], statuses: Mapping[UserId, InstallationStatus] | None = None
    ) -> tuple[UserOverview, ...]:
        """What the overview shows about each of `users`, with the statuses already read."""
        ids = [user.id for user in users]
        since = first_counted_day(self.clock.now().astimezone(UTC).date())
        statuses = statuses if statuses is not None else self.statuses.of(ids)
        with self.installation() as installation:
            resources = installation.resource_use(ids, since)
        allowances = self._allowances(ids)
        return tuple(
            UserOverview(
                user, statuses[user.id], resources[user.id], since, allowances.get(user.id)
            )
            for user in users
        )

    def _allowances(self, users: Collection[UserId]) -> Mapping[UserId, Allowance]:
        """Each User's Allowance in one read, once any Plan exists. None while no Plan exists,
        and none when Plans cannot be read: a Plans fault never fails People or a person's page."""
        try:
            return self.allowances.of_users(users) if self.plans.any_plans() else {}
        except Exception as error:
            # Only the class: the error's text could name more than the Users shown.
            logger.warning(
                "The Operator Overview could not read Plans, so it shows none (%s)",
                error.__class__.__name__,
            )
            return {}
```

In `src/calendar_sync/bootstrap/container.py`, import the use case right after the
`operator_overview` import:

```python
from calendar_sync.application.operations.operator_overview import OperatorOverview, UserStatuses
from calendar_sync.application.operations.own_plan import ShowOwnPlan
```

add the field to `UserServices` right after the one task 8 added:

```python
    get_installation_status: GetInstallationStatus
    integration_tokens: IntegrationTokens
    issue_integration_token: IssueIntegrationToken
    """Issues a token within the User's Plan; installation:read only for administrators."""
    show_own_plan: ShowOwnPlan
    """What the User's Plan allows them and how much of it they have, for Your plan."""
    inspect_activity_event: InspectActivityEvent
```

In `_compose_user`, task 8 made the User's token store once, right after `operations`
(`tokens = adapters.integration_tokens(user_id)`); if that line is missing, add it there. Pass the
same `tokens` to `ShowOwnPlan`, adding one line to the `UserServices(...)` call:

```diff
         get_installation_status=GetInstallationStatus(
             list_sync_rules, operations, clock, heartbeat
         ),
         integration_tokens=tokens,
         issue_integration_token=IssueIntegrationToken(
             user_id, adapters.users, tokens, adapters.allowances
         ),
+        show_own_plan=ShowOwnPlan(adapters.allowances, unit_of_work, accounts, tokens, user_id),
         inspect_activity_event=InspectActivityEvent(
             adapters.activity(user_id), unit_of_work, provider
         ),
```

In `compose`, replace the `operator_overview=` argument of `Container(...)`:

```diff
-        operator_overview=OperatorOverview(
-            adapters.users, statuses, adapters.installation_units, adapters.clock
-        ),
+        operator_overview=OperatorOverview(
+            adapters.users,
+            statuses,
+            adapters.installation_units,
+            adapters.clock,
+            adapters.allowances,
+            adapters.plan_catalog,
+        ),
```

In `scripts/dev_preview.py` `build_preview_container`, replace the `operator_overview=` argument of
the `replace(composed, ...)` call:

```diff
-        operator_overview=OperatorOverview(
-            adapters.users, statuses, adapters.installation_units, preview_clock
-        ),
+        operator_overview=OperatorOverview(
+            adapters.users,
+            statuses,
+            adapters.installation_units,
+            preview_clock,
+            adapters.allowances,
+            adapters.plan_catalog,
+        ),
```

- [ ] **Step 8: Run the tests and the backend gates**

```sh
.venv/bin/pytest tests/application/test_own_plan.py tests/application/test_operator_overview.py tests/adapters/test_operator_overview_api.py tests/adapters/test_operator_overview_reads.py tests/adapters/test_users_api.py tests/adapters/test_composition.py tests/test_dev_preview.py tests/test_architecture.py tests/test_openapi_contract.py -q
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy
.venv/bin/lint-imports
```

Expected: all pass (`test_own_plan.py` 14 passed; `test_operator_overview.py` gains 6 passing
tests; the dev preview still builds and its people pages answer as before, because no Plan exists
there); the architecture test accepts `ShowOwnPlan` (5 fields) and `OperatorOverview` (6 fields);
the OpenAPI contract is unchanged; Ruff, mypy, and lint-imports are clean (operations imports
identity, sync, and domain only).

- [ ] **Step 9: Commit**

```sh
git add src/calendar_sync/application/operations/own_plan.py src/calendar_sync/application/operations/operator_overview.py src/calendar_sync/bootstrap/container.py scripts/dev_preview.py tests/application/test_own_plan.py tests/application/test_operator_overview.py
git commit -F - <<'EOF'
Show what each person's plan allows, to them and to administrators

Your plan now has a use case: the signed-in User's Allowance beside the
rules, calendar accounts, and Integration Tokens that count toward it, and
whether there is room for another. The Operator Overview reads every shown
person's Allowance in one read once any Plan exists, Plans on or off, and
shows none when Plans cannot be read, so People never fails on a Plans
fault.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
```

## Part 7: The Plans API (Task 13)

### Task 13: Plans API routes and schemas

The Web API for Plans: an Installation Administrator lists, defines, changes, and removes Plans,
chooses the Default Plan, turns Plans on and off, and assigns a person their own Plan; every User
reads Your plan. The person page's overview carries the Plan once one exists. Nothing in the Web
UI uses these routes yet (tasks 14 to 18 do), so the only web changes are the regenerated types
and two test fixtures.

**Files:**
- Create: `src/calendar_sync/interfaces/api/plan_payload.py`
- Create: `src/calendar_sync/interfaces/api/routes/plans.py`
- Modify: `src/calendar_sync/interfaces/api/schemas.py` (two `Literal` aliases after
  `EffectiveCadenceValue`; the Plan request and response models between `ResourceUseResponse` and
  `PersonResponse`; `UserOverviewResponse.plan`)
- Modify: `src/calendar_sync/interfaces/api/routes/users.py` (module docstring; imports;
  `Administration.assign_plan`; new `assign_plan` route after `change_state`;
  `user_overview_response`)
- Modify: `src/calendar_sync/interfaces/api/app.py` (router import, `UserApiServices`,
  `ApiServices`, the router tuple in `create_app`)
- Verify only, no edit: `src/calendar_sync/bootstrap/container.py` (tasks 7 and 12 already give
  `Container.plans`, `AdministrationServices.assign_plan`, and `UserServices.show_own_plan`, which
  the new protocols read)
- Regenerate: `web/openapi.json`, `web/src/lib/api-schema.ts`
- Modify: `web/src/app.test.tsx` (`NOTHING_SET_UP` gains `plan: null`),
  `web/src/features/person-page.test.tsx` (`robin` gains `plan: null`)
- Test: `tests/adapters/test_plans_api.py` (Create)
- Test: `tests/adapters/test_api_authorization.py`
- Test: `tests/adapters/test_schema_enums.py`
- Test: `tests/adapters/test_operator_overview_api.py`

**Interfaces:**
- Consumes:
  - Task 1, `calendar_sync.domain.plans`: `PlanKey(value: str)` (raises `InvalidPlan` with
    reason `KEY`), `Plan(key, name, limits)` (raises `InvalidPlan` with reason `NAME`),
    `PlanLimits(rules, connected_accounts, integration_tokens, sync_interval)` (raises
    `InvalidPlan` with reason `LIMIT`), `SyncInterval`, `AllowanceBasis`,
    `Allowance(basis, plan=None, on_default=False, assigned=None)` with the properties
    `limits -> PlanLimits` and `cadence -> SyncCadence`, `InvalidPlan` (`.reason`),
    `PlansNeedDefault`, `PlanIsDefault`, `PlanInUse(people)`, `AssignmentSource`.
  - Task 4: `calendar_sync.application.identity.ports` `PlansSetting(enabled, default)`,
    `PlanListing(plan, is_default, people, limited_people)`,
    `AssignmentChange(source, actor, at)`; `calendar_sync.application.identity.errors`
    `PlanNotFound`, `PlanKeyTaken`; `calendar_sync.infrastructure.persistence.plans`
    `SqlitePlans(database_path)` (`assign`, `change_settings`); test helpers
    `tests.users.limited_user(database, user=OTHER_USER, *, plan=None, email=None) -> UserId`,
    `tests.plans.FREE`, `tests.plans.FAMILY`, `tests.plans.plans_on(catalog, default=FREE, *others)`.
  - Task 6: `problem_from` maps `PlanLimitReached` to `plan_limit_reached` with
    `{"reason", "limit", "count"}`, `PlanInUse` to `plan_in_use` with `{"people", "count"}`,
    `InvalidPlan` to `invalid_plan` with `{"reason"}`, and `PlansNeedDefault`, `PlanNotFound`,
    `PlanKeyTaken`, `PlanIsDefault` to their codes with no params.
  - Task 7, `calendar_sync.application.identity.plans`:
    `PlansOverview(setting, plans, offered)`, `ShowPlans.execute(actor) -> PlansOverview`,
    `DefinePlan.execute(actor, plan) -> PlanListing`,
    `ChangePlan.execute(actor, plan) -> PlanListing`, `RemovePlan.execute(actor, key) -> None`,
    `SetPlansSetting.execute(actor, enabled, default) -> PlansOverview`,
    `AssignPlan.execute(actor, user, plan) -> Allowance`; `Container.plans: PlanServices`;
    `AdministrationServices.assign_plan: AssignPlan`.
  - Task 9 (tests only): `POST /api/v1/rules/{rule_id}/enable` answers 409 `plan_limit_reached`.
  - Task 12: `calendar_sync.application.operations.own_plan` `OwnPlan(allowance, rules_counted,
    connected_accounts, integration_tokens)` with `may_connect_account`, `may_issue_token`,
    `over_rule_limit`; `ShowOwnPlan.execute() -> OwnPlan`; `UserServices.show_own_plan`;
    `UserOverview.allowance: Allowance | None`.
- Produces:
  - `calendar_sync.interfaces.api.schemas`: `SyncIntervalValue`, `AllowanceBasisValue`,
    `PlanNameResponse`, `AppliedPlanResponse`, `PlanLimitsResponse`, `PlanResponse`,
    `PlansResponse`, `PersonPlanResponse`, `OwnPlanResponse`, `PlanLimitsRequest`,
    `DefinePlanRequest`, `ChangePlanRequest`, `PlansSettingRequest`, `AssignPlanRequest`,
    `UserOverviewResponse.plan: PersonPlanResponse | None`.
  - `calendar_sync.interfaces.api.plan_payload`: `named_plan(raw: str) -> PlanKey`,
    `plan_limits(payload: PlanLimitsRequest) -> PlanLimits`,
    `plan_limits_response(limits: PlanLimits) -> PlanLimitsResponse`,
    `plan_response(listing: PlanListing) -> PlanResponse`,
    `plans_response(overview: PlansOverview) -> PlansResponse`,
    `person_plan_response(allowance: Allowance) -> PersonPlanResponse`,
    `own_plan_response(own: OwnPlan) -> OwnPlanResponse`.
  - `calendar_sync.interfaces.api.routes.plans`: `PlanAdministration`, `PlansApiServices`,
    `OwnPlanServices`, and the routes `GET/POST /api/v1/plans`,
    `PUT/DELETE /api/v1/plans/{plan_key}`, `PUT /api/v1/plan-settings`,
    `GET /api/v1/account/plan`.
  - `calendar_sync.interfaces.api.routes.users`: `Administration.assign_plan`, the route
    `PUT /api/v1/users/{user_id}/plan`.
  - Generated web types `Schemas["PlansResponse"]`, `Schemas["PlanResponse"]`,
    `Schemas["PlanLimitsResponse"]`, `Schemas["DefinePlanRequest"]`,
    `Schemas["ChangePlanRequest"]`, `Schemas["PersonPlanResponse"]`,
    `Schemas["OwnPlanResponse"]`, and `UserOverview["plan"]`, which task 14 names in `lib/api.ts`.

- [ ] **Step 1: Write the failing test for the schema mirrors**

In `tests/adapters/test_schema_enums.py`, add the Plans import after the `calendar_sync.domain.model`
import, so the imports read:

```python
from calendar_sync.domain.model import (
    ProjectionContent,
    ProjectionHandling,
    TentativeEventPolicy,
    UnansweredInvitationPolicy,
)
from calendar_sync.domain.plans import AllowanceBasis, SyncInterval
```

and add the two Plans mirrors to `MIRRORS`, keeping every entry that is already there
(`FoundByValue`, `RunReasonValue`, and `SourceComparisonValue` came with Activity's provenance).
The keys stay in alphabetical order, so `MIRRORS` reads:

```python
MIRRORS: dict[str, type[StrEnum]] = {
    "AllowanceBasisValue": AllowanceBasis,
    "CauseValue": Cause,
    "EffectiveCadenceValue": CadenceReason,
    "FoundByValue": FoundBy,
    "HintKindValue": HintKind,
    "IncidentCategoryValue": IncidentCategory,
    "IncidentResolutionValue": IncidentResolution,
    "IncidentStepValue": IncidentStep,
    "InstantSyncAvailabilityValue": Availability,
    "PrivacyPolicy": ProjectionContent,
    "ProblemKindValue": ProblemKind,
    "ProjectionChoice": ProjectionHandling,
    "RunReasonValue": RunReason,
    "SourceComparisonValue": ComparisonKind,
    "StatusVerdictValue": StatusVerdict,
    "SyncIntervalValue": SyncInterval,
    "TentativeChoice": TentativeEventPolicy,
    "TokenScope": IntegrationTokenScope,
    "UnansweredChoice": UnansweredInvitationPolicy,
    "WorkKind": RuleWorkKind,
}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/adapters/test_schema_enums.py -q`
Expected: FAIL, 3 failed, 18 passed: the two new mirror cases raise `AttributeError: module
'calendar_sync.interfaces.api.schemas' has no attribute 'AllowanceBasisValue'` (and
`'SyncIntervalValue'`), and `test_every_schema_literal_alias_mirrors_an_enum_or_says_why_not`
finds two `MIRRORS` keys with no alias.

- [ ] **Step 3: Add the Literal aliases and the Plan models**

In `src/calendar_sync/interfaces/api/schemas.py`, add the two aliases right after the
`EffectiveCadenceValue` alias and its docstring, and before `RunReasonValue`, so that block reads:

```python
EffectiveCadenceValue = Literal[
    "instant",
    "not_watchable",
    "waiting_for_provider",
    "off_by_user",
    "not_in_plan",
    "no_public_address",
    "not_reaching",
]
"""How a rule syncs: "instant", or why Scheduled Sync runs it instead."""
SyncIntervalValue = Literal[
    "instant", "5_minutes", "10_minutes", "15_minutes", "30_minutes", "60_minutes"
]
"""How soon a Plan's rules sync (ADR 0038); only the offered ones may be saved."""
AllowanceBasisValue = Literal["plans_off", "administrator", "plan"]
"""Why a User has the limits they have: Plans are off, they administer, or a Plan limits them."""
```

`RunReasonValue`, `FoundByValue`, and `SourceComparisonValue` follow them unchanged.

Then insert the Plan models between `ResourceUseResponse` (unchanged, ending with its `since`
field) and `class PersonResponse(UserResponse):`. They must come before
`UserOverviewResponse`, which names `PersonPlanResponse` in Step 10:

```python
class PlanNameResponse(ApiResponse):
    """A Plan as people know it: its key, which never changes, and its name."""

    key: str
    name: str


class AppliedPlanResponse(PlanNameResponse):
    """The Plan that limits a User now."""

    on_default: bool
    """It is the Default Plan, because they have no Plan of their own."""


class PlanLimitsResponse(ApiResponse):
    """What a Plan allows; null is unlimited."""

    rules: int | None
    """Rules that count: enabled, stopped only by Lapsed Authorization, or a Rule Replacement
    draft that keeps its place."""
    connected_accounts: int | None
    """Calendar accounts, Disconnected Accounts included."""
    integration_tokens: int | None
    """Unrevoked Integration Tokens; 0 offers none."""
    sync_interval: SyncIntervalValue


class PlanResponse(ApiResponse):
    """One Plan, as Administration lists it."""

    key: str
    name: str
    limits: PlanLimitsResponse
    is_default: bool
    people: int
    """Everyone who has it: their own Plan, plus, for the default, everyone with none."""
    limited_people: int
    """Active Users who do not administer and have it, whom it limits while Plans are on."""


class PlansResponse(ApiResponse):
    """The Plans setting, the sync intervals offered now, and every Plan by name."""

    enabled: bool
    """Whether Plans limit anyone; while they are off, nobody is limited."""
    default_plan: str | None
    """The Default Plan's key; null until an administrator chooses one."""
    sync_intervals: list[SyncIntervalValue]
    """The sync intervals a Plan may be given now, in order."""
    plans: list[PlanResponse]


class PersonPlanResponse(ApiResponse):
    """A person's Plan, as the Operator Overview shows it (ADR 0038)."""

    basis: AllowanceBasisValue
    plan: AppliedPlanResponse | None
    """The Plan that limits them; null unless the basis is "plan"."""
    assigned: PlanNameResponse | None
    """Their own Plan, whatever the basis; null when they have the Default Plan."""


class OwnPlanResponse(ApiResponse):
    """What the signed-in User's Plan allows and how much of it they have, for Your plan."""

    basis: AllowanceBasisValue
    plan: AppliedPlanResponse | None
    """The Plan that limits them; null unless the basis is "plan"."""
    limits: PlanLimitsResponse | None
    """What their Plan allows; null unless the basis is "plan", since then nothing limits them."""
    rules_counted: int
    connected_accounts: int
    """Every calendar account, Disconnected Accounts included."""
    integration_tokens: int
    """Unrevoked Integration Tokens."""
    instant: bool
    """Whether their Plan includes Instant Sync."""
    poll_every_minutes: int
    """How often Scheduled Sync runs their rules, as their Plan says."""
    may_connect_account: bool
    may_issue_token: bool
    over_rule_limit: bool
    """More rules count than the rule limit: nothing stops, but no other rule can start."""


class PlanLimitsRequest(BaseModel):
    """Each limit is a whole number, or null for unlimited."""

    rules: int | None
    connected_accounts: int | None
    integration_tokens: int | None
    sync_interval: SyncIntervalValue


class DefinePlanRequest(BaseModel):
    key: str = Field(max_length=200)
    """1 to 32 lower-case letters, digits, and hyphens; it never changes."""
    name: str = Field(max_length=200)
    limits: PlanLimitsRequest


class ChangePlanRequest(BaseModel):
    name: str = Field(max_length=200)
    limits: PlanLimitsRequest


class PlansSettingRequest(BaseModel):
    enabled: bool
    default_plan: str | None = Field(max_length=200)
    """Required. Null clears the default, which Plans allow only while they are off."""


class AssignPlanRequest(BaseModel):
    plan: str | None = Field(max_length=200)
    """Required: the Plan's key, or null to return the User to the Default Plan."""
```

`PersonResponse`, `RuleResponse`, `RuleSummaryResponse`, and `DashboardResponse` do not change
(slice 1 shows a Plan only on the person page). `RuleDetailResponse.can_start` and `rule_limit`
came with task 9. Leave `UserOverviewResponse` alone until Step 10: its new field is required,
so adding it before `user_overview_response` fills it would break the person page.

- [ ] **Step 4: Run it to verify it passes**

Run: `.venv/bin/pytest tests/adapters/test_schema_enums.py -q`
Expected: PASS, 21 passed.

- [ ] **Step 5: Write the failing route tests**

Create `tests/adapters/test_plans_api.py`. Its bodies define the same Plans as `tests/plans.py`
(`FREE`: 1 rule, 1 account, 0 tokens, every 5 minutes; `FAMILY`: 5, 3, 2, instant). The
installation has a master key, so Your plan counts calendar accounts; the first User administers,
and the member is a `limited_user`.

```python
"""The Plans routes over the Web API: an Installation Administrator defines, changes, removes,
and assigns Plans and turns them on, and every User reads their own Plan (ADR 0038)."""

from collections.abc import Iterator
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import build_adapters, compose
from calendar_sync.domain.access import UserId
from calendar_sync.domain.model import SyncRuleId, SyncRuleState
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.security import CredentialCipher
from calendar_sync.interfaces.api.app import create_app
from calendar_sync.interfaces.api.dependencies import SESSION_COOKIE
from tests.helpers import NOW, endpoint, rule
from tests.users import (
    ADMIN_EMAIL,
    ADMIN_PASSWORD,
    OTHER_USER,
    administrator,
    limited_user,
    session_for,
    sqlite_units,
)

MEMBER_EMAIL = "member@example.test"
# What defines tests.plans.FREE and FAMILY through the Web API.
FREE_BODY: dict[str, Any] = {
    "key": "free",
    "name": "Free",
    "limits": {
        "rules": 1,
        "connected_accounts": 1,
        "integration_tokens": 0,
        "sync_interval": "5_minutes",
    },
}
FAMILY_BODY: dict[str, Any] = {
    "key": "family",
    "name": "Family",
    "limits": {
        "rules": 5,
        "connected_accounts": 3,
        "integration_tokens": 2,
        "sync_interval": "instant",
    },
}
CHANGE_FREE = {"name": "Free", "limits": FREE_BODY["limits"]}
CHANGE_FAMILY = {"name": "Family", "limits": FAMILY_BODY["limits"]}
OFFERED = ["instant", "5_minutes"]
# Your plan for someone no Plan limits.
UNLIMITED = {
    "plan": None,
    "limits": None,
    "instant": True,
    "poll_every_minutes": 5,
    "may_connect_account": True,
    "may_issue_token": True,
    "over_rule_limit": False,
}


@dataclass(frozen=True, slots=True)
class Installation:
    database: Path
    client: TestClient
    admin: UserId
    member: UserId
    """Someone Plans can limit: they do not administer."""

    def as_admin(self) -> None:
        self.client.cookies.set(SESSION_COOKIE, session_for(self.database, self.admin))

    def as_member(self) -> None:
        self.client.cookies.set(SESSION_COOKIE, session_for(self.database, self.member))

    def define(self, *bodies: dict[str, Any]) -> None:
        for body in bodies:
            response = self.client.post("/api/v1/plans", json=body)
            assert response.status_code == 201, response.text

    def turn_on(self, default: str) -> None:
        response = self.client.put(
            "/api/v1/plan-settings", json={"enabled": True, "default_plan": default}
        )
        assert response.status_code == 200, response.text

    def overview_plan(self, user: UserId) -> Any:
        """The Plan the person page shows about `user`, read by the administrator."""
        response = self.client.get(f"/api/v1/users/{user.value}/overview")
        assert response.status_code == 200, response.text
        return response.json()["plan"]


@pytest.fixture
def installation(tmp_path: Path) -> Iterator[Installation]:
    database = tmp_path / "test.db"
    # A master key, so Your plan counts calendar accounts; no scheduler runs anyone's rules.
    settings = Settings(database, master_key=CredentialCipher.generate_key())
    adapters = build_adapters(settings)
    admin = administrator(adapters)
    member = limited_user(database, OTHER_USER, email=MEMBER_EMAIL)
    app = create_app(replace(compose(settings, adapters), scheduler=None))
    with TestClient(app) as client:
        installation = Installation(database, client, admin, member)
        installation.as_admin()
        yield installation


def _problem(response: Any) -> tuple[int, str, dict[str, Any]]:
    """The status, code, and params an error answer carries."""
    body = response.json()
    return response.status_code, body["code"], body["params"]


def _with_limits(body: dict[str, Any], **limits: Any) -> dict[str, Any]:
    return {**body, "limits": {**body["limits"], **limits}}


def _member_rules(installation: Installation) -> None:
    """Two enabled rules between the member's two calendar accounts, which count, and a previewed
    rule that has not started, which does not."""
    first = rule()
    second = replace(
        first, id=SyncRuleId("rule-2"), source=first.destination, destination=first.source
    )
    previewed = replace(
        rule(state=SyncRuleState.PREVIEWED),
        id=SyncRuleId("rule-3"),
        source=endpoint("personal-account", "other-calendar"),
    )
    with sqlite_units(installation.database, user=installation.member)() as uow:
        for each in (first, second, previewed):
            uow.rules.add(each)
        uow.commit()


def test_an_administrator_defines_lists_changes_and_removes_plans(
    installation: Installation,
) -> None:
    client = installation.client
    empty = client.get("/api/v1/plans").json()
    defined = client.post("/api/v1/plans", json=FREE_BODY)
    installation.define(FAMILY_BODY)
    listed = client.get("/api/v1/plans").json()["plans"]
    changed = client.put(
        "/api/v1/plans/free",
        json={
            "name": "  Starter  ",
            "limits": {**FREE_BODY["limits"], "rules": 2, "integration_tokens": None},
        },
    )
    removed = client.delete("/api/v1/plans/family")
    after = client.get("/api/v1/plans").json()["plans"]

    assert empty == {
        "enabled": False,
        "default_plan": None,
        "sync_intervals": OFFERED,
        "plans": [],
    }
    assert defined.status_code == 201
    assert defined.json() == {**FREE_BODY, "is_default": False, "people": 0, "limited_people": 0}
    # By name: Family before Free.
    assert [plan["key"] for plan in listed] == ["family", "free"]
    # The key stays, spaces around the name go, and null is unlimited.
    assert changed.status_code == 200
    assert changed.json() == {
        "key": "free",
        "name": "Starter",
        "limits": {
            "rules": 2,
            "connected_accounts": 1,
            "integration_tokens": None,
            "sync_interval": "5_minutes",
        },
        "is_default": False,
        "people": 0,
        "limited_people": 0,
    }
    assert removed.status_code == 204
    assert [plan["key"] for plan in after] == ["free"]


def test_plans_turn_on_only_with_a_default_and_turning_them_off_keeps_every_plan(
    installation: Installation,
) -> None:
    client = installation.client
    installation.define(FREE_BODY)

    def setting(enabled: bool, default: str | None) -> Any:
        return client.put(
            "/api/v1/plan-settings", json={"enabled": enabled, "default_plan": default}
        )

    without_default = setting(True, None)
    chosen = setting(False, "free")
    turned_on = setting(True, "free")
    cleared_while_on = setting(True, None)
    turned_off = setting(False, "free")
    cleared_while_off = setting(False, None)
    removed = client.delete("/api/v1/plans/free")

    assert _problem(without_default) == (409, "plans_need_default", {})
    assert chosen.json() == {
        "enabled": False,
        "default_plan": "free",
        "sync_intervals": OFFERED,
        # Everyone has the default; it would limit only the member, never an administrator.
        "plans": [{**FREE_BODY, "is_default": True, "people": 2, "limited_people": 1}],
    }
    assert (turned_on.json()["enabled"], turned_on.json()["default_plan"]) == (True, "free")
    assert _problem(cleared_while_on) == (409, "plans_need_default", {})
    assert (turned_off.json()["enabled"], turned_off.json()["default_plan"]) == (False, "free")
    assert [plan["key"] for plan in turned_off.json()["plans"]] == ["free"]
    assert (cleared_while_off.json()["enabled"], cleared_while_off.json()["default_plan"]) == (
        False,
        None,
    )
    # No longer the default and nobody's own, so it may go.
    assert removed.status_code == 204


def test_each_refusal_answers_its_code_and_params(installation: Installation) -> None:
    client, member = installation.client, installation.member.value
    installation.define(FREE_BODY, FAMILY_BODY)
    installation.turn_on("free")
    assigned = client.put(f"/api/v1/users/{member}/plan", json={"plan": "family"})

    answers = {
        "taken": client.post("/api/v1/plans", json={**FAMILY_BODY, "name": "Another"}),
        "default": client.delete("/api/v1/plans/free"),
        "in_use": client.delete("/api/v1/plans/family"),
        "needs_default": client.put(
            "/api/v1/plan-settings", json={"enabled": True, "default_plan": None}
        ),
        "unknown_default": client.put(
            "/api/v1/plan-settings", json={"enabled": True, "default_plan": "gold"}
        ),
        "unknown_change": client.put("/api/v1/plans/gold", json=CHANGE_FAMILY),
        "unknown_removal": client.delete("/api/v1/plans/gold"),
        "unknown_plan": client.put(f"/api/v1/users/{member}/plan", json={"plan": "gold"}),
        "unknown_user": client.put("/api/v1/users/nobody/plan", json={"plan": "free"}),
        "malformed_user": client.put("/api/v1/users/%20/plan", json={"plan": "free"}),
    }
    listed = client.get("/api/v1/plans").json()

    assert assigned.status_code == 200
    assert {name: _problem(response) for name, response in answers.items()} == {
        "taken": (409, "plan_key_taken", {}),
        "default": (409, "plan_is_default", {}),
        "in_use": (409, "plan_in_use", {"people": 1, "count": 1}),
        "needs_default": (409, "plans_need_default", {}),
        "unknown_default": (404, "plan_not_found", {}),
        "unknown_change": (404, "plan_not_found", {}),
        "unknown_removal": (404, "plan_not_found", {}),
        "unknown_plan": (404, "plan_not_found", {}),
        "unknown_user": (404, "user_not_found", {}),
        "malformed_user": (404, "user_not_found", {}),
    }
    # Nothing a refusal answered changed anything.
    assert (listed["enabled"], listed["default_plan"]) == (True, "free")
    assert [(plan["key"], plan["name"]) for plan in listed["plans"]] == [
        ("family", "Family"),
        ("free", "Free"),
    ]


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        pytest.param({**FREE_BODY, "key": "Bad"}, "key", id="upper-case-key"),
        pytest.param({**FREE_BODY, "key": "-free"}, "key", id="leading-hyphen"),
        pytest.param({**FREE_BODY, "key": "free plan"}, "key", id="space-in-key"),
        pytest.param({**FREE_BODY, "key": "a" * 33}, "key", id="33-character-key"),
        pytest.param({**FREE_BODY, "key": ""}, "key", id="empty-key"),
        pytest.param({**FREE_BODY, "name": "   "}, "name", id="blank-name"),
        pytest.param({**FREE_BODY, "name": "Free\nplan"}, "name", id="line-break"),
        pytest.param({**FREE_BODY, "name": "x" * 61}, "name", id="61-character-name"),
        pytest.param(_with_limits(FREE_BODY, rules=0), "limit", id="no-rules"),
        pytest.param(_with_limits(FREE_BODY, connected_accounts=0), "limit", id="no-accounts"),
        pytest.param(_with_limits(FREE_BODY, integration_tokens=-1), "limit", id="minus-tokens"),
        pytest.param(_with_limits(FREE_BODY, rules=10_001), "limit", id="10001-rules"),
        pytest.param(
            _with_limits(FREE_BODY, sync_interval="15_minutes"), "interval", id="not-offered"
        ),
    ],
)
def test_a_new_plan_that_is_not_valid_is_refused_with_its_reason(
    installation: Installation, body: dict[str, Any], reason: str
) -> None:
    response = installation.client.post("/api/v1/plans", json=body)

    assert _problem(response) == (422, "invalid_plan", {"reason": reason})
    assert installation.client.get("/api/v1/plans").json()["plans"] == []


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        pytest.param({**CHANGE_FREE, "name": ""}, "name", id="empty-name"),
        pytest.param(
            _with_limits(CHANGE_FREE, connected_accounts=10_001), "limit", id="10001-accounts"
        ),
        pytest.param(
            _with_limits(CHANGE_FREE, sync_interval="60_minutes"), "interval", id="not-offered"
        ),
    ],
)
def test_a_plan_change_that_is_not_valid_is_refused_with_its_reason(
    installation: Installation, change: dict[str, Any], reason: str
) -> None:
    installation.define(FREE_BODY)
    response = installation.client.put("/api/v1/plans/free", json=change)
    listed = installation.client.get("/api/v1/plans").json()["plans"]

    assert _problem(response) == (422, "invalid_plan", {"reason": reason})
    assert listed == [{**FREE_BODY, "is_default": False, "people": 0, "limited_people": 0}]


def test_an_interval_this_release_does_not_know_is_an_invalid_request(
    installation: Installation,
) -> None:
    response = installation.client.post(
        "/api/v1/plans", json=_with_limits(FREE_BODY, sync_interval="2_minutes")
    )
    body = response.json()

    assert (response.status_code, body["code"], body["params"]["field"]) == (
        422,
        "invalid_request",
        "sync_interval",
    )


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        pytest.param("PUT", "/api/v1/plans/Bad%20Key", CHANGE_FREE, id="change-with-a-space"),
        pytest.param("PUT", f"/api/v1/plans/{'a' * 33}", CHANGE_FREE, id="change-33-characters"),
        pytest.param("DELETE", "/api/v1/plans/%20", None, id="remove-blank"),
        pytest.param("DELETE", "/api/v1/plans/UPPER", None, id="remove-upper-case"),
        pytest.param(
            "PUT",
            "/api/v1/plan-settings",
            {"enabled": True, "default_plan": "UPPER"},
            id="default-upper-case",
        ),
        pytest.param(
            "PUT",
            "/api/v1/plan-settings",
            {"enabled": False, "default_plan": "x y"},
            id="default-with-a-space",
        ),
        pytest.param("PUT", "/api/v1/users/{member}/plan", {"plan": "x y"}, id="assign-space"),
        pytest.param("PUT", "/api/v1/users/{member}/plan", {"plan": ""}, id="assign-empty"),
    ],
)
def test_a_malformed_plan_key_names_no_plan(
    installation: Installation, method: str, path: str, body: dict[str, Any] | None
) -> None:
    """Never 422 or 500: a key this release refuses is answered as an unknown Plan."""
    installation.define(FREE_BODY)
    response = installation.client.request(
        method, path.format(member=installation.member.value), json=body
    )

    assert _problem(response) == (404, "plan_not_found", {})


def test_an_interval_a_later_release_offered_may_be_kept_but_not_newly_chosen(
    installation: Installation,
) -> None:
    client = installation.client
    installation.define(FAMILY_BODY)
    # Saved by a release that offers every interval, then rolled back.
    with transaction(installation.database) as connection:
        connection.execute("UPDATE plans SET sync_interval = '15_minutes' WHERE key = 'family'")
    listed = client.get("/api/v1/plans").json()["plans"][0]["limits"]["sync_interval"]
    kept = client.put(
        "/api/v1/plans/family",
        json={**_with_limits(CHANGE_FAMILY, sync_interval="15_minutes"), "name": "Household"},
    )
    newly_chosen = client.put(
        "/api/v1/plans/family",
        json={**_with_limits(CHANGE_FAMILY, sync_interval="30_minutes"), "name": "Household"},
    )

    assert listed == "15_minutes"
    assert kept.status_code == 200
    assert (kept.json()["name"], kept.json()["limits"]["sync_interval"]) == (
        "Household",
        "15_minutes",
    )
    assert _problem(newly_chosen) == (422, "invalid_plan", {"reason": "interval"})


def test_an_interval_this_release_does_not_know_reads_as_instant(
    installation: Installation,
) -> None:
    client = installation.client
    installation.define(FREE_BODY)
    installation.turn_on("free")
    with transaction(installation.database) as connection:
        connection.execute("UPDATE plans SET sync_interval = 'every_2_minutes' WHERE key = 'free'")
    listed = client.get("/api/v1/plans").json()["plans"][0]["limits"]["sync_interval"]
    installation.as_member()
    reads = [client.get(path) for path in ("/api/v1/session", "/api/v1/rules")]
    own = client.get("/api/v1/account/plan").json()

    assert listed == "instant"
    assert [response.status_code for response in reads] == [200, 200]
    assert (own["limits"]["sync_interval"], own["instant"]) == ("instant", True)


def test_a_stored_plan_key_this_release_refuses_never_breaks_sign_in_or_the_rules_api(
    installation: Installation,
) -> None:
    client = installation.client
    installation.define(FREE_BODY)
    installation.turn_on("free")
    # A key a later release might write, given to both Users.
    with transaction(installation.database) as connection:
        connection.execute(
            """
            INSERT INTO plans (
                key, name, rule_limit, account_limit, token_limit, sync_interval, created_at,
                updated_at
            ) VALUES ('Later Key', 'Later', 1, 1, 0, 'instant', ?, ?)
            """,
            (NOW.isoformat(), NOW.isoformat()),
        )
        connection.execute(
            "UPDATE users SET plan_key = 'Later Key' WHERE id IN (?, ?)",
            (installation.admin.value, installation.member.value),
        )
    client.cookies.clear()
    signed_in = client.post(
        "/api/v1/session", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    administrator_reads = [
        client.get(path)
        for path in (
            "/api/v1/session",
            "/api/v1/rules",
            "/api/v1/account/plan",
            f"/api/v1/users/{installation.member.value}/overview",
        )
    ]
    installation.as_member()
    member_reads = [
        client.get(path) for path in ("/api/v1/session", "/api/v1/rules", "/api/v1/account/plan")
    ]

    assert signed_in.status_code == 200, signed_in.text
    assert [response.status_code for response in administrator_reads + member_reads] == [200] * 7
    assert member_reads[0].json()["user"]["id"] == installation.member.value
    # The key names no Plan, so the Default Plan still limits the member.
    assert member_reads[2].json()["basis"] == "plan"


def test_an_administrator_assigns_plans_even_while_plans_are_off(
    installation: Installation,
) -> None:
    client, member = installation.client, installation.member.value
    installation.define(FREE_BODY, FAMILY_BODY)
    while_off = client.put(f"/api/v1/users/{member}/plan", json={"plan": "family"})
    installation.turn_on("free")
    once_on = installation.overview_plan(installation.member)
    returned = client.put(f"/api/v1/users/{member}/plan", json={"plan": None})
    to_administrator = client.put(
        f"/api/v1/users/{installation.admin.value}/plan", json={"plan": "family"}
    )
    listed = {plan["key"]: plan for plan in client.get("/api/v1/plans").json()["plans"]}

    family = {"key": "family", "name": "Family"}
    assert while_off.status_code == 200
    assert while_off.json() == {"basis": "plans_off", "plan": None, "assigned": family}
    assert once_on == {
        "basis": "plan",
        "plan": {**family, "on_default": False},
        "assigned": family,
    }
    assert returned.json() == {
        "basis": "plan",
        "plan": {"key": "free", "name": "Free", "on_default": True},
        "assigned": None,
    }
    # An administrator's own Plan is kept, and limits them only once they stop administering.
    assert to_administrator.json() == {"basis": "administrator", "plan": None, "assigned": family}
    assert (listed["family"]["people"], listed["family"]["limited_people"]) == (1, 0)
    assert (listed["free"]["people"], listed["free"]["limited_people"]) == (1, 1)


def test_everyone_without_a_plan_of_their_own_follows_a_new_default_at_once(
    installation: Installation,
) -> None:
    client, database = installation.client, installation.database
    installation.define(FREE_BODY, FAMILY_BODY)
    own_free = limited_user(database, UserId("user-3"), plan="free", email="own@example.test")
    installation.turn_on("free")
    switched = client.put("/api/v1/plan-settings", json={"enabled": True, "default_plan": "family"})
    # Someone invited after the change joins with no Plan of their own.
    client.put("/api/v1/registration", json={"policy": "invitation_only"})
    token = client.post("/api/v1/invitations").json()["token"]
    joined = client.post(
        "/api/v1/invitations/accept",
        json={"token": token, "email": "invited@example.test", "password": "a long password here"},
    )
    invited = UserId(joined.json()["user"]["id"])
    client.cookies.clear()
    installation.as_admin()
    member_seen = installation.overview_plan(installation.member)
    invited_seen = installation.overview_plan(invited)
    own_seen = installation.overview_plan(own_free)
    old_default = client.delete("/api/v1/plans/free")
    new_default = client.delete("/api/v1/plans/family")
    cleared = client.put("/api/v1/plan-settings", json={"enabled": True, "default_plan": None})
    installation.as_member()
    member_own = client.get("/api/v1/account/plan").json()

    on_family = {
        "basis": "plan",
        "plan": {"key": "family", "name": "Family", "on_default": True},
        "assigned": None,
    }
    assert switched.status_code == 200
    assert joined.status_code == 200, joined.text
    assert member_seen == on_family
    assert invited_seen == on_family
    # Someone with a Plan of their own keeps it.
    assert own_seen == {
        "basis": "plan",
        "plan": {"key": "free", "name": "Free", "on_default": False},
        "assigned": {"key": "free", "name": "Free"},
    }
    assert (member_own["plan"], member_own["limits"]) == (
        {"key": "family", "name": "Family", "on_default": True},
        FAMILY_BODY["limits"],
    )
    # The old default is someone's own Plan, the new one is the default, and Plans stay on.
    assert _problem(old_default) == (409, "plan_in_use", {"people": 1, "count": 1})
    assert _problem(new_default) == (409, "plan_is_default", {})
    assert _problem(cleared) == (409, "plans_need_default", {})


def test_a_member_is_refused_every_plans_administrator_route_and_reads_their_own_plan(
    installation: Installation,
) -> None:
    client = installation.client
    installation.define(FREE_BODY)
    before = client.get("/api/v1/plans").json()
    installation.as_member()
    refused = [
        client.get("/api/v1/plans"),
        client.post("/api/v1/plans", json=FAMILY_BODY),
        client.put("/api/v1/plans/free", json=CHANGE_FREE),
        client.delete("/api/v1/plans/free"),
        client.put("/api/v1/plan-settings", json={"enabled": True, "default_plan": "free"}),
        client.put(f"/api/v1/users/{installation.member.value}/plan", json={"plan": "free"}),
    ]
    own = client.get("/api/v1/account/plan")
    installation.as_admin()
    after = client.get("/api/v1/plans").json()

    assert {(response.status_code, response.json()["code"]) for response in refused} == {
        (403, "administrator_required")
    }
    assert own.status_code == 200
    assert after == before


def test_your_plan_while_plans_are_off_for_an_administrator_and_for_a_limited_member(
    installation: Installation,
) -> None:
    client = installation.client
    _member_rules(installation)
    installation.as_member()
    while_off = client.get("/api/v1/account/plan").json()
    installation.as_admin()
    installation.define(FREE_BODY)
    installation.turn_on("free")
    administering = client.get("/api/v1/account/plan").json()
    installation.as_member()
    limited = client.get("/api/v1/account/plan").json()

    assert while_off == {
        "basis": "plans_off",
        **UNLIMITED,
        "rules_counted": 2,
        "connected_accounts": 2,
        "integration_tokens": 0,
    }
    assert administering == {
        "basis": "administrator",
        **UNLIMITED,
        "rules_counted": 0,
        "connected_accounts": 0,
        "integration_tokens": 0,
    }
    assert limited == {
        "basis": "plan",
        "plan": {"key": "free", "name": "Free", "on_default": True},
        "limits": FREE_BODY["limits"],
        "rules_counted": 2,
        "connected_accounts": 2,
        "integration_tokens": 0,
        "instant": False,
        "poll_every_minutes": 5,
        "may_connect_account": False,
        "may_issue_token": False,
        "over_rule_limit": True,
    }


def test_a_lower_default_refuses_new_starts_and_stops_nothing(installation: Installation) -> None:
    client = installation.client
    _member_rules(installation)
    installation.define(FREE_BODY)
    installation.turn_on("free")
    installation.as_member()
    refused = client.post("/api/v1/rules/rule-3/enable")
    rules = client.get("/api/v1/rules").json()

    assert _problem(refused) == (
        409,
        "plan_limit_reached",
        {"reason": "rules", "limit": 1, "count": 1},
    )
    assert [(each["id"], each["state"]) for each in rules] == [
        ("rule-1", "enabled"),
        ("rule-2", "enabled"),
        ("rule-3", "dry_run_validated"),
    ]
```

In `tests/adapters/test_api_authorization.py`, replace the `ADMINISTRATOR_ROUTES` comment and set
with:

```python
# Only an Installation Administrator may use these (ADR 0030), Plans among them (ADR 0038).
ADMINISTRATOR_ROUTES = {
    ("GET", "/api/v1/registration"),
    ("PUT", "/api/v1/registration"),
    ("GET", "/api/v1/invitations"),
    ("POST", "/api/v1/invitations"),
    ("DELETE", "/api/v1/invitations/{invitation_id}"),
    ("GET", "/api/v1/users"),
    ("PUT", "/api/v1/users/{user_id}/role"),
    ("PUT", "/api/v1/users/{user_id}/state"),
    ("POST", "/api/v1/users/{user_id}/password-reset-links"),
    ("DELETE", "/api/v1/users/{user_id}"),
    ("PUT", "/api/v1/users/{user_id}/plan"),
    ("GET", "/api/v1/plans"),
    ("POST", "/api/v1/plans"),
    ("PUT", "/api/v1/plans/{plan_key}"),
    ("DELETE", "/api/v1/plans/{plan_key}"),
    ("PUT", "/api/v1/plan-settings"),
    ("GET", "/api/v1/storage"),
    ("GET", "/api/v1/storage/activity"),
    ("POST", "/api/v1/storage/activity/clear"),
    ("GET", "/api/v1/storage/logs"),
    ("DELETE", "/api/v1/storage/logs"),
}
```

and replace `test_an_administrator_naming_a_malformed_user_is_told_nobody_has_it` with (the body
gains `"plan": None`, which the new route requires, and the count goes from 5 to 6):

```python
def test_an_administrator_naming_a_malformed_user_is_told_nobody_has_it(tmp_path: Path) -> None:
    """A blank identifier names nobody: 404, never a server error (review on PR 68)."""
    app = create_app(build_container(Settings(tmp_path / "test.db")))
    with TestClient(app) as client:
        sign_in(client)
        answers = {
            (method, path): client.request(
                method,
                path.replace("{user_id}", "%20"),
                json={"role": "user", "state": "active", "plan": None},
            ).status_code
            for method, path in ADMINISTRATOR_ROUTES | USER_NAMING_ADMINISTRATOR_ROUTES
            if "{user_id}" in path
        }

    assert len(answers) == 6
    assert set(answers.values()) == {404}, answers
```

In `tests/adapters/test_operator_overview_api.py`, replace the `calendar_sync` and `tests`
imports (everything between `from fastapi.testclient import TestClient` and
`MEMBER_EMAIL = "member@example.test"`) with:

```python
from calendar_sync.application.identity.ports import AssignmentChange
from calendar_sync.application.operations.installation_health import (
    InstallationIncident,
    InstallationNotifications,
)
from calendar_sync.application.operations.ports import SchedulerProgress
from calendar_sync.application.sync.errors import ProviderFailure
from calendar_sync.application.sync.ports import (
    CalendarAccess,
    DiscoveredCalendar,
    ProviderCallCounts,
)
from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import Container, build_adapters, compose
from calendar_sync.domain.access import UserId
from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.audit import AuditAction, AuditEntry, AuditOutcome, RecordedEvent
from calendar_sync.domain.causes import Cause
from calendar_sync.domain.model import ConnectedAccountId, SyncRuleId, SyncRuleState
from calendar_sync.domain.plans import AssignmentSource
from calendar_sync.domain.providers import ProviderFailureKind
from calendar_sync.infrastructure.clock import SystemClock
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.persistence.plans import SqlitePlans
from calendar_sync.infrastructure.scheduling import SchedulerWatch
from calendar_sync.interfaces.api.app import create_app
from calendar_sync.interfaces.api.dependencies import SESSION_COOKIE
from tests.adapters.microsoft.test_calendar_provider_contract import outlook
from tests.adapters.test_notifications import RecordingSmtp
from tests.fake_microsoft_graph_api import Refusal
from tests.helpers import endpoint, rule
from tests.plans import FAMILY, FREE, plans_on
from tests.users import OTHER_USER, add_user, administrator, session_for, sqlite_units
```

and append these two tests at the end of the file:

```python
def test_the_person_page_shows_no_plan_until_one_exists(installation: Installation) -> None:
    client = installation.client
    seen = client.get(f"/api/v1/users/{installation.member.user.value}/overview").json()
    people = client.get("/api/v1/users").json()["users"]

    assert seen["plan"] is None
    # People rows never carry a Plan; only the person page shows it.
    assert all("plan" not in row for row in people)


def test_the_person_page_shows_the_plan_that_limits_them_and_their_own(
    installation: Installation,
) -> None:
    client = installation.client
    plans = SqlitePlans(installation.database)
    plans_on(plans, FREE, FAMILY)
    admin = installation.admin.user
    given = AssignmentChange(AssignmentSource.ADMINISTRATOR, admin, datetime.now(UTC))
    assigned = plans.assign(admin, FAMILY.key, given)

    def plan_of(user: UserId) -> Any:
        return client.get(f"/api/v1/users/{user.value}/overview").json()["plan"]

    member_while_on = plan_of(installation.member.user)
    admin_while_on = plan_of(admin)
    plans.change_settings(False, FREE.key)
    member_while_off = plan_of(installation.member.user)
    people = client.get("/api/v1/users").json()["users"]

    assert assigned
    assert member_while_on == {
        "basis": "plan",
        "plan": {"key": "free", "name": "Free", "on_default": True},
        "assigned": None,
    }
    # No Plan limits an administrator; the one they were given waits until they stop.
    assert admin_while_on == {
        "basis": "administrator",
        "plan": None,
        "assigned": {"key": "family", "name": "Family"},
    }
    # Once a Plan exists, the person page shows it even while Plans are off.
    assert member_while_off == {"basis": "plans_off", "plan": None, "assigned": None}
    assert all("plan" not in row for row in people)
```

- [ ] **Step 6: Run them to verify they fail**

Run: `.venv/bin/pytest tests/adapters/test_plans_api.py tests/adapters/test_api_authorization.py tests/adapters/test_operator_overview_api.py -q`
Expected: FAIL.
- `test_plans_api.py`: every test fails. No Plans route exists yet, so `/api/v1/plans` answers
  404 `not_found` from `UnknownApiPath` (for example `AssertionError` in `Installation.define`,
  with a body whose code is `not_found`).
- `test_api_authorization.py`: 2 failed, 4 passed: `administered == ADMINISTRATOR_ROUTES` (the
  six routes are missing), and the member's requests to the six new paths answer 404 from
  `UnknownApiPath`, not 403. The malformed-user test already passes, because an unknown path
  answers 404 too; it pins the new route once it exists.
- `test_operator_overview_api.py`: the two new tests fail with `KeyError: 'plan'`; the other 9
  pass.

- [ ] **Step 7: Create the payload translation**

Create `src/calendar_sync/interfaces/api/plan_payload.py`:

```python
"""Plans as the Web API reads and answers them (ADR 0038): keys, limits, and Allowances."""

from __future__ import annotations

from fastapi import status

from calendar_sync.application.identity.errors import PlanNotFound
from calendar_sync.application.identity.plans import PlansOverview
from calendar_sync.application.identity.ports import PlanListing
from calendar_sync.application.operations.own_plan import OwnPlan
from calendar_sync.domain.plans import (
    Allowance,
    AllowanceBasis,
    InvalidPlan,
    Plan,
    PlanKey,
    PlanLimits,
    SyncInterval,
)
from calendar_sync.interfaces.api.problems import problem_from
from calendar_sync.interfaces.api.schemas import (
    AppliedPlanResponse,
    OwnPlanResponse,
    PersonPlanResponse,
    PlanLimitsRequest,
    PlanLimitsResponse,
    PlanNameResponse,
    PlanResponse,
    PlansResponse,
)


def named_plan(raw: str) -> PlanKey:
    """The Plan a path or a request names. A key this release refuses names no Plan, so it is
    answered 404 as an unknown Plan is, never as a validation or server error."""
    try:
        return PlanKey(raw)
    except InvalidPlan as error:
        missing = PlanNotFound(f"plan {raw} does not exist")
        raise problem_from(status.HTTP_404_NOT_FOUND, missing) from error


def plan_limits(payload: PlanLimitsRequest) -> PlanLimits:
    """The limits a request asks for; raises InvalidPlan when one is out of range."""
    return PlanLimits(
        payload.rules,
        payload.connected_accounts,
        payload.integration_tokens,
        SyncInterval(payload.sync_interval),
    )


def plan_limits_response(limits: PlanLimits) -> PlanLimitsResponse:
    return PlanLimitsResponse(
        rules=limits.rules,
        connected_accounts=limits.connected_accounts,
        integration_tokens=limits.integration_tokens,
        sync_interval=limits.sync_interval.value,
    )


def plan_response(listing: PlanListing) -> PlanResponse:
    plan = listing.plan
    return PlanResponse(
        key=plan.key.value,
        name=plan.name,
        limits=plan_limits_response(plan.limits),
        is_default=listing.is_default,
        people=listing.people,
        limited_people=listing.limited_people,
    )


def plans_response(overview: PlansOverview) -> PlansResponse:
    default = overview.setting.default
    return PlansResponse(
        enabled=overview.setting.enabled,
        default_plan=default.value if default is not None else None,
        sync_intervals=[interval.value for interval in overview.offered],
        plans=[plan_response(listing) for listing in overview.plans],
    )


def person_plan_response(allowance: Allowance) -> PersonPlanResponse:
    """A person's Plan for the Operator Overview: the one that limits them, and their own."""
    assigned = allowance.assigned
    return PersonPlanResponse(
        basis=allowance.basis.value,
        plan=_applied(allowance),
        assigned=_named(assigned) if assigned is not None else None,
    )


def own_plan_response(own: OwnPlan) -> OwnPlanResponse:
    allowance = own.allowance
    cadence = allowance.cadence
    limited = allowance.basis is AllowanceBasis.PLAN
    return OwnPlanResponse(
        basis=allowance.basis.value,
        plan=_applied(allowance),
        limits=plan_limits_response(allowance.limits) if limited else None,
        rules_counted=own.rules_counted,
        connected_accounts=own.connected_accounts,
        integration_tokens=own.integration_tokens,
        instant=cadence.instant,
        poll_every_minutes=int(cadence.poll_every.total_seconds() // 60),
        may_connect_account=own.may_connect_account,
        may_issue_token=own.may_issue_token,
        over_rule_limit=own.over_rule_limit,
    )


def _applied(allowance: Allowance) -> AppliedPlanResponse | None:
    """The Plan that limits the User; None unless one does."""
    plan = allowance.plan
    if allowance.basis is not AllowanceBasis.PLAN or plan is None:
        return None
    return AppliedPlanResponse(key=plan.key.value, name=plan.name, on_default=allowance.on_default)


def _named(plan: Plan) -> PlanNameResponse:
    return PlanNameResponse(key=plan.key.value, name=plan.name)
```

`named_plan` is the one place a Plan key from a path or a body becomes a `PlanKey`: a key this
release refuses answers 404 `plan_not_found`, never 422 or 500 (Review Focus 4). Only
`POST /api/v1/plans` builds `PlanKey(payload.key)` itself, because there a refused key is a 422
`invalid_plan` with `reason=key`.

- [ ] **Step 8: Create the Plans router**

Create `src/calendar_sync/interfaces/api/routes/plans.py`:

```python
"""Plans (ADR 0038): the limits an Installation Administrator defines, the Default Plan, the
setting that turns Plans on, and what the signed-in User's own Plan allows.

Every route here is an Installation Administrator's, except Your plan, which every User reads.
Assigning a Plan to a User is in `users.py`, beside the other changes to a User.
"""

from __future__ import annotations

from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, status

from calendar_sync.application.identity.administration import AdministratorRequired
from calendar_sync.application.identity.errors import PlanKeyTaken, PlanNotFound
from calendar_sync.application.identity.plans import (
    ChangePlan,
    DefinePlan,
    RemovePlan,
    SetPlansSetting,
    ShowPlans,
)
from calendar_sync.application.operations.own_plan import ShowOwnPlan
from calendar_sync.domain.access import UserId
from calendar_sync.domain.plans import (
    InvalidPlan,
    Plan,
    PlanInUse,
    PlanIsDefault,
    PlanKey,
    PlansNeedDefault,
)
from calendar_sync.interfaces.api.dependencies import administrator, app_services, user_services
from calendar_sync.interfaces.api.plan_payload import (
    named_plan,
    own_plan_response,
    plan_limits,
    plan_response,
    plans_response,
)
from calendar_sync.interfaces.api.problems import problem_from
from calendar_sync.interfaces.api.schemas import (
    ChangePlanRequest,
    DefinePlanRequest,
    OwnPlanResponse,
    PlanLimitsRequest,
    PlanResponse,
    PlansResponse,
    PlansSettingRequest,
)


class PlanAdministration(Protocol):
    @property
    def show_plans(self) -> ShowPlans: ...
    @property
    def define_plan(self) -> DefinePlan: ...
    @property
    def change_plan(self) -> ChangePlan: ...
    @property
    def remove_plan(self) -> RemovePlan: ...
    @property
    def set_plans_setting(self) -> SetPlansSetting: ...


class PlansApiServices(Protocol):
    @property
    def plans(self) -> PlanAdministration: ...


class OwnPlanServices(Protocol):
    @property
    def show_own_plan(self) -> ShowOwnPlan: ...


Services = Annotated[PlansApiServices, Depends(app_services)]
OwnServices = Annotated[OwnPlanServices, Depends(user_services)]
Administrator = Annotated[UserId, Depends(administrator)]
router = APIRouter()


@router.get("/api/v1/plans", response_model=PlansResponse)
def list_plans(services: Services, actor: Administrator) -> PlansResponse:
    """Every Plan with how many people have it, the Plans setting, and the offered intervals."""
    try:
        return plans_response(services.plans.show_plans.execute(actor))
    except AdministratorRequired as error:
        raise problem_from(status.HTTP_403_FORBIDDEN, error) from error


@router.put("/api/v1/plan-settings", response_model=PlansResponse)
def set_plans_setting(
    payload: PlansSettingRequest, services: Services, actor: Administrator
) -> PlansResponse:
    """Turn Plans on or off, and choose the Default Plan. Plans turn on only with a default;
    turning them off is always allowed and keeps every Plan and assignment."""
    default = named_plan(payload.default_plan) if payload.default_plan is not None else None
    try:
        overview = services.plans.set_plans_setting.execute(actor, payload.enabled, default)
    except PlanNotFound as error:
        raise problem_from(status.HTTP_404_NOT_FOUND, error) from error
    except PlansNeedDefault as error:
        raise problem_from(status.HTTP_409_CONFLICT, error) from error
    except AdministratorRequired as error:
        raise problem_from(status.HTTP_403_FORBIDDEN, error) from error
    return plans_response(overview)


@router.post("/api/v1/plans", response_model=PlanResponse, status_code=status.HTTP_201_CREATED)
def define_plan(
    payload: DefinePlanRequest, services: Services, actor: Administrator
) -> PlanResponse:
    """Add a Plan. Its key never changes, so billing can name it later."""
    try:
        plan = _plan(PlanKey(payload.key), payload.name, payload.limits)
        listing = services.plans.define_plan.execute(actor, plan)
    except InvalidPlan as error:
        raise problem_from(status.HTTP_422_UNPROCESSABLE_CONTENT, error) from error
    except PlanKeyTaken as error:
        raise problem_from(status.HTTP_409_CONFLICT, error) from error
    except AdministratorRequired as error:
        raise problem_from(status.HTTP_403_FORBIDDEN, error) from error
    return plan_response(listing)


@router.put("/api/v1/plans/{plan_key}", response_model=PlanResponse)
def change_plan(
    plan_key: str, payload: ChangePlanRequest, services: Services, actor: Administrator
) -> PlanResponse:
    """Rename a Plan or change its limits; its key stays. New limits apply at once to new
    rules, accounts, and tokens, and stop nothing that exists."""
    key = named_plan(plan_key)
    try:
        plan = _plan(key, payload.name, payload.limits)
        listing = services.plans.change_plan.execute(actor, plan)
    except InvalidPlan as error:
        raise problem_from(status.HTTP_422_UNPROCESSABLE_CONTENT, error) from error
    except PlanNotFound as error:
        raise problem_from(status.HTTP_404_NOT_FOUND, error) from error
    except AdministratorRequired as error:
        raise problem_from(status.HTTP_403_FORBIDDEN, error) from error
    return plan_response(listing)


@router.delete("/api/v1/plans/{plan_key}", status_code=status.HTTP_204_NO_CONTENT)
def remove_plan(plan_key: str, services: Services, actor: Administrator) -> None:
    """Remove a Plan that is not the default and that nobody has."""
    key = named_plan(plan_key)
    try:
        services.plans.remove_plan.execute(actor, key)
    except PlanNotFound as error:
        raise problem_from(status.HTTP_404_NOT_FOUND, error) from error
    except (PlanIsDefault, PlanInUse) as error:
        raise problem_from(status.HTTP_409_CONFLICT, error) from error
    except AdministratorRequired as error:
        raise problem_from(status.HTTP_403_FORBIDDEN, error) from error


@router.get("/api/v1/account/plan", response_model=OwnPlanResponse)
def own_plan(services: OwnServices) -> OwnPlanResponse:
    """What the signed-in User's Plan allows and how much of it they have, for Your plan. A
    fault reading Plans fails this request; each limit is still checked where it applies."""
    return own_plan_response(services.show_own_plan.execute())


def _plan(key: PlanKey, name: str, limits: PlanLimitsRequest) -> Plan:
    """The Plan a request describes, without spaces around its name; raises InvalidPlan."""
    return Plan(key, name.strip(), plan_limits(limits))
```

The `administrator` dependency already answers 403 before any lookup. Each route also turns
`AdministratorRequired` from its use case into 403, for an administrator whose role is removed
between the guard and the use case; without it that race would answer 500.

- [ ] **Step 9: Register the router**

In `src/calendar_sync/interfaces/api/app.py`, import the module:

```python
from calendar_sync.interfaces.api.routes import (
    account,
    accounts,
    activity,
    compatibility,
    health,
    incidents,
    integrations,
    plans,
    rules,
    session,
    setup,
    storage,
    users,
    watch_notices,
)
```

add `plans.OwnPlanServices` to `UserApiServices`:

```python
class UserApiServices(
    accounts.AccountServices,
    activity.ActivityServices,
    incidents.IncidentServices,
    integrations.IntegrationServices,
    plans.OwnPlanServices,
    rules.RuleServices,
    McpUserServices,
    Protocol,
):
    """Everything the routers read from one User's services."""
```

add `plans.PlansApiServices` to `ApiServices`:

```python
class ApiServices(
    session.SessionServices,
    users.AdministrationServices,
    setup.SetupServices,
    account.OwnAccountServices,
    accounts.AuthorizationServices,
    integrations.StatusServices,
    plans.PlansApiServices,
    storage.StorageServices,
    watch_notices.NoticeServices,
    McpServices,
    Protocol,
):
    """Everything the routers read from the composed container."""

    @property
    def identity(self) -> ApiIdentity: ...
    @property
    def administration(self) -> ApiAdministration: ...
    def for_user(self, user_id: UserId) -> UserApiServices: ...
```

and add `plans` after `users` in the router tuple in `create_app`:

```python
    for module in (
        health,
        setup,
        session,
        account,
        activity,
        accounts,
        compatibility,
        rules,
        incidents,
        storage,
        integrations,
        users,
        plans,
        watch_notices,
    ):
        app.router.routes.extend(module.router.routes)
```

`services: ApiServices = resolved` in `create_app` makes mypy prove the container has
`plans: PlanServices` (task 7) and that `for_user` gives `show_own_plan` (task 12).

- [ ] **Step 10: Assign a Plan in People, and put the Plan on the person page**

In `src/calendar_sync/interfaces/api/schemas.py`, add the `plan` field to `UserOverviewResponse`:

```python
class UserOverviewResponse(ApiResponse):
    """What the Operator Overview shows about one User, to an administrator and to that User:
    their Installation Status with calendars named "Calendar 1", "Calendar 2", and so on, and
    their resource use. Never a calendar's name or identifier, an account's email, or an event."""

    user: UserResponse
    status: StatusResponse
    resources: ResourceUseResponse
    plan: PersonPlanResponse | None
    """Their Plan, and their own if it differs; null while no Plan exists (ADR 0038)."""
```

In `src/calendar_sync/interfaces/api/routes/users.py`, change the module docstring's first
sentence:

```python
"""People and Who can join: the Registration Policy, Invitations, roles, Plans, disabling, and
deletion.

Every route here is an Installation Administrator's, except the two links people follow to join
or to choose a new password, which are public and need the link's token.
"""
```

replace the `calendar_sync` imports (from `from calendar_sync.application.identity.administration
import (` through `from calendar_sync.interfaces.api.status_payload import ...`) with:

```python
from calendar_sync.application.identity.administration import (
    AcceptInvitation,
    AdministratorRequired,
    ChangeRole,
    ChangeUserState,
    CheckInvitation,
    CheckPasswordReset,
    DeleteUser,
    DeletionResult,
    InviteUser,
    IssuePasswordReset,
    LinkAttemptsThrottled,
    LinkUnusable,
    ListInvitations,
    RegistrationClosed,
    RegistrationStatus,
    ResetPassword,
    RevokeInvitation,
    SetRegistrationPolicy,
    ShowRegistration,
    UserDeletionInterrupted,
    UserNotFound,
    YourOwnDeletion,
    YourOwnResetLink,
    YourOwnState,
)
from calendar_sync.application.identity.errors import (
    EmailTaken,
    IncorrectCredentials,
    PasswordPolicyViolation,
    PlanNotFound,
)
from calendar_sync.application.identity.plans import AssignPlan
from calendar_sync.application.identity.ports import IssuedLink, UserQuery, UserSort
from calendar_sync.application.operations.operator_overview import (
    OperatorOverview,
    OverviewQuery,
    UserOverview,
)
from calendar_sync.application.operations.status import StatusVerdict
from calendar_sync.domain.access import (
    InvalidEmail,
    LastAdministrator,
    OnlyMeNeedsOneUser,
    RegistrationPolicy,
    Role,
    User,
    UserId,
    UserState,
)
from calendar_sync.domain.errors import DomainValidationError
from calendar_sync.interfaces.api.dependencies import (
    Identity,
    administrator,
    app_services,
    current_user,
    set_session_cookie,
)
from calendar_sync.interfaces.api.plan_payload import named_plan, person_plan_response
from calendar_sync.interfaces.api.problems import ApiProblem, problem_from
from calendar_sync.interfaces.api.routes.session import SignedInAnswers, signed_in
from calendar_sync.interfaces.api.schemas import (
    AcceptInvitationRequest,
    AssignPlanRequest,
    IssuedLinkResponse,
    LinkRequest,
    LinkStatusResponse,
    PendingInvitationResponse,
    PeopleQuery,
    PersonPlanResponse,
    PersonResponse,
    RegistrationRequest,
    RegistrationResponse,
    ResetPasswordRequest,
    RoleRequest,
    SessionResponse,
    UserDeletionResponse,
    UserOverviewResponse,
    UserPageResponse,
    UserResponse,
    UserStateRequest,
)
from calendar_sync.interfaces.api.status_payload import resource_use_response, status_response
```

add `assign_plan` at the end of the `Administration` protocol:

```python
class Administration(Protocol):
    @property
    def show_registration(self) -> ShowRegistration: ...
    @property
    def set_registration_policy(self) -> SetRegistrationPolicy: ...
    @property
    def invite_user(self) -> InviteUser: ...
    @property
    def list_invitations(self) -> ListInvitations: ...
    @property
    def revoke_invitation(self) -> RevokeInvitation: ...
    @property
    def check_invitation(self) -> CheckInvitation: ...
    @property
    def accept_invitation(self) -> AcceptInvitation: ...
    @property
    def issue_password_reset(self) -> IssuePasswordReset: ...
    @property
    def check_password_reset(self) -> CheckPasswordReset: ...
    @property
    def reset_password(self) -> ResetPassword: ...
    @property
    def change_role(self) -> ChangeRole: ...
    @property
    def change_user_state(self) -> ChangeUserState: ...
    @property
    def delete_user(self) -> DeleteUser: ...
    @property
    def assign_plan(self) -> AssignPlan: ...
```

add the `assign_plan` route right after `change_state` (shown with it):

```python
@router.put("/api/v1/users/{user_id}/state", response_model=UserResponse)
def change_state(
    user_id: str, payload: UserStateRequest, services: Services, actor: Administrator
) -> UserResponse:
    try:
        changed = services.administration.change_user_state.execute(
            actor, _named_user(user_id), UserState(payload.state)
        )
    except UserNotFound as error:
        raise problem_from(status.HTTP_404_NOT_FOUND, error) from error
    except (LastAdministrator, YourOwnState) as error:
        raise problem_from(status.HTTP_409_CONFLICT, error) from error
    return _user(changed)


@router.put("/api/v1/users/{user_id}/plan", response_model=PersonPlanResponse)
def assign_plan(
    user_id: str, payload: AssignPlanRequest, services: Services, actor: Administrator
) -> PersonPlanResponse:
    """Give a User their own Plan, or with null return them to the Default Plan. Allowed while
    Plans are off, so an administrator can prepare; an administrator's own Plan limits them only
    once they stop administering."""
    subject = _named_user(user_id)
    plan = named_plan(payload.plan) if payload.plan is not None else None
    try:
        allowance = services.administration.assign_plan.execute(actor, subject, plan)
    except (UserNotFound, PlanNotFound) as error:
        raise problem_from(status.HTTP_404_NOT_FOUND, error) from error
    except AdministratorRequired as error:
        raise problem_from(status.HTTP_403_FORBIDDEN, error) from error
    return person_plan_response(allowance)
```

and fill the new field in `user_overview_response`:

```python
def user_overview_response(overview: UserOverview) -> UserOverviewResponse:
    allowance = overview.allowance
    return UserOverviewResponse(
        user=_user(overview.user),
        status=status_response(overview.status),
        resources=resource_use_response(overview),
        plan=person_plan_response(allowance) if allowance is not None else None,
    )
```

`_person` (People rows) does not change: `PersonResponse` carries no Plan in slice 1.

- [ ] **Step 11: Run the tests to verify they pass**

First confirm that the composition root already satisfies the new protocols, with no edit:

Run: `grep -nE "^    plans: PlanServices|^    assign_plan: AssignPlan|^    show_own_plan: ShowOwnPlan" src/calendar_sync/bootstrap/container.py`
Expected: three lines (`Container.plans`, `AdministrationServices.assign_plan`,
`UserServices.show_own_plan`). If one is missing, task 7 or 12 is incomplete: finish it there.

Run: `.venv/bin/pytest tests/adapters/test_plans_api.py tests/adapters/test_api_authorization.py tests/adapters/test_schema_enums.py tests/adapters/test_operator_overview_api.py tests/adapters/test_users_api.py -q`
Expected: PASS (36, 6, 18, 11, and the 11 of `test_users_api.py`).

Run: `.venv/bin/ruff format --check . && .venv/bin/ruff check . && .venv/bin/mypy && .venv/bin/lint-imports`
Expected: every check clean; `lint-imports` reports 10 contracts kept.

- [ ] **Step 12: Regenerate the OpenAPI schema and the frontend types**

Run: `.venv/bin/python scripts/export_openapi.py && (cd web && pnpm run api:types)`
Expected: `web/openapi.json` gains the paths `/api/v1/plans`, `/api/v1/plans/{plan_key}`,
`/api/v1/plan-settings`, `/api/v1/users/{user_id}/plan`, and `/api/v1/account/plan`, the twelve
new schemas, and `plan` in `UserOverviewResponse.required`; `web/src/lib/api-schema.ts` is
regenerated. Never edit either file by hand.

- [ ] **Step 13: Run the web type check to verify the fixtures fail**

Run: `cd web && pnpm run typecheck`
Expected: FAIL in `src/app.test.tsx` (`NOTHING_SET_UP`) and `src/features/person-page.test.tsx`
(`robin`): property `plan` is missing in the object but required in `UserOverviewResponse`.

- [ ] **Step 14: Give the two overview fixtures no Plan**

In `web/src/app.test.tsx`, `NOTHING_SET_UP` ends:

```tsx
  resources: { rules: 0, connected_accounts: 0, activity_entries: 0, provider_calls: [], since: "2026-09-01" },
  plan: null,
}
```

In `web/src/features/person-page.test.tsx`, `robin` ends:

```tsx
  resources: {
    rules: 1,
    connected_accounts: 2,
    activity_entries: 40,
    provider_calls: [{ provider: "google", calls: 75, rate_limited: 1, failed: 0 }],
    since: "2026-09-10",
  },
  plan: null,
}
```

Task 16 gives the person page fixtures a Plan; `null` is what the server sends while no Plan
exists.

- [ ] **Step 15: Run the web checks and the build**

Run: `cd web && pnpm run api:check && pnpm run typecheck && pnpm run lint && pnpm exec vitest run src/app.test.tsx src/features/person-page.test.tsx && pnpm run knip && pnpm run build`
Expected: every check clean, both Vitest files pass, and the build succeeds.

This task changes no runtime web code (the generated schema is types only, and the other two
files are tests), so the rebuilt bundle differs only by the commit SHA the build embeds. From the
repository root, confirm it, then restore the committed bundle:

```bash
old_js=$(git show HEAD:src/calendar_sync/interfaces/api/static/index.html | grep -o 'assets/index-[A-Za-z0-9_-]*\.js')
new_js=$(grep -o 'assets/index-[A-Za-z0-9_-]*\.js' src/calendar_sync/interfaces/api/static/index.html)
diff <(git show "HEAD:src/calendar_sync/interfaces/api/static/$old_js" | sed -E 's#tree/[0-9a-f]{40}#tree/SHA#') <(sed -E 's#tree/[0-9a-f]{40}#tree/SHA#' "src/calendar_sync/interfaces/api/static/$new_js") && echo "only the commit SHA differs"
git checkout -- src/calendar_sync/interfaces/api/static
git clean -fq -- src/calendar_sync/interfaces/api/static
```

Expected: `only the commit SHA differs`, then `git status --short src/calendar_sync/interfaces/api/static`
prints nothing. If the diff shows any other change, an earlier task left the bundle stale: run
`cd web && pnpm run build` again and add `src/calendar_sync/interfaces/api/static` to the commit.

- [ ] **Step 16: Run the backend gate**

Run: `.venv/bin/ruff format --check . && .venv/bin/ruff check . && .venv/bin/mypy && .venv/bin/lint-imports && .venv/bin/pytest --cov --cov-report=term-missing --cov-fail-under=80`
Expected: every check clean, `tests/test_openapi_contract.py` passes (the committed schema matches
the routes), and total coverage is at least 80%.

- [ ] **Step 17: Commit**

```bash
git add src/calendar_sync/interfaces/api/schemas.py src/calendar_sync/interfaces/api/plan_payload.py src/calendar_sync/interfaces/api/routes/plans.py src/calendar_sync/interfaces/api/routes/users.py src/calendar_sync/interfaces/api/app.py tests/adapters/test_plans_api.py tests/adapters/test_api_authorization.py tests/adapters/test_schema_enums.py tests/adapters/test_operator_overview_api.py web/openapi.json web/src/lib/api-schema.ts web/src/app.test.tsx web/src/features/person-page.test.tsx
git commit -F - <<'EOF'
Let administrators define, assign, and turn on Plans through the Web API

Administrators list, define, change, and remove Plans, choose the
Default Plan, turn Plans on and off, and give a person their own Plan;
every User reads Your plan. A Plan key this release refuses names no
Plan, so it answers 404 plan_not_found. The person page's overview
carries the Plan once one exists. The frontend types are regenerated
for the Web UI tasks that follow.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
```

## Part 8: Web foundation and Administration, Plans (Tasks 14 and 15)

These tasks follow the contract `.context/plans-slice1-contract.md` (sections 3.19 to 3.21 and the
task map). Run every `pnpm` command from inside `web/` (Corepack reads its version there). Every
command below starts with `cd web &&` from the repository root, because each shell starts there.

Both tasks were checked end to end against a copy of `web/` with the task 6, 9, 11, and 13 outputs
in place: `tsc -b`, `eslint . --max-warnings 0`, `knip`, `react-doctor`, the full Vitest suite, and
`vite build` all pass.

### Task 14: Web foundation

**Files:**
- Modify: `web/src/lib/api.ts` (new types after `RegistrationPolicy`; new `api` members: `ownPlan` after `setInstantSync`; `plans`, `setPlansSetting`, `definePlan`, `changePlan`, `removePlan` after `setRegistrationPolicy`; `setPersonPlan` after `setPersonState`)
- Create: `web/src/lib/plans.ts`
- Create: `web/src/lib/use-own-plan.ts`
- Create: `web/src/lib/use-plans.ts`
- Create: `web/src/components/your-plan-link.tsx`
- Modify: `web/src/lib/use-rule-commands.ts` (imports; `RULE_CHANGE_QUERIES`)
- Modify: `web/src/lib/use-account-commands.ts` (imports; `disconnect` and `permanentDelete` mutations)
- Modify: `web/src/lib/use-integration-tokens.ts` (imports; `issue` and `revoke` mutations)
- Modify: `web/src/i18n/locales/en/common.json` (`plan.accountLimit`)
- Modify: `web/src/i18n/locales/en/settings.json` (new `ownPlan` group after `ownAccount`; new `plans` group after `registration` with `limits`, `interval`, `saved`)
- Modify: `web/src/i18n/locales/en/people.json` (new `plan.fact` group after `person`)
- Modify: `web/src/i18n/catalog.test.ts` (`TEMPLATE_VALUES`)
- Regenerate: `src/calendar_sync/interfaces/api/static/` (`pnpm run build`)
- Test: `web/src/lib/plans.test.ts` (new), `web/src/lib/use-own-plan.test.tsx` (new), `web/src/lib/use-plans.test.tsx` (new), `web/src/components/your-plan-link.test.tsx` (new), `web/src/lib/api.test.ts` (one new case)

**Interfaces:**
- Consumes:
  - Task 13: the regenerated `web/src/lib/api-schema.ts` with `components["schemas"]` `PlansResponse`, `PlanResponse`, `PlanLimitsResponse`, `DefinePlanRequest`, `ChangePlanRequest`, `PersonPlanResponse` (`basis`, `plan: AppliedPlanResponse | null`, `assigned: PlanNameResponse | null`), `OwnPlanResponse` (`basis`, `plan`, `limits`, `rules_counted`, `connected_accounts`, `integration_tokens`, `instant`, `poll_every_minutes`, `may_connect_account`, `may_issue_token`, `over_rule_limit`), and the paths `GET`/`POST /api/v1/plans`, `PUT`/`DELETE /api/v1/plans/{plan_key}`, `PUT /api/v1/plan-settings`, `PUT /api/v1/users/{user_id}/plan`, `GET /api/v1/account/plan`.
  - Task 9: `RuleDetailResponse.can_start: boolean` and `RuleDetailResponse.rule_limit: number | null` in the same schema, so `RuleDetail` carries them.
  - Task 11: `export function yourPlanPath(): string` in `web/src/lib/navigation.ts` (answers `"/settings/account#your-plan"`), and the `common.plan` group in `common.json` with `seeYourPlan` "See your plan".
  - Task 6: `common.apiError.plan_limit_reached`, `common.apiError.plan_limit_reached_rules` (plural), `common.apiError.plan_limit_reached_integration_tokens` (plural) in `common.json`.
- Produces:
  - `web/src/lib/api.ts`: types `PlansOverview`, `PlanSummary`, `PlanLimits`, `SyncInterval`, `PlanPayload`, `PlanChange`, `PersonPlan`, `OwnPlan`; `api.ownPlan(): Promise<OwnPlan>`, `api.plans(): Promise<PlansOverview>`, `api.setPlansSetting(enabled: boolean, defaultPlan: string | null): Promise<PlansOverview>`, `api.definePlan(payload: PlanPayload): Promise<PlanSummary>`, `api.changePlan(key: string, payload: PlanChange): Promise<PlanSummary>`, `api.removePlan(key: string): Promise<undefined>`, `api.setPersonPlan(userId: string, plan: string | null): Promise<PersonPlan>`.
  - `web/src/lib/plans.ts`: `ownPlanShown(plan: OwnPlan | undefined, policy: RegistrationPolicy | undefined): boolean`; `planWarning(plan: OwnPlan | undefined): boolean`; `startRefusal(i18n: I18n, detail: Pick<RuleDetail, "can_start" | "rule_limit">): string | null`; `intervalLabel(i18n: I18n, interval: SyncInterval): string`; `planLimitsSummary(i18n: I18n, limits: PlanLimits): string` (the three counts; the interval shows apart); `ownPlanSummary(i18n: I18n, plan: OwnPlan): string | null` (null unless a Plan limits the User); `personPlanFact(i18n: I18n, plan: PersonPlan): string`.
  - `web/src/lib/use-own-plan.ts`: `OWN_PLAN_QUERY = ["own-plan"] as const`; `useOwnPlan()` (the `useQuery` result); `usePlanWarning(): boolean`; `useAccountLimitReason(): string | undefined`; `useTokenLimitReason(): string | undefined`. A pending, failed, or `{}` answer gives `false` and `undefined`.
  - `web/src/lib/use-plans.ts`: `PLANS_QUERY = ["plans"] as const`; `usePlans()` answering `{ plans, setting, define, change, remove, message }` with `setting.mutate({ enabled: boolean; defaultPlan: string | null })`, `define.mutate(payload: PlanPayload)`, `change.mutate({ key: string; payload: PlanChange })`, `remove.mutate(key: string)`, and `message: string`; `export type PlanCommands = ReturnType<typeof usePlans>`.
  - `web/src/components/your-plan-link.tsx`: `YourPlanLink()`.
  - `RULE_CHANGE_QUERIES` now ends with `OWN_PLAN_QUERY`.
  - i18n keys: `common.plan.accountLimit`; `settings.plans.limits.*`, `settings.plans.interval.*`, `settings.plans.saved.*`; `settings.ownPlan.name`, `nameDefault`, `summary`, `rules`, `rulesUnlimited`, `accounts`, `accountsUnlimited`, `tokens`, `tokensUnlimited`, `noTokens`, `cadence.instant`, `cadence.every`; `people.plan.fact.*`.

- [ ] **Step 1: Confirm the tasks this one builds on are in place**

Run:

```sh
grep -c "OwnPlanResponse\|PlansResponse\|PersonPlanResponse\|can_start" web/src/lib/api-schema.ts
grep -n "export function yourPlanPath" web/src/lib/navigation.ts
grep -n '"seeYourPlan"\|"plan_limit_reached_rules"\|"plan_limit_reached_integration_tokens"' web/src/i18n/locales/en/common.json
```

Expected: a count above 0; one `yourPlanPath` line; three `common.json` lines. If any is missing, finish task 6, 9, 11, or 13 first.

- [ ] **Step 2: Write the failing tests for the Plan helpers and the API methods (cycle A)**

Create `web/src/lib/plans.test.ts`:

```ts
import { describe, expect, it } from "vitest"

import { testI18n } from "@/i18n/testing"
import type { OwnPlan, PersonPlan, PlanLimits, RegistrationPolicy, SyncInterval } from "@/lib/api"
import {
  intervalLabel,
  ownPlanShown,
  ownPlanSummary,
  personPlanFact,
  planLimitsSummary,
  planWarning,
  startRefusal,
} from "@/lib/plans"

const i18n = testI18n()

const FAMILY_LIMITS: PlanLimits = { rules: 5, connected_accounts: 3, integration_tokens: 2, sync_interval: "instant" }
const FREE_LIMITS: PlanLimits = { rules: 1, connected_accounts: 1, integration_tokens: 0, sync_interval: "5_minutes" }
const UNLIMITED: PlanLimits = { rules: null, connected_accounts: null, integration_tokens: null, sync_interval: "instant" }

/** A User the Family Plan limits, their own Plan, with room left for everything. */
const family: OwnPlan = {
  basis: "plan",
  plan: { key: "family", name: "Family", on_default: false },
  limits: FAMILY_LIMITS,
  rules_counted: 3,
  connected_accounts: 2,
  integration_tokens: 1,
  instant: true,
  poll_every_minutes: 5,
  may_connect_account: true,
  may_issue_token: true,
  over_rule_limit: false,
}

const plansOff: OwnPlan = {
  ...family,
  basis: "plans_off",
  plan: null,
  limits: null,
}

const administering: OwnPlan = { ...plansOff, basis: "administrator" }

describe("ownPlanShown", () => {
  it.each<[string, OwnPlan | undefined, RegistrationPolicy | undefined, boolean]>([
    ["a User a Plan limits", family, undefined, true],
    ["a User a Plan limits, under Invitation only", family, "invitation_only", true],
    ["anyone while Plans are off", plansOff, "invitation_only", false],
    ["an administrator under Only me", administering, "only_me", false],
    ["an administrator under Invitation only", administering, "invitation_only", true],
    ["an administrator while the Registration Policy loads", administering, undefined, false],
    ["a read that has not answered", undefined, "invitation_only", false],
    ["an empty answer", {} as OwnPlan, "invitation_only", false],
  ])("for %s", (_case, plan, policy, shown) => {
    expect(ownPlanShown(plan, policy)).toBe(shown)
  })
})

describe("planWarning", () => {
  it("warns only while more rules count than the Plan allows", () => {
    expect(planWarning({ ...family, rules_counted: 6, over_rule_limit: true })).toBe(true)
    expect(planWarning({ ...family, rules_counted: 5 })).toBe(false)
    expect(planWarning(plansOff)).toBe(false)
  })

  it("never warns without an answer", () => {
    expect(planWarning(undefined)).toBe(false)
    expect(planWarning({} as OwnPlan)).toBe(false)
  })
})

describe("startRefusal", () => {
  it("says nothing when the rule may start", () => {
    expect(startRefusal(i18n, { can_start: true, rule_limit: 3 })).toBeNull()
    expect(startRefusal(i18n, { can_start: true, rule_limit: null })).toBeNull()
  })

  it("gives the rule limit's message, in the plural its limit needs", () => {
    expect(startRefusal(i18n, { can_start: false, rule_limit: 1 })).toBe(
      "Your plan lets 1 rule sync. Pause or remove it to start this rule.",
    )
    expect(startRefusal(i18n, { can_start: false, rule_limit: 3 })).toBe(
      "Your plan lets 3 rules sync. Pause or remove one to start this rule.",
    )
  })

  it("falls back to the general limit message without a limit", () => {
    expect(startRefusal(i18n, { can_start: false, rule_limit: null })).toBe(
      "Your plan's limit is reached. Settings, Your account, Your plan shows what it allows.",
    )
  })
})

describe("intervalLabel", () => {
  it.each<[SyncInterval, string]>([
    ["instant", "Instant sync, and a check every 5 minutes"],
    ["5_minutes", "Every 5 minutes"],
    ["10_minutes", "Every 10 minutes"],
    ["15_minutes", "Every 15 minutes"],
    ["30_minutes", "Every 30 minutes"],
    ["60_minutes", "Every hour"],
  ])("names %s", (interval, label) => {
    expect(intervalLabel(i18n, interval)).toBe(label)
  })
})

describe("planLimitsSummary", () => {
  it("counts each limit", () => {
    expect(planLimitsSummary(i18n, FAMILY_LIMITS)).toBe("5 rules, 3 calendar accounts, 2 tokens")
    expect(planLimitsSummary(i18n, { ...FAMILY_LIMITS, rules: 1, connected_accounts: 1, integration_tokens: 1 })).toBe(
      "1 rule, 1 calendar account, 1 token",
    )
  })

  it("names unlimited values and a Plan that offers no tokens", () => {
    expect(planLimitsSummary(i18n, UNLIMITED)).toBe("Unlimited rules, unlimited calendar accounts, unlimited tokens")
    expect(planLimitsSummary(i18n, FREE_LIMITS)).toBe("1 rule, 1 calendar account, no tokens")
  })
})

describe("ownPlanSummary", () => {
  it("counts what the User has against each limit, with Instant Sync", () => {
    expect(ownPlanSummary(i18n, family)).toBe(
      "Family: 3 of 5 rules counted, 2 of 3 calendar accounts, 1 of 2 tokens, instant sync included",
    )
  })

  it("names the Default Plan and its slower syncs", () => {
    const free: OwnPlan = {
      ...family,
      plan: { key: "free", name: "Free", on_default: true },
      limits: FREE_LIMITS,
      rules_counted: 1,
      connected_accounts: 1,
      integration_tokens: 0,
      instant: false,
      poll_every_minutes: 5,
    }
    expect(ownPlanSummary(i18n, free)).toBe(
      "Free (default): 1 of 1 rule counted, 1 of 1 calendar account, no Integration Tokens, syncs about every 5 minutes",
    )
  })

  it("counts without a limit where the Plan sets none", () => {
    expect(ownPlanSummary(i18n, { ...family, limits: UNLIMITED, rules_counted: 1, connected_accounts: 4, integration_tokens: 0 })).toBe(
      "Family: 1 rule counted, 4 calendar accounts, 0 tokens, instant sync included",
    )
  })

  it("still counts tokens kept from before a Plan that offers none", () => {
    expect(ownPlanSummary(i18n, { ...family, limits: { ...FAMILY_LIMITS, integration_tokens: 0 }, integration_tokens: 2 })).toBe(
      "Family: 3 of 5 rules counted, 2 of 3 calendar accounts, 2 of 0 tokens, instant sync included",
    )
  })

  it("has nothing to say when no Plan limits the User", () => {
    expect(ownPlanSummary(i18n, plansOff)).toBeNull()
    expect(ownPlanSummary(i18n, administering)).toBeNull()
  })
})

describe("personPlanFact", () => {
  const familyName = { key: "family", name: "Family" }

  it.each<[string, PersonPlan, string]>([
    ["their own Plan", { basis: "plan", plan: { ...familyName, on_default: false }, assigned: familyName }, "Family"],
    [
      "the Default Plan",
      { basis: "plan", plan: { key: "free", name: "Free", on_default: true }, assigned: null },
      "Free (default)",
    ],
    ["their own Plan while Plans are off", { basis: "plans_off", plan: null, assigned: familyName }, "Family, once plans are on"],
    [
      "the Default Plan while Plans are off",
      { basis: "plans_off", plan: null, assigned: null },
      "The default plan, once plans are on",
    ],
    ["an administrator", { basis: "administrator", plan: null, assigned: null }, "No plan limits administrators"],
    [
      "an administrator given a Plan",
      { basis: "administrator", plan: null, assigned: familyName },
      "No plan limits administrators (assigned: Family)",
    ],
  ])("names %s", (_case, plan, fact) => {
    expect(personPlanFact(i18n, plan)).toBe(fact)
  })
})
```

In `web/src/lib/api.test.ts`, add this case at the end of the `describe("api routes", ...)` block,
right after the existing `"returns undefined for an empty success response"` case (shown for
context):

```ts
  it("returns undefined for an empty success response", async () => {
    stubFetch(204)
    await expect(api.logOut()).resolves.toBeUndefined()
  })

  it("sends each Plans change to its route, with null for no default and no Plan of one's own", async () => {
    const limits = { rules: 5, connected_accounts: null, integration_tokens: 0, sync_interval: "instant" } as const
    const cases: [() => Promise<unknown>, ReturnType<typeof requested>][] = [
      [() => api.ownPlan(), { url: "/api/v1/account/plan", method: "GET", body: undefined }],
      [() => api.plans(), { url: "/api/v1/plans", method: "GET", body: undefined }],
      [
        () => api.setPlansSetting(false, null),
        { url: "/api/v1/plan-settings", method: "PUT", body: JSON.stringify({ enabled: false, default_plan: null }) },
      ],
      [
        () => api.definePlan({ key: "family", name: "Family", limits }),
        { url: "/api/v1/plans", method: "POST", body: JSON.stringify({ key: "family", name: "Family", limits }) },
      ],
      [
        () => api.changePlan("family", { name: "Family", limits }),
        { url: "/api/v1/plans/family", method: "PUT", body: JSON.stringify({ name: "Family", limits }) },
      ],
      [() => api.removePlan("a b"), { url: "/api/v1/plans/a%20b", method: "DELETE", body: undefined }],
      [
        () => api.setPersonPlan("user-1", null),
        { url: "/api/v1/users/user-1/plan", method: "PUT", body: JSON.stringify({ plan: null }) },
      ],
    ]
    for (const [send, expected] of cases) {
      const fetch = stubFetch(expected.method === "DELETE" ? 204 : 200)
      await send()
      expect(requested(fetch)).toEqual(expected)
    }
  })
})
```

- [ ] **Step 3: Run them to verify they fail**

Run: `cd web && pnpm exec vitest run src/lib/plans.test.ts src/lib/api.test.ts`

Expected: FAIL. `src/lib/plans.test.ts` cannot load (`Error: Cannot find package '@/lib/plans'` or `Failed to resolve import "@/lib/plans"`), and `api routes > sends each Plans change to its route...` fails with `TypeError: api.ownPlan is not a function`. The other 16 `api.test.ts` cases pass.

- [ ] **Step 4: Implement the API methods, the Plan helpers, and their messages (cycle A)**

In `web/src/lib/api.ts`, add the Plan types right after the Registration types:

```ts
/** Who may become a User: Only Me, the default, or Invitation Only. */
export type Registration = Schemas["RegistrationResponse"]
export type RegistrationPolicy = Registration["policy"]
/** Every Plan, whether Plans limit people, the Default Plan, and the sync intervals offered now. */
export type PlansOverview = Schemas["PlansResponse"]
/** One Plan as an administrator manages it: its limits, and who has it. */
export type PlanSummary = Schemas["PlanResponse"]
/** What a Plan allows; null means unlimited. */
export type PlanLimits = Schemas["PlanLimitsResponse"]
/** How soon a Plan's rules sync (ADR 0038). */
export type SyncInterval = PlanLimits["sync_interval"]
/** A new Plan: its key, chosen once, its name, and its limits. */
export type PlanPayload = Schemas["DefinePlanRequest"]
/** A Plan's new name and limits; its key never changes. */
export type PlanChange = Schemas["ChangePlanRequest"]
/** Which Plan limits one person, as the Operator Overview shows it, and the Plan they were given. */
export type PersonPlan = Schemas["PersonPlanResponse"]
/** What the signed-in User's Plan allows and how much of it they have, for Your plan. */
export type OwnPlan = Schemas["OwnPlanResponse"]
/** A User as an Installation Administrator sees them: never their calendars, rules, or events. */
export type Person = Schemas["UserResponse"]
```

In the `api` object, add `ownPlan` right after `setInstantSync`:

```ts
  /** Whether the signed-in User's rules run soon after their provider reports a change. */
  setInstantSync: (instantSync: boolean) =>
    call("/api/v1/account/instant-sync", "put", { body: { instant_sync: instantSync } }),
  /** What the signed-in User's Plan allows and how much of it they have. */
  ownPlan: () => call("/api/v1/account/plan", "get"),
```

then the Plans methods right after `setRegistrationPolicy`:

```ts
  registration: () => call("/api/v1/registration", "get"),
  setRegistrationPolicy: (policy: RegistrationPolicy) => call("/api/v1/registration", "put", { body: { policy } }),
  plans: () => call("/api/v1/plans", "get"),
  /** Turning Plans off keeps every Plan; send the current default when only the switch changes. */
  setPlansSetting: (enabled: boolean, defaultPlan: string | null) =>
    call("/api/v1/plan-settings", "put", { body: { enabled, default_plan: defaultPlan } }),
  definePlan: (payload: PlanPayload) => call("/api/v1/plans", "post", { body: payload }),
  changePlan: (key: string, payload: PlanChange) =>
    call("/api/v1/plans/{plan_key}", "put", { params: { plan_key: key }, body: payload }),
  removePlan: (key: string) => call("/api/v1/plans/{plan_key}", "delete", { params: { plan_key: key } }),
```

and `setPersonPlan` right after `setPersonState`:

```ts
  setPersonState: (userId: string, state: PersonState) =>
    call("/api/v1/users/{user_id}/state", "put", { params: { user_id: userId }, body: { state } }),
  /** Gives a person their own Plan; null returns them to the Default Plan. */
  setPersonPlan: (userId: string, plan: string | null) =>
    call("/api/v1/users/{user_id}/plan", "put", { params: { user_id: userId }, body: { plan } }),
```

Create `web/src/lib/plans.ts`:

```ts
import type { I18n } from "@/i18n/translator"
import type { OwnPlan, PersonPlan, PlanLimits, RegistrationPolicy, RuleDetail, SyncInterval } from "@/lib/api"

/**
 * Whether Your plan shows: only when a Plan limits the User, or for an administrator while other
 * people can join. It stays hidden while Plans are off, and under Only Me, where the only person
 * administers. Only an administrator can read the Registration Policy, so `policy` is undefined
 * for everyone else and while it loads.
 */
export function ownPlanShown(plan: OwnPlan | undefined, policy: RegistrationPolicy | undefined): boolean {
  if (plan?.basis === "plan") return true
  if (plan?.basis === "administrator") return policy !== undefined && policy !== "only_me"
  return false
}

/**
 * Whether a privacy edit, a Pause, or a Disconnect may keep a rule from starting again: only Rule
 * Replacement keeps a rule's place under the rule limit, and the User has more rules counted than
 * their Plan allows (ADR 0038).
 */
export function planWarning(plan: OwnPlan | undefined): boolean {
  return plan?.over_rule_limit === true
}

/** The refusal Start would meet, or null when the rule may start; a refused Start shows the same text. */
export function startRefusal(
  { t }: I18n,
  { can_start, rule_limit }: Pick<RuleDetail, "can_start" | "rule_limit">,
): string | null {
  if (can_start) return null
  return rule_limit === null
    ? t("common.apiError.plan_limit_reached")
    : t("common.apiError.plan_limit_reached_rules", { count: rule_limit })
}

/** How soon a Plan's rules sync, as an administrator chooses it. */
export function intervalLabel({ t }: I18n, interval: SyncInterval): string {
  return t(`settings.plans.interval.${interval}`)
}

function tokenLimit({ t }: I18n, tokens: number | null): string {
  if (tokens === null) return t("settings.plans.limits.unlimitedTokens")
  return tokens === 0 ? t("settings.plans.limits.noTokens") : t("settings.plans.limits.tokens", { count: tokens })
}

/** A Plan's counts on its Administration row: rules, calendar accounts, then Integration Tokens. */
export function planLimitsSummary(i18n: I18n, { rules, connected_accounts, integration_tokens }: PlanLimits): string {
  const { t } = i18n
  return i18n.format.unitList([
    rules === null ? t("settings.plans.limits.unlimitedRules") : t("settings.plans.limits.rules", { count: rules }),
    connected_accounts === null
      ? t("settings.plans.limits.unlimitedAccounts")
      : t("settings.plans.limits.accounts", { count: connected_accounts }),
    tokenLimit(i18n, integration_tokens),
  ])
}

function ruleUse({ t }: I18n, used: number, limit: number | null): string {
  return limit === null
    ? t("settings.ownPlan.rulesUnlimited", { count: used })
    : t("settings.ownPlan.rules", { used, count: limit })
}

function accountUse({ t }: I18n, used: number, limit: number | null): string {
  return limit === null
    ? t("settings.ownPlan.accountsUnlimited", { count: used })
    : t("settings.ownPlan.accounts", { used, count: limit })
}

function tokenUse({ t }: I18n, used: number, limit: number | null): string {
  if (limit === null) return t("settings.ownPlan.tokensUnlimited", { count: used })
  // A Plan may offer no tokens; one lowered to none still counts the tokens kept from before.
  if (limit === 0 && used === 0) return t("settings.ownPlan.noTokens")
  return t("settings.ownPlan.tokens", { used, count: limit })
}

/**
 * Your plan's one line, such as "Family: 3 of 5 rules counted, 2 of 3 calendar accounts, 1 of 2
 * tokens, instant sync included". Null when no Plan limits the User, so there is none to name.
 */
export function ownPlanSummary(i18n: I18n, plan: OwnPlan): string | null {
  const { plan: applied, limits } = plan
  if (applied === null || limits === null) return null
  const { t } = i18n
  return t("settings.ownPlan.summary", {
    plan: t(applied.on_default ? "settings.ownPlan.nameDefault" : "settings.ownPlan.name", { name: applied.name }),
    rules: ruleUse(i18n, plan.rules_counted, limits.rules),
    accounts: accountUse(i18n, plan.connected_accounts, limits.connected_accounts),
    tokens: tokenUse(i18n, plan.integration_tokens, limits.integration_tokens),
    cadence: plan.instant
      ? t("settings.ownPlan.cadence.instant")
      : t("settings.ownPlan.cadence.every", { count: plan.poll_every_minutes }),
  })
}

/**
 * The Plan fact on a person's page: the Plan that limits them, the one that will once Plans are
 * on, or that no Plan limits an administrator, with the Plan they were given if any.
 */
export function personPlanFact({ t }: I18n, { basis, plan, assigned }: PersonPlan): string {
  if (basis === "administrator") {
    return assigned
      ? t("people.plan.fact.administratorAssigned", { name: assigned.name })
      : t("people.plan.fact.administrator")
  }
  if (basis === "plan" && plan) {
    return plan.on_default
      ? t("people.plan.fact.default", { name: plan.name })
      : t("people.plan.fact.own", { name: plan.name })
  }
  return assigned ? t("people.plan.fact.later", { name: assigned.name }) : t("people.plan.fact.laterDefault")
}
```

In `web/src/i18n/locales/en/settings.json`, add the `ownPlan` group between the end of `ownAccount`
and `registration` (the two lines above it and the line below it are the existing ones):

```json
      "pending": "Deleting…"
    }
  },
  "ownPlan": {
    "name": "{name}",
    "nameDefault": "{name} (default)",
    "summary": "{plan}: {rules}, {accounts}, {tokens}, {cadence}",
    "rules": {
      "one": "{used} of {count} rule counted",
      "other": "{used} of {count} rules counted"
    },
    "rulesUnlimited": {
      "one": "{count} rule counted",
      "other": "{count} rules counted"
    },
    "accounts": {
      "one": "{used} of {count} calendar account",
      "other": "{used} of {count} calendar accounts"
    },
    "accountsUnlimited": {
      "one": "{count} calendar account",
      "other": "{count} calendar accounts"
    },
    "tokens": {
      "one": "{used} of {count} token",
      "other": "{used} of {count} tokens"
    },
    "tokensUnlimited": {
      "one": "{count} token",
      "other": "{count} tokens"
    },
    "noTokens": "no Integration Tokens",
    "cadence": {
      "instant": "instant sync included",
      "every": {
        "one": "syncs about every minute",
        "other": "syncs about every {count} minutes"
      }
    }
  },
  "registration": {
```

and the `plans` group between the end of `registration` and `links`:

```json
      "invitationOnly": "People can now join with an invitation link."
    }
  },
  "plans": {
    "limits": {
      "rules": {
        "one": "{count} rule",
        "other": "{count} rules"
      },
      "accounts": {
        "one": "{count} calendar account",
        "other": "{count} calendar accounts"
      },
      "tokens": {
        "one": "{count} token",
        "other": "{count} tokens"
      },
      "unlimitedRules": "Unlimited rules",
      "unlimitedAccounts": "unlimited calendar accounts",
      "unlimitedTokens": "unlimited tokens",
      "noTokens": "no tokens"
    },
    "interval": {
      "instant": "Instant sync, and a check every 5 minutes",
      "5_minutes": "Every 5 minutes",
      "10_minutes": "Every 10 minutes",
      "15_minutes": "Every 15 minutes",
      "30_minutes": "Every 30 minutes",
      "60_minutes": "Every hour"
    }
  },
  "links": {
```

In `web/src/i18n/locales/en/people.json`, add the `plan` group between the end of `person` and
`tabs`:

```json
    "documentTitle": "{name} – People"
  },
  "plan": {
    "fact": {
      "own": "{name}",
      "default": "{name} (default)",
      "later": "{name}, once plans are on",
      "laterDefault": "The default plan, once plans are on",
      "administrator": "No plan limits administrators",
      "administratorAssigned": "No plan limits administrators (assigned: {name})"
    }
  },
  "tabs": {
```

The wording keeps the Web UI's sentence-case "instant sync" (as `settings.ownAccount.instantSync`
and `rule-details.json` write it). `unlimitedAccounts`, `unlimitedTokens`, and `noTokens` start
lower-case because `planLimitsSummary` lists them after the rule count; `unlimitedRules` always
comes first.

In `web/src/i18n/catalog.test.ts`, give the interval template its values in `TEMPLATE_VALUES`,
right after the Instant Sync entry:

```ts
  "settings.ownAccount.instantSync.blocked.*": ["not_in_plan", "no_public_address", "not_reaching", "unknown"],
  "settings.plans.interval.*": ["instant", "5_minutes", "10_minutes", "15_minutes", "30_minutes", "60_minutes"],
```

- [ ] **Step 5: Run them to verify they pass**

Run: `cd web && pnpm exec vitest run src/lib/plans.test.ts src/lib/api.test.ts src/i18n/catalog.test.ts && pnpm run typecheck`

Expected: PASS (`plans.test.ts` 32 tests, `api.test.ts` 17 tests, `catalog.test.ts` all green: every new key is named in `lib/plans.ts`, and `settings.plans.interval.*` has its values). Typecheck clean.

- [ ] **Step 6: Write the failing test for the own-plan hooks (cycle B)**

Create `web/src/lib/use-own-plan.test.tsx`:

```tsx
/* @vitest-environment happy-dom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, useEffect } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, describe, expect, it, vi } from "vitest"

import { StaticI18nProvider } from "@/i18n/provider"
import { testI18n } from "@/i18n/testing"
import type { OwnPlan } from "@/lib/api"
import {
  OWN_PLAN_QUERY,
  useAccountLimitReason,
  useOwnPlan,
  usePlanWarning,
  useTokenLimitReason,
} from "@/lib/use-own-plan"

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

/** A User at every limit of their Plan, with more rules counted than it allows. */
const atEveryLimit: OwnPlan = {
  basis: "plan",
  plan: { key: "free", name: "Free", on_default: true },
  limits: { rules: 1, connected_accounts: 2, integration_tokens: 0, sync_interval: "5_minutes" },
  rules_counted: 2,
  connected_accounts: 2,
  integration_tokens: 0,
  instant: false,
  poll_every_minutes: 5,
  may_connect_account: false,
  may_issue_token: false,
  over_rule_limit: true,
}

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status < 400, status, json: () => Promise.resolve(body) } as Response
}

type Hints = { loaded: boolean; warning: boolean; account: string | undefined; token: string | undefined }

let root: Root | null = null
let hints: Hints = { loaded: false, warning: false, account: undefined, token: undefined }
let queryClient: QueryClient

function Probe({ onHints }: { onHints: (next: Hints) => void }) {
  const loaded = !useOwnPlan().isPending
  const warning = usePlanWarning()
  const account = useAccountLimitReason()
  const token = useTokenLimitReason()
  useEffect(() => {
    onHints({ loaded, warning, account, token })
  })
  return null
}

async function render(answer: Response) {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.resolve(answer)),
  )
  queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  root = createRoot(document.createElement("div"))
  act(() => {
    root?.render(
      <StaticI18nProvider i18n={testI18n()}>
        <QueryClientProvider client={queryClient}>
          <Probe
            onHints={(next) => {
              hints = next
            }}
          />
        </QueryClientProvider>
      </StaticI18nProvider>,
    )
  })
  for (let i = 0; i < 4; i += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0))
    })
  }
}

afterEach(() => {
  if (root) act(() => root?.unmount())
  root = null
  vi.restoreAllMocks()
})

describe("own plan hints", () => {
  it("reads the signed-in User's Plan once, under its own key", async () => {
    await render(jsonResponse(atEveryLimit))
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(vi.mocked(fetch).mock.calls[0]?.[0]).toBe("/api/v1/account/plan")
    expect(queryClient.getQueryData(OWN_PLAN_QUERY)).toEqual(atEveryLimit)
  })

  it("warns and says why Connect and new tokens are unavailable at the Plan's limits", async () => {
    await render(jsonResponse(atEveryLimit))
    expect(hints).toEqual({
      loaded: true,
      warning: true,
      account: "Your plan allows 2 calendar accounts, and disconnected accounts count too.",
      token: "Your plan allows at most 0 Integration Tokens. Revoked tokens do not count.",
    })
  })

  it("says nothing while the Plan has room", async () => {
    await render(
      jsonResponse({ ...atEveryLimit, may_connect_account: true, may_issue_token: true, over_rule_limit: false }),
    )
    expect(hints).toEqual({ loaded: true, warning: false, account: undefined, token: undefined })
  })

  it("says nothing for an administrator or while Plans are off", async () => {
    await render(
      jsonResponse({
        ...atEveryLimit,
        basis: "administrator",
        plan: null,
        limits: null,
        may_connect_account: true,
        may_issue_token: true,
        over_rule_limit: false,
      }),
    )
    expect(hints).toEqual({ loaded: true, warning: false, account: undefined, token: undefined })
  })

  it("gives no hint and no warning for an empty answer", async () => {
    await render(jsonResponse({}))
    expect(hints).toEqual({ loaded: true, warning: false, account: undefined, token: undefined })
  })

  it("gives no hint and no warning when the Plan cannot be read, so every control stays enabled", async () => {
    await render(jsonResponse({ detail: "Internal Server Error" }, 500))
    expect(hints).toEqual({ loaded: true, warning: false, account: undefined, token: undefined })
  })
})
```

- [ ] **Step 7: Run it to verify it fails**

Run: `cd web && pnpm exec vitest run src/lib/use-own-plan.test.tsx`

Expected: FAIL, `Failed to resolve import "@/lib/use-own-plan"` (or `Cannot find package '@/lib/use-own-plan'`).

- [ ] **Step 8: Implement the own-plan hooks (cycle B)**

Create `web/src/lib/use-own-plan.ts`:

```ts
import { useQuery } from "@tanstack/react-query"

import { useI18n } from "@/i18n/provider"
import { api } from "@/lib/api"
import { planWarning } from "@/lib/plans"

/** The signed-in User's own Plan; a change to their rules, accounts, or tokens refreshes it. */
export const OWN_PLAN_QUERY = ["own-plan"] as const

/**
 * What the signed-in User's Plan allows and how much of it they have. Hints read it, so a failed
 * or pending read gives no hint and no warning: every control stays enabled, and the server
 * still checks each limit.
 */
export function useOwnPlan() {
  return useQuery({ queryKey: OWN_PLAN_QUERY, queryFn: api.ownPlan })
}

/** Whether a note should say that a change may keep a rule from starting again. */
export function usePlanWarning(): boolean {
  return planWarning(useOwnPlan().data)
}

/** Why Connect is unavailable: every calendar account place of the Plan is in use. */
export function useAccountLimitReason(): string | undefined {
  const { t } = useI18n()
  const plan = useOwnPlan().data
  const limit = plan?.limits?.connected_accounts
  if (plan?.may_connect_account !== false || typeof limit !== "number") return undefined
  return t("common.plan.accountLimit", { count: limit })
}

/** Why a new Integration Token cannot be issued: the Plan's tokens are all in use. */
export function useTokenLimitReason(): string | undefined {
  const { t } = useI18n()
  const plan = useOwnPlan().data
  const limit = plan?.limits?.integration_tokens
  if (plan?.may_issue_token !== false || typeof limit !== "number") return undefined
  return t("common.apiError.plan_limit_reached_integration_tokens", { count: limit })
}
```

In `web/src/i18n/locales/en/common.json`, the `plan` group task 11 added gains `accountLimit`. Its
full new version:

```json
  "plan": {
    "seeYourPlan": "See your plan",
    "accountLimit": {
      "one": "Your plan allows {count} calendar account, and disconnected accounts count too.",
      "other": "Your plan allows {count} calendar accounts, and disconnected accounts count too."
    }
  }
```

- [ ] **Step 9: Run it to verify it passes**

Run: `cd web && pnpm exec vitest run src/lib/use-own-plan.test.tsx src/i18n/catalog.test.ts`

Expected: PASS (6 tests in `use-own-plan.test.tsx`; the catalog test finds `common.plan.accountLimit` named in `use-own-plan.ts`).

- [ ] **Step 10: Write the failing test for the Plans hook (cycle C)**

Create `web/src/lib/use-plans.test.tsx`:

```tsx
/* @vitest-environment happy-dom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, useEffect } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { StaticI18nProvider } from "@/i18n/provider"
import { testI18n } from "@/i18n/testing"
import type { PlanSummary, PlansOverview } from "@/lib/api"
import { OWN_PLAN_QUERY } from "@/lib/use-own-plan"
import { PLANS_QUERY, type PlanCommands, usePlans } from "@/lib/use-plans"

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const family: PlanSummary = {
  key: "family",
  name: "Family",
  limits: { rules: 5, connected_accounts: 3, integration_tokens: 2, sync_interval: "instant" },
  is_default: false,
  people: 4,
  limited_people: 3,
}
const free: PlanSummary = {
  key: "free",
  name: "Free",
  limits: { rules: 1, connected_accounts: 1, integration_tokens: 0, sync_interval: "5_minutes" },
  is_default: true,
  people: 2,
  limited_people: 2,
}
const overview: PlansOverview = {
  enabled: false,
  default_plan: "free",
  sync_intervals: ["instant", "5_minutes"],
  plans: [family, free],
}

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status < 400, status, json: () => Promise.resolve(body) } as Response
}

const NO_CONTENT = { ok: true, status: 204, json: () => Promise.resolve(null) } as Response

type Call = { method: string; path: string; body: unknown }
let calls: Call[] = []
let root: Root | null = null
let queryClient: QueryClient
let commands: PlanCommands | undefined

function serve(answers: Record<string, Response>) {
  const routes: Record<string, Response> = { "GET /api/v1/plans": jsonResponse(overview), ...answers }
  calls = []
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string | URL, init?: RequestInit) => {
      const method = init?.method ?? "GET"
      const path = String(input)
      const body: unknown = init?.body ? JSON.parse(init.body as string) : undefined
      calls.push({ method, path, body })
      return Promise.resolve(routes[`${method} ${path}`] ?? jsonResponse({}))
    }),
  )
}

function Probe({ onCommands }: { onCommands: (next: PlanCommands) => void }) {
  const plans = usePlans()
  useEffect(() => {
    onCommands(plans)
  })
  return null
}

async function settle() {
  for (let i = 0; i < 6; i += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0))
    })
  }
}

async function render(answers: Record<string, Response> = {}) {
  serve(answers)
  queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  // Someone's person page and the administrator's own Plan, both open before the change.
  queryClient.setQueryData(["people", "overview", "user-robin"], { plan: null })
  queryClient.setQueryData(OWN_PLAN_QUERY, { basis: "administrator" })
  root = createRoot(document.createElement("div"))
  act(() => {
    root?.render(
      <StaticI18nProvider i18n={testI18n()}>
        <QueryClientProvider client={queryClient}>
          <Probe
            onCommands={(next) => {
              commands = next
            }}
          />
        </QueryClientProvider>
      </StaticI18nProvider>,
    )
  })
  await settle()
}

/** Runs one command and waits for its answer and every refresh after it. */
async function run(command: (plans: PlanCommands) => void) {
  act(() => {
    if (commands) command(commands)
  })
  await settle()
}

/** Whether a change marked a query stale, so it reads again when next shown. */
function refreshed(queryKey: readonly unknown[]): boolean {
  return queryClient.getQueryState(queryKey)?.isInvalidated === true
}

beforeEach(() => {
  commands = undefined
})

afterEach(() => {
  if (root) act(() => root?.unmount())
  root = null
  vi.restoreAllMocks()
})

describe("usePlans", () => {
  it("lists every Plan under its own key", async () => {
    await render()
    expect(commands?.plans.data).toEqual(overview)
    expect(queryClient.getQueryData(PLANS_QUERY)).toEqual(overview)
  })

  it("turns Plans on with the default it already has, and says so", async () => {
    const on: PlansOverview = { ...overview, enabled: true }
    await render({ "PUT /api/v1/plan-settings": jsonResponse(on) })
    await run((plans) => plans.setting.mutate({ enabled: true, defaultPlan: "free" }))
    expect(calls.find((call) => call.method === "PUT")).toEqual({
      method: "PUT",
      path: "/api/v1/plan-settings",
      body: { enabled: true, default_plan: "free" },
    })
    expect(queryClient.getQueryData(PLANS_QUERY)).toEqual(on)
    expect(commands?.message).toBe("Plans now limit people.")
    expect(refreshed(["people", "overview", "user-robin"])).toBe(true)
    expect(refreshed(OWN_PLAN_QUERY)).toBe(true)
  })

  it("turns Plans off, keeping every Plan", async () => {
    await render({
      "GET /api/v1/plans": jsonResponse({ ...overview, enabled: true }),
      "PUT /api/v1/plan-settings": jsonResponse(overview),
    })
    await run((plans) => plans.setting.mutate({ enabled: false, defaultPlan: "free" }))
    expect(commands?.message).toBe("Plans no longer limit anyone.")
  })

  it("names a new Default Plan", async () => {
    const changed: PlansOverview = {
      ...overview,
      default_plan: "family",
      plans: [{ ...family, is_default: true }, { ...free, is_default: false }],
    }
    await render({ "PUT /api/v1/plan-settings": jsonResponse(changed) })
    await run((plans) => plans.setting.mutate({ enabled: false, defaultPlan: "family" }))
    expect(commands?.message).toBe("Family is now the default plan.")
  })

  it("adds, saves, and removes a Plan, naming it each time", async () => {
    await render({
      "POST /api/v1/plans": jsonResponse({ ...family, key: "family-2", name: "Family Plus" }, 201),
      "PUT /api/v1/plans/family": jsonResponse({ ...family, name: "Family Large" }),
      "DELETE /api/v1/plans/family": NO_CONTENT,
    })
    const payload = { key: "family-2", name: "Family Plus", limits: family.limits }
    await run((plans) => plans.define.mutate(payload))
    expect(calls.find((call) => call.method === "POST")?.body).toEqual(payload)
    expect(commands?.message).toBe("Family Plus was added.")

    await run((plans) => plans.change.mutate({ key: "family", payload: { name: "Family Large", limits: family.limits } }))
    expect(calls.find((call) => call.method === "PUT")?.path).toBe("/api/v1/plans/family")
    expect(commands?.message).toBe("Family Large was saved.")

    await run((plans) => plans.remove.mutate("family"))
    expect(calls.find((call) => call.method === "DELETE")?.path).toBe("/api/v1/plans/family")
    expect(commands?.message).toBe("Family was removed.")
    // Each change lists the Plans again.
    expect(calls.filter((call) => call.method === "GET" && call.path === "/api/v1/plans").length).toBeGreaterThan(1)
  })

  it("keeps the last message until the next change starts, and none after a refusal", async () => {
    await render({
      "POST /api/v1/plans": jsonResponse({ code: "plan_key_taken", params: {}, detail: "taken" }, 409),
      "PUT /api/v1/plan-settings": jsonResponse({ ...overview, enabled: true }),
    })
    await run((plans) => plans.setting.mutate({ enabled: true, defaultPlan: "free" }))
    expect(commands?.message).toBe("Plans now limit people.")
    await run((plans) => plans.define.mutate({ key: "free", name: "Free", limits: free.limits }))
    expect(commands?.define.error).not.toBeNull()
    expect(commands?.message).toBe("")
  })
})
```

- [ ] **Step 11: Run it to verify it fails**

Run: `cd web && pnpm exec vitest run src/lib/use-plans.test.tsx`

Expected: FAIL, `Failed to resolve import "@/lib/use-plans"` (or `Cannot find package '@/lib/use-plans'`).

- [ ] **Step 12: Implement the Plans hook (cycle C)**

Create `web/src/lib/use-plans.ts`:

```ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"

import { useI18n } from "@/i18n/provider"
import type { I18n } from "@/i18n/translator"
import { api, type PlanChange, type PlanPayload, type PlansOverview } from "@/lib/api"
import { OWN_PLAN_QUERY } from "@/lib/use-own-plan"

/** Every Plan and the Plans setting; only Installation Administrators may read them. */
export const PLANS_QUERY = ["plans"] as const

/** The Plans setting's change: whether Plans limit people now, and the Default Plan. */
type SettingChange = { enabled: boolean; defaultPlan: string | null }

/** What a change of the Plans setting did, in the active language; empty when nothing to say. */
function settingMessage({ t }: I18n, before: PlansOverview | undefined, after: PlansOverview): string {
  if (before?.enabled !== after.enabled) return t(after.enabled ? "settings.plans.saved.on" : "settings.plans.saved.off")
  const chosen = after.plans.find((plan) => plan.key === after.default_plan)
  return chosen ? t("settings.plans.saved.defaultChanged", { name: chosen.name }) : ""
}

/**
 * Plans and the commands that change them, for Installation Administrators. Every change also
 * refreshes People, whose person pages show each person's Plan, and the administrator's own Plan.
 */
export function usePlans() {
  const i18n = useI18n()
  const { t } = i18n
  const queryClient = useQueryClient()
  const plans = useQuery({ queryKey: PLANS_QUERY, queryFn: api.plans })
  const [message, setMessage] = useState("")
  const refreshOthers = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ["people"] }),
      queryClient.invalidateQueries({ queryKey: OWN_PLAN_QUERY }),
    ])
  const saved = async (text: string) => {
    setMessage(text)
    await Promise.all([queryClient.invalidateQueries({ queryKey: PLANS_QUERY }), refreshOthers()])
  }
  const setting = useMutation({
    mutationFn: ({ enabled, defaultPlan }: SettingChange) => api.setPlansSetting(enabled, defaultPlan),
    onMutate: () => setMessage(""),
    onSuccess: async (overview) => {
      setMessage(settingMessage(i18n, queryClient.getQueryData<PlansOverview>(PLANS_QUERY), overview))
      queryClient.setQueryData(PLANS_QUERY, overview)
      await refreshOthers()
    },
  })
  const define = useMutation({
    mutationFn: (payload: PlanPayload) => api.definePlan(payload),
    onMutate: () => setMessage(""),
    onSuccess: (plan) => saved(t("settings.plans.saved.defined", { name: plan.name })),
  })
  const change = useMutation({
    mutationFn: ({ key, payload }: { key: string; payload: PlanChange }) => api.changePlan(key, payload),
    onMutate: () => setMessage(""),
    onSuccess: (plan) => saved(t("settings.plans.saved.changed", { name: plan.name })),
  })
  const remove = useMutation({
    mutationFn: (key: string) => api.removePlan(key),
    onMutate: () => setMessage(""),
    onSuccess: (_result, key) => {
      const listed = queryClient.getQueryData<PlansOverview>(PLANS_QUERY)?.plans.find((plan) => plan.key === key)
      return saved(t("settings.plans.saved.removed", { name: listed?.name ?? key }))
    },
  })
  return { plans, setting, define, change, remove, message }
}

export type PlanCommands = ReturnType<typeof usePlans>
```

`usePlans` names the `settings.plans.saved.*` messages, so they are added here (task 15 adds the
rest of the `plans` group). In `web/src/i18n/locales/en/settings.json`, the full new version of the
`plans` group, still between `registration` and `links`:

```json
  "plans": {
    "limits": {
      "rules": {
        "one": "{count} rule",
        "other": "{count} rules"
      },
      "accounts": {
        "one": "{count} calendar account",
        "other": "{count} calendar accounts"
      },
      "tokens": {
        "one": "{count} token",
        "other": "{count} tokens"
      },
      "unlimitedRules": "Unlimited rules",
      "unlimitedAccounts": "unlimited calendar accounts",
      "unlimitedTokens": "unlimited tokens",
      "noTokens": "no tokens"
    },
    "interval": {
      "instant": "Instant sync, and a check every 5 minutes",
      "5_minutes": "Every 5 minutes",
      "10_minutes": "Every 10 minutes",
      "15_minutes": "Every 15 minutes",
      "30_minutes": "Every 30 minutes",
      "60_minutes": "Every hour"
    },
    "saved": {
      "on": "Plans now limit people.",
      "off": "Plans no longer limit anyone.",
      "defaultChanged": "{name} is now the default plan.",
      "defined": "{name} was added.",
      "changed": "{name} was saved.",
      "removed": "{name} was removed."
    }
  }
```

- [ ] **Step 13: Run it to verify it passes**

Run: `cd web && pnpm exec vitest run src/lib/use-plans.test.tsx src/i18n/catalog.test.ts`

Expected: PASS (6 tests in `use-plans.test.tsx`; catalog green).

- [ ] **Step 14: Write the failing test for the Your plan link (cycle D)**

Create `web/src/components/your-plan-link.test.tsx`:

```tsx
/* @vitest-environment happy-dom */

import { act } from "react"
import { createRoot } from "react-dom/client"
import { describe, expect, it } from "vitest"

import { StaticI18nProvider } from "@/i18n/provider"
import { pseudoI18n, testI18n, untranslatedText } from "@/i18n/testing"

import { YourPlanLink } from "./your-plan-link"

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

function rendered(i18n = testI18n()): HTMLDivElement {
  const container = document.createElement("div")
  const root = createRoot(container)
  act(() =>
    root.render(
      <StaticI18nProvider i18n={i18n}>
        <YourPlanLink />
      </StaticI18nProvider>,
    ),
  )
  return container
}

describe("YourPlanLink", () => {
  it("opens Settings at Your plan", () => {
    const link = rendered().querySelector("a")
    expect(link?.textContent).toBe("See your plan")
    expect(link?.getAttribute("href")).toBe("/settings/account#your-plan")
  })

  it("has no untranslated text", () => {
    expect(untranslatedText(rendered(pseudoI18n()))).toEqual([])
  })
})
```

- [ ] **Step 15: Run it to verify it fails**

Run: `cd web && pnpm exec vitest run src/components/your-plan-link.test.tsx`

Expected: FAIL, `Failed to resolve import "./your-plan-link" from "src/components/your-plan-link.test.tsx". Does the file exist?`

- [ ] **Step 16: Implement the Your plan link (cycle D)**

Create `web/src/components/your-plan-link.tsx`:

```tsx
import { useI18n } from "@/i18n/provider"
import { yourPlanPath } from "@/lib/navigation"

/**
 * "See your plan", beside a limit's reason. A full navigation, so Settings opens at Your plan
 * wherever the reason was shown.
 */
export function YourPlanLink() {
  const { t } = useI18n()
  return (
    <a className="text-link" href={yourPlanPath()}>
      {t("common.plan.seeYourPlan")}
    </a>
  )
}
```

- [ ] **Step 17: Run it to verify it passes**

Run: `cd web && pnpm exec vitest run src/components/your-plan-link.test.tsx`

Expected: PASS (2 tests).

- [ ] **Step 18: Write the failing tests for refreshing the own Plan (cycle E)**

A rule change, a disconnect or deletion of an account, and a token issued or revoked can each
change what Your plan counts. These tests run the real account and token hooks against a stubbed
API, beside a Your plan that was already read, and check that each command marks it stale. In
`web/src/lib/use-own-plan.test.tsx`, replace the `@/lib/api` type import and the
`@/lib/use-own-plan` import:

```tsx
import type { OwnPlan } from "@/lib/api"
import {
  OWN_PLAN_QUERY,
  useAccountLimitReason,
  useOwnPlan,
  usePlanWarning,
  useTokenLimitReason,
} from "@/lib/use-own-plan"
```

with:

```tsx
import type { IntegrationToken, OwnPlan } from "@/lib/api"
import { type AccountCommands, useAccountCommands } from "@/lib/use-account-commands"
import { type IntegrationTokens, useIntegrationTokens } from "@/lib/use-integration-tokens"
import {
  OWN_PLAN_QUERY,
  useAccountLimitReason,
  useOwnPlan,
  usePlanWarning,
  useTokenLimitReason,
} from "@/lib/use-own-plan"
import { RULE_CHANGE_QUERIES } from "@/lib/use-rule-commands"
```

and append this block at the end of the file (it reuses the file's `atEveryLimit`, `jsonResponse`,
`root`, and `queryClient`, and its `afterEach` unmounts what it renders):

```tsx
const NO_CONTENT = { ok: true, status: 204, json: () => Promise.resolve(null) } as Response

/** An unrevoked token the person can revoke. */
const homeMonitor: IntegrationToken = {
  id: "token-1",
  name: "Home monitor",
  scopes: ["status:read"],
  created_at: "2026-10-15T09:00:00Z",
  last_used_at: null,
  revoked_at: null,
}

type Commands = { accounts: AccountCommands; tokens: IntegrationTokens }
let commands: Commands | undefined

/** Answers each account and token command by its method and path. */
function serveCommands() {
  const routes: Record<string, Response> = {
    "GET /api/v1/integration-tokens": jsonResponse([homeMonitor]),
    "POST /api/v1/integration-tokens": jsonResponse({ ...homeMonitor, token: "cg_synthetic_token" }, 201),
    "DELETE /api/v1/integration-tokens/token-1": NO_CONTENT,
    "POST /api/v1/accounts/account-1/disconnect": jsonResponse({ id: "account-1", display_name: "Work" }),
    "DELETE /api/v1/accounts/account-1": NO_CONTENT,
  }
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string | URL, init?: RequestInit) =>
      Promise.resolve(routes[`${init?.method ?? "GET"} ${String(input)}`] ?? jsonResponse({})),
    ),
  )
}

function CommandsProbe({ onCommands }: { onCommands: (next: Commands) => void }) {
  const accounts = useAccountCommands(undefined)
  const tokens = useIntegrationTokens()
  useEffect(() => {
    onCommands({ accounts, tokens })
  })
  return null
}

async function settle() {
  for (let i = 0; i < 6; i += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0))
    })
  }
}

/**
 * Runs one account or token command beside a Your plan that was already read, and answers
 * whether the command marked it stale, so it reads again when next shown.
 */
async function refreshesOwnPlan(command: (current: Commands) => void): Promise<boolean> {
  serveCommands()
  queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient.setQueryData(OWN_PLAN_QUERY, atEveryLimit)
  root = createRoot(document.createElement("div"))
  act(() => {
    root?.render(
      <StaticI18nProvider i18n={testI18n()}>
        <QueryClientProvider client={queryClient}>
          <CommandsProbe
            onCommands={(next) => {
              commands = next
            }}
          />
        </QueryClientProvider>
      </StaticI18nProvider>,
    )
  })
  await settle()
  expect(queryClient.getQueryState(OWN_PLAN_QUERY)?.isInvalidated).toBe(false)
  act(() => {
    if (commands) command(commands)
  })
  await settle()
  return queryClient.getQueryState(OWN_PLAN_QUERY)?.isInvalidated === true
}

describe("own plan refresh", () => {
  it("reads the Plan again after every rule change, which can change how many rules count", () => {
    expect(RULE_CHANGE_QUERIES).toContainEqual(OWN_PLAN_QUERY)
  })

  it("reads the Plan again after an account is disconnected, which stops its rules", async () => {
    expect(await refreshesOwnPlan(({ accounts }) => accounts.disconnect.mutate("account-1"))).toBe(true)
  })

  it("reads the Plan again after an account is deleted, which frees a calendar account", async () => {
    expect(await refreshesOwnPlan(({ accounts }) => accounts.permanentDelete.mutate("account-1"))).toBe(true)
  })

  it("reads the Plan again after a token is issued", async () => {
    expect(await refreshesOwnPlan(({ tokens }) => tokens.issue.mutate())).toBe(true)
  })

  it("reads the Plan again after a token is revoked", async () => {
    expect(await refreshesOwnPlan(({ tokens }) => tokens.revoke.mutate(homeMonitor))).toBe(true)
  })
})
```

Each command's `onSuccess` is where the refresh belongs, so a test passes only when the command
succeeds and then marks Your plan stale.

- [ ] **Step 19: Run them to verify they fail**

Run: `cd web && pnpm exec vitest run src/lib/use-own-plan.test.tsx`

Expected: FAIL, 5 failed and 6 passed: `own plan refresh > reads the Plan again after every rule change...` (`expected [ [ 'rules' ], ... ] to deep equally contain [ 'own-plan' ]`) and the four account and token cases (`AssertionError: expected false to be true`), because no command marks Your plan stale yet.

- [ ] **Step 20: Refresh the own Plan after rule, account, and token changes (cycle E)**

In `web/src/lib/use-rule-commands.ts`, import the key:

```ts
import {
  pausedMessage,
  reconcileResultMessage,
  syncResultMessage,
} from "@/lib/rule-run"
import { OWN_PLAN_QUERY } from "@/lib/use-own-plan"
import { withoutKey } from "@/lib/utils"
```

and end `RULE_CHANGE_QUERIES` with it:

```ts
export const RULE_CHANGE_QUERIES = [
  ["rules"],
  ["dashboard"],
  ["activity"],
  ["accounts"],
  ["recent-changes"],
  ["incidents"],
  // Starting, pausing, previewing, or removing a rule changes how many rules count toward the Plan.
  OWN_PLAN_QUERY,
] as const
```

In `web/src/lib/use-account-commands.ts`, import the key:

```ts
import { useI18n } from "@/i18n/provider"
import { type ConnectedAccount, api } from "@/lib/api"
import { OWN_PLAN_QUERY } from "@/lib/use-own-plan"
import { withoutKey } from "@/lib/utils"
```

and replace the `disconnect` and `permanentDelete` mutations with:

```ts
  const disconnect = useMutation({
    mutationFn: api.disconnectAccount,
    onSuccess: async (account) => {
      setConfirmingAccountId(null)
      setStatusMessage(t("settings.accounts.status.disconnected", { name: account.display_name }))
      setAccessChecks((current) => withoutKey(current, account.id))
      // A disconnect stops the account's rules, so fewer may count toward the Plan.
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["accounts"] }),
        queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
        queryClient.invalidateQueries({ queryKey: ["rules"] }),
        queryClient.invalidateQueries({ queryKey: OWN_PLAN_QUERY }),
      ])
    },
  })
  const permanentDelete = useMutation({
    mutationFn: async (accountId: string) => {
      const account = accounts?.find((candidate) => candidate.id === accountId)
      await api.deleteAccount(accountId)
      return {
        accountId,
        displayName: account?.display_name ?? t("settings.accounts.status.unknownName"),
        ruleCount: account?.rule_count ?? 0,
      }
    },
    onSuccess: async ({ accountId, displayName, ruleCount }) => {
      setDeletingAccountId(null)
      setStatusMessage(
        ruleCount > 0
          ? t("settings.accounts.status.deletedWithRules", { name: displayName, count: ruleCount })
          : t("settings.accounts.status.deleted", { name: displayName }),
      )
      setAccessChecks((current) => withoutKey(current, accountId))
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["accounts"] }),
        queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
        queryClient.invalidateQueries({ queryKey: ["rules"] }),
        queryClient.invalidateQueries({ queryKey: ["activity"] }),
        queryClient.invalidateQueries({ queryKey: ["incidents"] }),
        queryClient.invalidateQueries({ queryKey: OWN_PLAN_QUERY }),
      ])
    },
  })
```

In `web/src/lib/use-integration-tokens.ts`, import the key:

```ts
import { api, type IntegrationToken, type IssuedIntegrationToken } from "@/lib/api"
import { tokenScopes } from "@/lib/integrations"
import { useCopyState } from "@/lib/use-copy-state"
import { OWN_PLAN_QUERY } from "@/lib/use-own-plan"
```

and replace the `issue` and `revoke` mutations with:

```ts
  const issue = useMutation({
    mutationFn: () => api.issueIntegrationToken(name, tokenScopes(installation)),
    onSuccess: async (token) => {
      setIssued(token)
      setName("")
      setInstallation(false)
      setCopyState("idle")
      // Announce the issue, never the token: a screen reader would read the secret aloud.
      setMessage(t("settings.integrations.status.issued", { name: token.name }))
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["integration-tokens"] }),
        queryClient.invalidateQueries({ queryKey: OWN_PLAN_QUERY }),
      ])
    },
  })
  const revoke = useMutation({
    mutationFn: (token: IntegrationToken) => api.revokeIntegrationToken(token.id),
    onSuccess: async (_result, token) => {
      setRevoking(null)
      // The plaintext token lives only in this component's state, shown once; if the admin
      // revokes it right away, stop showing a secret that no longer works.
      setIssued((current) => (current?.id === token.id ? null : current))
      setMessage(t("settings.integrations.status.revoked", { name: token.name }))
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["integration-tokens"] }),
        queryClient.invalidateQueries({ queryKey: OWN_PLAN_QUERY }),
      ])
      // The revoked row loses its button, so focus returns to the group it belongs to.
      summaryButton.current?.focus()
    },
  })
```

- [ ] **Step 21: Run the touched tests and the frontend checks**

Run:

```sh
cd web && pnpm exec vitest run src/lib/plans.test.ts src/lib/api.test.ts src/lib/use-own-plan.test.tsx src/lib/use-plans.test.tsx src/components/your-plan-link.test.tsx src/lib/use-rule-commands.test.ts src/i18n/catalog.test.ts
cd web && pnpm run typecheck && pnpm run lint && pnpm run knip && pnpm run doctor
cd web && pnpm run test
```

Expected: every listed test file passes (11 tests in `use-own-plan.test.tsx`); typecheck, lint (`--max-warnings 0`), knip, and doctor report nothing; the full suite passes. Knip passes because every new export has a consumer: the helpers and hooks in their tests, `OWN_PLAN_QUERY` in the three hooks, `PlanSummary` and `PlanCommands` in `use-plans.test.tsx`.

- [ ] **Step 22: Rebuild the static bundle**

Run: `cd web && pnpm run build`

Expected: `tsc -b` clean and `vite build` writes new hashed assets under `src/calendar_sync/interfaces/api/static/assets/` and a new `index.html` (the catalogs and hooks changed, so the bundle changes beyond the embedded commit).

- [ ] **Step 23: Commit**

```sh
git add web/src/lib/api.ts web/src/lib/api.test.ts web/src/lib/plans.ts web/src/lib/plans.test.ts \
  web/src/lib/use-own-plan.ts web/src/lib/use-own-plan.test.tsx web/src/lib/use-plans.ts web/src/lib/use-plans.test.tsx \
  web/src/lib/use-rule-commands.ts web/src/lib/use-account-commands.ts web/src/lib/use-integration-tokens.ts \
  web/src/components/your-plan-link.tsx web/src/components/your-plan-link.test.tsx \
  web/src/i18n/locales/en/common.json web/src/i18n/locales/en/settings.json web/src/i18n/locales/en/people.json \
  web/src/i18n/catalog.test.ts
git add -A src/calendar_sync/interfaces/api/static
.venv/bin/pytest tests/test_no_em_dashes.py tests/test_ubiquitous_language.py -q
git commit -F - <<'EOF'
Teach the Web UI to read Plans and say what each one allows

Adds the Plans API methods and types, pure helpers for Plan copy (Your
plan's line, a person's Plan fact, interval labels, the Start refusal),
the own-plan and Plans hooks, and the "See your plan" link. Rule,
account, and token changes now refresh the own-plan query. No screen
shows Plans yet.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
```

The two pytest checks read `git ls-files`, so they run after staging. Expected: `passed` (no em
dash and no avoided term in the new files); nothing else in the backend changes in this task.

### Task 15: Administration, Plans

**Files:**
- Create: `web/src/features/settings-plans.tsx`
- Create: `web/src/features/plan-editor.tsx`
- Modify: `web/src/features/settings.tsx` (imports; `AdministrationTab`)
- Modify: `web/src/i18n/locales/en/settings.json` (the rest of the `plans` group)
- Modify: `web/src/features/settings-administration.test.tsx` (`serve` defaults answer `GET /api/v1/plans`; the "holds who can join..." case also expects the Plans section)
- Regenerate: `src/calendar_sync/interfaces/api/static/` (`pnpm run build`)
- Test: `web/src/features/settings-plans.test.tsx` (new)

**Interfaces:**
- Consumes (task 14): `usePlans()`, `PlanCommands`, `PLANS_QUERY`; `intervalLabel(i18n, interval)`, `planLimitsSummary(i18n, limits)`; types `PlansOverview`, `PlanSummary`, `PlanPayload`, `SyncInterval`; `settings.plans.limits.*`, `settings.plans.interval.*`, `settings.plans.saved.*`. From task 6: `common.apiError.plan_not_found`, `plan_key_taken`, `plan_in_use` (plural, `count`), `plan_is_default`, `invalid_plan_key`, rendered through `apiErrorMessage`. Existing: `useRegistration()` (answers `{ registration, change, message }`), `DestructiveConfirmation`, `Badge`, `Button`, `Input`, `Label`, `NativeSelect`, `Skeleton`.
- Produces:
  - `export function PlansSection({ commands }: { commands: PlanCommands })`: `<section aria-labelledby="plans-title">`. Element ids tests and later tasks may rely on: `plans-enabled` (checkbox), `plans-enabled-hint`, `plans-default` (select), `plan-edit-<key>` and `plan-edit-new` (editor wrappers), `plan-remove-<key>` (confirmation).
  - `export function PlanEditor({ plan, intervals, pending, error, onSave, onCancel }: { plan: PlanSummary | null; intervals: SyncInterval[]; pending: boolean; error: unknown; onSave: (payload: PlanPayload) => void; onCancel: () => void })`: field ids `<prefix>-key`, `<prefix>-key-hint` (new Plan only), `<prefix>-name`, `<prefix>-rules`, `<prefix>-rules-unlimited`, `<prefix>-accounts`, `<prefix>-accounts-unlimited`, `<prefix>-tokens`, `<prefix>-tokens-unlimited`, `<prefix>-interval`, where `<prefix>` is `plan-<key>` or `plan-new`.
  - `AdministrationTab` renders `RegistrationSection`, then `PlansSection` only while the Registration Policy is `invitation_only`, then `StorageSection`.
  - The full `settings.plans` group (section 3.21 keys).

- [ ] **Step 1: Write the failing tests**

Create `web/src/features/settings-plans.test.tsx`:

```tsx
/* @vitest-environment happy-dom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { ThemeProvider } from "@/components/theme-provider"
import { StaticI18nProvider } from "@/i18n/provider"
import { dateWords, pseudoI18n, testI18n, untranslatedText } from "@/i18n/testing"
import type { I18n } from "@/i18n/translator"
import type { PlanSummary, PlansOverview, Registration, SessionStatus } from "@/lib/api"

import { SettingsPage } from "./settings"

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const ORIGIN = "http://localhost:8000"

const session: SessionStatus = {
  authenticated: true,
  installation_sends_email: true,
  user: {
    id: "user-dana",
    email: "dana@example.test",
    role: "installation_administrator",
    notify_by_email: true,
    instant_sync: true,
    instant_sync_availability: "on",
    instant_sync_help: null,
    language: null,
  },
}

const family: PlanSummary = {
  key: "family",
  name: "Family",
  limits: { rules: 5, connected_accounts: 3, integration_tokens: 2, sync_interval: "instant" },
  is_default: false,
  people: 4,
  limited_people: 3,
}
const free: PlanSummary = {
  key: "free",
  name: "Free",
  limits: { rules: 1, connected_accounts: 1, integration_tokens: 0, sync_interval: "5_minutes" },
  is_default: false,
  people: 2,
  limited_people: 2,
}

/** Plans as GET /api/v1/plans answers, with `defaultPlan` marked as the default. */
function overview({
  enabled = false,
  defaultPlan = null,
  plans = [family, free],
}: { enabled?: boolean; defaultPlan?: string | null; plans?: PlanSummary[] } = {}): PlansOverview {
  return {
    enabled,
    default_plan: defaultPlan,
    sync_intervals: ["instant", "5_minutes"],
    plans: plans.map((plan) => ({ ...plan, is_default: plan.key === defaultPlan })),
  }
}

const INVITATION_ONLY: Registration = { policy: "invitation_only", only_me_available: false }

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status < 400, status, json: () => Promise.resolve(body) } as Response
}

function refusal(status: number, code: string, params: Record<string, string | number> = {}): Response {
  return jsonResponse({ detail: "The server's English.", code, params }, status)
}

const NO_CONTENT = { ok: true, status: 204, json: () => Promise.resolve(null) } as Response

type Call = { method: string; path: string; body: unknown }
type Scenario = {
  registration?: Registration
  plans?: PlansOverview
  /** Answers by "METHOD /path", overriding the defaults. */
  answers?: Record<string, Response>
}

let calls: Call[] = []

function serve({ registration = INVITATION_ONLY, plans = overview(), answers = {} }: Scenario) {
  const defaults: Record<string, Response> = {
    "GET /api/v1/session": jsonResponse(session),
    "GET /api/v1/providers": jsonResponse([]),
    "GET /api/v1/storage": jsonResponse({
      database: { bytes: 1024 * 1024, reclaimable_bytes: 0, activity_entries: 0, oldest_activity_at: null },
      logs: { bytes: 0, files: 0, oldest_at: null, newest_at: null },
      activity_ages: [30, 90, 180, 365],
    }),
    "GET /api/v1/registration": jsonResponse(registration),
    "GET /api/v1/plans": jsonResponse(plans),
  }
  const routes = { ...defaults, ...answers }
  calls = []
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string | URL, init?: RequestInit) => {
      const method = init?.method ?? "GET"
      const path = String(input).split("?")[0] ?? ""
      const body: unknown = init?.body ? JSON.parse(init.body as string) : undefined
      calls.push({ method, path, body })
      return Promise.resolve(routes[`${method} ${path}`] ?? jsonResponse({}))
    }),
  )
}

let container: HTMLDivElement
let root: Root | null = null
let address: string

function page() {
  return window as typeof window & { happyDOM: { setURL: (url: string) => void } }
}

beforeEach(() => {
  container = document.createElement("div")
  document.body.append(container)
  address = window.location.href
  page().happyDOM.setURL(`${ORIGIN}/settings/administration`)
})

afterEach(() => {
  if (root) {
    act(() => root?.unmount())
    root = null
  }
  container.remove()
  page().happyDOM.setURL(address)
  vi.restoreAllMocks()
})

async function settle(times = 8) {
  for (let i = 0; i < times; i += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0))
    })
  }
}

async function renderAdministration(i18n: I18n, scenario: Scenario = {}) {
  serve(scenario)
  root = createRoot(container)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  act(() => {
    root?.render(
      <StaticI18nProvider i18n={i18n}>
        <ThemeProvider>
          <QueryClientProvider client={queryClient}>
            <SettingsPage tab="administration" onOpenTab={() => undefined} onOpenPeople={() => undefined} />
          </QueryClientProvider>
        </ThemeProvider>
      </StaticI18nProvider>,
    )
  })
  await settle()
}

function plansSection(): HTMLElement {
  const found = container.querySelector<HTMLElement>("[aria-labelledby='plans-title']")
  if (!found) throw new Error("No Plans section")
  return found
}

function sections(): (string | null)[] {
  return [...container.querySelectorAll(".settings-page > section")].map((item) => item.getAttribute("aria-labelledby"))
}

function button(name: string, within: ParentNode = plansSection()): HTMLButtonElement {
  const found = [...within.querySelectorAll("button")].find((candidate) => candidate.textContent.trim() === name)
  if (!found) throw new Error(`No button "${name}"`)
  return found
}

/** The row of one Plan, by its name. */
function planRow(name: string): HTMLElement {
  const found = [...plansSection().querySelectorAll<HTMLElement>(".setting-item")].find(
    (item) => item.querySelector("h3")?.textContent === name,
  )
  if (!found) throw new Error(`No row for ${name}`)
  return found
}

function element(id: string): HTMLElement {
  const found = container.querySelector<HTMLElement>(`#${id}`)
  if (!found) throw new Error(`No element ${id}`)
  return found
}

function field(id: string): HTMLInputElement {
  return element(id) as HTMLInputElement
}

function select(id: string): HTMLSelectElement {
  return element(id) as HTMLSelectElement
}

async function click(target: HTMLElement) {
  act(() => target.click())
  await settle()
}

function type(input: HTMLInputElement, value: string) {
  act(() => {
    Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set?.call(input, value)
    input.dispatchEvent(new Event("input", { bubbles: true }))
  })
}

async function choose(select: HTMLSelectElement, value: string) {
  act(() => {
    select.value = value
    select.dispatchEvent(new Event("change", { bubbles: true }))
  })
  await settle()
}

async function submit(form: HTMLFormElement) {
  await act(async () => {
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }))
    await new Promise((resolve) => setTimeout(resolve, 0))
  })
  await settle()
}

function sent(method: string, path: string): unknown {
  return calls.find((call) => call.method === method && call.path === path)?.body
}

function status(): string | null | undefined {
  return plansSection().querySelector("[role='status']")?.textContent
}

function alertText(): string | null | undefined {
  return plansSection().querySelector("[role='alert']")?.textContent
}

describe("Plans under Administration", () => {
  it("is hidden under Only me, where the only person administers", async () => {
    await renderAdministration(testI18n(), { registration: { policy: "only_me", only_me_available: true } })
    expect(container.querySelector("[aria-labelledby='plans-title']")).toBeNull()
    expect(sections()).toEqual(["registration-title", "storage-title"])
  })

  it("sits between who can join and storage under Invitation only", async () => {
    await renderAdministration(testI18n())
    expect(sections()).toEqual(["registration-title", "plans-title", "storage-title"])
    expect(plansSection().querySelector("h2")?.textContent).toBe("Plans")
  })

  it("lists each Plan with its limits, interval, people, and which is the default", async () => {
    await renderAdministration(testI18n(), { plans: overview({ defaultPlan: "free" }) })
    expect([...planRow("Family").querySelectorAll("p")].map((line) => line.textContent)).toEqual([
      "5 rules, 3 calendar accounts, 2 tokens",
      "Instant sync, and a check every 5 minutes",
      "4 people",
    ])
    expect([...planRow("Free").querySelectorAll("p")].map((line) => line.textContent)).toEqual([
      "1 rule, 1 calendar account, no tokens",
      "Every 5 minutes",
      "2 people",
    ])
    expect(planRow("Free").textContent).toContain("Default")
    expect(planRow("Family").textContent).not.toContain("Default")
  })

  it("keeps Limit people with plans unavailable until a default exists, and says why", async () => {
    await renderAdministration(testI18n())
    const enabled = field("plans-enabled")
    expect(enabled.disabled).toBe(true)
    expect(element("plans-enabled-hint").textContent).toBe("Choose a default plan first.")
  })

  it("chooses a default, leaving plans off", async () => {
    await renderAdministration(testI18n(), {
      answers: { "PUT /api/v1/plan-settings": jsonResponse(overview({ defaultPlan: "family" })) },
    })
    await choose(select("plans-default"), "family")
    expect(sent("PUT", "/api/v1/plan-settings")).toEqual({ enabled: false, default_plan: "family" })
    expect(status()).toBe("Family is now the default plan.")
    expect(field("plans-enabled").disabled).toBe(false)
    expect(element("plans-enabled-hint").textContent).toBe("While this is off, nobody is limited.")
  })

  it("turns plans on with the default it has", async () => {
    await renderAdministration(testI18n(), {
      plans: overview({ defaultPlan: "free" }),
      answers: { "PUT /api/v1/plan-settings": jsonResponse(overview({ enabled: true, defaultPlan: "free" })) },
    })
    await click(field("plans-enabled"))
    expect(sent("PUT", "/api/v1/plan-settings")).toEqual({ enabled: true, default_plan: "free" })
    expect(status()).toBe("Plans now limit people.")
    expect(field("plans-enabled").checked).toBe(true)
  })

  it("offers no way to clear the default while plans are on", async () => {
    await renderAdministration(testI18n(), { plans: overview({ enabled: true, defaultPlan: "free" }) })
    const none = select("plans-default").querySelector<HTMLOptionElement>("option[value='']")!
    expect(none.textContent).toBe("No default")
    expect(none.disabled).toBe(true)
  })

  it("says why a setting was refused", async () => {
    await renderAdministration(testI18n(), {
      answers: { "PUT /api/v1/plan-settings": refusal(404, "plan_not_found") },
    })
    await choose(select("plans-default"), "family")
    expect(alertText()).toBe("This plan no longer exists. Reload to see the current plans.")
  })

  it("adds a plan, warning that its key cannot change, with Unlimited sent as no limit", async () => {
    const added: PlanSummary = {
      key: "family-2",
      name: "Family Plus",
      limits: { rules: 8, connected_accounts: null, integration_tokens: 0, sync_interval: "5_minutes" },
      is_default: false,
      people: 0,
      limited_people: 0,
    }
    await renderAdministration(testI18n(), { answers: { "POST /api/v1/plans": jsonResponse(added, 201) } })
    await click(button("Add a plan"))
    expect(element("plan-new-key-hint").textContent).toBe(
      "Lower-case letters, digits, and hyphens. The key cannot change later.",
    )
    expect(document.activeElement).toBe(field("plan-new-key"))
    const intervals = select("plan-new-interval")
    expect([...intervals.options].map((option) => [option.value, option.textContent])).toEqual([
      ["instant", "Instant sync, and a check every 5 minutes"],
      ["5_minutes", "Every 5 minutes"],
    ])

    type(field("plan-new-key"), "family-2")
    type(field("plan-new-name"), " Family Plus ")
    await click(field("plan-new-rules-unlimited"))
    type(field("plan-new-rules"), "8")
    await click(field("plan-new-tokens-unlimited"))
    type(field("plan-new-tokens"), "0")
    await choose(intervals, "5_minutes")
    await submit(field("plan-new-key").closest("form")!)

    expect(sent("POST", "/api/v1/plans")).toEqual({
      key: "family-2",
      name: "Family Plus",
      limits: { rules: 8, connected_accounts: null, integration_tokens: 0, sync_interval: "5_minutes" },
    })
    expect(status()).toBe("Family Plus was added.")
    expect(container.querySelector("#plan-edit-new")).toBeNull()
    expect(document.activeElement).toBe(button("Add a plan"))
  })

  it("keeps Save unavailable until each limit has a number or Unlimited", async () => {
    await renderAdministration(testI18n())
    await click(button("Add a plan"))
    type(field("plan-new-key"), "family-2")
    type(field("plan-new-name"), "Family Plus")
    await click(field("plan-new-accounts-unlimited"))
    expect(button("Save plan").disabled).toBe(true)
    type(field("plan-new-accounts"), "2")
    await settle()
    expect(button("Save plan").disabled).toBe(false)
  })

  it.each([
    [refusal(409, "plan_key_taken"), "Another plan already uses this key. Choose a different key."],
    [
      refusal(422, "invalid_plan", { reason: "key" }),
      "Use 1 to 32 lower-case letters, digits, and hyphens for the key, starting with a letter or digit.",
    ],
  ])("keeps the new plan's form open with the reason it was refused", async (answer, reason) => {
    await renderAdministration(testI18n(), { answers: { "POST /api/v1/plans": answer } })
    await click(button("Add a plan"))
    type(field("plan-new-key"), "Family")
    type(field("plan-new-name"), "Family")
    await submit(field("plan-new-key").closest("form")!)
    expect(element("plan-edit-new").querySelector("[role='alert']")?.textContent).toBe(reason)
    expect(status()).toBe("")
  })

  it("edits a plan without changing its key, and warns before lowering its rule limit", async () => {
    await renderAdministration(testI18n(), {
      answers: { "PUT /api/v1/plans/family": jsonResponse({ ...family, name: "Family Large" }) },
    })
    await click(button("Edit", planRow("Family")))
    const key = field("plan-family-key")
    expect(key.readOnly).toBe(true)
    expect(key.value).toBe("family")
    expect(container.querySelector("#plan-family-key-hint")).toBeNull()
    expect(document.activeElement).toBe(field("plan-family-name"))
    expect(element("plan-edit-family").querySelector("[data-tone='attention']")).toBeNull()

    type(field("plan-family-rules"), "2")
    await settle()
    expect(element("plan-edit-family").querySelector("[data-tone='attention']")?.textContent).toBe(
      "This plan limits 3 people. Rules beyond a lower limit keep syncing, but no new rule can start until the count is within it.",
    )
    type(field("plan-family-name"), "Family Large")
    await submit(field("plan-family-name").closest("form")!)

    expect(sent("PUT", "/api/v1/plans/family")).toEqual({
      name: "Family Large",
      limits: { rules: 2, connected_accounts: 3, integration_tokens: 2, sync_interval: "instant" },
    })
    expect(status()).toBe("Family Large was saved.")
    expect(container.querySelector("#plan-edit-family")).toBeNull()
    expect(document.activeElement).toBe(button("Edit", planRow("Family")))
  })

  it("does not warn about a lower rule limit when the plan limits nobody", async () => {
    await renderAdministration(testI18n(), { plans: overview({ plans: [{ ...family, limited_people: 0 }] }) })
    await click(button("Edit", planRow("Family")))
    type(field("plan-family-rules"), "2")
    await settle()
    expect(element("plan-edit-family").querySelector("[data-tone='attention']")).toBeNull()
  })

  it("keeps an interval a later release saved, beside the offered ones", async () => {
    const hourly: PlanSummary = { ...family, limits: { ...family.limits, sync_interval: "60_minutes" } }
    await renderAdministration(testI18n(), { plans: overview({ plans: [hourly] }) })
    expect(planRow("Family").textContent).toContain("Every hour")
    await click(button("Edit", planRow("Family")))
    const intervals = select("plan-family-interval")
    expect([...intervals.options].map((option) => option.value)).toEqual(["instant", "5_minutes", "60_minutes"])
    expect(intervals.value).toBe("60_minutes")
  })

  it("closes the form on Cancel, sending nothing", async () => {
    await renderAdministration(testI18n())
    await click(button("Edit", planRow("Family")))
    await click(button("Cancel"))
    expect(container.querySelector("#plan-edit-family")).toBeNull()
    expect(calls.some((call) => call.method !== "GET")).toBe(false)
    expect(document.activeElement).toBe(button("Edit", planRow("Family")))
  })

  it("asks inline before removing a plan", async () => {
    await renderAdministration(testI18n(), { answers: { "DELETE /api/v1/plans/family": NO_CONTENT } })
    await click(button("Remove", planRow("Family")))
    const confirmation = element("plan-remove-family")
    expect(confirmation.querySelector("h3")?.textContent).toBe("Remove Family?")
    expect(confirmation.querySelector("p")?.textContent).toBe(
      "Nobody can have this plan afterwards. Rules, accounts, and tokens stay as they are.",
    )
    await click(button("Keep plan", confirmation))
    expect(container.querySelector("#plan-remove-family")).toBeNull()
    expect(sent("DELETE", "/api/v1/plans/family")).toBeUndefined()

    await click(button("Remove", planRow("Family")))
    await click(button("Remove plan", element("plan-remove-family")))
    expect(calls.some((call) => call.method === "DELETE" && call.path === "/api/v1/plans/family")).toBe(true)
    expect(status()).toBe("Family was removed.")
    expect(container.querySelector("#plan-remove-family")).toBeNull()
    expect(document.activeElement).toBe(button("Add a plan"))
  })

  it.each([
    [refusal(409, "plan_in_use", { people: 2, count: 2 }), "2 people have this plan. Give them another plan before you remove it."],
    [refusal(409, "plan_in_use", { people: 1, count: 1 }), "1 person has this plan. Give them another plan before you remove it."],
    [refusal(409, "plan_is_default"), "This is the default plan. Choose another default before you remove it."],
  ])("says why a plan cannot be removed", async (answer, reason) => {
    await renderAdministration(testI18n(), { answers: { "DELETE /api/v1/plans/family": answer } })
    await click(button("Remove", planRow("Family")))
    await click(button("Remove plan", element("plan-remove-family")))
    expect(planRow("Family").querySelector("[role='alert']")?.textContent).toBe(reason)
    expect(element("plan-remove-family")).not.toBeNull()
  })

  it("shows its own error with Try again when plans cannot load, and the rest still works", async () => {
    await renderAdministration(testI18n(), { answers: { "GET /api/v1/plans": jsonResponse({ detail: "boom" }, 500) } })
    expect(alertText()).toContain("Plans could not load.")
    expect(button("Try again")).not.toBeNull()
    expect(sections()).toEqual(["registration-title", "plans-title", "storage-title"])
  })

  it("has no untranslated text", async () => {
    await renderAdministration(pseudoI18n(), { plans: overview({ defaultPlan: "free" }) })
    await click(container.querySelector<HTMLButtonElement>("[aria-controls='plan-edit-new']")!)
    expect(untranslatedText(container, [...dateWords(), family.name, free.name])).toEqual([])
    await click(container.querySelector<HTMLButtonElement>("[aria-controls='plan-edit-family']")!)
    type(field("plan-family-rules"), "2")
    await settle()
    expect(untranslatedText(container, [...dateWords(), family.name, free.name])).toEqual([])
    await click(container.querySelector<HTMLButtonElement>("[aria-controls='plan-remove-family']")!)
    expect(untranslatedText(container, [...dateWords(), family.name, free.name])).toEqual([])
  })
})
```

In `web/src/features/settings-administration.test.tsx`, answer `GET /api/v1/plans` by default with
an installation that has no Plan yet. The new version of the `defaults` in `serve`:

```tsx
  const defaults: Record<string, Response> = {
    "GET /api/v1/session": jsonResponse(session(role)),
    "GET /api/v1/providers": jsonResponse([]),
    "GET /api/v1/accounts": jsonResponse([]),
    "GET /api/v1/integration-tokens": jsonResponse([]),
    "GET /api/v1/storage": jsonResponse({
      database: { bytes: 1024 * 1024, reclaimable_bytes: 0, activity_entries: 0, oldest_activity_at: null },
      logs: { bytes: 0, files: 0, oldest_at: null, newest_at: null },
      activity_ages: [30, 90, 180, 365],
    }),
    "GET /api/v1/registration": jsonResponse(registration ?? { policy: "invitation_only", only_me_available: false }),
    // No Plan defined yet, as a new installation starts.
    "GET /api/v1/plans": jsonResponse({ enabled: false, default_plan: null, sync_intervals: ["instant", "5_minutes"], plans: [] }),
  }
```

and replace the `"holds who can join and storage..."` case with:

```tsx
  it("holds who can join, plans, and storage, and leaves people and invitations to the People page", async () => {
    await renderSettings(testI18n(), { registration: { policy: "invitation_only", only_me_available: false } })
    expect(section("registration-title")).not.toBeNull()
    expect(section("plans-title")).not.toBeNull()
    expect(section("storage-title")).not.toBeNull()
    expect(section("people-list-title")).toBeNull()
    expect(section("invitations-title")).toBeNull()
    expect(requested("/api/v1/users")).toBe(false)
    expect(requested("/api/v1/invitations")).toBe(false)
  })
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd web && pnpm exec vitest run src/features/settings-plans.test.tsx src/features/settings-administration.test.tsx`

Expected: FAIL, 22 failed and 6 passed. In `settings-plans.test.tsx` every case but "is hidden under Only me, where the only person administers" fails (`Error: No Plans section`, `Error: No element plans-enabled`, `Error: No element plans-default`, or a section list without `plans-title`); in `settings-administration.test.tsx` "holds who can join, plans, and storage..." fails on `section("plans-title")`.

- [ ] **Step 3: Implement the editor, the section, its place in Administration, and its messages**

Create `web/src/features/plan-editor.tsx`:

```tsx
import { useEffect, useRef, useState, type RefObject, type SyntheticEvent } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { NativeSelect } from "@/components/ui/native-select"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import type { PlanPayload, PlanSummary, SyncInterval } from "@/lib/api"
import { intervalLabel } from "@/lib/plans"

/** One limit as the form holds it: the number typed, or Unlimited. */
type LimitDraft = { amount: string; unlimited: boolean }

type PlanDraft = {
  key: string
  name: string
  rules: LimitDraft
  accounts: LimitDraft
  tokens: LimitDraft
  interval: SyncInterval
}

/** The largest count a limit takes, as `COUNT_LIMIT` in domain/plans.py sets it. */
const COUNT_LIMIT = 10_000

function limitDraft(limit: number | null): LimitDraft {
  return limit === null ? { amount: "", unlimited: true } : { amount: String(limit), unlimited: false }
}

/** A new Plan starts with no limits and the first offered interval; an existing one as saved. */
function draftOf(plan: PlanSummary | null, intervals: SyncInterval[]): PlanDraft {
  if (plan === null) {
    const none = limitDraft(null)
    return { key: "", name: "", rules: none, accounts: none, tokens: none, interval: intervals[0] ?? "instant" }
  }
  const { rules, connected_accounts, integration_tokens, sync_interval } = plan.limits
  return {
    key: plan.key,
    name: plan.name,
    rules: limitDraft(rules),
    accounts: limitDraft(connected_accounts),
    tokens: limitDraft(integration_tokens),
    interval: sync_interval,
  }
}

/** null for Unlimited, the whole number typed, or undefined while the field holds none. */
function limitValue({ amount, unlimited }: LimitDraft): number | null | undefined {
  if (unlimited) return null
  const value = Number(amount)
  return amount.trim() !== "" && Number.isInteger(value) ? value : undefined
}

/** What Save sends, or null while a field still needs a value. The server checks each range. */
function payloadOf(draft: PlanDraft): PlanPayload | null {
  const rules = limitValue(draft.rules)
  const accounts = limitValue(draft.accounts)
  const tokens = limitValue(draft.tokens)
  if (!draft.key.trim() || !draft.name.trim() || rules === undefined || accounts === undefined || tokens === undefined) {
    return null
  }
  return {
    key: draft.key.trim(),
    name: draft.name.trim(),
    limits: { rules, connected_accounts: accounts, integration_tokens: tokens, sync_interval: draft.interval },
  }
}

/** Whether the rule limit typed is lower than the saved one, so some people may be over it. */
function lowersRules(plan: PlanSummary | null, draft: LimitDraft): boolean {
  const next = limitValue(draft)
  if (plan === null || plan.limited_people === 0 || typeof next !== "number") return false
  return plan.limits.rules === null || next < plan.limits.rules
}

/**
 * The inline form that adds a Plan or changes one. A new Plan's key is chosen once and never
 * changes, so the form warns about it; an existing Plan shows its key read-only. Each limit is a
 * whole number or Unlimited. `intervals` are the offered ones, plus the Plan's own when a later
 * release saved one this release does not offer.
 */
export function PlanEditor({
  plan,
  intervals,
  pending,
  error,
  onSave,
  onCancel,
}: {
  plan: PlanSummary | null
  intervals: SyncInterval[]
  pending: boolean
  error: unknown
  onSave: (payload: PlanPayload) => void
  onCancel: () => void
}) {
  const i18n = useI18n()
  const { t } = i18n
  const [draft, setDraft] = useState(() => draftOf(plan, intervals))
  const first = useRef<HTMLInputElement>(null)
  useEffect(() => {
    first.current?.focus()
  }, [])
  const id = plan ? `plan-${plan.key}` : "plan-new"
  const payload = payloadOf(draft)
  const change = (next: Partial<PlanDraft>) => setDraft((current) => ({ ...current, ...next }))

  function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    if (payload && !pending) onSave(payload)
  }

  return (
    <form className="setting-form" onSubmit={submit}>
      <KeyField id={id} plan={plan} value={draft.key} inputRef={first} onChange={(key) => change({ key })} />
      <div className="field-stack">
        <Label htmlFor={`${id}-name`}>{t("settings.plans.editor.name")}</Label>
        <Input
          ref={plan ? first : undefined}
          id={`${id}-name`}
          value={draft.name}
          maxLength={60}
          autoComplete="off"
          onChange={(event) => change({ name: event.target.value })}
        />
      </div>
      <LimitField
        id={`${id}-rules`}
        label={t("settings.plans.editor.rules")}
        limit={draft.rules}
        minimum={1}
        onChange={(rules) => change({ rules })}
      />
      <LimitField
        id={`${id}-accounts`}
        label={t("settings.plans.editor.accounts")}
        limit={draft.accounts}
        minimum={1}
        onChange={(accounts) => change({ accounts })}
      />
      <LimitField
        id={`${id}-tokens`}
        label={t("settings.plans.editor.tokens")}
        limit={draft.tokens}
        minimum={0}
        onChange={(tokens) => change({ tokens })}
      />
      <div className="field-stack">
        <Label htmlFor={`${id}-interval`}>{t("settings.plans.editor.interval")}</Label>
        <NativeSelect
          id={`${id}-interval`}
          value={draft.interval}
          onChange={(event) => change({ interval: event.target.value as SyncInterval })}
        >
          {intervals.map((interval) => (
            <option key={interval} value={interval}>
              {intervalLabel(i18n, interval)}
            </option>
          ))}
        </NativeSelect>
      </div>
      {plan && lowersRules(plan, draft.rules) && (
        <p className="field-hint" data-tone="attention">
          {t("settings.plans.editor.lowerWarning", { count: plan.limited_people })}
        </p>
      )}
      {error ? (
        <p className="field-error" role="alert">
          {apiErrorMessage(i18n, error)}
        </p>
      ) : null}
      <div className="setting-form-actions">
        <Button type="submit" disabled={!payload || pending}>
          {t("settings.plans.editor.save")}
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel}>
          {t("settings.plans.editor.cancel")}
        </Button>
      </div>
    </form>
  )
}

/** The Plan's key: chosen once, with a warning, for a new Plan; read-only for an existing one. */
function KeyField({
  id,
  plan,
  value,
  inputRef,
  onChange,
}: {
  id: string
  plan: PlanSummary | null
  value: string
  inputRef: RefObject<HTMLInputElement | null>
  onChange: (key: string) => void
}) {
  const { t } = useI18n()
  return (
    <div className="field-stack">
      <Label htmlFor={`${id}-key`}>{t("settings.plans.editor.key")}</Label>
      {plan ? (
        <Input id={`${id}-key`} value={plan.key} readOnly />
      ) : (
        <>
          <Input
            ref={inputRef}
            id={`${id}-key`}
            value={value}
            maxLength={32}
            autoComplete="off"
            spellCheck={false}
            aria-describedby={`${id}-key-hint`}
            onChange={(event) => onChange(event.target.value)}
          />
          <p id={`${id}-key-hint`} className="field-hint">
            {t("settings.plans.editor.keyHint")}
          </p>
        </>
      )}
    </div>
  )
}

/** One limit: a whole number, or Unlimited, which leaves the number aside. */
function LimitField({
  id,
  label,
  limit,
  minimum,
  onChange,
}: {
  id: string
  label: string
  limit: LimitDraft
  /** Rules and calendar accounts allow at least 1; a Plan may offer no Integration Tokens. */
  minimum: number
  onChange: (next: LimitDraft) => void
}) {
  const { t } = useI18n()
  return (
    <fieldset className="field-stack">
      <legend id={`${id}-label`}>{label}</legend>
      <Input
        id={id}
        type="number"
        inputMode="numeric"
        min={minimum}
        max={COUNT_LIMIT}
        step={1}
        value={limit.amount}
        disabled={limit.unlimited}
        aria-labelledby={`${id}-label`}
        onChange={(event) => onChange({ ...limit, amount: event.target.value })}
      />
      <label className="checkbox-row" htmlFor={`${id}-unlimited`}>
        <input
          id={`${id}-unlimited`}
          type="checkbox"
          checked={limit.unlimited}
          onChange={(event) => onChange({ ...limit, unlimited: event.target.checked })}
        />
        <span>
          <strong>{t("settings.plans.editor.unlimited")}</strong>
        </span>
      </label>
    </fieldset>
  )
}
```

Create `web/src/features/settings-plans.tsx`:

```tsx
import { Plus } from "lucide-react"
import { useRef, useState, type RefObject } from "react"

import { DestructiveConfirmation } from "@/components/destructive-confirmation"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { NativeSelect } from "@/components/ui/native-select"
import { Skeleton } from "@/components/ui/skeleton"
import { PlanEditor } from "@/features/plan-editor"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import type { PlanSummary, PlansOverview, SyncInterval } from "@/lib/api"
import { intervalLabel, planLimitsSummary } from "@/lib/plans"
import type { PlanCommands } from "@/lib/use-plans"

/** The one form or confirmation open in the section: a Plan's edit or removal, or a new Plan. */
type Opened = { action: "edit" | "remove"; key: string } | { action: "add" } | null
type Open = (next: Opened) => void

/**
 * Plans, between who can join and storage: whether Plans limit people, the Default Plan, and each
 * Plan with its limits, an inline edit, and Remove. Settings shows it only under Invitation only:
 * under Only me the only person administers, and no Plan limits an administrator.
 */
export function PlansSection({ commands }: { commands: PlanCommands }) {
  const { t } = useI18n()
  const { plans, message } = commands
  const overview = plans.data
  return (
    <section className="settings-section" aria-labelledby="plans-title">
      <div className="section-heading">
        <div>
          <h2 id="plans-title">{t("settings.plans.title")}</h2>
          <p>{t("settings.plans.intro")}</p>
        </div>
      </div>
      {plans.isPending && <Skeleton className="h-16 w-full" />}
      {plans.error && (
        <div className="inline-error integration-load-error" role="alert">
          <span>{t("settings.plans.loadError")}</span>
          <Button type="button" variant="outline" onClick={() => void plans.refetch()}>
            {t("settings.plans.tryAgain")}
          </Button>
        </div>
      )}
      {overview?.plans && <PlansList overview={overview} commands={commands} />}
      {/* Always present, so a screen reader announces each change as it is saved. */}
      <p role="status" className={message ? undefined : "sr-only"}>
        {message}
      </p>
    </section>
  )
}

function PlansList({ overview, commands }: { overview: PlansOverview; commands: PlanCommands }) {
  const [opened, setOpened] = useState<Opened>(null)
  const addButton = useRef<HTMLButtonElement>(null)

  // Opening one form or confirmation closes any other, and forgets their refusals.
  function open(next: Opened) {
    commands.define.reset()
    commands.change.reset()
    commands.remove.reset()
    setOpened(next)
  }

  return (
    <div className="settings-list">
      <EnabledItem overview={overview} commands={commands} />
      <DefaultItem overview={overview} commands={commands} />
      {overview.plans.map((plan) => (
        <PlanItem
          key={plan.key}
          plan={plan}
          intervals={editorIntervals(overview.sync_intervals, plan)}
          opened={opened}
          onOpen={open}
          commands={commands}
          onRemoved={() => {
            open(null)
            addButton.current?.focus()
          }}
        />
      ))}
      <AddPlanItem
        intervals={overview.sync_intervals}
        adding={opened?.action === "add"}
        onOpen={open}
        commands={commands}
        addButton={addButton}
      />
    </div>
  )
}

/** The offered intervals, plus a Plan's own when a later release saved one not offered here. */
function editorIntervals(offered: SyncInterval[], plan: PlanSummary): SyncInterval[] {
  const own = plan.limits.sync_interval
  return offered.includes(own) ? offered : [...offered, own]
}

/** Whether Plans limit people. It turns on only once a default exists, and keeps that default. */
function EnabledItem({ overview, commands }: { overview: PlansOverview; commands: PlanCommands }) {
  const { t } = useI18n()
  const { setting } = commands
  const hasDefault = overview.default_plan !== null
  // While a change is on its way, the box shows what was asked for.
  const checked = setting.isPending ? setting.variables.enabled : overview.enabled
  return (
    <div className="setting-item">
      <div className="setting-row">
        <label className="checkbox-row" htmlFor="plans-enabled">
          <input
            id="plans-enabled"
            type="checkbox"
            checked={checked}
            disabled={setting.isPending || (!hasDefault && !overview.enabled)}
            aria-describedby="plans-enabled-hint"
            onChange={(event) => setting.mutate({ enabled: event.target.checked, defaultPlan: overview.default_plan })}
          />
          <span>
            <strong>{t("settings.plans.enabled.label")}</strong>
            <small id="plans-enabled-hint">
              {hasDefault ? t("settings.plans.enabled.hint") : t("settings.plans.enabled.needsDefault")}
            </small>
          </span>
        </label>
      </div>
    </div>
  )
}

/** The Default Plan. It cannot be cleared while Plans limit people. */
function DefaultItem({ overview, commands }: { overview: PlansOverview; commands: PlanCommands }) {
  const i18n = useI18n()
  const { t } = i18n
  const { setting } = commands
  return (
    <div className="setting-item">
      <div className="setting-row">
        <div className="setting-copy">
          <h3 id="plans-default-title">{t("settings.plans.default.label")}</h3>
          <p id="plans-default-hint">{t("settings.plans.default.hint")}</p>
        </div>
        <div className="appearance-control">
          <NativeSelect
            id="plans-default"
            aria-labelledby="plans-default-title"
            aria-describedby="plans-default-hint"
            value={overview.default_plan ?? ""}
            disabled={setting.isPending}
            onChange={(event) => setting.mutate({ enabled: overview.enabled, defaultPlan: event.target.value || null })}
          >
            <option value="" disabled={overview.enabled}>
              {t("settings.plans.default.none")}
            </option>
            {overview.plans.map((plan) => (
              <option key={plan.key} value={plan.key}>
                {plan.name}
              </option>
            ))}
          </NativeSelect>
        </div>
      </div>
      {setting.error && (
        <p className="field-error" role="alert">
          {apiErrorMessage(i18n, setting.error)}
        </p>
      )}
    </div>
  )
}

/** One Plan: its name, limits, interval, and who has it, with Edit and Remove. */
function PlanItem({
  plan,
  intervals,
  opened,
  onOpen,
  commands,
  onRemoved,
}: {
  plan: PlanSummary
  intervals: SyncInterval[]
  opened: Opened
  onOpen: Open
  commands: PlanCommands
  /** Moves focus on once the Plan's row is gone. */
  onRemoved: () => void
}) {
  const i18n = useI18n()
  const { t } = i18n
  const editButton = useRef<HTMLButtonElement>(null)
  const removeButton = useRef<HTMLButtonElement>(null)
  const mine = opened !== null && opened.action !== "add" && opened.key === plan.key
  const editing = mine && opened.action === "edit"
  const removing = mine && opened.action === "remove"
  const { change } = commands

  function close(toggle: RefObject<HTMLButtonElement | null>) {
    onOpen(null)
    toggle.current?.focus()
  }

  return (
    <div className="setting-item">
      <div className="setting-row">
        <div className="setting-copy">
          <h3>{plan.name}</h3>
          {plan.is_default && <Badge variant="neutral">{t("settings.plans.isDefault")}</Badge>}
          <p>{planLimitsSummary(i18n, plan.limits)}</p>
          <p>{intervalLabel(i18n, plan.limits.sync_interval)}</p>
          <p>{t("settings.plans.people", { count: plan.people })}</p>
        </div>
        <div className="setting-form-actions">
          <Button
            ref={editButton}
            type="button"
            variant="outline"
            aria-expanded={editing}
            aria-controls={`plan-edit-${plan.key}`}
            onClick={() => onOpen({ action: "edit", key: plan.key })}
          >
            {t("settings.plans.edit")}
          </Button>
          <Button
            ref={removeButton}
            type="button"
            variant="ghost"
            aria-expanded={removing}
            aria-controls={`plan-remove-${plan.key}`}
            onClick={() => onOpen({ action: "remove", key: plan.key })}
          >
            {t("settings.plans.remove")}
          </Button>
        </div>
      </div>
      {editing && (
        <div id={`plan-edit-${plan.key}`}>
          <PlanEditor
            plan={plan}
            intervals={intervals}
            pending={change.isPending}
            error={change.error}
            onSave={({ name, limits }) =>
              change.mutate({ key: plan.key, payload: { name, limits } }, { onSuccess: () => close(editButton) })
            }
            onCancel={() => close(editButton)}
          />
        </div>
      )}
      {removing && (
        <PlanRemoval plan={plan} commands={commands} onRemoved={onRemoved} onKeep={() => close(removeButton)} />
      )}
    </div>
  )
}

/** Remove, confirmed inline. The server refuses the default and a Plan someone has, and says why. */
function PlanRemoval({
  plan,
  commands,
  onRemoved,
  onKeep,
}: {
  plan: PlanSummary
  commands: PlanCommands
  onRemoved: () => void
  onKeep: () => void
}) {
  const i18n = useI18n()
  const { t } = i18n
  const { remove } = commands
  return (
    <>
      <DestructiveConfirmation
        id={`plan-remove-${plan.key}`}
        title={t("settings.plans.removeConfirm.title", { name: plan.name })}
        body={t("settings.plans.removeConfirm.body")}
        cancelLabel={t("settings.plans.removeConfirm.keep")}
        confirmLabel={t("settings.plans.removeConfirm.confirm")}
        pendingLabel={t("settings.plans.removeConfirm.pending")}
        pending={remove.isPending}
        onConfirm={() => remove.mutate(plan.key, { onSuccess: onRemoved })}
        onCancel={onKeep}
      />
      {remove.error && (
        <p className="field-error" role="alert">
          {apiErrorMessage(i18n, remove.error)}
        </p>
      )}
    </>
  )
}

/** "Add a plan", and its inline form once opened. */
function AddPlanItem({
  intervals,
  adding,
  onOpen,
  commands,
  addButton,
}: {
  intervals: SyncInterval[]
  adding: boolean
  onOpen: Open
  commands: PlanCommands
  addButton: RefObject<HTMLButtonElement | null>
}) {
  const { t } = useI18n()
  const { define } = commands

  function close() {
    onOpen(null)
    addButton.current?.focus()
  }

  return (
    <div className="setting-item">
      <div className="setting-row">
        <Button
          ref={addButton}
          type="button"
          variant="outline"
          aria-expanded={adding}
          aria-controls="plan-edit-new"
          onClick={() => onOpen({ action: "add" })}
        >
          <Plus aria-hidden="true" />
          {t("settings.plans.add")}
        </Button>
      </div>
      {adding && (
        <div id="plan-edit-new">
          <PlanEditor
            plan={null}
            intervals={intervals}
            pending={define.isPending}
            error={define.error}
            onSave={(payload) => define.mutate(payload, { onSuccess: close })}
            onCancel={close}
          />
        </div>
      )}
    </div>
  )
}
```

In `web/src/features/settings.tsx`, import the hook beside `useRegistration`:

```tsx
import { useOAuthReturn } from "@/lib/use-oauth-return"
import { usePlans } from "@/lib/use-plans"
import { useRegistration } from "@/lib/use-registration"
```

import the section beside the other Settings sections:

```tsx
import { OwnAccountSection } from "@/features/settings-own-account"
import { PlansSection } from "@/features/settings-plans"
import { RegistrationSection } from "@/features/settings-registration"
```

and replace `AdministrationTab` with:

```tsx
/**
 * Who can join, Plans, and storage. Only an Installation Administrator sees them; the server
 * refuses everyone else. The people here and their invitations have their own page. Plans show
 * only under Invitation only: under Only me the only person administers, and no Plan limits them.
 */
function AdministrationTab() {
  const registration = useRegistration()
  const plans = usePlans()
  return (
    <>
      <RegistrationSection commands={registration} />
      {registration.registration.data?.policy === "invitation_only" && <PlansSection commands={plans} />}
      <StorageSection />
    </>
  )
}
```

In `web/src/i18n/locales/en/settings.json`, the full new version of the `plans` group (between
`registration` and `links`; `limits`, `interval`, and `saved` are task 14's, unchanged):

```json
  "plans": {
    "title": "Plans",
    "intro": "Plans limit how many rules, calendar accounts, and Integration Tokens each person may have, and how soon their calendars sync. Administrators are never limited.",
    "loadError": "Plans could not load.",
    "tryAgain": "Try again",
    "enabled": {
      "label": "Limit people with plans",
      "hint": "While this is off, nobody is limited.",
      "needsDefault": "Choose a default plan first."
    },
    "default": {
      "label": "Default plan",
      "hint": "People without a plan of their own have it, including people who join later.",
      "none": "No default"
    },
    "people": {
      "one": "{count} person",
      "other": "{count} people"
    },
    "isDefault": "Default",
    "limits": {
      "rules": {
        "one": "{count} rule",
        "other": "{count} rules"
      },
      "accounts": {
        "one": "{count} calendar account",
        "other": "{count} calendar accounts"
      },
      "tokens": {
        "one": "{count} token",
        "other": "{count} tokens"
      },
      "unlimitedRules": "Unlimited rules",
      "unlimitedAccounts": "unlimited calendar accounts",
      "unlimitedTokens": "unlimited tokens",
      "noTokens": "no tokens"
    },
    "interval": {
      "instant": "Instant sync, and a check every 5 minutes",
      "5_minutes": "Every 5 minutes",
      "10_minutes": "Every 10 minutes",
      "15_minutes": "Every 15 minutes",
      "30_minutes": "Every 30 minutes",
      "60_minutes": "Every hour"
    },
    "edit": "Edit",
    "remove": "Remove",
    "add": "Add a plan",
    "editor": {
      "name": "Name",
      "key": "Key",
      "keyHint": "Lower-case letters, digits, and hyphens. The key cannot change later.",
      "rules": "Rules that sync",
      "accounts": "Calendar accounts",
      "tokens": "Integration Tokens",
      "unlimited": "Unlimited",
      "interval": "How soon calendars sync",
      "save": "Save plan",
      "cancel": "Cancel",
      "lowerWarning": {
        "one": "This plan limits {count} person. Rules beyond a lower limit keep syncing, but no new rule can start until the count is within it.",
        "other": "This plan limits {count} people. Rules beyond a lower limit keep syncing, but no new rule can start until the count is within it."
      }
    },
    "removeConfirm": {
      "title": "Remove {name}?",
      "body": "Nobody can have this plan afterwards. Rules, accounts, and tokens stay as they are.",
      "confirm": "Remove plan",
      "keep": "Keep plan",
      "pending": "Removing…"
    },
    "saved": {
      "on": "Plans now limit people.",
      "off": "Plans no longer limit anyone.",
      "defaultChanged": "{name} is now the default plan.",
      "defined": "{name} was added.",
      "changed": "{name} was saved.",
      "removed": "{name} was removed."
    }
  }
```

- [ ] **Step 4: Run the tests and the frontend checks to verify they pass**

Run:

```sh
cd web && pnpm exec vitest run src/features/settings-plans.test.tsx src/features/settings-administration.test.tsx src/features/settings.test.tsx src/i18n/catalog.test.ts
cd web && pnpm run typecheck && pnpm run lint && pnpm run knip && pnpm run doctor
cd web && pnpm run test
```

Expected: PASS (22 tests in `settings-plans.test.tsx`, 6 in `settings-administration.test.tsx`; `settings.test.tsx` unchanged because its Registration answer is Only me, so the Plans section stays hidden there; the catalog finds every `settings.plans.*` key named). Typecheck, lint, knip, and doctor report nothing; the full suite passes.

- [ ] **Step 5: Rebuild the static bundle**

Run: `cd web && pnpm run build`

Expected: `tsc -b` clean and a new hashed bundle under `src/calendar_sync/interfaces/api/static/`.

- [ ] **Step 6: Commit**

```sh
git add web/src/features/settings-plans.tsx web/src/features/plan-editor.tsx web/src/features/settings.tsx \
  web/src/features/settings-plans.test.tsx web/src/features/settings-administration.test.tsx \
  web/src/i18n/locales/en/settings.json
git add -A src/calendar_sync/interfaces/api/static
.venv/bin/pytest tests/test_no_em_dashes.py tests/test_ubiquitous_language.py -q
git commit -F - <<'EOF'
Let administrators define Plans, choose the default, and turn Plans on

Settings, Administration gains Plans between Who can join and Storage,
shown under Invitation only: a switch that limits people once a default
exists, the Default Plan, each Plan with its limits and an inline edit,
Remove with an inline confirmation, and Add a plan, which warns that the
key cannot change.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
```

The two pytest checks read `git ls-files`, so they run after staging. Expected: `passed` (no em
dash and no avoided term in the new files); nothing else in the backend changes in this task.


## Part 9: People, Your plan, and limit hints (Tasks 16, 17, and 18)

These three tasks finish the Web UI of slice 1. Task 16 shows each person's Plan on their page and
lets an administrator change it inline. Task 17 adds Settings, Your account, Your plan. Task 18
adds every limit hint: Start, Connect, and Issue token wait at a limit and say why, and a note
warns before a privacy edit, a Pause, or a Disconnect while more rules count than the Plan allows.
Task numbers follow `.context/plans-slice1-contract.md` section 5.

Before you start: read `DESIGN.md` (no modals, inline disclosure, one visible next step, the Quiet
Indicator Rule), `CONTEXT.md` (Plan, Default Plan, Allowance, Rule Replacement), and `AGENTS.md`.
These tasks need tasks 9, 11, 13, and 14 merged: they use `RuleDetail.can_start` and
`RuleDetail.rule_limit` (task 9), `common.plan.seeYourPlan` and `yourPlanPath()` (task 11),
`UserOverview.plan` and the Plans routes (task 13), and from task 14 the API methods
`api.plans`, `api.setPersonPlan`, `api.ownPlan`, the types `PersonPlan`, `PlansOverview`,
`OwnPlan`, the helpers in `web/src/lib/plans.ts`, the hooks in `web/src/lib/use-own-plan.ts`,
`PLANS_QUERY` in `web/src/lib/use-plans.ts`, and `YourPlanLink` in
`web/src/components/your-plan-link.tsx`.

Run `pnpm` commands from `web/` and every other command from the repository root. Every number
in a plural message goes in as `count`. Never write an em dash, and never write a term that
`AVOIDED` in `tests/test_ubiquitous_language.py` lists, including the four task 19 adds for Plans
and Plan Hold; the check also matches an identifier that joins the words in camelCase. No task
here changes a schema, so none regenerates the OpenAPI files. Every task rebuilds the static
bundle and commits it with its source.

ESLint's `complexity` bound is 10 per function, and several functions these tasks touch were
already close (`PreviewFooter` 10, `SettingsView` 9, `PolicyEditor` 9, `RuleCommandMenu` 8,
`StartButton` 8). The code below moves new decisions into small helpers and components so each
function stays within the bound; keep it that way if you adjust anything.

---

### Task 16: People, the Plan fact and Change plan

**Files:**
- Create: `web/src/features/person-plan.tsx` (`PersonPlanChoice`)
- Modify: `web/src/lib/use-people.ts` (`PersonAction`, `PersonCommand`, `CHANGED`, `run`, `usePersonCommands`: new `choosingPlan` state, `finish`, `start`, `hasDetails`, the returned object)
- Modify: `web/src/features/person-actions.tsx` (imports, `PersonMenu`, `personActions`, `PersonDetails`)
- Modify: `web/src/features/person-page.tsx` (imports, `PersonContent`, `PersonFacts`)
- Modify: `web/src/i18n/locales/en/people.json` (`actions.changePlan`, `actions.changePlanHint`, `status.planChanged`, and `plan.label`, `plan.default`, `plan.save`, `plan.cancel` inside the `plan` object task 14 added)
- Modify: `src/calendar_sync/interfaces/api/static/` (rebuilt bundle)
- Test: `web/src/features/person-page.test.tsx`, `web/src/features/people-page.test.tsx`

**Interfaces:**
- Consumes:
  - Task 13: `UserOverview.plan: PersonPlan | null` (null while no Plan exists); `PUT /api/v1/users/{user_id}/plan` with body `{ plan: string | null }`; `GET /api/v1/plans` answering `PlansOverview`; error code `plan_not_found` (404).
  - Task 14: `api.plans(): Promise<PlansOverview>`, `api.setPersonPlan(userId: string, plan: string | null): Promise<PersonPlan>`, `type PersonPlan = Schemas["PersonPlanResponse"]` (`basis`, `plan: { key, name, on_default } | null`, `assigned: { key, name } | null`), `type PlansOverview = Schemas["PlansResponse"]` (`enabled`, `default_plan`, `sync_intervals`, `plans: PlanSummary[]`), `PLANS_QUERY = ["plans"] as const` from `@/lib/use-plans`, `personPlanFact(i18n: I18n, plan: PersonPlan): string` from `@/lib/plans`, and the `people.plan.fact.*` keys.
  - Task 6: `common.apiError.plan_not_found` ("This plan no longer exists. Reload to see the current plans.").
- Produces:
  - `type PersonAction = "promote" | "demote" | "disable" | "enable" | "reset" | "delete" | "plan"` (private to `use-people.ts`).
  - `export type PersonCommand = { person: Person; action: PersonAction; plan?: string | null }`.
  - `usePersonCommands()` result gains `choosingPlan: string | null` and `setChoosingPlan: (personId: string | null) => void`; `start({ person, action: "plan" })` without `plan` opens the choice; `hasDetails(person)` also counts `choosingPlan === person.id`.
  - `export function PersonPlanChoice({ person, current, commands }: { person: Person; current: PersonPlan | null; commands: PeopleCommands })` in `features/person-plan.tsx`; its select has id `person-plan-<person.id>`.
  - `PersonMenu({ person, name, commands, plan }: { person: Person; name: string; commands: PeopleCommands; plan?: PersonPlan | null })`: "Change plan" only when `plan` is given and not null.
  - `PersonDetails({ person, name, commands, plan }: { person: Person; name: string; commands: PeopleCommands; plan?: PersonPlan | null })`: renders `PersonPlanChoice` when `commands.choosingPlan === person.id`.
  - i18n keys: `people.actions.changePlan`, `people.actions.changePlanHint`, `people.plan.label`, `people.plan.default`, `people.plan.save`, `people.plan.cancel`, `people.status.planChanged`.

- [ ] **Step 1: Write the failing tests**

In `web/src/features/person-page.test.tsx`, change the type import from `@/lib/api` (line 12) to:

```tsx
import type { PersonPlan, PlansOverview, SessionStatus, UserOverview } from "@/lib/api"
```

After the `session` constant (it ends with `user: { id: "user-dana", ... },\n}`), add these fixtures:

```tsx
/** Robin's own Plan, which limits them while Plans are on. */
const onFamily: PersonPlan = {
  basis: "plan",
  plan: { key: "family", name: "Family", on_default: false },
  assigned: { key: "family", name: "Family" },
}

/** What assigning Robin the Default Plan answers. */
const onFree: PersonPlan = {
  basis: "plan",
  plan: { key: "free", name: "Free", on_default: true },
  assigned: null,
}

/** The Plans an administrator chooses from, by name then key, as the server lists them. */
const plans: PlansOverview = {
  enabled: true,
  default_plan: "free",
  sync_intervals: ["instant", "5_minutes"],
  plans: [
    {
      key: "family",
      name: "Family",
      limits: { rules: 5, connected_accounts: 3, integration_tokens: 2, sync_interval: "instant" },
      is_default: false,
      people: 1,
      limited_people: 1,
    },
    {
      key: "free",
      name: "Free",
      limits: { rules: 1, connected_accounts: 1, integration_tokens: 0, sync_interval: "5_minutes" },
      is_default: true,
      people: 3,
      limited_people: 2,
    },
  ],
}
```

After the existing `choose` helper (it ends with `await click(item)\n}`), add:

```tsx
/** The facts under the person's name, in order. */
function facts() {
  return [...container.querySelectorAll(".person-facts li")].map((item) => item.textContent)
}

/** The labels of the open actions menu, in order. */
function menuLabels() {
  return [...container.querySelectorAll("[role='menuitem'] .overflow-menu-label")].map((label) => label.textContent)
}

/** Chooses a value in the open Plan choice. */
async function pick(value: string) {
  const select = container.querySelector<HTMLSelectElement>("#person-plan-user-robin")!
  act(() => {
    select.value = value
    select.dispatchEvent(new Event("change", { bubbles: true }))
  })
  await settle()
}
```

Inside `describe("A person's page", ...)`, after the test `"says when nobody here has the address"`, add:

```tsx
  describe("their plan", () => {
    const withPlan = (plan: PersonPlan, extra: Record<string, Response> = {}) => ({
      "GET /api/v1/users/user-robin/overview": jsonResponse({ ...robin, plan }),
      "GET /api/v1/plans": jsonResponse(plans),
      ...extra,
    })

    it("shows no plan fact and offers no Change plan while no plan exists", async () => {
      await renderPerson(testI18n())
      expect(facts()).toEqual(["User", "Joined just now", "Never signed in"])
      await click(container.querySelector<HTMLButtonElement>("[aria-haspopup='menu']")!)
      expect(menuLabels()).toEqual(["Make administrator", "Disable", "Create password reset link", "Delete"])
    })

    const CASES: [string, PersonPlan, string][] = [
      ["their own plan", onFamily, "Family"],
      ["the default plan, which they have without one of their own", onFree, "Free (default)"],
      [
        "their own plan while plans are off",
        { basis: "plans_off", plan: null, assigned: { key: "family", name: "Family" } },
        "Family, once plans are on",
      ],
      [
        "the default plan while plans are off",
        { basis: "plans_off", plan: null, assigned: null },
        "The default plan, once plans are on",
      ],
      ["that no plan limits an administrator", { basis: "administrator", plan: null, assigned: null }, "No plan limits administrators"],
      [
        "a plan kept for an administrator, which limits nothing",
        { basis: "administrator", plan: null, assigned: { key: "family", name: "Family" } },
        "No plan limits administrators (assigned: Family)",
      ],
    ]

    it.each(CASES)("states %s as a fact beside their role", async (_case, plan, fact) => {
      await renderPerson(testI18n(), "user-robin", withPlan(plan))
      expect(facts()).toEqual(["User", fact, "Joined just now", "Never signed in"])
    })

    it("offers Change plan beside their other actions once a plan exists", async () => {
      await renderPerson(testI18n(), "user-robin", withPlan(onFamily))
      await click(container.querySelector<HTMLButtonElement>("[aria-haspopup='menu']")!)
      expect(menuLabels()).toEqual(["Make administrator", "Disable", "Change plan", "Create password reset link", "Delete"])
      const item = [...container.querySelectorAll("[role='menuitem']")].find(
        (candidate) => candidate.querySelector(".overflow-menu-label")?.textContent === "Change plan",
      )
      expect(item?.querySelector(".overflow-menu-description")?.textContent).toBe("Choose which plan limits this person.")
    })

    it("chooses inline among the plans and the default plan, and returns them to the default", async () => {
      await renderPerson(testI18n(), "user-robin", withPlan(onFamily, { "PUT /api/v1/users/user-robin/plan": jsonResponse(onFree) }))
      await choose("Change plan")

      const select = container.querySelector<HTMLSelectElement>("#person-plan-user-robin")!
      expect(container.querySelector("label[for='person-plan-user-robin']")?.textContent).toBe("Plan for robin@example.test")
      expect([...select.options].map((option) => [option.value, option.textContent])).toEqual([
        ["", "The default plan"],
        ["family", "Family"],
        ["free", "Free"],
      ])
      // It opens on their own Plan, with focus on the choice.
      expect(select.value).toBe("family")
      expect(document.activeElement).toBe(select)

      await pick("")
      await click(button("Save plan"))
      expect(calls.filter((call) => call.method === "PUT")).toEqual([
        { method: "PUT", path: "/api/v1/users/user-robin/plan", body: { plan: null } },
      ])
      expect(container.querySelector("[role='status']")?.textContent).toBe("robin@example.test has a new plan.")
      expect(container.querySelector(".command-result")?.textContent).toBe("robin@example.test has a new plan.")
      expect(container.querySelector("#person-plan-user-robin")).toBeNull()
    })

    it("gives them a plan of their own by its key", async () => {
      await renderPerson(testI18n(), "user-robin", withPlan(onFree, { "PUT /api/v1/users/user-robin/plan": jsonResponse(onFamily) }))
      await choose("Change plan")
      expect(container.querySelector<HTMLSelectElement>("#person-plan-user-robin")?.value).toBe("")

      await pick("family")
      await click(button("Save plan"))
      expect(calls.find((call) => call.method === "PUT")?.body).toEqual({ plan: "family" })
    })

    it("shows the server's refusal beside them and keeps the choice open", async () => {
      const refusal = { detail: "plan free does not exist", code: "plan_not_found", params: {} }
      await renderPerson(testI18n(), "user-robin", withPlan(onFamily, { "PUT /api/v1/users/user-robin/plan": jsonResponse(refusal, 404) }))
      await choose("Change plan")
      await pick("free")
      await click(button("Save plan"))

      expect(container.querySelector(".field-error[role='alert']")?.textContent).toBe(
        "This plan no longer exists. Reload to see the current plans.",
      )
      expect(container.querySelector("#person-plan-user-robin")).not.toBeNull()
      expect(container.querySelector("[role='status']")?.textContent).toBe("")
    })

    it("closes the choice on Cancel without saving", async () => {
      await renderPerson(testI18n(), "user-robin", withPlan(onFamily))
      await choose("Change plan")
      await click(button("Cancel"))

      expect(container.querySelector("#person-plan-user-robin")).toBeNull()
      expect(calls.some((call) => call.method === "PUT")).toBe(false)
    })

    it("has no untranslated text with the plan fact and the plan choice open", async () => {
      await renderPerson(pseudoI18n(), "user-robin", withPlan(onFamily))
      await click(container.querySelector<HTMLButtonElement>("[aria-haspopup='menu']")!)
      // The item's description id ends with its action, "plan"; its label is pseudo-translated.
      const change = [...container.querySelectorAll<HTMLButtonElement>("[role='menuitem']")].find((item) =>
        item.getAttribute("aria-describedby")?.endsWith("-plan"),
      )!
      await click(change)

      expect(container.querySelector("#person-plan-user-robin")).not.toBeNull()
      expect(untranslatedText(container, ["robin@example.test", RULE_NAME, "Family", "Free", ...dateWords()])).toEqual([])
    })
  })
```

In `web/src/features/people-page.test.tsx`, inside `describe("People page", ...)`, after the test `"makes someone an administrator"`, add:

```tsx
  it("keeps Change plan to a person's own page, out of the table's rows", async () => {
    await renderPeople(testI18n())
    await click(personRow("robin@example.test").querySelector<HTMLButtonElement>("[aria-haspopup='menu']")!)
    const labels = [...personRow("robin@example.test").querySelectorAll("[role='menuitem'] .overflow-menu-label")].map(
      (label) => label.textContent,
    )
    expect(labels).toEqual(["Make administrator", "Disable", "Create password reset link", "Delete"])
  })
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd web && pnpm exec vitest run src/features/person-page.test.tsx src/features/people-page.test.tsx`

Expected: FAIL. The six `states ... as a fact beside their role` cases fail with `expected [ 'User', 'Joined just now', 'Never signed in' ] to deeply equal [ 'User', 'Family', ... ]`; `offers Change plan ...` fails on the menu labels; the choice tests fail with `Error: No action Change plan`; the pseudo test fails because `change` is undefined. Two tests already pass, because they pin what must not change: `shows no plan fact and offers no Change plan while no plan exists` and the People page's `keeps Change plan to a person's own page, out of the table's rows`.

- [ ] **Step 3: Add the copy**

In `web/src/i18n/locales/en/people.json`, make three exact replacements. Each inserts keys right after an object's opening line, so it works wherever task 14 put its keys.

Replace:

```json
  "actions": {
    "label": "Actions for {email}",
```

with:

```json
  "actions": {
    "label": "Actions for {email}",
    "changePlan": "Change plan",
    "changePlanHint": "Choose which plan limits this person.",
```

Replace:

```json
  "status": {
    "administrator": "{email} is now an administrator.",
```

with:

```json
  "status": {
    "administrator": "{email} is now an administrator.",
    "planChanged": "{email} has a new plan.",
```

Replace the opening line of the `plan` object task 14 added (it holds `fact`):

```json
  "plan": {
```

with:

```json
  "plan": {
    "label": "Plan for {email}",
    "default": "The default plan",
    "save": "Save plan",
    "cancel": "Cancel",
```

After the edit, the whole `plan` object reads (the `fact` keys are task 14's, unchanged):

```json
  "plan": {
    "label": "Plan for {email}",
    "default": "The default plan",
    "save": "Save plan",
    "cancel": "Cancel",
    "fact": {
      "own": "{name}",
      "default": "{name} (default)",
      "later": "{name}, once plans are on",
      "laterDefault": "The default plan, once plans are on",
      "administrator": "No plan limits administrators",
      "administratorAssigned": "No plan limits administrators (assigned: {name})"
    }
  },
```

- [ ] **Step 4: Teach the person commands to change a Plan**

Replace the whole of `web/src/lib/use-people.ts` with:

```ts
import { keepPreviousData, useIsMutating, useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"

import { useI18n } from "@/i18n/provider"
import type { MessageKey } from "@/i18n/types"
import { api, type IssuedLink, type PeopleQuery, type Person, type UserDeletion } from "@/lib/api"
import { deletionMessage, personName } from "@/lib/people"

/** What an Installation Administrator can do to another User. */
type PersonAction = "promote" | "demote" | "disable" | "enable" | "reset" | "delete" | "plan"
/**
 * A command on someone. `plan` is the Plan a "plan" command gives them, null for the Default
 * Plan; starting "plan" without it opens the choice instead, as "delete" opens its confirmation.
 */
export type PersonCommand = { person: Person; action: PersonAction; plan?: string | null }

/** What a command returned that the administrator needs next: a link to pass on, or a deletion's counts. */
type Outcome = { link?: IssuedLink; deletion?: UserDeletion }

const CHANGED: Partial<Record<PersonAction, MessageKey>> = {
  promote: "people.status.administrator",
  demote: "people.status.notAdministrator",
  disable: "people.status.disabled",
  enable: "people.status.enabled",
  plan: "people.status.planChanged",
}

// Every person command shares this key, so the query client, which outlives the People page,
// knows one is running even after the page that sent it is gone.
const PERSON_COMMAND = ["person-command"]

async function run({ person, action, plan }: PersonCommand): Promise<Outcome> {
  switch (action) {
    case "promote":
      await api.setPersonRole(person.id, "installation_administrator")
      return {}
    case "demote":
      await api.setPersonRole(person.id, "user")
      return {}
    case "disable":
      await api.setPersonState(person.id, "disabled")
      return {}
    case "enable":
      await api.setPersonState(person.id, "active")
      return {}
    case "reset":
      return { link: await api.issuePasswordResetLink(person.id) }
    case "delete":
      return { deletion: await api.deletePerson(person.id) }
    case "plan":
      await api.setPersonPlan(person.id, plan ?? null)
      return {}
  }
}

/** One page of the people matching a query; the page shown stays while the next one loads. */
export function usePeoplePage(query: PeopleQuery) {
  return useQuery({
    queryKey: ["people", query],
    queryFn: () => api.people(query),
    placeholderData: keepPreviousData,
  })
}

/**
 * The commands an administrator runs on someone else. One command runs at a time, even across
 * opening the page again: a second one started before the first answers could undo what the
 * first returned, as a new Password Reset Link revokes the one just shown. Its error is shown
 * beside the person it was for. `onDeleted` hears what a deletion did, for a page that cannot
 * stay once its person is gone.
 */
export function usePersonCommands({ onDeleted }: { onDeleted?: (message: string) => void } = {}) {
  const i18n = useI18n()
  const queryClient = useQueryClient()
  const [message, setMessage] = useState("")
  const [deleting, setDeleting] = useState<string | null>(null)
  // The person whose Plan is being chosen, inline beside them.
  const [choosingPlan, setChoosingPlan] = useState<string | null>(null)
  const [resetLink, setResetLink] = useState<{ personId: string; link: IssuedLink } | null>(null)
  // What the last command on someone still listed did, shown beside them.
  const [result, setResult] = useState<{ personId: string; text: string } | null>(null)
  const [deletedMessage, setDeletedMessage] = useState("")
  const busy = useIsMutating({ mutationKey: PERSON_COMMAND }) > 0
  const command = useMutation({
    mutationKey: PERSON_COMMAND,
    mutationFn: run,
    onSuccess: async (outcome, command) => {
      finish(outcome, command)
      // Whether Only Me is available depends on who is left.
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["people"] }),
        queryClient.invalidateQueries({ queryKey: ["registration"] }),
      ])
    },
  })

  function finish({ link, deletion }: Outcome, { person, action }: PersonCommand) {
    const name = personName(i18n, person)
    const changed = CHANGED[action]
    if (link) setResetLink({ personId: person.id, link })
    if (action === "plan") setChoosingPlan(null)
    if (deletion) {
      const deleted = deletionMessage(i18n, name, deletion)
      setDeleting(null)
      setMessage(deleted)
      setDeletedMessage(deleted)
    }
    if (changed) {
      const text = i18n.t(changed, { email: name })
      setMessage(text)
      setResult({ personId: person.id, text })
    }
  }

  // Asks the query client rather than `busy`, so even a second click before the page shows the
  // first command running waits.
  function running(): boolean {
    return queryClient.isMutating({ mutationKey: PERSON_COMMAND }) > 0
  }

  function send(next: PersonCommand) {
    if (running()) return
    // A callback given to this one call runs only while the page that sent it is still shown,
    // so a deletion that finishes after leaving it never navigates from wherever the
    // administrator went.
    command.mutate(next, {
      onSuccess: ({ deletion }) => {
        if (deletion && onDeleted) onDeleted(deletionMessage(i18n, personName(i18n, next.person), deletion))
      },
    })
  }

  function start(next: PersonCommand) {
    if (running()) return
    command.reset()
    setMessage("")
    setResult(null)
    setDeletedMessage("")
    if (next.action === "delete") setDeleting(next.person.id)
    else if (next.action === "plan" && next.plan === undefined) setChoosingPlan(next.person.id)
    else send(next)
  }

  /** The error of the last command, when it was for this person. */
  function errorFor(person: Person): unknown {
    return command.variables?.person.id === person.id ? command.error : null
  }

  /** What the last command on this person did, when it was for them. */
  function resultFor(person: Person): string | null {
    return result?.personId === person.id ? result.text : null
  }

  /** Whether a command on this person has something to show beside them. */
  function hasDetails(person: Person): boolean {
    return (
      errorFor(person) !== null ||
      deleting === person.id ||
      choosingPlan === person.id ||
      resetLink?.personId === person.id ||
      resultFor(person) !== null
    )
  }

  return {
    command,
    busy,
    message,
    deletedMessage,
    deleting,
    setDeleting,
    choosingPlan,
    setChoosingPlan,
    resetLink,
    setResetLink,
    start,
    send,
    errorFor,
    resultFor,
    hasDetails,
  }
}

export type PeopleCommands = ReturnType<typeof usePersonCommands>

// The person whose page was opened from People, and the list's address then, so coming back
// restores the same search, filters, sort, and page. The address lasts until someone else is
// opened, so Back then Forward to their page still leads to the same list; focusing their row
// on return happens once.
let opened: { personId: string; search: string } | null = null
let focusTarget: string | null = null

/** Remember the person whose page People is about to open, and the list's search then. */
export function rememberOpenedPerson(personId: string, search: string): void {
  opened = { personId, search }
  focusTarget = personId
}

/** The list's address search to return to from this person's page; empty when opened elsewhere. */
export function peopleReturnSearch(personId: string): string {
  return opened?.personId === personId ? opened.search : ""
}

/** The person whose row People focuses on return, once; later calls answer null. */
export function takeOpenedPerson(): string | null {
  const personId = focusTarget
  focusTarget = null
  return personId
}
```

- [ ] **Step 5: Add the inline Plan choice**

Create `web/src/features/person-plan.tsx`:

```tsx
import { useQuery } from "@tanstack/react-query"
import { useEffect, useRef, useState, type SyntheticEvent } from "react"

import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { NativeSelect } from "@/components/ui/native-select"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import { api, type Person, type PersonPlan } from "@/lib/api"
import { personName } from "@/lib/people"
import type { PeopleCommands } from "@/lib/use-people"
import { PLANS_QUERY } from "@/lib/use-plans"

/** The choice's value for the Default Plan; no Plan key is empty. */
const DEFAULT_PLAN = ""

/**
 * Which Plan limits this person, chosen inline beside them: one of the Plans, or the Default
 * Plan, which they then follow whenever it changes. It opens on their own Plan. Save sends the
 * key, or null for the default; the server's refusal shows beside them, as for any command.
 */
export function PersonPlanChoice({
  person,
  current,
  commands,
}: {
  person: Person
  current: PersonPlan | null
  commands: PeopleCommands
}) {
  const i18n = useI18n()
  const { t } = i18n
  // The Administration Plans section reads the same list under the same key.
  const plans = useQuery({ queryKey: PLANS_QUERY, queryFn: api.plans })
  // Null until the administrator chooses, so the choice opens on their own Plan.
  const [chosen, setChosen] = useState<string | null>(null)
  const value = chosen ?? current?.assigned?.key ?? DEFAULT_PLAN
  const select = useRef<HTMLSelectElement>(null)
  useEffect(() => {
    select.current?.focus()
  }, [])
  const id = `person-plan-${person.id}`

  function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    commands.send({ person, action: "plan", plan: value || null })
  }

  return (
    <form className="setting-form person-plan-choice" onSubmit={submit}>
      <div className="field-stack">
        <Label htmlFor={id}>{t("people.plan.label", { email: personName(i18n, person) })}</Label>
        <NativeSelect ref={select} id={id} value={value} onChange={(event) => setChosen(event.target.value)}>
          <option value={DEFAULT_PLAN}>{t("people.plan.default")}</option>
          {(plans.data?.plans ?? []).map((plan) => (
            <option key={plan.key} value={plan.key}>
              {plan.name}
            </option>
          ))}
        </NativeSelect>
      </div>
      {plans.error && (
        <p className="field-error" role="alert">
          {apiErrorMessage(i18n, plans.error)}
        </p>
      )}
      <div className="setting-form-actions">
        <Button type="submit" disabled={commands.busy || !plans.data}>
          {t("people.plan.save")}
        </Button>
        <Button type="button" variant="ghost" onClick={() => commands.setChoosingPlan(null)}>
          {t("people.plan.cancel")}
        </Button>
      </div>
    </form>
  )
}
```

- [ ] **Step 6: Offer Change plan and show the choice beside the person**

Replace the whole of `web/src/features/person-actions.tsx` with:

```tsx
import { DestructiveConfirmation } from "@/components/destructive-confirmation"
import { LinkReveal } from "@/components/link-reveal"
import { OverflowMenu, type OverflowMenuItem } from "@/components/overflow-menu"
import { PersonPlanChoice } from "@/features/person-plan"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import type { I18n } from "@/i18n/translator"
import type { Person, PersonPlan } from "@/lib/api"
import { isAdministrator } from "@/lib/people"
import { passwordResetLink } from "@/lib/public-links"
import type { PeopleCommands, PersonCommand } from "@/lib/use-people"

/**
 * The menu of what an administrator can do to someone else. Change plan shows only on their own
 * page, once any Plan exists: there `plan` is their Plan, null while no Plan exists; the People
 * table passes none.
 */
export function PersonMenu({
  person,
  name,
  commands,
  plan,
}: {
  person: Person
  name: string
  commands: PeopleCommands
  plan?: PersonPlan | null
}) {
  const i18n = useI18n()
  return (
    <OverflowMenu
      label={i18n.t("people.actions.label", { email: name })}
      items={personActions(i18n, person, commands, Boolean(plan))}
    />
  )
}

/**
 * Someone else's commands: their role, whether they can sign in, their Plan, a new password, or
 * deletion. They wait while any command runs.
 */
function personActions({ t }: I18n, person: Person, { busy, start }: PeopleCommands, offersPlan: boolean): OverflowMenuItem[] {
  const item = (id: PersonCommand["action"], label: string, description: string): OverflowMenuItem => ({
    id,
    label,
    description,
    disabled: busy,
    onSelect: () => start({ person, action: id }),
  })
  return [
    isAdministrator(person)
      ? item("demote", t("people.actions.removeAdministrator"), t("people.actions.removeAdministratorHint"))
      : item("promote", t("people.actions.makeAdministrator"), t("people.actions.makeAdministratorHint")),
    person.state === "disabled"
      ? item("enable", t("people.actions.enable"), t("people.actions.enableHint"))
      : item("disable", t("people.actions.disable"), t("people.actions.disableHint")),
    ...(offersPlan ? [item("plan", t("people.actions.changePlan"), t("people.actions.changePlanHint"))] : []),
    item("reset", t("people.actions.passwordReset"), t("people.actions.passwordResetHint")),
    item("delete", t("people.actions.delete"), t("people.actions.deleteHint")),
  ]
}

/**
 * What a command on this person shows beside them: its error, the Plan to choose, the deletion
 * to confirm, or a link. `plan` is their Plan, which the choice opens on.
 */
export function PersonDetails({
  person,
  name,
  commands,
  plan,
}: {
  person: Person
  name: string
  commands: PeopleCommands
  plan?: PersonPlan | null
}) {
  const i18n = useI18n()
  const { t } = i18n
  const error = commands.errorFor(person)
  const result = commands.resultFor(person)
  return (
    <>
      {result !== null && <p className="command-result">{result}</p>}
      {error !== null && (
        <p className="field-error" role="alert">
          {apiErrorMessage(i18n, error)}
        </p>
      )}
      {commands.choosingPlan === person.id && (
        <PersonPlanChoice person={person} current={plan ?? null} commands={commands} />
      )}
      {commands.deleting === person.id && <PersonDeletion person={person} name={name} commands={commands} />}
      {commands.resetLink?.personId === person.id && (
        <LinkReveal
          title={t("people.reset.title", { email: name })}
          body={t("people.reset.body", { expires: i18n.format.dateTime(commands.resetLink.link.expires_at) })}
          label={t("people.reset.label", { email: name })}
          link={passwordResetLink(window.location.origin, commands.resetLink.link.token)}
          onDone={() => {
            commands.setResetLink(null)
            // The link is gone, so focus returns to this person's actions.
            const label = i18n.t("people.actions.label", { email: name })
            document.querySelector<HTMLElement>(`[aria-label=${JSON.stringify(label)}]`)?.focus()
          }}
        />
      )}
    </>
  )
}

function PersonDeletion({ person, name, commands }: { person: Person; name: string; commands: PeopleCommands }) {
  const { t } = useI18n()
  const { command } = commands
  return (
    <DestructiveConfirmation
      id={`delete-person-${person.id}`}
      title={t("people.delete.title", { email: name })}
      body={t("people.delete.body")}
      cancelLabel={t("people.delete.keep")}
      confirmLabel={t("people.delete.confirm")}
      pendingLabel={t("people.delete.pending")}
      pending={command.isPending}
      onConfirm={() => commands.send({ person, action: "delete" })}
      onCancel={() => commands.setDeleting(null)}
    />
  )
}
```

`web/src/features/people-table.tsx` does not change: its `PersonMenu` and `PersonDetails` calls pass no `plan`, so the table's rows keep their four actions.

- [ ] **Step 7: Show the Plan fact on the person page**

In `web/src/features/person-page.tsx`, replace the two import lines:

```tsx
import { api, ApiError, type Person, type RuleSummary, type UserOverview } from "@/lib/api"
import { documentTitle } from "@/lib/brand"
```

with:

```tsx
import { api, ApiError, type Person, type PersonPlan, type RuleSummary, type UserOverview } from "@/lib/api"
import { documentTitle } from "@/lib/brand"
```

and add, after `import { isAdministrator, personName } from "@/lib/people"`:

```tsx
import { personPlanFact } from "@/lib/plans"
```

In `PersonContent`, replace this block:

```tsx
          <PersonFacts person={person} now={now} />
        </div>
        {you === null && <PersonMenu person={person} name={name} commands={commands} />}
      </div>
      {you === null && <PersonDetails person={person} name={name} commands={commands} />}
```

with:

```tsx
          <PersonFacts person={person} plan={overview.plan} now={now} />
        </div>
        {you === null && <PersonMenu person={person} name={name} commands={commands} plan={overview.plan} />}
      </div>
      {you === null && <PersonDetails person={person} name={name} commands={commands} plan={overview.plan} />}
```

Replace the whole `PersonFacts` function (from its doc comment `/** Their role, and when they joined and last signed in. */` to its closing brace) with:

```tsx
/**
 * Their role, the Plan that limits them once any Plan exists (`plan` is null before then), and
 * when they joined and last signed in.
 */
function PersonFacts({ person, plan, now }: { person: Person; plan: PersonPlan | null; now: number }) {
  const i18n = useI18n()
  const { t } = i18n
  const facts = [
    t(`people.roles.${person.role}`),
    ...(plan ? [personPlanFact(i18n, plan)] : []),
    t("people.person.joined", { relative: i18n.format.relative(person.created_at, now) }),
    person.last_sign_in_at
      ? t("people.person.lastSignIn", { relative: i18n.format.relative(person.last_sign_in_at, now) })
      : t("people.person.neverSignedIn"),
  ]
  return (
    <ul className="person-facts" data-administrator={isAdministrator(person)}>
      {facts.map((fact) => (
        <li key={fact}>{fact}</li>
      ))}
    </ul>
  )
}
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `cd web && pnpm exec vitest run src/features/person-page.test.tsx src/features/people-page.test.tsx src/i18n/catalog.test.ts`

Expected: PASS, every test in the three files, including the existing People tests that list a row's four actions.

- [ ] **Step 9: Run the frontend gates and rebuild the static bundle**

Run:

```sh
cd web
pnpm run typecheck
pnpm run lint
pnpm run doctor
pnpm run knip
pnpm run test
pnpm run build
cd ..
.venv/bin/pytest tests/test_no_em_dashes.py tests/test_ubiquitous_language.py
git status --short src/calendar_sync/interfaces/api/static
```

Expected: `typecheck`, `lint` (0 warnings), `doctor`, and `knip` report nothing; `pnpm run test` passes every file; `pnpm run build` writes a new bundle, so `git status` lists changed files under `src/calendar_sync/interfaces/api/static/`; both pytest files pass. If `lint` reports `complexity`, the function named is over 10: move the new branch into a helper as the code above does, never disable the rule.

- [ ] **Step 10: Commit**

```sh
git add web/src/lib/use-people.ts web/src/features/person-plan.tsx web/src/features/person-actions.tsx \
  web/src/features/person-page.tsx web/src/i18n/locales/en/people.json \
  web/src/features/person-page.test.tsx web/src/features/people-page.test.tsx
git add -A src/calendar_sync/interfaces/api/static
git commit -F - <<'EOF'
Show each person's plan on their page, and let an administrator change it

Once any plan exists, the person page states which plan limits someone,
including the default plan and a plan kept for an administrator. Change
plan opens an inline choice of the plans or the default plan beside them,
and a refusal shows there. The People table keeps its four actions.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 17: Your plan

**Files:**
- Create: `web/src/features/settings-own-plan.tsx` (`OwnPlanSection`)
- Modify: `web/src/features/settings.tsx` (import block; `SettingsView`'s account-tab lines; new private `AccountTab` after `SettingsView`)
- Modify: `web/src/i18n/locales/en/settings.json` (`ownPlan.title`, `ownPlan.administrator`, `ownPlan.loadError`, `ownPlan.overRules` inside the `ownPlan` object task 14 added)
- Modify: `src/calendar_sync/interfaces/api/static/` (rebuilt bundle)
- Test: `web/src/features/settings-own-plan.test.tsx` (new), `web/src/features/settings.test.tsx` (fixtures `plansOff`, `familyPlan`; `Scenario` fields `ownPlan`, `registration`; new helper `planRoutes` that `mockFetch` spreads, with default answers for `GET /api/v1/account/plan` and `GET /api/v1/registration`; two tab tests)

**Interfaces:**
- Consumes:
  - Task 13: `GET /api/v1/account/plan` answering `OwnPlanResponse` (`basis`, `plan`, `limits`, `rules_counted`, `connected_accounts`, `integration_tokens`, `instant`, `poll_every_minutes`, `may_connect_account`, `may_issue_token`, `over_rule_limit`); it fails (500) on a Plans fault.
  - Task 14: `useOwnPlan()` (a `useQuery` on `OWN_PLAN_QUERY` with `api.ownPlan`) from `@/lib/use-own-plan`; `ownPlanShown(plan: OwnPlan | undefined, policy: RegistrationPolicy | undefined): boolean` and `ownPlanSummary(i18n: I18n, plan: OwnPlan): string` from `@/lib/plans`; `type OwnPlan = Schemas["OwnPlanResponse"]`; the `settings.ownPlan.*` keys `ownPlanSummary` builds from (`name`, `nameDefault`, `summary`, `rules`, `rulesUnlimited`, `accounts`, `accountsUnlimited`, `tokens`, `tokensUnlimited`, `noTokens`, `cadence.instant`, `cadence.every`).
  - Task 11: `yourPlanPath()` returns `"/settings/account#your-plan"`, so the section's id is `your-plan`.
  - Existing: `api.registration` (administrators only), `type Registration`, `common.loadFailure.retry` ("Try again").
- Produces:
  - `export function OwnPlanSection({ administrator }: { administrator: boolean })`: `<section id="your-plan" aria-labelledby="your-plan-title">`, rendered on Settings, Your account between the account section and Appearance; hidden (renders nothing) while Plans are off, while the query is pending, for an `{}` answer, and for an administrator under Only Me; on a failed load (except for an administrator under Only Me) it shows `settings.ownPlan.loadError` with Try again; scrolls itself into view on mount when `location.hash` is `#your-plan`.
  - i18n keys: `settings.ownPlan.title`, `settings.ownPlan.administrator`, `settings.ownPlan.loadError`, `settings.ownPlan.overRules`.
  - `settings.test.tsx`: `Scenario` gains `ownPlan?: Response` (default: Plans off) and `registration?: Response` (default: Only Me), answered through `planRoutes`; fixtures `plansOff` and `familyPlan`. Task 18 uses all of them.

- [ ] **Step 1: Write the failing tests**

Create `web/src/features/settings-own-plan.test.tsx`. The fixtures choose counts whose plural form is the same whether a message counts the limit or the use, and the expected lines follow the `settings.ownPlan.*` messages of contract section 3.21.

```tsx
/* @vitest-environment happy-dom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { StaticI18nProvider } from "@/i18n/provider"
import { pseudoI18n, testI18n, untranslatedText } from "@/i18n/testing"
import type { I18n } from "@/i18n/translator"
import type { OwnPlan, Registration } from "@/lib/api"

import { OwnPlanSection } from "./settings-own-plan"

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

/** Someone on their own Family plan, with room left everywhere. */
const family: OwnPlan = {
  basis: "plan",
  plan: { key: "family", name: "Family", on_default: false },
  limits: { rules: 5, connected_accounts: 3, integration_tokens: 2, sync_interval: "instant" },
  rules_counted: 3,
  connected_accounts: 2,
  integration_tokens: 0,
  instant: true,
  poll_every_minutes: 5,
  may_connect_account: true,
  may_issue_token: true,
  over_rule_limit: false,
}

/** Someone on the Default Plan with more rules counting than it allows, as after a demotion. */
const freeOverLimit: OwnPlan = {
  basis: "plan",
  plan: { key: "free", name: "Free", on_default: true },
  limits: { rules: 2, connected_accounts: 1, integration_tokens: 0, sync_interval: "5_minutes" },
  rules_counted: 3,
  connected_accounts: 1,
  integration_tokens: 0,
  instant: false,
  poll_every_minutes: 5,
  may_connect_account: false,
  may_issue_token: false,
  over_rule_limit: true,
}

/** Plans are off: nothing limits anyone, so Your plan stays hidden. */
const plansOff: OwnPlan = {
  basis: "plans_off",
  plan: null,
  limits: null,
  rules_counted: 4,
  connected_accounts: 2,
  integration_tokens: 1,
  instant: true,
  poll_every_minutes: 5,
  may_connect_account: true,
  may_issue_token: true,
  over_rule_limit: false,
}

/** An Installation Administrator, whom no plan limits. */
const administering: OwnPlan = { ...plansOff, basis: "administrator" }

const onlyMe: Registration = { policy: "only_me", only_me_available: true }
const invitationOnly: Registration = { policy: "invitation_only", only_me_available: false }

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status < 400, status, json: () => Promise.resolve(body) } as Response
}

const UNREADABLE = { detail: "database is locked", code: null, params: {} }

type Call = { method: string; path: string }
let calls: Call[] = []

/** Answers by "METHOD /path", reading `answers` at each call so a test can change one. */
function serve(answers: Record<string, Response>) {
  calls = []
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string | URL, init?: RequestInit) => {
      const method = init?.method ?? "GET"
      const path = String(input).split("?")[0] ?? ""
      calls.push({ method, path })
      return Promise.resolve(answers[`${method} ${path}`] ?? jsonResponse({}))
    }),
  )
}

let container: HTMLDivElement
let root: Root | null = null

beforeEach(() => {
  container = document.createElement("div")
  document.body.append(container)
})

afterEach(() => {
  if (root) {
    act(() => root?.unmount())
    root = null
  }
  container.remove()
  window.history.replaceState(null, "", "/")
  vi.restoreAllMocks()
})

async function settle(times = 6) {
  for (let i = 0; i < times; i += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0))
    })
  }
}

/** What the section reads: the own plan, the Registration Policy, and whether the User administers. */
type Scenario = { ownPlan: Response; registration?: Registration; administrator?: boolean }

async function renderSection(i18n: I18n, { ownPlan, registration = invitationOnly, administrator = false }: Scenario) {
  const answers: Record<string, Response> = {
    "GET /api/v1/account/plan": ownPlan,
    "GET /api/v1/registration": jsonResponse(registration),
  }
  serve(answers)
  root = createRoot(container)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  act(() => {
    root?.render(
      <StaticI18nProvider i18n={i18n}>
        <QueryClientProvider client={queryClient}>
          <OwnPlanSection administrator={administrator} />
        </QueryClientProvider>
      </StaticI18nProvider>,
    )
  })
  await settle()
  return answers
}

function section(): HTMLElement | null {
  return container.querySelector<HTMLElement>("section#your-plan")
}

function button(label: string): HTMLButtonElement {
  const found = [...container.querySelectorAll("button")].find((item) => item.textContent.trim() === label)
  if (!found) throw new Error(`No button labelled ${label}`)
  return found
}

async function click(target: HTMLElement) {
  act(() => target.click())
  await settle()
}

describe("OwnPlanSection", () => {
  it("stays hidden while plans are off", async () => {
    await renderSection(testI18n(), { ownPlan: jsonResponse(plansOff) })
    expect(section()).toBeNull()
    expect(container.textContent).toBe("")
  })

  it("stays hidden for an answer that names no basis", async () => {
    await renderSection(testI18n(), { ownPlan: jsonResponse({}) })
    expect(section()).toBeNull()
  })

  it("stays hidden for an administrator under Only Me, where plans have no effect", async () => {
    await renderSection(testI18n(), { ownPlan: jsonResponse(administering), registration: onlyMe, administrator: true })
    expect(section()).toBeNull()
  })

  it("tells an administrator under Invitation Only that no plan limits them", async () => {
    await renderSection(testI18n(), { ownPlan: jsonResponse(administering), registration: invitationOnly, administrator: true })
    expect(section()?.querySelector("h2")?.textContent).toBe("Your plan")
    expect(section()?.getAttribute("aria-labelledby")).toBe("your-plan-title")
    expect(section()?.querySelector("p")?.textContent).toBe("You administer this installation, so no plan limits you.")
  })

  it("asks for the Registration Policy only as an administrator, since nobody else may read it", async () => {
    await renderSection(testI18n(), { ownPlan: jsonResponse(family) })
    expect(calls.map((call) => call.path)).not.toContain("/api/v1/registration")

    act(() => root?.unmount())
    root = null
    await renderSection(testI18n(), { ownPlan: jsonResponse(administering), administrator: true })
    expect(calls.map((call) => call.path)).toContain("/api/v1/registration")
  })

  it("shows a limited person their plan in one line: counts, limits, and how soon it syncs", async () => {
    await renderSection(testI18n(), { ownPlan: jsonResponse(family) })
    expect([...section()!.querySelectorAll("p")].map((line) => line.textContent)).toEqual([
      "Family: 3 of 5 rules counted, 2 of 3 calendar accounts, 0 of 2 tokens, instant sync included",
    ])
  })

  it("names the default plan, a plan with no tokens, and a slower sync", async () => {
    await renderSection(testI18n(), { ownPlan: jsonResponse(freeOverLimit) })
    // The first line is the summary; the over-limit note follows it.
    expect(section()?.querySelector("p")?.textContent).toBe(
      "Free (default): 3 of 2 rules counted, 1 of 1 calendar account, no Integration Tokens, syncs about every 5 minutes",
    )
  })

  it("says plainly what an unlimited plan allows", async () => {
    const unlimited: OwnPlan = {
      ...family,
      limits: { rules: null, connected_accounts: null, integration_tokens: null, sync_interval: "instant" },
    }
    await renderSection(testI18n(), { ownPlan: jsonResponse(unlimited) })
    expect(section()?.querySelector("p")?.textContent).toBe(
      "Family: 3 rules counted, 2 calendar accounts, 0 tokens, instant sync included",
    )
  })

  it("says when more rules count than the plan allows, as after an administrator is demoted, and that nothing stops", async () => {
    await renderSection(testI18n(), { ownPlan: jsonResponse(freeOverLimit) })
    const over = section()?.querySelector(".field-hint[data-tone='attention']")
    expect(over?.textContent).toBe("More rules count than your plan's 2. Nothing stops, but no rule can start until fewer count.")
  })

  it("says nothing about the limit while the rules counted fit", async () => {
    await renderSection(testI18n(), { ownPlan: jsonResponse(family) })
    expect(section()?.querySelector(".field-hint")).toBeNull()
  })

  it("scrolls itself into view once when the address names it, as a link beside a limit does", async () => {
    window.history.replaceState(null, "", "/settings/account#your-plan")
    const scrolled = vi.spyOn(Element.prototype, "scrollIntoView").mockImplementation(() => undefined)
    await renderSection(testI18n(), { ownPlan: jsonResponse(family) })
    await settle()

    expect(scrolled).toHaveBeenCalledOnce()
    expect(scrolled.mock.contexts[0]).toBe(section())
  })

  it("does not scroll when the address names something else", async () => {
    window.history.replaceState(null, "", "/settings/account")
    const scrolled = vi.spyOn(Element.prototype, "scrollIntoView").mockImplementation(() => undefined)
    await renderSection(testI18n(), { ownPlan: jsonResponse(family) })
    expect(section()).not.toBeNull()
    expect(scrolled).not.toHaveBeenCalled()
  })

  it("shows its own error with Try again when it cannot load, and loads on Try again", async () => {
    const answers = await renderSection(testI18n(), { ownPlan: jsonResponse(UNREADABLE, 500) })
    const alert = section()?.querySelector("[role='alert']")
    expect(alert?.textContent).toBe("Your plan could not load.Try again")

    answers["GET /api/v1/account/plan"] = jsonResponse(family)
    await click(button("Try again"))
    expect(section()?.querySelector("[role='alert']")).toBeNull()
    expect(section()?.querySelector("p")?.textContent).toContain("Family: 3 of 5 rules counted")
  })

  it("hides a failed load from an administrator under Only Me, where plans have no effect", async () => {
    await renderSection(testI18n(), { ownPlan: jsonResponse(UNREADABLE, 500), registration: onlyMe, administrator: true })
    expect(section()).toBeNull()
  })

  const SHOWN: [string, Scenario][] = [
    ["a limited person over their rule limit", { ownPlan: jsonResponse(freeOverLimit) }],
    ["an administrator under Invitation Only", { ownPlan: jsonResponse(administering), administrator: true }],
    ["a plan that cannot load", { ownPlan: jsonResponse(UNREADABLE, 500) }],
  ]

  it.each(SHOWN)("has no untranslated text for %s", async (_case, scenario) => {
    await renderSection(pseudoI18n(), scenario)
    expect(section()).not.toBeNull()
    expect(untranslatedText(container, ["Family", "Free"])).toEqual([])
  })
})
```

Then, in `web/src/features/settings.test.tsx`:

1. In the import from `@/lib/api`, add `type OwnPlan`:

```tsx
import {
  type CalendarProvider,
  api,
  type ConnectedAccount,
  type IntegrationToken,
  type IssuedIntegrationToken,
  type OwnPlan,
} from "@/lib/api"
```

2. After the `issued` constant, add:

```tsx
/** Plans are off: Your plan stays hidden and nothing is limited. */
const plansOff: OwnPlan = {
  basis: "plans_off",
  plan: null,
  limits: null,
  rules_counted: 2,
  connected_accounts: 2,
  integration_tokens: 2,
  instant: true,
  poll_every_minutes: 5,
  may_connect_account: true,
  may_issue_token: true,
  over_rule_limit: false,
}

/** Someone on their own Family plan, with room left everywhere. */
const familyPlan: OwnPlan = {
  basis: "plan",
  plan: { key: "family", name: "Family", on_default: false },
  limits: { rules: 5, connected_accounts: 3, integration_tokens: 2, sync_interval: "instant" },
  rules_counted: 3,
  connected_accounts: 2,
  integration_tokens: 0,
  instant: true,
  poll_every_minutes: 5,
  may_connect_account: true,
  may_issue_token: true,
  over_rule_limit: false,
}
```

3. Replace the `Scenario` type with:

```tsx
type Scenario = {
  tab?: SettingsTab
  configured?: boolean
  redirectUri?: string | null
  providers?: CalendarProvider[]
  accounts?: ConnectedAccount[]
  storage?: StorageUsage
  clearable?: Response
  cleared?: Response
  tokens?: IntegrationToken[]
  /** GET /api/v1/account/plan; Plans are off unless a test says otherwise. */
  ownPlan?: Response
  /** GET /api/v1/registration; Only Me unless a test says otherwise. */
  registration?: Response
}
```

4. Replace the whole `mockFetch` function with the two functions below. The Plans and
   Registration answers sit in their own helper because `mockFetch` is already at ESLint's
   complexity bound of 10, and each default value counts.

```tsx
/** What the Plans and Registration routes answer: Plans off and Only Me unless a test says otherwise. */
function planRoutes({
  ownPlan = jsonResponse(plansOff),
  registration = jsonResponse({ policy: "only_me", only_me_available: true }),
}: Scenario): Record<string, Response> {
  return { "/api/v1/registration": registration, "/api/v1/account/plan": ownPlan }
}

function mockFetch({
  providers,
  configured = true,
  redirectUri = REDIRECT_URI,
  accounts = [connected, disconnected],
  storage = usage,
  clearable,
  cleared,
  tokens = [kuma, homepage],
  ...rest
}: Scenario) {
  const responses: Record<string, Response> = {
    "/api/v1/providers": jsonResponse(providers ?? (configured ? [googleProvider(redirectUri)] : [])),
    "/api/v1/accounts": jsonResponse(accounts),
    "/api/v1/storage": jsonResponse(storage),
    "/api/v1/storage/activity": clearable ?? jsonResponse({ older_than_days: 90, entries: 41880 }),
    "/api/v1/storage/activity/clear": cleared ?? jsonResponse({ removed: 41880, database: usage.database }),
    "/api/v1/integration-tokens": jsonResponse(tokens),
    "/api/v1/session": jsonResponse(adminSession),
    ...planRoutes(rest),
  }
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string | URL) => {
      const path = String(input).split("?")[0] ?? ""
      const verify = /^\/api\/v1\/accounts\/.+\/verify$/.test(path)
      return Promise.resolve(responses[path] ?? jsonResponse(verify ? sourceOnlyAccess : {}))
    }),
  )
}
```

5. In `describe("Settings tabs", ...)`, after the `it.each([...])("shows the %s tab's sections", ...)` test, add:

```tsx
  it("shows Your plan between the account section and Appearance once a plan limits you", async () => {
    await renderSettings(testI18n(), { tab: "account", ownPlan: jsonResponse(familyPlan) })
    expect(sections()).toEqual(["own-account-title", "your-plan-title", "appearance-title"])
    expect(container.querySelector("#your-plan")?.textContent).toContain("Family: 3 of 5 rules counted")
  })

  it("keeps the rest of Your account working when Your plan cannot load", async () => {
    await renderSettings(testI18n(), {
      tab: "account",
      ownPlan: jsonResponse({ detail: "database is locked" }, 500),
      registration: jsonResponse({ policy: "invitation_only", only_me_available: false }),
    })
    expect(sections()).toEqual(["own-account-title", "your-plan-title", "appearance-title"])
    expect(container.querySelector("#your-plan [role='alert']")?.textContent).toContain("Your plan could not load.")
    expect(container.querySelector("#own-account-title")?.textContent).toBe("Sign-in, email, and sync")
    expect(container.querySelector("#appearance-title")).not.toBeNull()
  })
```

`web/src/features/settings-own-account.test.tsx` does not change: it renders `OwnAccountSection` alone, and `OwnPlanSection` renders beside it in `settings.tsx`, never inside it.

- [ ] **Step 2: Run them to verify they fail**

Run: `cd web && pnpm exec vitest run src/features/settings-own-plan.test.tsx src/features/settings.test.tsx`

Expected: FAIL. `settings-own-plan.test.tsx` fails to load with `Failed to resolve import "./settings-own-plan"`. In `settings.test.tsx`, the two new tests fail with `expected [ 'own-account-title', 'appearance-title' ] to deeply equal [ 'own-account-title', 'your-plan-title', 'appearance-title' ]`; every existing test still passes, because the default answer keeps Plans off.

- [ ] **Step 3: Add the copy**

In `web/src/i18n/locales/en/settings.json`, replace the opening line of the `ownPlan` object task 14 added:

```json
  "ownPlan": {
```

with:

```json
  "ownPlan": {
    "title": "Your plan",
    "administrator": "You administer this installation, so no plan limits you.",
    "loadError": "Your plan could not load.",
    "overRules": {
      "one": "More rules count than your plan's {count}. Nothing stops, but no rule can start until fewer count.",
      "other": "More rules count than your plan's {count}. Nothing stops, but no rule can start until fewer count."
    },
```

After the edit, the whole `ownPlan` object reads (every key after `overRules` is task 14's, unchanged):

```json
  "ownPlan": {
    "title": "Your plan",
    "administrator": "You administer this installation, so no plan limits you.",
    "loadError": "Your plan could not load.",
    "overRules": {
      "one": "More rules count than your plan's {count}. Nothing stops, but no rule can start until fewer count.",
      "other": "More rules count than your plan's {count}. Nothing stops, but no rule can start until fewer count."
    },
    "name": "{name}",
    "nameDefault": "{name} (default)",
    "summary": "{plan}: {rules}, {accounts}, {tokens}, {cadence}",
    "rules": {
      "one": "{used} of {count} rule counted",
      "other": "{used} of {count} rules counted"
    },
    "rulesUnlimited": {
      "one": "{count} rule counted",
      "other": "{count} rules counted"
    },
    "accounts": {
      "one": "{used} of {count} calendar account",
      "other": "{used} of {count} calendar accounts"
    },
    "accountsUnlimited": {
      "one": "{count} calendar account",
      "other": "{count} calendar accounts"
    },
    "tokens": {
      "one": "{used} of {count} token",
      "other": "{used} of {count} tokens"
    },
    "tokensUnlimited": {
      "one": "{count} token",
      "other": "{count} tokens"
    },
    "noTokens": "no Integration Tokens",
    "cadence": {
      "instant": "instant sync included",
      "every": {
        "one": "syncs about every minute",
        "other": "syncs about every {count} minutes"
      }
    }
  },
```

The section's Try again uses the existing `common.loadFailure.retry` ("Try again"), so no other key is added.

- [ ] **Step 4: Add the section**

Create `web/src/features/settings-own-plan.tsx`:

```tsx
import { useQuery } from "@tanstack/react-query"

import { Button } from "@/components/ui/button"
import { useI18n } from "@/i18n/provider"
import { api, type OwnPlan } from "@/lib/api"
import { ownPlanShown, ownPlanSummary } from "@/lib/plans"
import { useOwnPlan } from "@/lib/use-own-plan"

/** Where links beside each limit land: `yourPlanPath()` names this anchor. */
const ANCHOR = "your-plan"

/**
 * Brings Your plan into view when the address names it. The section appears only once its data
 * loads, after the browser looked for the anchor, so it scrolls itself; a stable callback runs
 * once per mount.
 */
function revealOnArrival(section: HTMLElement | null) {
  if (section && window.location.hash === `#${ANCHOR}`) section.scrollIntoView({ block: "start" })
}

/**
 * What the signed-in User's Plan allows and how much of it they use, in one line, and a note when
 * more rules count than it allows. An administrator reads that no plan limits them. Hidden while
 * Plans are off and for an administrator under Only Me, where Plans have no effect; a failed load
 * shows its own error, and the server still checks every limit.
 */
export function OwnPlanSection({ administrator }: { administrator: boolean }) {
  const { t } = useI18n()
  const ownPlan = useOwnPlan()
  // Only administrators may read the Registration Policy; under Only Me the only User administers.
  const registration = useQuery({ queryKey: ["registration"], queryFn: api.registration, enabled: administrator })
  const policy = registration.data?.policy
  const failed = ownPlan.isError && !(administrator && policy === "only_me")
  if (!failed && !ownPlanShown(ownPlan.data, policy)) return null
  return (
    <section ref={revealOnArrival} id={ANCHOR} className="settings-section" aria-labelledby="your-plan-title">
      <div className="section-heading">
        <div>
          <h2 id="your-plan-title">{t("settings.ownPlan.title")}</h2>
          {!failed && ownPlan.data && <OwnPlanLines plan={ownPlan.data} />}
        </div>
      </div>
      {failed && (
        <div className="inline-error integration-load-error" role="alert">
          <span>{t("settings.ownPlan.loadError")}</span>
          <Button type="button" variant="outline" onClick={() => void ownPlan.refetch()}>
            {t("common.loadFailure.retry")}
          </Button>
        </div>
      )}
    </section>
  )
}

/** The Plan in one line, or why no plan limits an administrator; then whether more rules count than it allows. */
function OwnPlanLines({ plan }: { plan: OwnPlan }) {
  const i18n = useI18n()
  const { t } = i18n
  if (plan.basis !== "plan") return <p>{t("settings.ownPlan.administrator")}</p>
  return (
    <>
      <p>{ownPlanSummary(i18n, plan)}</p>
      {plan.over_rule_limit && (
        <p className="field-hint" data-tone="attention">
          {t("settings.ownPlan.overRules", { count: plan.limits?.rules ?? 0 })}
        </p>
      )}
    </>
  )
}
```

- [ ] **Step 5: Render it on Your account**

In `web/src/features/settings.tsx`, after the line `import { OwnAccountSection } from "@/features/settings-own-account"`, add:

```tsx
import { OwnPlanSection } from "@/features/settings-own-plan"
```

Replace the whole `SettingsView` function with this version, and add `AccountTab` right after it. Moving the account tab into its own component keeps `SettingsView` within ESLint's complexity bound.

```tsx
function SettingsView({ session, tab, onOpenTab, onOpenPeople, ...connections }: SettingsViewProps) {
  const { t } = useI18n()
  const { user } = session
  const administrator = isAdministrator(user)
  // Someone else opening Administration's address sees Your account, as Settings itself shows.
  const shown = tab === "administration" && !administrator ? DEFAULT_SETTINGS_TAB : tab

  return (
    <div className="page-section settings-page">
      <div>
        <h1>{t("settings.page.title")}</h1>
        <p className="page-intro">{t(administrator ? "settings.page.introAdministrator" : "settings.page.intro")}</p>
      </div>
      <SettingsTabs current={shown} administrator={administrator} onOpen={onOpenTab} />
      {shown === "account" && <AccountTab session={session} administrator={administrator} onOpenPeople={onOpenPeople} />}
      {shown === "connections" && <ConnectionsTab providers={connections.providers} administrator={administrator} />}
      {shown === "administration" && <AdministrationTab />}
    </div>
  )
}

/** The signed-in User's own sign-in and sync, Your plan once a Plan applies, and how the app looks. */
function AccountTab({
  session,
  administrator,
  onOpenPeople,
}: {
  session: SessionStatus
  administrator: boolean
  onOpenPeople: () => void
}) {
  const { user } = session
  return (
    <>
      {user && <OwnAccountSection user={user} sendsEmail={session.installation_sends_email} onOpenPeople={onOpenPeople} />}
      <OwnPlanSection administrator={administrator} />
      <AppearanceSection />
    </>
  )
}
```

`AccountTab` returns a fragment, so its sections stay direct children of `.settings-page`, as the tab tests read them.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd web && pnpm exec vitest run src/features/settings-own-plan.test.tsx src/features/settings.test.tsx src/features/settings-own-account.test.tsx src/i18n/catalog.test.ts`

Expected: PASS, every test in the four files.

- [ ] **Step 7: Run the frontend gates and rebuild the static bundle**

Run:

```sh
cd web
pnpm run typecheck
pnpm run lint
pnpm run doctor
pnpm run knip
pnpm run test
pnpm run build
cd ..
.venv/bin/pytest tests/test_no_em_dashes.py tests/test_ubiquitous_language.py
git status --short src/calendar_sync/interfaces/api/static
```

Expected: `typecheck`, `lint` (0 warnings), `doctor`, and `knip` report nothing; `pnpm run test` passes every file (the app and settings tests answer `GET /api/v1/account/plan` with `{}` or Plans off, so Your plan stays hidden there); `pnpm run build` writes a new bundle, so `git status` lists changed files under `src/calendar_sync/interfaces/api/static/`; both pytest files pass.

- [ ] **Step 8: Commit**

```sh
git add web/src/features/settings-own-plan.tsx web/src/features/settings-own-plan.test.tsx \
  web/src/features/settings.tsx web/src/features/settings.test.tsx web/src/i18n/locales/en/settings.json
git add -A src/calendar_sync/interfaces/api/static
git commit -F - <<'EOF'
Show people what their plan allows, and how much of it they use

Settings, Your account, Your plan sums up the plan in one line, says when
more rules count than it allows, and tells an administrator that no plan
limits them. It stays hidden while plans are off and under Only Me, shows
its own error when it cannot load, and scrolls into view when a link
beside a limit leads to it.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 18: Limit hints and decision-4 notes

**Files:**
- Modify: `web/src/features/rule-preview-footer.tsx` (whole file: `StartFailure`, new `startFailure`, `PreviewFooter`, `StartSummary`, `StartButton`, new `StartNote`)
- Modify: `web/src/components/connect-account.tsx` (whole file: `ConnectAccount` gains `disabledReason`; new private `connectLabel`, `UnavailableConnect`)
- Modify: `web/src/features/settings-accounts.tsx` (import block; `AccountsHeading`; `AccountGroup`)
- Modify: `web/src/features/overview.tsx` (import block; `ConnectStep`)
- Modify: `web/src/features/settings-integrations.tsx` (import block; `IssueTokenForm`)
- Modify: `web/src/components/rule-commands.tsx` (import block; `RuleCommandMenu`; new private `countsTowardPlan`, `pauseDescription`)
- Modify: `web/src/features/rule-policy-editor.tsx` (import block; the form's actions in `PolicyEditor`; new private `PlanRestartNote`)
- Modify: `web/src/features/settings-account-row.tsx` (import block; `DisconnectConfirmation`)
- Modify: `web/src/i18n/locales/en/common.json` (`plan.mayNotRestart` inside the `plan` object tasks 11 and 14 added)
- Modify: `src/calendar_sync/interfaces/api/static/` (rebuilt bundle)
- Test: `web/src/features/rule-preview.test.tsx`, `web/src/features/settings.test.tsx`, `web/src/features/overview.test.tsx`, `web/src/features/rules.test.tsx`, `web/src/features/rule-details.test.tsx`

**Interfaces:**
- Consumes:
  - Task 9: `RuleDetail.can_start: boolean`, `RuleDetail.rule_limit: number | null`; `POST /api/v1/rules/{rule_id}/enable` answers 409 `plan_limit_reached` with params `reason: "rules"`, `limit`, `count`.
  - Task 6: `common.apiError.plan_limit_reached_rules` (one "Your plan lets {count} rule sync. Pause or remove it to start this rule." / other "Your plan lets {count} rules sync. Pause or remove one to start this rule."), `common.apiError.plan_limit_reached_integration_tokens` (other "Your plan allows at most {count} Integration Tokens. Revoked tokens do not count.").
  - Task 11: `common.plan.seeYourPlan` ("See your plan"), `yourPlanPath()` (`"/settings/account#your-plan"`).
  - Task 14: `startRefusal(i18n: I18n, detail: RuleDetail): string | null` from `@/lib/plans`; `usePlanWarning(): boolean`, `useAccountLimitReason(): string | undefined`, `useTokenLimitReason(): string | undefined` from `@/lib/use-own-plan` (a pending, failed, or `{}` own-plan query gives no hint and no warning); `YourPlanLink()` from `@/components/your-plan-link` (`<a className="text-link" href="/settings/account#your-plan">See your plan</a>`); `common.plan.accountLimit` (one "Your plan allows {count} calendar account, and disconnected accounts count too."); `api.ownPlan`; `type OwnPlan`.
  - Task 17: the `ownPlan` and `registration` fields of `Scenario` in `settings.test.tsx`, and its `plansOff` fixture.
- Produces:
  - `ConnectAccount({ providers, primary, disabledReason }: { providers: readonly CalendarProvider[]; primary: boolean; disabledReason?: string | undefined })`: with `disabledReason`, the same label on a `Button` with `aria-disabled`, never a link or a menu, described (`aria-describedby`) by a `p.action-hint` holding the reason and `YourPlanLink`, inside a `div.heading-action`.
  - The rule preview footer: Start is `aria-disabled` and described by `#rule-preview-start-note` (the refusal and `YourPlanLink`) when `startRefusal` is not null; a 409 `plan_limit_reached` on Start shows `apiErrorMessage` and `YourPlanLink` in the summary (role `alert`) in place of `rulePreview.page.enableFailed`.
  - `IssueTokenForm`: submit disabled, and the form sends nothing, while `useTokenLimitReason()` is defined; the reason with `YourPlanLink` in `p#integration-limit` under the name field, which the field names in its `aria-describedby`.
  - The decision-4 note `common.plan.mayNotRestart` ("Your plan may not let this rule start again."): appended to the Pause item's description for a rule that counts (`state === "enabled"`, or `state === "degraded"` with an account to reauthorize); in a `p.field-hint[data-tone="attention"]` just above the policy form's actions for an `enabled` or `degraded` rule; appended to the Disconnect confirmation's body when the account has rules. Each shows only while `usePlanWarning()` is true.
  - i18n key: `common.plan.mayNotRestart`.

- [ ] **Step 1: Write the failing tests for Start**

In `web/src/features/rule-preview.test.tsx`, inside `describe("RulePreviewView", ...)`, after the test `"starts syncing and returns to the rule"`, add:

```tsx
  it("keeps Start unavailable, with the plan's refusal and a link to Your plan, when the rule may not start", async () => {
    mockFetch({ status: 200, body: preview }, { ...previewedRule, can_start: false, rule_limit: 3 })
    await renderPreview(testI18n())

    const start = button("Start syncing to Work")
    expect(start.getAttribute("aria-disabled")).toBe("true")
    expect(start.getAttribute("aria-describedby")).toBe("rule-preview-start-note")
    const note = container.querySelector("#rule-preview-start-note")
    expect(note?.textContent).toBe("Your plan lets 3 rules sync. Pause or remove one to start this rule. See your plan")
    expect(note?.querySelector("a")?.getAttribute("href")).toBe("/settings/account#your-plan")

    act(() => start.click())
    await settle()
    expect(calls).not.toContain("POST /api/v1/rules/rule-1/enable")
  })

  it("offers Start with nothing about the plan when the rule may start", async () => {
    mockFetch({ status: 200, body: preview })
    await renderPreview(testI18n())

    expect(button("Start syncing to Work").getAttribute("aria-disabled")).toBeNull()
    expect(container.querySelector("#rule-preview-start-note")).toBeNull()
    expect(container.querySelector(".rule-preview-footer a[href='/settings/account#your-plan']")).toBeNull()
  })

  it("says what the plan allows, not to try again, when Start meets the rule limit", async () => {
    mockFetch({ status: 200, body: preview })
    const answer = vi.mocked(fetch).getMockImplementation()
    const refusal = {
      detail: "the plan's limit of 2 rules is reached",
      code: "plan_limit_reached",
      params: { reason: "rules", limit: 2, count: 2 },
    }
    // After the refusal, the rule's details say it may not start, as the server then answers.
    let refused = false
    vi.mocked(fetch).mockImplementation((input, init) => {
      const url = input instanceof Request ? input.url : input.toString()
      if (url.endsWith("/enable")) {
        refused = true
        return Promise.resolve(jsonResponse({ status: 409, body: refusal }))
      }
      if (refused && url === "/api/v1/rules/rule-1") {
        return Promise.resolve(jsonResponse({ status: 200, body: { ...previewedRule, can_start: false, rule_limit: 2 } }))
      }
      return answer?.(input, init) ?? Promise.reject(new Error("no answer"))
    })
    await renderPreview(testI18n())

    act(() => button("Start syncing to Work").click())
    await settle()

    const summary = container.querySelector(".rule-preview-summary[role='alert']")
    expect(summary?.textContent).toBe("Your plan lets 2 rules sync. Pause or remove one to start this rule. See your plan")
    expect(summary?.querySelector("a")?.getAttribute("href")).toBe("/settings/account#your-plan")
    expect(container.querySelector(".rule-preview-footer")?.textContent).not.toContain("Try again in a moment")
    // The note under Start does not repeat it: one link to Your plan.
    expect(container.querySelectorAll(".rule-preview-footer a[href='/settings/account#your-plan']")).toHaveLength(1)
    expect(button("Start syncing to Work").getAttribute("aria-disabled")).toBe("true")
  })

  it("leaves no text untranslated when the plan refuses Start", async () => {
    mockFetch({ status: 200, body: preview }, { ...previewedRule, can_start: false, rule_limit: 3 })
    await renderPreview(pseudoI18n())

    expect(container.querySelector("#rule-preview-start-note")).not.toBeNull()
    expect(untranslatedText(container, FIXTURE_TEXT)).toEqual([])
  })
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd web && pnpm exec vitest run src/features/rule-preview.test.tsx`

Expected: FAIL. `keeps Start unavailable ...` fails with `expected null to be 'true'` on `aria-disabled`; `says what the plan allows ...` fails because the summary reads `Syncing did not start. Try again in a moment.`; the pseudo test fails because `#rule-preview-start-note` is null. `offers Start with nothing about the plan ...` already passes; it pins that a rule that may start shows no plan text.

- [ ] **Step 3: Disable Start with the plan's refusal, and show a refused Start's reason**

Replace the whole of `web/src/features/rule-preview-footer.tsx` with:

```tsx
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { ArrowLeft, LoaderCircle } from "lucide-react"
import { useEffect, useRef } from "react"

import { Button } from "@/components/ui/button"
import { YourPlanLink } from "@/components/your-plan-link"
import { OutcomeSigns } from "@/features/rule-preview-table"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import { ApiError, api, type RuleDetail } from "@/lib/api"
import { appPathForRule, isPlainLeftClick, type OpenRule } from "@/lib/navigation"
import { startRefusal } from "@/lib/plans"
import { outcomeCounts, type PreviewNames, type PreviewRun } from "@/lib/rule-preview"
import { outcomeParts } from "@/lib/rule-preview-text"
import { enabledMessage } from "@/lib/rule-run"
import { RULE_CHANGE_QUERIES, rulePreviewKey } from "@/lib/use-rule-commands"

/** What enabling answers when the rule is no longer the one previewed. */
const CHANGED_CODES = ["rule_not_executable", "invalid_state_transition"]
/**
 * Why starting the rule did not work: it changed since the preview, its User's plan has no room
 * for another rule that syncs, or something else.
 */
type StartFailure = "changed" | "limited" | "failed"

/** Why enabling failed, read from the server's code. */
function startFailure(error: Error | null): StartFailure | null {
  if (!error) return null
  const code = error instanceof ApiError ? error.code : null
  if (CHANGED_CODES.includes(code ?? "")) return "changed"
  return code === "plan_limit_reached" ? "limited" : "failed"
}

/**
 * Keeps `--rule-preview-footer` on the page at the footer's height, which grows with text size and
 * with what it holds, so focus moved by keyboard always stops above it.
 */
function useFooterHeight() {
  const footer = useRef<HTMLElement>(null)
  useEffect(() => {
    const element = footer.current
    if (!element) return
    const root = document.documentElement
    const observer = new ResizeObserver(([entry]) => {
      if (entry) root.style.setProperty("--rule-preview-footer", `${entry.borderBoxSize[0]?.blockSize ?? element.offsetHeight}px`)
    })
    observer.observe(element)
    return () => {
      observer.disconnect()
      root.style.removeProperty("--rule-preview-footer")
    }
  }, [])
  return footer
}

/** Back to the rule, when the preview was made, and the page's one primary action. */
export function PreviewFooter({
  detail,
  names,
  run,
  busy,
  failed,
  onRetry,
  onOpenRule,
}: {
  detail: RuleDetail
  names: PreviewNames
  run: PreviewRun | undefined
  busy: boolean
  failed: boolean
  onRetry: () => void
  onOpenRule: OpenRule
}) {
  const i18n = useI18n()
  const queryClient = useQueryClient()
  const enable = useMutation({
    mutationFn: () => api.enableRule(detail.id),
    onError: () => void queryClient.invalidateQueries({ queryKey: ["rule", detail.id] }),
    onSuccess: async () => {
      queryClient.removeQueries({ queryKey: rulePreviewKey(detail.id) })
      await Promise.all(
        [...RULE_CHANGE_QUERIES, ["rule", detail.id]].map((queryKey) => queryClient.invalidateQueries({ queryKey })),
      )
      onOpenRule(detail.id, { notice: enabledMessage(i18n, names.destination) })
    },
  })
  const failure = startFailure(enable.error)
  // Another tab or a scheduled run moved the rule on; its details are refetched below.
  const changed = failure === "changed"
  // What the plan says before Start; once a Start was refused, the summary already says it.
  const refusal = failure === "limited" ? null : startRefusal(i18n, detail)
  const canStart = run !== undefined && !failed && !changed && detail.state === "dry_run_validated" && detail.can_start
  const footer = useFooterHeight()
  return (
    <footer ref={footer} className="rule-preview-footer">
      <div className="rule-preview-footer-inner">
        <a
          className="back-link"
          href={appPathForRule(detail.id)}
          onClick={(event) => {
            if (!isPlainLeftClick(event)) return
            event.preventDefault()
            onOpenRule(detail.id)
          }}
        >
          <ArrowLeft aria-hidden="true" /> {i18n.t("rulePreview.page.back")}
        </a>
        <StartSummary run={run} destination={names.destination} outcome={failure} error={enable.error} />
        {changed ? (
          // Start would only fail again, so a fresh preview takes its place as the one action.
          <RefreshInstead
            onRefresh={() => {
              enable.reset()
              onRetry()
            }}
          />
        ) : detail.state !== "enabled" && (
          <StartButton
            destination={names.destination}
            sharesDetails={detail.privacy_policy === "copy_details"}
            ready={canStart}
            refusal={refusal}
            starting={enable.isPending}
            waiting={busy}
            onStart={() => enable.mutate()}
          />
        )}
      </div>
    </footer>
  )
}

/**
 * Beside Start syncing, what it will do, so the decision is made with the counts in view; or why
 * starting did not work. A plan's refusal says what the plan allows, with a link to Your plan.
 */
function StartSummary({
  run,
  destination,
  outcome,
  error,
}: {
  run: PreviewRun | undefined
  destination: string
  outcome: StartFailure | null
  error: Error | null
}) {
  const i18n = useI18n()
  const { t } = i18n
  if (outcome === "limited") {
    return (
      <p className="rule-preview-summary" role="alert">
        {apiErrorMessage(i18n, error)} <YourPlanLink />
      </p>
    )
  }
  if (outcome) {
    return (
      <p className="rule-preview-summary" role="alert">
        {outcome === "changed" ? t("rulePreview.page.changedSincePreview") : t("rulePreview.page.enableFailed")}
      </p>
    )
  }
  if (!run) return <p className="rule-preview-summary" />
  return (
    <div className="rule-preview-summary">
      <p className="rule-preview-counts">
        <span className="sr-only">{t("rulePreview.counts.label", { destination })}</span>
        <OutcomeSigns parts={outcomeParts(i18n, outcomeCounts(run.items))} />
      </p>
      <p className="rule-preview-consequence">{t("rulePreview.page.pauseAnyTime")}</p>
    </div>
  )
}

/** In Start's place once the rule changed, taking the focus Start had when it was pressed. */
function RefreshInstead({ onRefresh }: { onRefresh: () => void }) {
  const { t } = useI18n()
  const button = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    button.current?.focus()
  }, [])
  return (
    <div className="rule-preview-start">
      <Button ref={button} className="rule-preview-start-button" onClick={onRefresh}>
        {t("rulePreview.page.previewAgain")}
      </Button>
    </div>
  )
}

function StartButton({
  destination,
  sharesDetails,
  ready,
  refusal,
  starting,
  waiting,
  onStart,
}: {
  destination: string
  sharesDetails: boolean
  ready: boolean
  /** Why the User's plan refuses this Start, in the words a refused Start shows; null when it may start. */
  refusal: string | null
  starting: boolean
  /** Whether Start waits on a preview that is reading; a failed one says why in its own panel. */
  waiting: boolean
  onStart: () => void
}) {
  const { t } = useI18n()
  const blocked = !ready || starting
  const described = refusal !== null || waiting
  return (
    <div className="rule-preview-start">
      <Button
        className="rule-preview-start-button"
        aria-disabled={blocked ? true : undefined}
        aria-describedby={described ? "rule-preview-start-note" : undefined}
        onClick={() => !blocked && onStart()}
      >
        {starting ? (
          <>
            <LoaderCircle aria-hidden="true" className="work-spinner" /> {t("rulePreview.page.starting")}
          </>
        ) : (
          t(sharesDetails ? "rulePreview.page.startSyncingDetails" : "rulePreview.page.startSyncing", { destination })
        )}
      </Button>
      <StartNote refusal={refusal} waiting={waiting} ready={ready} />
    </div>
  )
}

/**
 * Under Start: why the plan refuses it, with a link to Your plan; that it waits for the preview;
 * or, once it may start, that the rule can be paused later.
 */
function StartNote({ refusal, waiting, ready }: { refusal: string | null; waiting: boolean; ready: boolean }) {
  const { t } = useI18n()
  if (refusal !== null) {
    return (
      <span id="rule-preview-start-note" className="rule-preview-start-note">
        {refusal} <YourPlanLink />
      </span>
    )
  }
  if (waiting) {
    return (
      <span id="rule-preview-start-note" className="rule-preview-start-note">
        {t("rulePreview.page.availableWhenDone")}
      </span>
    )
  }
  // Beside the counts on wide screens; here, under the button, where narrow screens put it.
  if (!ready) return null
  return <span className="rule-preview-start-note rule-preview-start-reassure">{t("rulePreview.page.pauseAnyTime")}</span>
}
```

- [ ] **Step 4: Run them to verify they pass**

Run: `cd web && pnpm exec vitest run src/features/rule-preview.test.tsx`

Expected: PASS, every test in the file, including the existing ones about Refresh in Start's place and a failed preview.

- [ ] **Step 5: Write the failing tests for Connect**

In `web/src/features/settings.test.tsx`, after the `familyPlan` constant task 17 added, add:

```tsx
/** Someone at every limit of their plan, with more rules counting than it allows. */
const atEveryLimit: OwnPlan = {
  basis: "plan",
  plan: { key: "free", name: "Free", on_default: true },
  limits: { rules: 1, connected_accounts: 1, integration_tokens: 0, sync_interval: "5_minutes" },
  rules_counted: 2,
  connected_accounts: 2,
  integration_tokens: 0,
  instant: false,
  poll_every_minutes: 5,
  may_connect_account: false,
  may_issue_token: false,
  over_rule_limit: true,
}

/** The own-plan answer when Plans cannot be read. */
const UNREADABLE_PLAN = { detail: "database is locked", code: null, params: {} }
```

Inside `describe("SettingsPage", ...)`, after the test `"connects the only configured provider directly, without a menu"`, add:

```tsx
  it("keeps Connect in place but unavailable at the plan's account limit, saying why, and keeps Reauthorize", async () => {
    await renderSettings(testI18n(), { ownPlan: jsonResponse(atEveryLimit) })

    const heading = container.querySelector<HTMLElement>("[aria-labelledby='accounts-title'] .section-heading")!
    const connect = heading.querySelector("button")!
    expect(connect.textContent.trim()).toBe("Connect Google account")
    expect(connect.getAttribute("aria-disabled")).toBe("true")
    // Nothing starts a provider's consent: no link, no menu.
    expect(heading.querySelector("a[href^='/api/v1/oauth']")).toBeNull()
    expect(heading.querySelector("[aria-haspopup='menu']")).toBeNull()
    const reason = document.getElementById(connect.getAttribute("aria-describedby") ?? "")
    expect(reason?.textContent).toBe("Your plan allows 1 calendar account, and disconnected accounts count too. See your plan")
    expect(reason?.querySelector("a")?.getAttribute("href")).toBe("/settings/account#your-plan")
    // Reauthorization is never refused, so the disconnected account keeps its way back.
    expect(container.querySelector("#account-acct-b a")?.getAttribute("href")).toBe("/api/v1/oauth/google/start?account=acct-b")
  })

  it("keeps the empty state's Connect unavailable at the plan's account limit, as disconnected accounts count", async () => {
    await renderSettings(testI18n(), { accounts: [], ownPlan: jsonResponse(atEveryLimit) })

    const connect = container.querySelector<HTMLButtonElement>(".account-empty button")!
    expect(connect.textContent.trim()).toBe("Connect Google account")
    expect(connect.getAttribute("aria-disabled")).toBe("true")
    expect(container.querySelector(".account-empty a[href^='/api/v1/oauth']")).toBeNull()
  })

  it("offers Connect as usual when the plan cannot be read, since the server still checks", async () => {
    await renderSettings(testI18n(), { ownPlan: jsonResponse(UNREADABLE_PLAN, 500) })

    const connect = [...container.querySelectorAll<HTMLAnchorElement>(".section-heading a")]
    expect(connect.map((link) => link.getAttribute("href"))).toEqual(["/api/v1/oauth/google/start"])
  })
```

In `web/src/features/overview.test.tsx`:

1. Change the type import from `@/lib/api` to:

```tsx
import type { CalendarProvider, ConnectedAccount, Dashboard, OwnPlan, RecentChange, RuleSummary, ServerProblem } from "@/lib/api"
```

2. Replace the `Scenario` type and the `mockFetch` function with:

```tsx
type Scenario = {
  dashboard: Dashboard
  rules: RuleSummary[]
  recentChanges: RecentChange[]
  providers?: CalendarProvider[]
  /** GET /api/v1/account/plan; `{}`, which names no plan, unless a test says otherwise. */
  ownPlan?: OwnPlan
}

function jsonResponse(body: unknown): Response {
  return { ok: true, status: 200, json: () => Promise.resolve(body) } as Response
}

function mockFetch(scenario: Scenario) {
  const responses: Record<string, unknown> = {
    "/api/v1/dashboard": scenario.dashboard,
    "/api/v1/rules": scenario.rules,
    "/api/v1/accounts": [accountA, accountB],
    "/api/v1/providers": scenario.providers ?? [],
    "/api/v1/recent-changes": scenario.recentChanges,
    "/api/v1/account/plan": scenario.ownPlan ?? {},
  }
  vi.stubGlobal("fetch", vi.fn((input: string | URL) => Promise.resolve(respond(String(input)))))
  function respond(url: string): Response {
    const path = url.split("?")[0] ?? ""
    if (path in responses) return jsonResponse(responses[path])
    if (/^\/api\/v1\/accounts\/.+\/calendars$/.test(path)) return jsonResponse([])
    return jsonResponse({})
  }
}
```

3. Inside `describe("OverviewView", ...)`, after the test `"offers one Connect action as the first step, choosing the provider in its menu"`, add:

```tsx
  it("keeps the first step's Connect unavailable at the plan's account limit, saying why", async () => {
    const google: CalendarProvider = {
      kind: "google",
      display_name: "Google",
      connect_url: "/api/v1/oauth/google/start",
      redirect_uri: "http://localhost/api/v1/oauth/google/callback",
      cause_anchors: {},
    }
    // A disconnected account still counts, so even the first step can meet the limit.
    const atAccountLimit: OwnPlan = {
      basis: "plan",
      plan: { key: "free", name: "Free", on_default: true },
      limits: { rules: 1, connected_accounts: 1, integration_tokens: 0, sync_interval: "5_minutes" },
      rules_counted: 0,
      connected_accounts: 1,
      integration_tokens: 0,
      instant: false,
      poll_every_minutes: 5,
      may_connect_account: false,
      may_issue_token: false,
      over_rule_limit: false,
    }
    const { container } = await renderOverview(testI18n(), {
      dashboard: {
        ...attentionDashboard,
        status: "setup",
        needs_attention: false,
        problems: [],
        connected_accounts: 0,
        sync_rules: 0,
        enabled_rules: 0,
        running_rules: 0,
        open_incidents: 0,
        last_synced_at: null,
      },
      rules: [],
      recentChanges: [],
      providers: [google],
      ownPlan: atAccountLimit,
    })

    const step = container.querySelector<HTMLElement>(".step-action")!
    expect(step.children).toHaveLength(1)
    const connect = step.querySelector("button")!
    expect(connect.textContent.trim()).toBe("Connect Google account")
    expect(connect.getAttribute("aria-disabled")).toBe("true")
    expect(step.querySelector("a[href^='/api/v1/oauth']")).toBeNull()
    expect(document.getElementById(connect.getAttribute("aria-describedby") ?? "")?.textContent).toBe(
      "Your plan allows 1 calendar account, and disconnected accounts count too. See your plan",
    )
  })
```

- [ ] **Step 6: Run them to verify they fail**

Run: `cd web && pnpm exec vitest run src/features/settings.test.tsx src/features/overview.test.tsx`

Expected: FAIL. The two "unavailable" settings tests and the Overview test fail because Connect is still a link (`heading.querySelector("button")` is null, so reading `textContent` throws `Cannot read properties of null`). `offers Connect as usual when the plan cannot be read ...` already passes; it pins the fail-open behavior.

- [ ] **Step 7: Let Connect stay in place but unavailable**

Replace the whole of `web/src/components/connect-account.tsx` with:

```tsx
import { Plus } from "lucide-react"
import { useId } from "react"

import { OverflowMenu } from "@/components/overflow-menu"
import { ProviderMark } from "@/components/provider-mark"
import { Button } from "@/components/ui/button"
import { YourPlanLink } from "@/components/your-plan-link"
import { useI18n } from "@/i18n/provider"
import type { I18n } from "@/i18n/translator"
import type { CalendarProvider } from "@/lib/api"
import { connectLink } from "@/lib/oauth-redirect"
import { accountNoun, providerDisplayName } from "@/lib/providers"

/**
 * The one action that adds a calendar account: a button for the only configured provider, or a
 * menu of providers when there are several, so the page never shows one equal button per provider.
 * `primary` only where connecting is the next step (DESIGN.md, Buttons). With `disabledReason`,
 * such as the User's plan's account limit, it stays in place but starts nothing, and says why.
 */
export function ConnectAccount({
  providers,
  primary,
  disabledReason,
}: {
  providers: readonly CalendarProvider[]
  primary: boolean
  /** Why no account can be connected now; the server still checks after the provider's consent. */
  disabledReason?: string | undefined
}) {
  const i18n = useI18n()
  const variant = primary ? "default" : "outline"
  const [only] = providers
  if (disabledReason !== undefined) {
    return <UnavailableConnect label={connectLabel(i18n, providers)} variant={variant} reason={disabledReason} />
  }
  if (providers.length === 1 && only) {
    return (
      <Button variant={variant} asChild>
        <a {...connectLink(only)}>
          <ProviderMark provider={only.kind} fallback={<Plus aria-hidden="true" />} />
          {connectLabel(i18n, providers)}
        </a>
      </Button>
    )
  }
  return (
    <OverflowMenu
      label={i18n.t("common.connectAccount.menu")}
      trigger={{ icon: <Plus aria-hidden="true" />, variant }}
      items={providers.map((provider) => {
        const link = connectLink(provider)
        return {
          id: provider.kind,
          label: accountNoun(i18n, provider.kind, providers),
          description: signInHint(i18n, provider, providers),
          icon: <ProviderMark provider={provider.kind} fallback={<Plus aria-hidden="true" />} />,
          href: link.href,
          newTab: link.target === "_blank",
          onSelect: link.onClick,
        }
      })}
    />
  )
}

/** Connect's label: the only provider's account, or the menu that chooses one. */
function connectLabel(i18n: I18n, providers: readonly CalendarProvider[]): string {
  const [only] = providers
  return providers.length === 1 && only
    ? i18n.t("common.connectAccount.one", { account: accountNoun(i18n, only.kind, providers) })
    : i18n.t("common.connectAccount.menu")
}

/**
 * Connect, unavailable: the same label on a button that leads nowhere, never a link to a
 * provider's consent or a menu of them, described by why and a link to Your plan. It stays
 * focusable, so keyboard and screen reader users reach the reason.
 */
function UnavailableConnect({
  label,
  variant,
  reason,
}: {
  label: string
  variant: "default" | "outline"
  reason: string
}) {
  const hint = useId()
  return (
    <div className="heading-action">
      <Button type="button" variant={variant} aria-disabled={true} aria-describedby={hint}>
        <Plus aria-hidden="true" />
        {label}
      </Button>
      <p id={hint} className="action-hint">
        {reason} <YourPlanLink />
      </p>
    </div>
  )
}

/** How to connect an account of the provider, then what is not yet verified for it, if anything. */
function signInHint(i18n: I18n, provider: CalendarProvider, providers: readonly CalendarProvider[]): string {
  const signIn = i18n.t("common.connectAccount.signIn", {
    provider: providerDisplayName(i18n, provider.kind, providers),
  })
  const note = `common.connectAccount.note.${provider.kind}`
  return i18n.has(note) ? `${signIn} ${i18n.t(note)}` : signIn
}
```

In `web/src/features/settings-accounts.tsx`, after the line `import { type AccountCommands, useAccountCommands } from "@/lib/use-account-commands"`, add:

```tsx
import { useAccountLimitReason } from "@/lib/use-own-plan"
```

Replace the whole `AccountsHeading` function with:

```tsx
/** The section's heading, with Connect once accounts exist; before that, the empty state holds it. */
function AccountsHeading({ providers, showConnect }: { providers: CalendarProvider[]; showConnect: boolean }) {
  const { t } = useI18n()
  // Read here, outside the condition below, as the rules of hooks require.
  const accountLimit = useAccountLimitReason()
  return (
    <div className="section-heading">
      <div>
        <h2 id="accounts-title">{t("settings.accounts.title")}</h2>
        <p>{t("settings.accounts.intro")}</p>
      </div>
      {providers.length === 0 ? (
        <Badge variant="attention"><ShieldAlert aria-hidden="true" /> {t("settings.accounts.notConfigured")}</Badge>
      ) : (
        showConnect && <ConnectAccount providers={providers} primary={false} disabledReason={accountLimit} />
      )}
    </div>
  )
}
```

Replace the whole `AccountGroup` function with:

```tsx
function AccountGroup({
  accounts,
  choice,
  onChoose,
  justConnected,
  focusAccountId,
  providers,
  returnHelp,
  commands,
}: {
  accounts: ConnectedAccount[]
  choice: boolean | null
  onChoose: (open: boolean) => void
  justConnected: boolean
  focusAccountId: string | null
  providers: CalendarProvider[]
  returnHelp: OAuthReturn
  commands: AccountCommands
}) {
  const i18n = useI18n()
  const { t } = i18n
  // Read here, outside the condition below, as the rules of hooks require.
  const accountLimit = useAccountLimitReason()
  const summary = accountSummary(i18n, accounts)
  // Collapsed while every account is healthy; open when one needs attention or just connected.
  const accountsOpen =
    choice ??
    Boolean(
      summary.needsAttention ||
        justConnected ||
        focusAccountId ||
        commands.confirmingAccountId ||
        commands.deletingAccountId,
    )
  return (
    <div className="account-group">
      {accounts.length === 0 ? (
        <div className="account-empty">
          <CircleUserRound aria-hidden="true" />
          <div className="account-empty-copy">
            <h3>{t("settings.accounts.empty.title")}</h3>
            <p>{t("settings.accounts.empty.body")}</p>
          </div>
          {providers.length > 0 && <ConnectAccount providers={providers} primary disabledReason={accountLimit} />}
        </div>
      ) : (
        <>
          <AccountSummaryToggle
            accounts={accounts}
            providers={providers}
            summary={summary}
            open={accountsOpen}
            onToggle={() => onChoose(!accountsOpen)}
          />
          {accountsOpen && (
            <AccountList
              accounts={accounts}
              focusAccountId={focusAccountId}
              providers={providers}
              commands={commands}
            />
          )}
        </>
      )}
      <OAuthReturnNote help={returnHelp} className="account-group-footer" />
    </div>
  )
}
```

Reauthorize buttons (`ReauthorizeButton` in `settings-account-row.tsx`) do not change: Reauthorization is never refused.

In `web/src/features/overview.tsx`, after the line `import { useNow } from "@/lib/use-now"`, add:

```tsx
import { useAccountLimitReason } from "@/lib/use-own-plan"
```

Replace the whole `ConnectStep` function with:

```tsx
/** The one Connect action, or why no account can be connected yet. */
function ConnectStep({ providers }: { providers: CalendarProvider[] }) {
  const { t } = useI18n()
  // Read before the early return below, as the rules of hooks require.
  const accountLimit = useAccountLimitReason()
  if (providers.length === 0) {
    return (
      <div className="step-action">
        <Button disabled>
          <Plus aria-hidden="true" /> {t("common.connectAccount.menu")}
        </Button>
        <p className="configuration-note">
          {rich(t("overview.onboarding.steps.connect.configurationNote"), { code: codeTag })}
        </p>
      </div>
    )
  }
  return (
    <div className="step-action">
      <ConnectAccount providers={providers} primary disabledReason={accountLimit} />
    </div>
  )
}
```

- [ ] **Step 8: Run them to verify they pass**

Run: `cd web && pnpm exec vitest run src/features/settings.test.tsx src/features/overview.test.tsx`

Expected: PASS, every test in both files, including the existing Connect, menu, and empty-state tests (the default own-plan answers keep Connect a link or a menu).

- [ ] **Step 9: Write the failing tests for Issue token**

In `web/src/features/settings.test.tsx`, in `describe("IntegrationsSection", ...)`, replace its `beforeEach` with:

```tsx
  beforeEach(() => {
    vi.spyOn(api, "integrationTokens").mockResolvedValue([kuma, homepage])
    vi.spyOn(api, "issueIntegrationToken").mockResolvedValue(issued)
    vi.spyOn(api, "revokeIntegrationToken").mockResolvedValue(undefined)
    // The form reads the own plan for its token limit; Plans are off unless a test says otherwise.
    vi.spyOn(api, "ownPlan").mockResolvedValue(plansOff)
  })
```

and after the test `"issues an administrator's token for their own status unless they ask for more"`, add:

```tsx
  it("keeps Issue token unavailable at the plan's token limit, saying why", async () => {
    vi.mocked(api.ownPlan).mockResolvedValue(atEveryLimit)
    await renderSection()
    await openGroup()
    await tick()
    await tick()

    // With a name typed, only the limit keeps Issue token from being pressed.
    const input = container.querySelector<HTMLInputElement>("#integration-name")!
    act(() => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(input, "Claude Code")
      input.dispatchEvent(new Event("input", { bubbles: true }))
    })
    expect(labelledButton("Issue token").disabled).toBe(true)
    const reason = container.querySelector("#integration-limit")
    expect(reason?.textContent).toBe("Your plan allows at most 0 Integration Tokens. Revoked tokens do not count. See your plan")
    expect(reason?.querySelector("a")?.getAttribute("href")).toBe("/settings/account#your-plan")
    expect(container.querySelector("#integration-name")?.getAttribute("aria-describedby")).toBe(
      "integration-name-hint integration-limit",
    )
    // Enter in the field sends nothing either.
    await issueToken("Claude Code")
    expect(api.issueIntegrationToken).not.toHaveBeenCalled()
  })

  it("offers Issue token as usual while Plans are off", async () => {
    await renderSection()
    await openGroup()
    await tick()

    expect(container.querySelector("#integration-limit")).toBeNull()
    expect(container.querySelector("#integration-name")?.getAttribute("aria-describedby")).toBe("integration-name-hint")
  })
```

- [ ] **Step 10: Run them to verify they fail**

Run: `cd web && pnpm exec vitest run src/features/settings.test.tsx -t "Issue token"`

Expected: FAIL. `keeps Issue token unavailable ...` fails with `expected false to be true` on `disabled`: with a name typed, nothing yet keeps the button from being pressed. `offers Issue token as usual while Plans are off` already passes.

- [ ] **Step 11: Wait at the token limit**

In `web/src/features/settings-integrations.tsx`, after the line `import { DestructiveConfirmation } from "@/components/destructive-confirmation"`, add:

```tsx
import { YourPlanLink } from "@/components/your-plan-link"
```

and after the line `import { useNow } from "@/lib/use-now"`, add:

```tsx
import { useTokenLimitReason } from "@/lib/use-own-plan"
```

Replace the whole `IssueTokenForm` function with:

```tsx
function IssueTokenForm({
  integrations,
  nameInput,
  administrator,
}: {
  integrations: IntegrationTokens
  nameInput: RefObject<HTMLInputElement | null>
  administrator: boolean
}) {
  const i18n = useI18n()
  const { t } = i18n
  const { name, setName, issue } = integrations
  // At the plan's token limit nothing can be issued; the server still checks.
  const limit = useTokenLimitReason()
  return (
    <form
      className="setting-row integration-issue"
      onSubmit={(event) => {
        event.preventDefault()
        if (limit === undefined) issue.mutate()
      }}
    >
      <div className="integration-issue-field">
        <Label htmlFor="integration-name">{t("settings.integrations.issue.label")}</Label>
        <p id="integration-name-hint">{t("settings.integrations.issue.hint")}</p>
        <Input
          ref={nameInput}
          id="integration-name"
          value={name}
          maxLength={80}
          placeholder={t("settings.integrations.issue.placeholder")}
          aria-describedby={limit === undefined ? "integration-name-hint" : "integration-name-hint integration-limit"}
          onChange={(event) => setName(event.target.value)}
        />
        {limit !== undefined && (
          <p id="integration-limit" className="field-hint">
            {limit} <YourPlanLink />
          </p>
        )}
        {administrator && <InstallationScopeField integrations={integrations} />}
        {issue.error && (
          <p className="field-error" role="alert">
            {apiErrorMessage(i18n, issue.error)}
          </p>
        )}
      </div>
      <Button type="submit" disabled={!name.trim() || issue.isPending || limit !== undefined}>
        {issue.isPending ? t("settings.integrations.issue.pending") : t("settings.integrations.issue.submit")}
      </Button>
    </form>
  )
}
```

- [ ] **Step 12: Run them to verify they pass**

Run: `cd web && pnpm exec vitest run src/features/settings.test.tsx`

Expected: PASS, every test in the file.

- [ ] **Step 13: Write the failing tests for the decision-4 notes, and pin that Create sync rule stays available**

In `web/src/features/rules.test.tsx`:

1. Change the type import from `@/lib/api` to:

```tsx
import type { ConnectedAccount, DiscoveredCalendar, OwnPlan, RuleSummary, RunOutcome } from "@/lib/api"
```

2. After the `jsonResponse` function (`function jsonResponse(body: unknown): Response { ... }`), add:

```tsx
/** Someone whose rules count past their plan's limit, so a rule they stop may not start again. */
const overTheLimit: OwnPlan = {
  basis: "plan",
  plan: { key: "free", name: "Free", on_default: true },
  limits: { rules: 1, connected_accounts: 1, integration_tokens: 0, sync_interval: "5_minutes" },
  rules_counted: 3,
  connected_accounts: 2,
  integration_tokens: 0,
  instant: false,
  poll_every_minutes: 5,
  may_connect_account: false,
  may_issue_token: false,
  over_rule_limit: true,
}

/** The own-plan answer when Plans cannot be read. */
const planUnreadable = { ok: false, status: 500, json: () => Promise.resolve({ detail: "database is locked" }) } as Response
```

3. Replace the whole `renderRulesList` function with:

```tsx
async function renderRulesList(
  i18n: I18n,
  {
    rows = RULE_ROWS,
    accounts = [accountA, accountB, accountC, accountD],
    onViewChange = () => undefined,
    ownPlan = jsonResponse({}),
  }: { rows?: RuleSummary[]; accounts?: ConnectedAccount[]; onViewChange?: ViewChange; ownPlan?: Response } = {},
) {
  vi.stubGlobal("fetch", vi.fn((input: string | URL) => Promise.resolve(respond(String(input)))))
  function respond(url: string): Response {
    const path = url.split("?")[0] ?? ""
    if (path === "/api/v1/rules") return jsonResponse(rows)
    if (path === "/api/v1/accounts") return jsonResponse(accounts)
    if (path === "/api/v1/account/plan") return ownPlan
    const calendars = /^\/api\/v1\/accounts\/(.+)\/calendars$/.exec(path)
    if (calendars) return jsonResponse(calendarsByAccount[decodeURIComponent(calendars[1] ?? "")] ?? [])
    return jsonResponse({})
  }
  root = createRoot(container)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  act(() => {
    root?.render(
      createElement(StaticI18nProvider, {
        i18n,
        children: createElement(
          QueryClientProvider,
          { client: queryClient },
          createElement(RulesView, { notice: null, createRule: false, onViewChange, onOpenRule: () => undefined, onOpenRulePreview: () => undefined }),
        ),
      }),
    )
  })
  for (let i = 0; i < 6; i += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0))
    })
  }
  return container
}

/** Opens a rule's More actions menu and reads what its Pause item says. */
function pauseDescription(menuLabel: string) {
  const trigger = container.querySelector<HTMLButtonElement>(`[aria-label="${menuLabel}"]`)!
  click(trigger)
  const pause = [...trigger.closest(".overflow-menu")!.querySelectorAll("[role='menuitem']")].find(
    (item) => item.querySelector(".overflow-menu-label")?.textContent === "Pause rule",
  )
  return pause?.querySelector(".overflow-menu-description")?.textContent
}
```

4. Inside `describe("RulesView", ...)`, after the test `"sends a rule an expired Google account stopped to that account in Settings"`, add:

```tsx
  it("keeps Create sync rule available at the plan's rule limit, since creating is never limited", async () => {
    await renderRulesList(testI18n(), { ownPlan: jsonResponse(overTheLimit) })
    const create = [...container.querySelectorAll("button")].find((item) => item.textContent.includes("Create sync rule"))!
    expect(create.disabled).toBe(false)
    expect(create.getAttribute("aria-disabled")).toBeNull()
  })

  it("warns in Pause that the plan may not let a rule that counts start again", async () => {
    await renderRulesList(testI18n(), { ownPlan: jsonResponse(overTheLimit) })
    expect(pauseDescription("More actions for Work A to Work B1")).toBe(
      "Stop writing to Work B1. Existing events stay; resuming needs a new preview. Your plan may not let this rule start again.",
    )
    // A rule a provider failure stopped no longer counts, so pausing it frees nothing.
    expect(pauseDescription("More actions for Work A to Work B2")).toBe(
      "Stop writing to Work B2. Existing events stay; resuming needs a new preview.",
    )
  })

  it("warns in Pause for a rule stopped only until its account is reauthorized, which still counts", async () => {
    const lapsed = { ...accountB, authorization_lapsed_at: justNow }
    const stopped = ruleSummary("stopped", {
      state: "degraded",
      last_sync: { ...lastSync, succeeded: false, failure_kind: "authentication", failure_provider: "google" },
    })
    await renderRulesList(testI18n(), { rows: [stopped], accounts: [accountA, lapsed], ownPlan: jsonResponse(overTheLimit) })
    expect(pauseDescription("More actions for Work A to Work B1")).toBe(
      "Stop writing to Work B1. Existing events stay; resuming needs a new preview. Your plan may not let this rule start again.",
    )
  })

  it.each([
    ["names no plan", jsonResponse({})],
    ["cannot be read", planUnreadable],
  ])("says nothing about the plan in Pause when the own plan %s", async (_case, ownPlan) => {
    await renderRulesList(testI18n(), { ownPlan })
    expect(pauseDescription("More actions for Work A to Work B1")).toBe(
      "Stop writing to Work B1. Existing events stay; resuming needs a new preview.",
    )
  })

  it("has no untranslated text in Pause's plan note", async () => {
    await renderRulesList(pseudoI18n(), { ownPlan: jsonResponse(overTheLimit) })
    for (const menu of container.querySelectorAll('[aria-haspopup="menu"]')) click(menu)
    expect(untranslatedText(container, FIXTURE_TEXT)).toEqual([])
  })
```

In `web/src/features/rule-details.test.tsx`:

1. Change the type import from `@/lib/api` to:

```tsx
import type { ConnectedAccount, DiscoveredCalendar, OwnPlan, RuleDetail, RunOutcome } from "@/lib/api"
```

2. After the `enabledRule` constant, add:

```tsx
/** Someone whose rules count past their plan's limit, so a rule they stop may not start again. */
const overTheLimit: OwnPlan = {
  basis: "plan",
  plan: { key: "free", name: "Free", on_default: true },
  limits: { rules: 1, connected_accounts: 1, integration_tokens: 0, sync_interval: "5_minutes" },
  rules_counted: 3,
  connected_accounts: 2,
  integration_tokens: 0,
  instant: false,
  poll_every_minutes: 5,
  may_connect_account: false,
  may_issue_token: false,
  over_rule_limit: true,
}
```

3. Replace the whole `mockFetch` function with:

```tsx
function mockFetch(rule: RuleDetail | null, ownPlan: Response = jsonResponse({})) {
  const calendars: Record<string, DiscoveredCalendar[]> = {
    [account.id]: [familyCalendar, errandsCalendar],
    [partner.id]: [writableCalendar, readOnlyCalendar],
  }
  vi.stubGlobal("fetch", vi.fn((input: string | URL) => Promise.resolve(respond(String(input)))))
  function respond(url: string): Response {
    const path = url.split("?")[0] ?? ""
    if (path === "/api/v1/accounts") return jsonResponse([account, partner])
    if (path === "/api/v1/account/plan") return ownPlan
    const calendarMatch = /^\/api\/v1\/accounts\/(.+)\/calendars$/.exec(path)
    if (calendarMatch) return jsonResponse(calendars[decodeURIComponent(calendarMatch[1] ?? "")] ?? [])
    if (path.startsWith("/api/v1/rules/")) {
      return rule ? jsonResponse(rule) : jsonResponse({ detail: "sync rule does not exist", code: "rule_not_found", params: {} }, 404)
    }
    return jsonResponse({})
  }
}
```

4. Replace the first line of `renderDetails` and its `mockFetch` call:

```tsx
async function renderDetails(i18n: I18n, rule: RuleDetail | null, notice: string | null = null) {
  mockFetch(rule)
```

with:

```tsx
async function renderDetails(
  i18n: I18n,
  rule: RuleDetail | null,
  notice: string | null = null,
  ownPlan: Response = jsonResponse({}),
) {
  mockFetch(rule, ownPlan)
```

5. Inside `describe("RuleDetailsView", ...)`, after the test `"says nothing about how soon a rule syncs until it is enabled"`, add:

```tsx
  it("warns before a privacy edit that the plan may not let the rule start again, while more rules count than it allows", async () => {
    await renderDetails(testI18n(), enabledRule, null, jsonResponse(overTheLimit))
    click(container.querySelector('[aria-controls="policy-form"]'))

    const note = container.querySelector("#policy-form .field-hint[data-tone='attention']")
    expect(note?.textContent).toBe("Your plan may not let this rule start again.")
    // Beside Save: the note comes right before the form's actions.
    expect(note?.nextElementSibling?.classList.contains("form-actions")).toBe(true)
  })

  it("warns before editing a stopped rule too, which may still count", async () => {
    await renderDetails(testI18n(), { ...enabledRule, state: "degraded" }, null, jsonResponse(overTheLimit))
    click(container.querySelector('[aria-controls="policy-form"]'))
    expect(container.querySelector("#policy-form")?.textContent).toContain("Your plan may not let this rule start again.")
  })

  it("says nothing about the plan before editing a paused rule, which no longer counts", async () => {
    await renderDetails(testI18n(), { ...enabledRule, state: "paused" }, null, jsonResponse(overTheLimit))
    click(container.querySelector('[aria-controls="policy-form"]'))
    expect(container.querySelector("#policy-form")).not.toBeNull()
    expect(container.querySelector("#policy-form")?.textContent).not.toContain("Your plan")
  })

  it.each([
    ["names no plan", jsonResponse({})],
    ["cannot be read", jsonResponse({ detail: "database is locked" }, 500)],
  ])("says nothing about the plan before a privacy edit when the own plan %s", async (_case, ownPlan) => {
    await renderDetails(testI18n(), enabledRule, null, ownPlan)
    click(container.querySelector('[aria-controls="policy-form"]'))
    expect(container.querySelector("#policy-form")).not.toBeNull()
    expect(container.querySelector("#policy-form")?.textContent).not.toContain("Your plan")
  })

  it("has no untranslated text with the plan's note before a privacy edit", async () => {
    await renderDetails(pseudoI18n(), enabledRule, null, jsonResponse(overTheLimit))
    click(container.querySelector('[aria-controls="policy-form"]'))
    // As the test with every form open does: the busy-only title it would show is data, not copy.
    choose("#edit-privacy-policy", "copy_details")
    click(container.querySelector('[aria-haspopup="menu"]'))
    expect(container.querySelector("#policy-form .field-hint")).not.toBeNull()
    expect(untranslatedText(container, FIXTURE_TEXT)).toEqual([])
  })
```

In `web/src/features/settings.test.tsx`, inside `describe("SettingsPage", ...)`, after the test `"keeps the English copy"`, add:

```tsx
  it("warns before a disconnect that the plan may not let its rules start again, while more rules count than it allows", async () => {
    await renderSettings(testI18n(), { ownPlan: jsonResponse(atEveryLimit) })
    await click(container.querySelector<HTMLButtonElement>("#account-acct-a [aria-haspopup='menu']")!)
    const disconnect = [...container.querySelectorAll<HTMLButtonElement>("[role='menuitem']")].find(
      (item) => item.querySelector(".overflow-menu-label")?.textContent === "Disconnect account",
    )!
    await click(disconnect)
    expect(container.querySelector("#disconnect-acct-a p")?.textContent).toBe(
      "Its stored credentials will be removed. 2 affected rules will require reauthorization before they can run. Your plan may not let this rule start again.",
    )
  })

  const NO_DISCONNECT_NOTE: [string, Scenario][] = [
    ["an account no rule uses", { accounts: [{ ...connected, rule_count: 0 }, disconnected], ownPlan: jsonResponse(atEveryLimit) }],
    ["a plan that cannot be read", { ownPlan: jsonResponse(UNREADABLE_PLAN, 500) }],
  ]

  it.each(NO_DISCONNECT_NOTE)("says nothing about the plan before disconnecting %s", async (_case, scenario) => {
    await renderSettings(testI18n(), scenario)
    await click(container.querySelector<HTMLButtonElement>("#account-acct-a [aria-haspopup='menu']")!)
    const disconnect = [...container.querySelectorAll<HTMLButtonElement>("[role='menuitem']")].find(
      (item) => item.querySelector(".overflow-menu-label")?.textContent === "Disconnect account",
    )!
    await click(disconnect)
    expect(container.querySelector("#disconnect-acct-a p")?.textContent).not.toContain("Your plan")
  })

  it("has no untranslated text at every limit of a plan", async () => {
    // The page's own address, so the Integrations examples match the fixture text.
    page().happyDOM.setURL(`${PUBLIC_ORIGIN}/settings`)
    await renderSettings(pseudoI18n(), { ownPlan: jsonResponse(atEveryLimit) })
    await click(container.querySelector<HTMLButtonElement>("[aria-labelledby='integrations-title'] .group-summary")!)
    await click(container.querySelector<HTMLButtonElement>("#account-acct-a [aria-haspopup='menu']")!)
    // The item's description id ends with its id, "disconnect"; its label is pseudo-translated.
    const disconnect = [...container.querySelectorAll<HTMLButtonElement>("#account-acct-a [role='menuitem']")].find((item) =>
      item.getAttribute("aria-describedby")?.endsWith("-disconnect"),
    )!
    await click(disconnect)

    expect(container.querySelector(".action-hint a")).not.toBeNull()
    expect(container.querySelector("#integration-limit")).not.toBeNull()
    expect(container.querySelector("#disconnect-acct-a")).not.toBeNull()
    expect(untranslatedText(container, FIXTURE_TEXT)).toEqual([])
  })
```

- [ ] **Step 14: Run them to verify they fail**

Run: `cd web && pnpm exec vitest run src/features/rules.test.tsx src/features/rule-details.test.tsx src/features/settings.test.tsx`

Expected: FAIL, 6 tests. The Pause warnings (two in `rules.test.tsx`), the privacy-edit warnings (two in `rule-details.test.tsx`), and the Disconnect warning fail because the note is missing (for example `expected 'Stop writing to Work B1. Existing events stay; resuming needs a new preview.' to be '... Your plan may not let this rule start again.'`, and `expected undefined to be 'Your plan may not let this rule start again.'` for the policy note); the pseudo test in `rule-details.test.tsx` fails on its `#policy-form .field-hint` line. These already pass and pin what must stay: `keeps Create sync rule available ...`, every `says nothing about the plan ...` case, and the pseudo tests in `rules.test.tsx` and `settings.test.tsx`.

- [ ] **Step 15: Add the note copy and show it before a privacy edit, in Pause, and in the Disconnect confirmation**

In `web/src/i18n/locales/en/common.json`, replace the opening line of the `plan` object tasks 11 and 14 added (it holds `seeYourPlan` and `accountLimit`):

```json
  "plan": {
```

with:

```json
  "plan": {
    "mayNotRestart": "Your plan may not let this rule start again.",
```

After the edit, the whole `plan` object reads (the other keys are tasks 11 and 14's, unchanged):

```json
  "plan": {
    "mayNotRestart": "Your plan may not let this rule start again.",
    "seeYourPlan": "See your plan",
    "accountLimit": {
      "one": "Your plan allows {count} calendar account, and disconnected accounts count too.",
      "other": "Your plan allows {count} calendar accounts, and disconnected accounts count too."
    }
  },
```

In `web/src/components/rule-commands.tsx`, replace the import lines:

```tsx
import { useI18n } from "@/i18n/provider"
import type { PreviewSummary } from "@/lib/api"
```

with:

```tsx
import { useI18n } from "@/i18n/provider"
import type { I18n } from "@/i18n/translator"
import type { PreviewSummary } from "@/lib/api"
```

and after the line `import { useNow } from "@/lib/use-now"`, add:

```tsx
import { usePlanWarning } from "@/lib/use-own-plan"
```

Replace the whole `RuleCommandMenu` function with this version, and add the two helpers right after it:

```tsx
export function RuleCommandMenu({
  state,
  unauthorized,
  pending,
  source,
  destination,
  reserveSpace = false,
  onRun,
}: {
  state: string
  /** Whether an account of the rule needs reauthorization, so running it now would fail. */
  unauthorized: boolean
  pending: RuleCommand | undefined
  source: string
  destination: string
  /** Keeps list rows aligned when a rule has no routine commands. */
  reserveSpace?: boolean
  onRun: (command: RunnableCommand) => void
}) {
  const i18n = useI18n()
  const { t } = i18n
  // Read before any return, as the rules of hooks require.
  const mayNotRestart = usePlanWarning() && countsTowardPlan(state, unauthorized)
  const busy = pending !== undefined
  const items: OverflowMenuItem[] = []
  if (state === "enabled" && !unauthorized) {
    items.push(
      {
        id: "sync",
        label: t("ruleDetails.commands.syncNow"),
        description: t("ruleDetails.commands.syncNowDescription", { source }),
        disabled: busy,
        onSelect: () => onRun("sync"),
      },
      {
        id: "reconcile",
        label: t("ruleDetails.commands.reconcileNow"),
        description: t("ruleDetails.commands.reconcileNowDescription", { destination }),
        disabled: busy,
        onSelect: () => onRun("reconcile"),
      },
    )
  }
  if (state === "enabled" || state === "degraded") {
    items.push({
      id: "pause",
      label: t("ruleDetails.commands.pause"),
      description: pauseDescription(i18n, destination, mayNotRestart),
      disabled: busy,
      onSelect: () => onRun("pause"),
    })
  }
  if (!items.length) return reserveSpace ? <span className="overflow-menu-spacer" aria-hidden="true" /> : null
  return <OverflowMenu label={t("ruleDetails.commands.moreActions", { source, destination })} items={items} />
}

/**
 * Whether the rule counts toward its User's plan, as the Web UI can tell: enabled, or stopped
 * only until an account of it is reauthorized.
 */
function countsTowardPlan(state: string, unauthorized: boolean): boolean {
  return state === "enabled" || (state === "degraded" && unauthorized)
}

/**
 * What Pause does; and, while more rules count than the plan allows, that the plan may not let
 * the rule start again, since a paused rule gives up its place (decision 4).
 */
function pauseDescription({ t }: I18n, destination: string, mayNotRestart: boolean): string {
  const description = t("ruleDetails.commands.pauseDescription", { destination })
  return mayNotRestart ? `${description} ${t("common.plan.mayNotRestart")}` : description
}
```

In `web/src/features/rule-policy-editor.tsx`, after the line `import { useDisclosureFocus } from "@/lib/use-disclosure-focus"`, add:

```tsx
import { usePlanWarning } from "@/lib/use-own-plan"
```

In `PolicyEditor`, replace this block:

```tsx
          {update.error && <div className="inline-error" role="alert">{apiErrorMessage(i18n, update.error)}</div>}
          <div className="form-actions">
```

with:

```tsx
          {update.error && <div className="inline-error" role="alert">{apiErrorMessage(i18n, update.error)}</div>}
          <PlanRestartNote state={detail.state} />
          <div className="form-actions">
```

Keep the Save button's `disabled={!changed || update.isPending}` exactly as it is: `web/src/lib/rule-details.test.ts` reads that text. Add this component after `PolicyEditor` (before `PolicyConsequences`):

```tsx
/**
 * Beside Save, while more rules count than the User's plan allows: a policy change stops the
 * rule until it is previewed again, and the plan may then not let it start (decision 4). Only an
 * enabled or stopped rule can count, so a paused or new one gets no note.
 */
function PlanRestartNote({ state }: { state: RuleDetail["state"] }) {
  const { t } = useI18n()
  const warning = usePlanWarning()
  if (!warning || (state !== "enabled" && state !== "degraded")) return null
  return (
    <p className="field-hint" data-tone="attention">
      {t("common.plan.mayNotRestart")}
    </p>
  )
}
```

In `web/src/features/settings-account-row.tsx`, after the line `import type { AccessCheck, AccountCommands } from "@/lib/use-account-commands"`, add:

```tsx
import { usePlanWarning } from "@/lib/use-own-plan"
```

Replace the whole `DisconnectConfirmation` function with:

```tsx
function DisconnectConfirmation({
  account,
  commands,
}: {
  account: ConnectedAccount
  commands: AccountCommands
}) {
  const { t } = useI18n()
  const { disconnect } = commands
  // Its rules stop and need a preview; while more rules count than the plan allows, the plan may
  // not let them start again (decision 4).
  const mayNotRestart = usePlanWarning() && account.rule_count > 0
  return (
    <div
      className="disconnect-confirmation"
      id={`disconnect-${account.id}`}
      role="group"
      aria-labelledby={`disconnect-title-${account.id}`}
    >
      <div>
        <h4 id={`disconnect-title-${account.id}`}>
          {t("settings.accounts.disconnect.title", { name: account.display_name })}
        </h4>
        <p>
          {account.rule_count > 0
            ? t("settings.accounts.disconnect.bodyWithRules", { count: account.rule_count })
            : t("settings.accounts.disconnect.bodyWithoutRules")}
          {mayNotRestart && ` ${t("common.plan.mayNotRestart")}`}
        </p>
      </div>
      <div className="confirmation-actions">
        <Button
          variant="outline"
          onClick={() => commands.setConfirmingAccountId(null)}
          disabled={disconnect.isPending}
        >
          {t("settings.accounts.actions.keep")}
        </Button>
        <Button
          variant="destructive"
          onClick={() => disconnect.mutate(account.id)}
          disabled={disconnect.isPending}
        >
          <Unplug aria-hidden="true" />
          {disconnect.isPending ? t("settings.accounts.disconnect.pending") : t("settings.accounts.actions.disconnect")}
        </Button>
      </div>
    </div>
  )
}
```

- [ ] **Step 16: Run them to verify they pass**

Run: `cd web && pnpm exec vitest run src/features/rules.test.tsx src/features/rule-details.test.tsx src/features/settings.test.tsx src/features/rule-preview.test.tsx src/features/overview.test.tsx src/i18n/catalog.test.ts src/lib/rule-details.test.ts src/lib/rule-recovery.test.ts src/lib/overview-onboarding.test.ts`

Expected: PASS, every test in the nine files.

- [ ] **Step 17: Run the frontend gates and rebuild the static bundle**

Run:

```sh
cd web
pnpm run typecheck
pnpm run lint
pnpm run doctor
pnpm run knip
pnpm run test
pnpm run build
cd ..
.venv/bin/pytest tests/test_no_em_dashes.py tests/test_ubiquitous_language.py
git status --short src/calendar_sync/interfaces/api/static
```

Expected: `typecheck`, `lint` (0 warnings), `doctor`, and `knip` report nothing; `pnpm run test` passes every file (tests whose fetch stub answers `GET /api/v1/account/plan` with `{}`, `[]`, or 404 show no hint and no note, and the IntegrationsSection tests answer it through the `api.ownPlan` spy); `pnpm run build` writes a new bundle, so `git status` lists changed files under `src/calendar_sync/interfaces/api/static/`; both pytest files pass. If `lint` reports `complexity` or `react-hooks/rules-of-hooks`, a hook moved below a condition or a function grew past 10: keep each hook call at the top of its component, as above.

- [ ] **Step 18: Commit**

```sh
git add web/src/features/rule-preview-footer.tsx web/src/components/connect-account.tsx \
  web/src/features/settings-accounts.tsx web/src/features/overview.tsx web/src/features/settings-integrations.tsx \
  web/src/components/rule-commands.tsx web/src/features/rule-policy-editor.tsx web/src/features/settings-account-row.tsx \
  web/src/i18n/locales/en/common.json \
  web/src/features/rule-preview.test.tsx web/src/features/settings.test.tsx web/src/features/overview.test.tsx \
  web/src/features/rules.test.tsx web/src/features/rule-details.test.tsx
git add -A src/calendar_sync/interfaces/api/static
git commit -F - <<'EOF'
Say why Start, Connect, and Issue token wait at a plan's limit

Start is unavailable with the plan's refusal when a rule cannot start, and
a refused Start shows that refusal in place of Try again. Connect and Issue
token wait at their limits with a link to Your plan, while Reauthorize and
Create sync rule stay available. While more rules count than the plan
allows, a note before a privacy edit, a Pause, or a Disconnect says the
plan may not let the rule start again. A plan that cannot be read changes
nothing, and the server still checks every limit.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
```

## Part 10: Documentation and quality gates (Tasks 19 and 20)

### Task 19: Documentation and ADRs

This task describes shipped behavior, so it runs after tasks 1 to 18 are committed. It writes no
production code. Its one test change is `tests/test_ubiquitous_language.py`; every other step is a
document edit, checked by the documentation tests that already exist
(`tests/test_ubiquitous_language.py`, `tests/test_no_em_dashes.py`,
`tests/test_instant_sync_docs.py`, `tests/test_troubleshooting_anchors.py`) and by `ruff format
--check .`, which also formats Python blocks inside `docs/*.md` (none of the text below has a
Python block).

Rules for every text in this task: no em dash (U+2014) anywhere; `CONTEXT.md` terms (Plan, Default
Plan, Allowance, Directional Sync Rule, Rule Replacement, Connected Account, Disconnected Account,
Reauthorization, Integration Token, Installation Administrator, Operator Overview, Sync Cadence);
never "entitlement", and never the four terms this task adds to `AVOIDED` (the new ADR and the
docs must not name them, not even to rule them out); never "usage" for Resource Use. Keep lines at
or under 100 characters, as the surrounding text does.

**Files:**
- Modify: `tests/test_ubiquitous_language.py` (`AVOIDED`, `test_avoided_terms_are_found_in_any_spelling`, `test_words_that_merely_contain_an_avoided_term_are_allowed`)
- Modify: `docs/superpowers/specs/2026-10-15-plans-design.md` (lines 734 to 736 only: the `tests/test_ubiquitous_language.py` bullet of section 11)
- Create: `docs/adr/0038-plans-allowances-and-limits.md`
- Modify: `docs/adr/0010-rule-removal-and-calendar-replacement.md` (top line; new amendment section at the end)
- Modify: `docs/adr/0023-hosted-service-runs-the-open-codebase.md` (top paragraph; new amendment section at the end)
- Modify: `docs/adr/0028-plans-apart-from-commercial-mode.md` (top line; new amendment section at the end)
- Modify: `docs/adr/0030-users-administrators-and-registration.md` (top paragraph; new amendment section before `## Considered Options`)
- Modify: `docs/adr/0036-instant-sync-through-provider-notices.md` (top paragraph; new amendment section at the end)
- Modify: `CONTEXT.md` (**Plan**; new **Default Plan** and **Allowance**; **Sync Cadence**; **Operator Overview**; Interface Wording rows)
- Modify: `AGENTS.md` (the Plans sentences under "Product invariants")
- Modify: `README.md` (the hosted-service passage, lines 30 to 33; the privacy bullet at lines 359 to 363)
- Modify: `docs/licensing.md` (the "Hosted service" paragraph, lines 28 to 33)
- Modify: `docs/architecture.md` (edition boundary, lines 16 to 19; Identity and Access bullet, lines 34 to 35; routes list, line 102; Operator Overview paragraph, lines 188 to 193; new Plans paragraph before "Read-only views follow the same direction.")
- Modify: `docs/instant-sync.md` (`### Not in your plan` body; `## Plans` body)
- Modify: `docs/data-ownership.md` (a Plans bullet after "The Registration Policy."; the administrator's list; the paragraph after it)
- Modify: `docs/self-hosting.md` ("Invite other people": item 3, the paragraph after the list, a new Plans paragraph)
- Modify: `docs/domain-model.md` (two paragraphs under "State machines")
- Modify: `docs/troubleshooting.md` (two new sections before `## Getting more help`)
- Modify: `docs/superpowers/specs/2026-10-09-multi-user-design.md` (phase 3)
- Modify: `CHANGELOG.md` (`## [Unreleased]`: first bullet of `### Added`, first bullet of `### Changed`)
- Test: `tests/test_ubiquitous_language.py`, `tests/test_no_em_dashes.py`, `tests/test_instant_sync_docs.py`, `tests/test_troubleshooting_anchors.py`

**Interfaces:**
- Consumes (named in the documents; Step 8 confirms each exists as shipped):
  - `calendar_sync.domain.plans`: `allowance_for(*, plans_on, administers, own, default) -> Allowance`, `Allowance`, `AllowanceBasis` (`plans_off`, `administrator`, `plan`), `SyncInterval` (`instant`, `5_minutes`, `10_minutes`, `15_minutes`, `30_minutes`, `60_minutes`), `OFFERED_INTERVALS`, `PlanLimitReached`.
  - `calendar_sync.domain.model.SyncRule`: `keeps_place`, `holdable`, `counts_toward_plan`, `take_place_of(old)`.
  - `application/sync/ports.py`: `Allowances.of(user)`, `Allowances.of_users(users)`.
  - `application/sync/watch_ports.py`: `SyncCadencePolicy.cadences(users)`, `EveryUserInstant`, `PlanCadence(allowances)`.
  - `application/sync/removal.py`: `RemoveSyncRule.execute(rule_id, handling, *, successor=None)`.
  - `application/sync/rules.py`: `EnableSyncRule(unit_of_work, locks, allowances, owner)`.
  - `application/identity/ports.py`: `PlanCatalog`, `PlanAssignments.assign(user, plan, change)`, `AssignmentChange(source, actor, at)`.
  - `application/identity/plans.py`: `ShowPlans`, `DefinePlan`, `ChangePlan`, `RemovePlan`, `SetPlansSetting`, `AssignPlan`.
  - `application/identity/integration_tokens.py`: `IssueIntegrationToken`.
  - `application/operations/own_plan.py`: `ShowOwnPlan`; `application/operations/operator_overview.py`: `OperatorOverview.page`, `OperatorOverview.of`.
  - `infrastructure/persistence/plans.py`: `SqlitePlans`; `infrastructure/persistence/0033_plans.sql` (migration 33).
  - Routes `GET /api/v1/plans`, `PUT /api/v1/plan-settings`, `POST /api/v1/plans`, `PUT`/`DELETE /api/v1/plans/{plan_key}`, `PUT /api/v1/users/{user_id}/plan`, `GET /api/v1/account/plan`; codes `plan_limit_reached`, `plans_need_default`, `plan_not_found`, `plan_key_taken`, `plan_in_use`, `plan_is_default`, `invalid_plan`; OAuth outcome `account_limit_reached`; `RuleDetailResponse.can_start`, `RuleDetailResponse.rule_limit`.
  - Web UI labels: `settings.plans.title` "Plans", `settings.plans.enabled.label` "Limit people with plans", `settings.plans.default.label` "Default plan", `settings.plans.add` "Add a plan", `settings.ownPlan.title` "Your plan", `people.actions.changePlan` "Change plan", `common.plan.seeYourPlan` "See your plan", `common.plan.mayNotRestart` "Your plan may not let this rule start again.", `settings.integrations.issue.submit` "Issue token", `rule-details` `replacement.open` "Replace calendars…".
  - Task 11's section `## Connect is unavailable: your plan's calendar accounts` in `docs/troubleshooting.md`.
- Produces:
  - `docs/adr/0038-plans-allowances-and-limits.md` (ADR 0038, "Plans: Allowances and limits"), which later slices extend with addenda.
  - `AVOIDED` gains `"downgrade deletion"`, `"plan pause"`, `"suspension"`, `"tier"`; from here on every searched file must be free of them.
  - `docs/troubleshooting.md` sections `## Start syncing is unavailable: your plan's rule limit` (anchor `start-syncing-is-unavailable-your-plans-rule-limit`) and `## Issue token is unavailable: your plan's token limit` (anchor `issue-token-is-unavailable-your-plans-token-limit`).

- [ ] **Step 1: Write the failing test**

In `tests/test_ubiquitous_language.py`, replace the two parametrized spelling tests (from the first
`@pytest.mark.parametrize(` down to the end of
`test_words_that_merely_contain_an_avoided_term_are_allowed`) with:

```python
@pytest.mark.parametrize(
    "text",
    [
        "a sync pair",
        "Sync Pairs",
        "sync_pair = None",
        "SYNC_PAIRS",
        "class SyncPair:",
        "mySyncPair",
        "sync-pair",
        "the sync\n  pair",
        "two event copies",
        "EventCopies",
        "target calendars",
        "a free tier",
        "PLAN_TIERS",
        "a plan pause",
        "PlanPause",
        "downgrade deletion",
        "downgrade\n  deletion",
        "rule suspensions",
    ],
)
def test_avoided_terms_are_found_in_any_spelling(text: str) -> None:
    assert avoided_terms_in(text)


@pytest.mark.parametrize(
    "text",
    [
        "async pairing",
        "sync pairing",
        "resync pair",
        "event copyright",
        "retarget calendar",
        "frontier",
        "a planned pause",
        "suspended",
        # CONTEXT.md avoids these two for Plan as well, but other concepts need them.
        "Cause.QUOTA_EXCEEDED",
        "a Graph subscription",
    ],
)
def test_words_that_merely_contain_an_avoided_term_are_allowed(text: str) -> None:
    assert not avoided_terms_in(text)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/test_ubiquitous_language.py -q`

Expected: `7 failed`, every other test passing. The seven failures are the new
`test_avoided_terms_are_found_in_any_spelling` cases (`a free tier`, `PLAN_TIERS`,
`a plan pause`, `PlanPause`, `downgrade deletion`, `downgrade\n  deletion`, `rule suspensions`),
each `AssertionError: assert []`, because `AVOIDED` does not hold those terms yet. The new allowed
cases already pass.

- [ ] **Step 3: Implement: add the four terms to `AVOIDED`**

In `tests/test_ubiquitous_language.py`, replace the comment above `AVOIDED` and the whole tuple
(it ends just before `SEARCHED = (...)`) with:

```python
# Avoided terms that always name the wrong concept. Many other avoided terms, such as "user" or
# "pause rule", are also ordinary English or interface labels, so they are left to review.
# "quota" and "subscription", which CONTEXT.md also avoids for Plan, stay out:
# `Cause.QUOTA_EXCEEDED` and Microsoft Graph subscriptions use them for other things.
AVOIDED = (
    "bidirectional rule",
    "cloned event",
    "copied event",
    "copy mode",
    "disable rule",
    "disabled rule",
    "downgrade deletion",
    "downstream calendar",
    "event copy",
    "master mapping",
    "origin calendar",
    "parent mapping",
    "plan pause",
    "push sync",
    "real-time sync",
    "recurring master",
    "suspension",
    "sync job",
    "sync pair",
    "target calendar",
    "tier",
    "upstream calendar",
)
```

- [ ] **Step 4: Run it to verify the spelling cases pass and the spec still names the terms**

Run: `.venv/bin/pytest tests/test_ubiquitous_language.py -q`

Expected: `1 failed`. Every spelling case passes, and
`test_every_checked_term_is_one_the_glossary_avoids` passes (CONTEXT.md lists Tier under **Plan**
and Suspension, plan pause, and downgrade deletion under **Plan Hold**).
`test_code_and_documentation_do_not_use_avoided_terms` fails with exactly:

```text
docs/superpowers/specs/2026-10-15-plans-design.md:734: tier
docs/superpowers/specs/2026-10-15-plans-design.md:734: suspension
docs/superpowers/specs/2026-10-15-plans-design.md:734: plan pause
docs/superpowers/specs/2026-10-15-plans-design.md:734: downgrade deletion
```

If any other file is listed, an earlier task introduced the word: reword that text in the same
commit as Step 7, using the CONTEXT.md term.

- [ ] **Step 5: Implement: reword the spec's bullet so it names none of the terms**

In `docs/superpowers/specs/2026-10-15-plans-design.md`, section 11, replace:

```markdown
- **`tests/test_ubiquitous_language.py`** adds `tier`, `suspension`, `plan pause`, and `downgrade
  deletion`. Not `quota` or `subscription`: `Cause.QUOTA_EXCEEDED` and Graph subscriptions use them
  for other things.
```

with:

```markdown
- **`tests/test_ubiquitous_language.py`** adds the terms `CONTEXT.md` avoids for Plan and Plan
  Hold, except `quota` and `subscription`, which `Cause.QUOTA_EXCEEDED` and Graph subscriptions use
  for other things.
```

Change nothing else in the spec.

- [ ] **Step 6: Run the tests to verify they pass**

Run:

```sh
.venv/bin/pytest tests/test_ubiquitous_language.py tests/test_no_em_dashes.py -q
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy
.venv/bin/lint-imports
```

Expected: every test passes; `ruff format --check .` reports every file already formatted;
`ruff check .` prints `All checks passed!`; `mypy` prints `Success: no issues found`;
`lint-imports` reports every contract `KEPT`.

- [ ] **Step 7: Commit**

```sh
git add tests/test_ubiquitous_language.py docs/superpowers/specs/2026-10-15-plans-design.md
git commit -F - <<'EOF'
Keep the words the glossary rules out for plans out of code and docs

The ubiquitous-language test now also fails on the four terms CONTEXT.md
avoids for Plan and Plan Hold that always name the wrong concept. Quota
and subscription stay allowed, because Cause.QUOTA_EXCEEDED and Microsoft
Graph subscriptions need them. The Plans spec no longer lists the terms
by name.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
```

- [ ] **Step 8: Confirm the names the documents cite**

Run each command from the repository root:

```sh
grep -nE "^(class Allowance:|class AllowanceBasis\(|def allowance_for\(|OFFERED_INTERVALS)" src/calendar_sync/domain/plans.py
grep -nE "keeps_place: bool|def holdable|def counts_toward_plan|def take_place_of" src/calendar_sync/domain/model.py
grep -nE "^class Allowances\(" src/calendar_sync/application/sync/ports.py
grep -nE "^class PlanCadence|^class EveryUserInstant|def cadences\(" src/calendar_sync/application/sync/watch_ports.py
grep -nE "successor: SyncRule \| None = None" src/calendar_sync/application/sync/removal.py
grep -nE "^class (PlanCatalog|PlanAssignments|AssignmentChange)\b" src/calendar_sync/application/identity/ports.py
grep -nE "^class (ShowPlans|DefinePlan|ChangePlan|RemovePlan|SetPlansSetting|AssignPlan)\b" src/calendar_sync/application/identity/plans.py
grep -nE "^class IssueIntegrationToken" src/calendar_sync/application/identity/integration_tokens.py
grep -nE "^class ShowOwnPlan" src/calendar_sync/application/operations/own_plan.py
grep -nE "^class SqlitePlans" src/calendar_sync/infrastructure/persistence/plans.py
grep -nE "plans_enabled|default_plan_key|plan_assigned_by|keeps_place" src/calendar_sync/infrastructure/persistence/0033_plans.sql
grep -nE "PlanCadence\(" src/calendar_sync/bootstrap/container.py
grep -nE '"/api/v1/(plans|plan-settings|account/plan)' src/calendar_sync/interfaces/api/routes/plans.py
grep -nE '"/api/v1/users/\{user_id\}/plan"' src/calendar_sync/interfaces/api/routes/users.py
grep -nE '"account_limit_reached"' src/calendar_sync/interfaces/api/routes/accounts.py
grep -nE '"(seeYourPlan|mayNotRestart)"' web/src/i18n/locales/en/common.json
grep -nE '"(Limit people with plans|Default plan|Add a plan|Your plan|Plans)"' web/src/i18n/locales/en/settings.json
grep -nE '"Change plan"' web/src/i18n/locales/en/people.json
grep -nE "^## Connect is unavailable: your plan's calendar accounts" docs/troubleshooting.md
```

Expected: every command prints at least one line. If a command prints nothing, an earlier task
shipped a different name or label (it reported the deviation in its own task): use the shipped
name, path, or label everywhere the texts below cite it, and nothing else changes.

- [ ] **Step 9: Write ADR 0038**

Create `docs/adr/0038-plans-allowances-and-limits.md`:

```markdown
# Plans: Allowances and limits

Builds on [ADR 0028](0028-plans-apart-from-commercial-mode.md),
[ADR 0029](0029-isolate-users-in-one-sqlite-database.md), and
[ADR 0032](0032-bounded-contexts-as-application-packages.md). Amends
[ADR 0010](0010-rule-removal-and-calendar-replacement.md),
[ADR 0023](0023-hosted-service-runs-the-open-codebase.md),
[ADR 0028](0028-plans-apart-from-commercial-mode.md),
[ADR 0030](0030-users-administrators-and-registration.md), and
[ADR 0036](0036-instant-sync-through-provider-notices.md).

## Context

ADR 0028 settled that an Installation Administrator may turn Plans on to limit how much each User
uses, and that billing will later set a User's Plan through the same model. It left open what a
Plan holds, whom it limits, what each limit counts, and how a limit holds when two requests race.

The Hosted Service needs a free Plan and larger ones, with Instant Sync perhaps only on some. A
household administrator needs to keep one User from using up a shared computer and the provider
quota every User draws from. A self-hosted installation must keep every feature, and with Plans
off nothing may change. The [Plans design](../superpowers/specs/2026-10-15-plans-design.md) holds
the whole design and its delivery in four slices. This record covers the first: Plans, their
limits, and Instant Sync or a five-minute sync per Plan. Later slices add their own sections here.

## Decision

- **Plans live in Identity and Access, and Synchronization enforces them through a port it
  declares.** `domain/plans.py` holds the Plan values and the one decision, `allowance_for`.
  Identity owns the administrator's use cases (`ShowPlans`, `DefinePlan`, `ChangePlan`,
  `RemovePlan`, `SetPlansSetting`, and `AssignPlan`, in `application/identity/plans.py`) over the
  `PlanCatalog` and `PlanAssignments` ports. Synchronization declares `Allowances` (`of(user)` and
  `of_users(users)`) in `application/sync/ports.py`, as it already declares `SyncCadencePolicy`,
  so it enforces limits without importing Identity. One `SqlitePlans`
  (`infrastructure/persistence/plans.py`) implements all three ports, and each client depends only
  on the one it uses. The lint-imports layers and the contexts of ADR 0032 do not change, and no
  new table holds a User's records.
- **A Plan** has a key, a name, three counts, and a sync interval. The key is 1 to 32 lower-case
  letters, digits, and hyphens, starting with a letter or digit, chosen when the Plan is defined
  and never changed, so billing can map prices to it. The name is 1 to 60 printable characters and
  can change. Rules and Connected Accounts allow 1 to 10000, and Integration Tokens 0 to 10000, so
  a Plan may offer none; each count may instead be unlimited.
- **The Default Plan.** The administrator marks one Plan as the default. A User whose own Plan is
  NULL (`users.plan_key`) has it, so changing the default changes every such User at once, with no
  write per User, including Users invited later. Plans cannot turn on without a default
  (`plans_need_default`). The default cannot be removed (`plan_is_default`), and no Plan can be
  removed while anyone has it (`plan_in_use`): the administrator moves those Users first, which is
  also safe for billing. Turning Plans off is always allowed and keeps every definition and
  assignment.
- **The Allowance decides everything a Plan limits.** `allowance_for` reads, in order: with Plans
  off, no limits (basis `plans_off`); for a User who administers, no limits (`administrator`);
  otherwise their own Plan, or the Default Plan when they have none (`plan`). Plans on with no Plan
  found cannot happen, because Plans cannot be on without a default, but it would read as
  `plans_off`, so a fault in Plans never limits anyone. Every Allowance also carries the User's own
  stored Plan, so an administrator sees a Plan that does not apply yet. The Allowance is read when
  it is needed, with no cache.
- **Installation Administrators are never limited.** Under Only Me the only User administers, so
  Plans have no effect there, and the Web UI hides them. Removing the role subjects a User to their
  Plan from their next request, and granting it lifts every limit at once.
- **What each limit counts, and where it is checked:**

  | Limit | What counts | Checked | Refusal |
  | --- | --- | --- | --- |
  | Rules | Enabled rules, rules stopped only by Lapsed Authorization, and a Rule Replacement's new draft that keeps its previous rule's place | At Start (`EnableSyncRule`). Creating and previewing a rule, and a rule resuming after Lapsed Authorization, are never checked. | 409 `plan_limit_reached`, reason `rules` |
  | Connected Accounts | Every account of the User, Disconnected Accounts included | When the OAuth callback saves a new provider and address | The OAuth outcome `account_limit_reached`, with `limit` |
  | Integration Tokens | Unrevoked tokens | `IssueIntegrationToken` | 409 `plan_limit_reached`, reason `integration_tokens` |
  | Sync interval | Not a count | Instant Sync, through `PlanCadence` | None |

  Disconnected Accounts count because reconnecting one is Reauthorization, which is never refused;
  otherwise a User could disconnect one account, connect another, and reauthorize the first.
  `installation:read` tokens are for administrators only, who are never limited, so health
  monitoring is never blocked. The rule page answers `can_start` and `rule_limit`, so the Web UI
  disables Start with the message a refused Start shows and computes nothing itself.
- **Only Rule Replacement keeps a place.** A rule's place under the rule limit is its counting
  toward it. Drafts, previewed rules, and paused rules do not count. A rule stopped by a provider
  error, or paused by a Material Rule Change, gives up its place, and its restart is checked like
  any Start. A Rule Replacement's new draft keeps its previous rule's place
  (`SyncRule.keeps_place`) when that rule counted, and takes its creation order, so it ranks where
  the previous rule ranked and its Start always succeeds. A replacement of a rule that did not
  count keeps no place and is the newest rule. The place moves atomically: `RemoveSyncRule` inserts
  the draft, with the checks every new rule passes, in the same transaction that begins the
  previous rule's removal, after it waits for that rule's run
  ([ADR 0010](0010-rule-removal-and-calendar-replacement.md), amended). No moment counts both
  rules, no client sees the draft before its place moves, and no cleanup path deletes it. The draft
  keeps the place through previews and Material Rule Changes until it starts or is removed;
  disconnecting one of its accounts gives the place up.
- **Every limit check reads the Allowance inside the transaction it guards, after that transaction
  holds SQLite's writer lock.** `SqlitePlans` writes under `BEGIN IMMEDIATE`, and the database runs
  in WAL mode, so the read sees every committed Plan change and no Plan change commits until the
  check's transaction ends. A Start saves the enabled rule, then reads the Allowance, counts, and
  rolls back with `plan_limit_reached` when the count after the Start passes the limit: two Starts
  cannot both take the last place, and a lowering cannot slip in between. A new account is counted
  inside the existing `BEGIN IMMEDIATE` of the account store's save, and only when no row has the
  same provider and address, so Reauthorization never reads Plans. A token is counted under
  `BEGIN IMMEDIATE` right before its insert.
- **Limit checks fail closed; every other read of Plans fails open.** A check that cannot read the
  Allowance fails its request, as any database error does, so a fault never admits a resource past
  a limit; at the OAuth callback that is a server error after the provider's consent, with nothing
  saved. Every other reader falls back to no limits: Instant Sync dispatch, watch upkeep, and
  Installation Hints treat the User as instant, so no Instant Sync Request is dropped and no watch
  retired; `InstantSyncStatus` answers the default cadence; the rule page answers `can_start` true,
  and the Start still checks; the Operator Overview leaves the Plan out. A fault in Plans never
  stops synchronization, sign-in, or the rules API. Your plan (`ShowOwnPlan`) fails its own request
  instead of showing a basis it could not read; the Web UI then shows no limit hints, and the
  server still checks.
- **Lowering a limit stops nothing.** Rules beyond a lower rule limit keep syncing, but no rule can
  start until fewer count. Existing Connected Accounts keep their Reauthorization, and existing
  Integration Tokens keep working, because a token that stops on its own breaks a monitor
  ([ADR 0024](0024-integration-tokens-installation-status-and-mcp.md)). Only new ones are refused.
  Plan Hold, which holds rules beyond a lower limit after a grace period, arrives in a later slice
  with its own record.
- **A changed account address at the limit.** When a provider reports another address for an
  account, such as a renamed Microsoft or Google Workspace account, the new address is a new
  Connected Account. At the limit, the documented recovery keeps every rule: get one free account
  place, connect the new address, use Replace calendars on each rule, then disconnect and delete
  the old account. Deleting the old account first would delete its rules. When every place holds
  an account with rules, the free place comes from an administrator, who raises the limit or
  assigns a larger Plan for the recovery.
- **Sync intervals are a fixed server list:** `instant`, `5_minutes`, `10_minutes`, `15_minutes`,
  `30_minutes`, and `60_minutes`. `instant` means Instant Sync plus a five-minute Scheduled Sync.
  This slice offers `instant` and `5_minutes`. It reads every value, so a database a later release
  wrote still works, and it polls every value other than `instant` every five minutes without
  Instant Sync, because its scheduler runs every rule at every pass. A value it does not know reads
  as `instant`, with a warning. `PlanCadence` (`application/sync/watch_ports.py`) turns each User's
  Allowance into their Sync Cadence and replaces `EveryUserInstant` as the installation's
  `SyncCadencePolicy` ([ADR 0036](0036-instant-sync-through-provider-notices.md), amended). The
  User keeps only their own choice to turn Instant Sync off.
- **One assignment port.** `PlanAssignments.assign(user, plan, change)` is the only way a User's
  own Plan changes, and `None` returns the User to the Default Plan. `change` is
  `AssignmentChange(source, actor, at)`, whose source is `administrator` or `billing`; the User's
  row keeps the current one in `plan_assigned_by`, `plan_assigner_id`, and `plan_assigned_at`. An
  administrator may assign while Plans are off, to prepare. Billing (Commercial Mode, a later
  phase) will call the same port and decide from `plan_assigned_by` whether it may overwrite an
  administrator's choice. Each change writes one log line with identifiers only; a history waits
  for the deferred record of administrator actions.
- **Returning to setup turns Plans off,** keeping their definitions and the default, so a new
  first User never inherits limits nobody can see. Invitations carry no Plan: an invited User
  starts on the Default Plan.
- **Migration 33** adds the `plans` table, `plans_enabled` and `default_plan_key` on
  `installation_settings`, `plan_key`, `plan_assigned_by`, `plan_assigner_id`, and
  `plan_assigned_at` on `users`, and `keeps_place` on `sync_rules`. Nothing is backfilled: Plans
  start off and limit nobody. The foreign keys keep NO ACTION, so the database refuses to delete a
  Plan that a User or the default names. Rolling back works with the same database: earlier
  releases ignore the table and the columns and limit nobody, and after upgrading again, Plans are
  as the administrator left them.

## Consequences

Plans and their enforcement are the same code on every installation, so self-hosters can read how
the Hosted Service limits its free Plan, and a household administrator can use the same limits.
With Plans off nothing changes, and every existing test keeps its expected behavior.

The Web API gains the administrator's Plans routes (`GET` and `POST /api/v1/plans`, `PUT` and
`DELETE /api/v1/plans/{plan_key}`, `PUT /api/v1/plan-settings`, and
`PUT /api/v1/users/{user_id}/plan`), and `GET /api/v1/account/plan` for Your plan. Rule details
gain `can_start` and `rule_limit`, and the person's overview gains `plan`. The new problem codes
are `plan_limit_reached`, `plans_need_default`, `plan_not_found`, `plan_key_taken`, `plan_in_use`,
`plan_is_default`, and `invalid_plan`. A malformed Plan key in a path, the default, or an
assignment names no Plan, so it answers 404 `plan_not_found`; a malformed new key answers 422
`invalid_plan`. `GET /api/v1/status`, Installation Health, and MCP do not change.

A Connected Account can be refused only after the provider's consent, because only then is its
address known, and the refusal leaves an unused grant at the provider; the Web UI disables Connect
at the limit, which makes this rare. Counting people per Plan scans `users`, which is fine at
household and early Hosted Service scale; an index can come in a later migration. Phase 4 of the
multi-user design rebuilds `installation_settings` and must carry `plans_enabled` and
`default_plan_key`.

## Alternatives considered

- **Plans as their own bounded context.** Rejected for now: it changes the lint-imports layers
  (ADR 0032), loosens the isolation test (ADR 0029), and adds ports for the same behavior. It
  remains open if billing grows large.
- **Places kept by stopped and paused rules.** Rejected: a paused rule would hold a place its User
  cannot use, and a stopped rule could hold one its User cannot give back. Only Rule Replacement
  keeps a place, because its new draft takes over a rule that was already counted.
- **Creating the replacement draft first, then moving its place.** Rejected: the draft would count
  beside its previous rule, or could be started before its place moved, and a removal that failed
  afterwards deleted it even after a client had started it.
- **Checking a limit before the write.** Rejected: two requests could both pass the check. Writing
  first, then counting under the writer lock, serializes them.
- **Failing open on a limit check.** Rejected: a fault would admit a resource past the limit for
  good, while a refused request can simply be tried again.
- **Disconnected Accounts outside the count.** Rejected: a User could disconnect one account,
  connect another, and then reauthorize the first, which is never refused.
```

- [ ] **Step 10: Amend ADR 0010**

In `docs/adr/0010-rule-removal-and-calendar-replacement.md`, replace the first two lines:

```markdown
# Remove rules explicitly and replace calendars instead of editing them

```

with:

```markdown
# Remove rules explicitly and replace calendars instead of editing them

Amended by [ADR 0038](0038-plans-allowances-and-limits.md): a Rule Replacement's new draft is
created in the transaction that begins the previous rule's removal.

```

Then replace the last paragraph of the file:

```markdown
Replacement produces a new rule identity; its history starts fresh, while the removed rule's audit
entries remain. Detached Events can never be adopted by a later rule. Interrupted removals are
visible as "Removal incomplete" until retried.
```

with:

```markdown
Replacement produces a new rule identity; its history starts fresh, while the removed rule's audit
entries remain. Detached Events can never be adopted by a later rule. Interrupted removals are
visible as "Removal incomplete" until retried.

## Amendment: the new draft is created when the removal begins (2026-10-15)

A Rule Replacement no longer creates its new draft first. It checks for a duplicate relationship,
then hands the draft to Rule Removal as the previous rule's successor. Once the removal has waited
for the previous rule's run, it inserts the draft, with the checks every new rule passes, in the
same transaction that moves the previous rule to Removing. If a check fails, such as a duplicate
relationship that appeared meanwhile or an account the User no longer has, the transaction rolls
back: the previous rule stays as it was, and no draft exists.

Before, the draft was visible while the removal waited, and a removal that then failed deleted it
without its locks, even after a client had started it. Now no client sees the draft before the
removal begins, and no cleanup path deletes it. The uniqueness constraint still reserves the
relationship before anything destructive happens, and an interrupted removal still leaves the new
draft and a retryable previous rule. When the previous rule counted toward its User's Plan, the
draft also keeps its place under the rule limit
([ADR 0038](0038-plans-allowances-and-limits.md)).
```

- [ ] **Step 11: Amend ADR 0023**

In `docs/adr/0023-hosted-service-runs-the-open-codebase.md`, replace:

```markdown
Supersedes [ADR 0020](0020-single-installation-community-edition.md) and amends the hosted-service
decision in [ADR 0021](0021-community-edition-agpl.md). Amended by
[ADR 0028](0028-plans-apart-from-commercial-mode.md): Plans are their own setting, and Commercial
Mode now means billing only.
```

with:

```markdown
Supersedes [ADR 0020](0020-single-installation-community-edition.md) and amends the hosted-service
decision in [ADR 0021](0021-community-edition-agpl.md). Amended by
[ADR 0028](0028-plans-apart-from-commercial-mode.md): Plans are their own setting, and Commercial
Mode now means billing only. [ADR 0038](0038-plans-allowances-and-limits.md) records how Plans
limit Users.
```

Then replace the last bullet of the file:

```markdown
- **Open core with a commercially licensed `ee/` directory.** Rejected: it creates two licenses in
  one repository and invites the open-core distrust that ADR 0021 set out to avoid.
```

with:

```markdown
- **Open core with a commercially licensed `ee/` directory.** Rejected: it creates two licenses in
  one repository and invites the open-core distrust that ADR 0021 set out to avoid.

## Amendment: Plans (2026-10-15)

Two bullets of the decision read differently now. Plan limits no longer depend on Commercial Mode
([ADR 0028](0028-plans-apart-from-commercial-mode.md)): they apply only while an installation's
own administrator turns Plans on, and never to its Installation Administrators
([ADR 0038](0038-plans-allowances-and-limits.md)). The Hosted Service runs this same code with
Plans on. Its Plans may differ in how many rules, Connected Accounts, and Integration Tokens a
User has and how soon their calendars sync, including Instant Sync, but never in how a rule
protects privacy or in the tools to see and recover from a problem. A self-hosted installation has
every feature and no limits unless its own administrator turns Plans on. The operator overview
shows each User's Plan once any Plan exists.
```

- [ ] **Step 12: Amend ADR 0028**

In `docs/adr/0028-plans-apart-from-commercial-mode.md`, replace:

```markdown
Amends [ADR 0023](0023-hosted-service-runs-the-open-codebase.md).
```

with:

```markdown
Amends [ADR 0023](0023-hosted-service-runs-the-open-codebase.md). Amended by
[ADR 0038](0038-plans-allowances-and-limits.md), which records how Plans work.
```

Then replace the last bullet of the file:

```markdown
- **Installation-wide resource settings without plans.** Rejected: the Hosted Service needs plans
  anyway, so this would build two limit mechanisms.
```

with:

```markdown
- **Installation-wide resource settings without plans.** Rejected: the Hosted Service needs plans
  anyway, so this would build two limit mechanisms.

## Amendment: what the design of Plans settled (2026-10-15)

The design of Plans ([ADR 0038](0038-plans-allowances-and-limits.md)) settled what this record left
open:

- **The Hosted Service drives Plans.** On the Hosted Service, Instant Sync may be only for Plans
  that cost more, and a free Plan may sync every 5 to 10 minutes. A self-hosted installation has
  every feature and no limits unless its own administrator turns Plans on.
- **A Default Plan.** The administrator marks one Plan as the default, which every User without a
  Plan of their own has. Plans cannot turn on until a default exists. Billing will return a User
  to it when a payment ends.
- **Installation Administrators are never limited.** Under Only Me the only User administers, so
  Plans have no effect there, and the Web UI hides them.
- **Sync intervals are a fixed list:** Instant, 5, 10, 15, 30, and 60 minutes, where Instant means
  Instant Sync plus a five-minute Scheduled Sync. The Plan decides the interval, in place of "the
  shortest sync interval" above, and the User keeps only their own choice to turn Instant Sync
  off. The first release of Plans offers Instant and 5 minutes.

Until Plan Hold ships, a lowered rule limit refuses new Starts and stops nothing: rules beyond it
keep syncing, and no grace period starts. The fixed rate limit for manual runs also comes in a
later release.
```

- [ ] **Step 13: Amend ADR 0030**

In `docs/adr/0030-users-administrators-and-registration.md`, replace:

```markdown
Builds on [ADR 0023](0023-hosted-service-runs-the-open-codebase.md) and
[ADR 0029](0029-isolate-users-in-one-sqlite-database.md).
```

with:

```markdown
Builds on [ADR 0023](0023-hosted-service-runs-the-open-codebase.md) and
[ADR 0029](0029-isolate-users-in-one-sqlite-database.md). Amended by
[ADR 0038](0038-plans-allowances-and-limits.md): the Operator Overview shows each User's Plan, and
returning to setup turns Plans off.
```

Then replace:

```markdown
## Considered Options
```

with:

```markdown
## Amendment: Plans (2026-10-15)

Plans arrived ([ADR 0038](0038-plans-allowances-and-limits.md)), and three decisions above gained
their detail:

- **The Operator Overview shows each User's Plan** once any Plan exists, whether Plans are on or
  off: the Plan that limits them, marked when it is the default; for an Installation
  Administrator, that no Plan limits administrators, with any Plan they were given; and a Plan that
  applies once Plans are on. A person's page offers "Change plan". A failure to read Plans leaves
  the Plan out instead of failing the page.
- **Plans have no effect under Only Me.** Installation Administrators are never limited, and under
  Only Me the only User administers, so the Web UI hides Plans there, as it hides Users and
  Invitations.
- **Returning to setup turns Plans off,** keeping their definitions and the default, so a new
  first User never inherits limits nobody can see. Invitations carry no Plan: an invited User
  starts on the Default Plan.

## Considered Options
```

- [ ] **Step 14: Amend ADR 0036**

In `docs/adr/0036-instant-sync-through-provider-notices.md`, replace:

```markdown
[ADR 0033](0033-decide-an-incidents-next-step-in-the-domain.md). Amends
[ADR 0029](0029-isolate-users-in-one-sqlite-database.md).
```

with:

```markdown
[ADR 0033](0033-decide-an-incidents-next-step-in-the-domain.md). Amends
[ADR 0029](0029-isolate-users-in-one-sqlite-database.md). Amended by
[ADR 0038](0038-plans-allowances-and-limits.md): each User's Plan decides their Sync Cadence.
```

Then replace the last bullet of the file:

```markdown
- **Running the rule inside the notice request.** Rejected: Graph needs an answer within 3 seconds,
  and a run takes longer; a durable request also survives a crash.
```

with:

```markdown
- **Running the rule inside the notice request.** Rejected: Graph needs an answer within 3 seconds,
  and a run takes longer; a durable request also survives a crash.

## Amendment: the Plan decides the Sync Cadence (2026-10-15)

`PlanCadence` (`application/sync/watch_ports.py`) replaces `EveryUserInstant` as the installation's
`SyncCadencePolicy`. Each User's Sync Cadence follows their Allowance
([ADR 0038](0038-plans-allowances-and-limits.md)), so their Plan decides whether Instant Sync is
allowed. With Plans off, and for every Installation Administrator, it is allowed, with a
five-minute Scheduled Sync, as before. `EveryUserInstant` remains the default of `Adapters`, which
`build_adapters` replaces, and a policy for tests.

- `SyncCadencePolicy` gains `cadences(users)`, one read for many Users. Instant Sync dispatch,
  watch upkeep, and Installation Hints read it once and, when it fails, each User alone. A User
  whose own read still fails counts as instant, so a transient fault never drops their Instant
  Sync Requests or retires their watches. `InstantSyncStatus` falls back to the default cadence,
  so a fault in Plans never breaks sign-in or the rules API.
- A Plan without Instant Sync needs no other code: dispatch drops the User's pending requests,
  upkeep retires their watches, and availability reads `not_in_plan`. The User's own choice is
  kept, so Instant Sync returns by itself if their Plan allows it again.
- Scheduled Sync still runs every rule every five minutes in this release, whatever the Plan's
  interval.
```

- [ ] **Step 15: Check the ADRs and commit them**

Run:

```sh
git add -N docs/adr/0038-plans-allowances-and-limits.md
.venv/bin/pytest tests/test_ubiquitous_language.py tests/test_no_em_dashes.py -q
.venv/bin/ruff format --check .
.venv/bin/python - <<'EOF'
import re
from pathlib import Path

for name in (
    "docs/adr/0038-plans-allowances-and-limits.md",
    "docs/adr/0010-rule-removal-and-calendar-replacement.md",
    "docs/adr/0023-hosted-service-runs-the-open-codebase.md",
    "docs/adr/0028-plans-apart-from-commercial-mode.md",
    "docs/adr/0030-users-administrators-and-registration.md",
    "docs/adr/0036-instant-sync-through-provider-notices.md",
):
    path = Path(name)
    for target in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", path.read_text(encoding="utf-8")):
        if "://" not in target and not (path.parent / target).resolve().exists():
            print(f"{name}: no such file {target}")
EOF
```

Expected: every test passes (`git add -N` makes `test_no_em_dashes.py` read the new ADR);
`ruff format --check .` reports every file already formatted; the link check prints nothing.

Commit:

```sh
git add docs/adr/0038-plans-allowances-and-limits.md \
  docs/adr/0010-rule-removal-and-calendar-replacement.md \
  docs/adr/0023-hosted-service-runs-the-open-codebase.md \
  docs/adr/0028-plans-apart-from-commercial-mode.md \
  docs/adr/0030-users-administrators-and-registration.md \
  docs/adr/0036-instant-sync-through-provider-notices.md
git commit -F - <<'EOF'
Record how Plans limit people, and amend the decisions they change

ADR 0038 records Plans: Allowances read in the transaction each limit
check guards, limit checks that fail closed while every other read fails
open, the Default Plan, administrators never limited, what each limit
counts, the place a Rule Replacement keeps, the interval list, and the
assignment port billing will share. ADRs 0010, 0023, 0028, 0030, and
0036 gain dated amendments that point to it.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
```

- [ ] **Step 16: Update the glossary (`CONTEXT.md`)**

Do not touch the **Rule Replacement** entry (task 10 rewrote it) or the **Plan Hold** entry (slice
4 refines it). Keep both `_Avoid_:` lines of **Plan** and **Plan Hold** exactly as they are:
`test_every_checked_term_is_one_the_glossary_avoids` reads them.

1. Replace the **Plan** entry:

```markdown
**Plan**:
A named set of limits, such as how many rules a User may have or how often they synchronize, that
an Installation Administrator defines and assigns to Users. A Plan limits only how much a User
uses, never how a rule projects events or how a User sees and recovers from a problem. Plans are an installation setting that
is off by default; when off, every User has every feature with no limits (ADR 0028).
_Avoid_: Tier, subscription, quota
```

with:

```markdown
**Plan**:
A named set of limits that an Installation Administrator defines and assigns to Users: how many
Directional Sync Rules may count toward it, how many Connected Accounts and Integration Tokens a
User may have, and how soon their rules sync. Each Plan has a stable key, chosen when it is defined
and never changed, and a name that can change; each count is a number or unlimited. The rules that
count are enabled rules, rules stopped only by Lapsed Authorization, and a Rule Replacement's new
draft that keeps its previous rule's place; drafts, previewed rules, and paused rules do not. Every
Connected Account counts, Disconnected Accounts included, and every Integration Token not revoked.
A Plan limits only how much a User uses, never how a rule projects events or how a User sees and
recovers from a problem. Plans are an installation setting that is off by default; when off, every
User has every feature with no limits (ADR 0028). An Installation Administrator is never limited.
A User's own Plan is set by an Installation Administrator, and later also by billing under
Commercial Mode, through one assignment that records who set it and when (ADR 0038).
_Avoid_: Tier, subscription, quota

**Default Plan**:
The Plan an Installation Administrator marks as the default. Every User without a Plan of their
own has it, including Users who join later, so changing the default changes their limits at once.
Plans cannot be turned on until a default exists, and the default cannot be removed while it is
the default. Billing will return a User to it when a payment ends.
_Avoid_: Base plan, fallback plan

**Allowance**:
What one User may use now, decided in this order: no limits while Plans are off, none for an
Installation Administrator, otherwise their own Plan, or the Default Plan when they have none. It
decides every limit check and the User's Sync Cadence. A limit check that cannot read it refuses,
as for any database error; every other reader falls back to no limits, so a fault in Plans never
stops synchronization or sign-in (ADR 0038).
_Avoid_: Entitlement
```

2. Replace the **Sync Cadence** entry:

```markdown
**Sync Cadence**:
How a User's rules may synchronize: whether Instant Sync is allowed, and how often Scheduled Sync
runs. With Plans off, every User has Instant Sync and a five-minute Scheduled Sync; once Plans
exist, a Plan's shortest sync interval decides it, whose shortest value is "instant".
_Avoid_: Sync frequency, polling interval
```

with:

```markdown
**Sync Cadence**:
How a User's rules may synchronize: whether Instant Sync is allowed, and how often Scheduled Sync
runs. The User's Allowance decides it from their Plan's sync interval, one of a fixed list:
instant, 5, 10, 15, 30, or 60 minutes, where instant means Instant Sync plus a five-minute
Scheduled Sync. With Plans off, and for an Installation Administrator, it is instant. An
administrator can choose instant or 5 minutes for now; until the longer intervals are offered,
every interval other than instant syncs every five minutes without Instant Sync. The User keeps
only their own choice to turn Instant Sync off.
_Avoid_: Sync frequency, polling interval
```

3. In the **Operator Overview** entry, whose definition is one long line, replace that line:

```markdown
The Installation Administrator's view of every User's health: each User's Installation Status with calendars shown only by neutral labels ("Calendar 1", "Calendar 2", numbered per User in the order their rules were created), plus the User's email, role, last sign-in, state, and Resource Use. It is the same on every installation, never shows calendar names, calendar identifiers, account emails, or event content. What it shows and never shows is documented, so every User can know it; Settings does not repeat it to them (ADR 0030, amended).
```

with (only the list after "plus" changes):

```markdown
The Installation Administrator's view of every User's health: each User's Installation Status with calendars shown only by neutral labels ("Calendar 1", "Calendar 2", numbered per User in the order their rules were created), plus the User's email, role, last sign-in, state, Resource Use, and, once any Plan exists, their Plan. It is the same on every installation, never shows calendar names, calendar identifiers, account emails, or event content. What it shows and never shows is documented, so every User can know it; Settings does not repeat it to them (ADR 0030, amended).
```

4. In the Interface Wording table, replace the row:

```markdown
| Operator Overview | "People", with a "Sync" status per person and "Installation health" above them |
```

with:

```markdown
| Operator Overview | "People", with a "Sync" status per person and "Installation health" above them |
| Plan | "plan" in lower case: "Your plan" under Settings → Your account, "Plans" under Administration, "Change plan" on a person's page. Counts read "3 of 5 rules counted", "2 of 3 calendar accounts", "1 of 2 tokens". A refusal names the limit and one way to make room, with "See your plan" |
| Default Plan | "Default plan"; a person who has it reads "Free (default)", with the Plan's name |
| Allowance | never named: Your plan says which Plan limits the person, or "You administer this installation, so no plan limits you." |
```

- [ ] **Step 17: Update `AGENTS.md`**

Replace:

```markdown
Plan limits apply only when an administrator turns Plans on, and billing only when Commercial Mode
is also on; both are off by default, and with Plans off every user has every feature (ADR 0028).
Preserve the self-hosting promise that there is no mandatory Calendar Ghost account, telemetry, or
hosted coordinator.
```

with:

```markdown
Plan limits apply only when an administrator turns Plans on, and billing only when Commercial Mode
is also on; both are off by default, and with Plans off every user has every feature (ADR 0028).
Installation Administrators are never limited. A limit check reads the User's Allowance inside the
transaction it guards and fails closed; every other read of Plans fails open, so a fault in Plans
never stops synchronization, sign-in, or the rules API (ADR 0038).
Preserve the self-hosting promise that there is no mandatory Calendar Ghost account, telemetry, or
hosted coordinator.
```

- [ ] **Step 18: Restate the hosted-service promise in `README.md` and `docs/licensing.md`**

In `README.md`, replace:

```markdown
see [TRADEMARKS.md](TRADEMARKS.md). A future Calendar Ghost hosted service will run this same open
code for people who do not want to operate it, with no closed components. It will charge for running
Calendar Ghost for you, not for features: the Community Edition will not have features removed,
limited, or held back to push people toward it.
```

with:

```markdown
see [TRADEMARKS.md](TRADEMARKS.md). A future Calendar Ghost hosted service will run this same open
code for people who do not want to operate it, with no closed components and with Plans on. Its
Plans may differ in how many rules, calendar accounts, and Integration Tokens you have and how soon
your calendars sync, including Instant Sync. They never limit how a rule protects your privacy, or
the tools to see and recover from a problem. A self-hosted installation has every feature and no
limits unless its own administrator turns Plans on
([ADR 0028](docs/adr/0028-plans-apart-from-commercial-mode.md)).
```

In `README.md`, also replace:

```markdown
- Every record belongs to one person, and nobody sees another person's calendars, rules, Activity,
  or tokens; an administrator sees each person's email, role, state, and last sign-in only
```

with:

```markdown
- Every record belongs to one person, and nobody sees another person's calendars, rules, Activity,
  or tokens; an administrator sees each person's email, role, state, last sign-in, and plan only
```

Leave the Rule Replacement sentence ("Changing a calendar removes the rule and creates a new
draft") as it is: it stays true.

In `docs/licensing.md`, replace:

```markdown
Plan limits apply only when an installation's own administrator turns Plans on, and billing
only when Commercial Mode is also on; both are off by default. Unless its administrator chooses
otherwise, every user of a self-hosted installation has every feature, and no billing code contacts
a payment provider ([ADR 0028](adr/0028-plans-apart-from-commercial-mode.md)). The hosted service charges for operating Calendar Ghost, not for features: the Community
Edition will not have features removed, limited, or held back to push people toward it. See
[ADR 0023](adr/0023-hosted-service-runs-the-open-codebase.md).
```

with:

```markdown
Plan limits apply only when an installation's own administrator turns Plans on, and billing
only when Commercial Mode is also on; both are off by default. Unless its administrator chooses
otherwise, every user of a self-hosted installation has every feature, and no billing code contacts
a payment provider ([ADR 0028](adr/0028-plans-apart-from-commercial-mode.md)). The hosted service
runs this same code with Plans on. Its Plans may differ in how many rules, calendar accounts, and
Integration Tokens you have and how soon your calendars sync, including Instant Sync. They never
limit how a rule protects your privacy, or the tools to see and recover from a problem, and no Plan
limits an installation's administrators ([ADR 0038](adr/0038-plans-allowances-and-limits.md)).
See [ADR 0023](adr/0023-hosted-service-runs-the-open-codebase.md).
```

- [ ] **Step 19: Update `docs/architecture.md`**

1. Edition boundary. Replace:

```markdown
before. The future hosted service runs this same codebase (ADR 0023). The Operator Overview shows
administrators every User's health without their calendars. Plans behind the Plans setting, and
billing behind Commercial Mode, both off by default (ADR 0028), follow in the phases of
`docs/superpowers/specs/2026-10-09-multi-user-design.md`.
```

with:

```markdown
before. The future hosted service runs this same codebase (ADR 0023). The Operator Overview shows
administrators every User's health without their calendars. Plans, behind their own setting and
off by default, let an administrator limit how much each User who does not administer uses
(ADR 0028, [ADR 0038](adr/0038-plans-allowances-and-limits.md)). Billing behind Commercial Mode,
also off by default, follows in the phases of
`docs/superpowers/specs/2026-10-09-multi-user-design.md`.
```

2. Identity and Access. Replace:

```markdown
- **Identity and Access** (`application/identity`) owns Users, their roles and sessions, the
  Registration Policy, Invitations and Password Reset Links, and Integration Tokens.
```

with:

```markdown
- **Identity and Access** (`application/identity`) owns Users, their roles and sessions, the
  Registration Policy, Invitations and Password Reset Links, Integration Tokens, and Plans: their
  definitions, the Plans setting, and each User's own Plan.
```

3. Route modules. Replace:

```markdown
account, users, accounts, rules, activity, incidents, storage, integrations, health). Each module
```

with:

```markdown
account, users, plans, accounts, rules, activity, incidents, storage, integrations, health). Each module
```

4. Operator Overview: drop the stale `own`. Replace:

```markdown
User's `provider_calls` row for that provider and UTC day. The scheduler pass discards days older
than 30. `OperatorOverview.of` answers an administrator about one User, and `own` answers a User
about themself; both come from one function, so they cannot differ. `interfaces/access.py` holds the one access decision both transports use: a present
```

with:

```markdown
User's `provider_calls` row for that provider and UTC day. The scheduler pass discards days older
than 30. Once any Plan exists, it also adds each User's Allowance, read for the whole page at once;
a failure to read Plans leaves it out instead of failing People. `OperatorOverview.page` lists
Users for People, and `OperatorOverview.of` answers an administrator about one User; both come
from one function, so they cannot differ. `interfaces/access.py` holds the one access decision both transports use: a present
```

5. Plans ports and adapters. Replace:

```markdown
Read-only views follow the same direction. Activity and the dashboard ask the query protocols in
```

with:

```markdown
Plans follow the same direction ([ADR 0038](adr/0038-plans-allowances-and-limits.md)).
`domain/plans.py` holds the Plan values and `allowance_for`, which decides a User's `Allowance`
from whether Plans are on, whether the User administers, their own Plan, and the Default Plan.
Identity and Access owns the administrator's use cases in `application/identity/plans.py`, over
the `PlanCatalog` and `PlanAssignments` ports; billing will set a User's Plan through
`PlanAssignments` alone. Synchronization enforces the limits without importing Identity, through
the `Allowances` port it declares in `application/sync/ports.py`: `EnableSyncRule` checks the rule
limit, the Connected Account store checks the account limit when it saves a new address, and
`IssueIntegrationToken` checks the token limit. `PlanCadence` in
`application/sync/watch_ports.py` turns each User's Allowance into their Sync Cadence. One
`SqlitePlans` (`infrastructure/persistence/plans.py`) implements the three ports, and
`build_adapters` passes the same instance as each, so every client depends only on the port it
uses. Each limit check reads the Allowance after its own transaction holds SQLite's writer lock,
and `SqlitePlans` writes under `BEGIN IMMEDIATE`, so a check and the limit it read cannot drift
apart; a read that fails refuses the request. Every other reader falls back to no limits, so a
fault in Plans never stops synchronization, sign-in, or the rules API. `ShowOwnPlan`
(`application/operations/own_plan.py`) reads the Allowance and the User's counts for Your plan.

Read-only views follow the same direction. Activity and the dashboard ask the query protocols in
```

- [ ] **Step 20: Update the Instant Sync guide (`docs/instant-sync.md`)**

Keep the heading `### Not in your plan` exactly: `tests/test_instant_sync_docs.py` and the Web UI
link to its anchor. Replace its body:

```markdown
Plans arrive in a later release. Once an administrator turns them on, each person's Plan decides
whether it includes Instant Sync and how often Scheduled Sync runs, and only an administrator can
change your Plan. With Plans off, which is the default, everyone has Instant Sync.
```

with:

```markdown
Your Plan does not include Instant Sync. An administrator turned Plans on and gave you, or everyone
without a Plan of their own, a Plan whose rules sync on a schedule instead; on the Hosted Service,
billing will set your Plan too. Your rules still sync on schedule, and Calendar Ghost keeps your
own **Instant sync** choice, so Instant Sync returns by itself if your Plan includes it again.
**Settings → Your account → Your plan** shows what your Plan allows, and only an administrator can
change it. Administrators always have Instant Sync, and so does everyone while Plans are off, which
is the default.
```

Replace the body of `## Plans`:

```markdown
Instant Sync asks one question of the installation: does this person's Sync Cadence allow it? With
Plans off, the default, every person's does, and Scheduled Sync runs every five minutes. When Plans
arrive, each Plan's shortest sync interval decides it, and its shortest value is "instant". There
is no separate administrator switch: each person can turn Instant Sync off for themselves
([ADR 0036](adr/0036-instant-sync-through-provider-notices.md)).
```

with:

```markdown
Instant Sync asks one question of the installation: does this person's Sync Cadence allow it?
Their Allowance answers ([ADR 0038](adr/0038-plans-allowances-and-limits.md)). With Plans off, the
default, and for every administrator, it does, and Scheduled Sync runs every five minutes. With
Plans on, the person's own Plan, or the default plan when they have none, decides through its sync
interval. This release offers two: **Instant sync, and a check every 5 minutes**, and **Every 5
minutes**, which has no Instant Sync. When a person's Plan stops including Instant Sync, their
pending Instant Sync Requests are dropped, the next watch upkeep retires their watches, and their
rules show [Not in your plan](#not-in-your-plan). A fault in reading Plans never takes Instant Sync
away: the installation then treats the person as having it. There is no separate administrator
switch: each person can turn Instant Sync off for themselves
([ADR 0036](adr/0036-instant-sync-through-provider-notices.md)).
```

- [ ] **Step 21: Update `docs/data-ownership.md`**

1. Replace:

```markdown
- The Registration Policy.
```

with:

```markdown
- The Registration Policy.
- Plans, once an administrator defines one: each Plan's key, name, limits, and sync interval, and
  when it was defined and last changed; whether Plans are on, and which Plan is the default. For
  each User given a Plan of their own: that Plan, whether an administrator or billing set it, which
  administrator, and when. A User without one has the default, and nothing more is stored for
  them. Each rule also records whether it keeps the place of the rule it replaced under its User's
  Plan ([ADR 0038](adr/0038-plans-allowances-and-limits.md)).
```

2. In "What an Installation Administrator can see", replace:

```markdown
- their email, role, state, when they joined, and when they last signed in;
```

with:

```markdown
- their email, role, state, when they joined, and when they last signed in;
- once any Plan exists, their Plan: which Plan limits them and whether it is their own or the
  default, or, while Plans are off or for an administrator, the Plan they were given that does not
  apply yet;
```

3. Replace:

```markdown
An administrator can still disable or delete a User, issue them a password reset link, and change
their role. Calendar Ghost does not yet record which administrator did what.
```

with:

```markdown
An administrator can still disable or delete a User, issue them a password reset link, change
their role, and give them a Plan. Calendar Ghost records which administrator last gave each User
their Plan, and when, but does not yet record which administrator did anything else.
```

- [ ] **Step 22: Update the self-hosting guide (`docs/self-hosting.md`, "Invite other people")**

1. Replace item 3:

```markdown
3. Everyone's calendar accounts, rules, Activity, and tokens are their own. As the administrator you
   see each person's email, role, whether they may sign in, when they joined, and when they last
   signed in, never their calendars or events. Search by part of an email, filter by role or
   state, sort by email, joining, or last sign-in, and page through 50 people at a time; the
   address keeps your choices, so a reload or a shared link shows the same list.
```

with:

```markdown
3. Everyone's calendar accounts, rules, Activity, and tokens are their own. As the administrator you
   see each person's email, role, whether they may sign in, when they joined, when they last signed
   in, and, once you define a Plan, their Plan, never their calendars or events. Search by part of
   an email, filter by role or state, sort by email, joining, or last sign-in, and page through 50
   people at a time; the address keeps your choices, so a reload or a shared link shows the same
   list.
```

2. Replace the end of the paragraph after the list:

```markdown
their rules wrote are deleted too. When the last person deletes
their own account, Calendar Ghost returns to setup: the next person to open it creates the
administrator, as on a new installation, and the OAuth settings and master key in `.env`
stay as they were.
```

with:

```markdown
their rules wrote are deleted too. When the last person deletes
their own account, Calendar Ghost returns to setup: the next person to open it creates the
administrator, as on a new installation, and the OAuth settings and master key in `.env`
stay as they were. Plans, if you turned them on, turn off and keep their definitions.

To keep one person from using up what everyone shares, open **Settings → Administration →
Plans**. Choose **Add a plan** for each set of limits you want: how many rules may sync, how many
calendar accounts and Integration Tokens a person may have, and whether their calendars sync
instantly or every 5 minutes. Choose a **Default plan**, which everyone without a Plan of their
own has, including people who join later, then tick **Limit people with plans**. **Change plan**
on someone's page under **People** gives them another Plan. Administrators are never limited, and
while Plans are off, which is the default, nobody is. A lower limit stops nothing: rules beyond it
keep syncing, and accounts and tokens keep working, but nobody can start a rule, connect a new
calendar account, or issue a token past it. Each person sees what their Plan allows under
**Settings → Your account → Your plan**
([ADR 0038](adr/0038-plans-allowances-and-limits.md)).
```

- [ ] **Step 23: Update the domain model (`docs/domain-model.md`, "State machines")**

Replace:

```markdown
`SyncRule` decides these itself, so use cases ask the rule instead of comparing states: whether it
synchronizes (only when Enabled), whether a preview may validate it (Draft, Paused, or Degraded),
whether it is stopped only by Lapsed Authorization, and what disconnecting one of its accounts
makes of it.
```

with:

```markdown
A rule counts toward its User's Plan (`counts_toward_plan`) when it is Enabled, when it is Degraded
only by Lapsed Authorization (`holdable`), or when it keeps a place (`keeps_place`, ADR 0038).
Only a Rule Replacement's new draft keeps a place: `take_place_of` gives it one when the previous
rule counted, in the transaction that begins the previous rule's removal, and only a Draft or
Previewed rule may keep one. Previewing it again and a Material Rule Change keep the place;
enabling it turns the place into an Enabled rule's count; a degrade, disconnecting one of its
accounts, a required recovery preview, and Rule Removal clear it. A rule that keeps a place may
always start, because its Start does not change how many rules count. Otherwise Draft, Previewed,
and Paused rules do not count, so a rule a provider failure stops, or a Material Rule Change
pauses, gives up its place, and its restart is checked like any Start.

`SyncRule` decides these itself, so use cases ask the rule instead of comparing states: whether it
synchronizes (only when Enabled), whether a preview may validate it (Draft, Paused, or Degraded),
whether it is stopped only by Lapsed Authorization, whether it counts toward its User's Plan, and
what disconnecting one of its accounts makes of it.
```

- [ ] **Step 24: Add the rule-limit and token-limit sections to `docs/troubleshooting.md`**

Task 11 already documents decision 10, the error page at the OAuth callback when Plans cannot be
read, in the last paragraph of `## Connect is unavailable: your plan's calendar accounts`. Leave
that text as it is and add no other section for it, so the fault is explained once.

Replace:

```markdown
## Getting more help
```

with:

```markdown
## Start syncing is unavailable: your plan's rule limit

Start syncing is unavailable on a rule's preview page, or starting it answers that your plan's
limit is reached, when an administrator turned Plans on and the rules that count toward your Plan
already reach its rule limit. **Settings → Your account → Your plan** shows how many rules count
and how many your Plan allows.

- Rules that count are enabled rules and rules stopped only because an account's access lapsed.
  Draft, previewed, and paused rules do not count, and creating or previewing a rule is never
  limited.
- Pause or remove a rule you no longer need, then start this one.
- A rule stopped by any other error, or paused by a change to its policy, gave up its place. Its
  restart is checked like any Start, so it may be refused while other rules fill your Plan. When
  more rules count than your Plan allows, Calendar Ghost warns "Your plan may not let this rule
  start again." before such a change.
- **Replace calendars…** on a rule that counts (enabled, or stopped only because an account's
  access lapsed) gives the new draft that rule's place, so the new rule can start whatever the
  limit. Replacing a paused rule, or one stopped by any other error, keeps no place.
- A rule that stopped because an account's access lapsed already counts, so it resumes after
  Reauthorization whatever the limit.
- A lower limit stops nothing: rules beyond it keep syncing, but no rule can start until fewer
  count. Ask your administrator for a larger Plan; administrators are never limited.

An API client receives `409` with the code `plan_limit_reached` and the reason `rules`.

## Issue token is unavailable: your plan's token limit

Under **Settings → Connections → Integrations**, **Issue token** is unavailable when your
unrevoked Integration Tokens reach your Plan's token limit; a Plan may offer none. Revoke a token
you no longer use, then issue the new one: revoked tokens do not count. Tokens you already have
keep working when a limit is lowered, so no monitor stops on its own. A token that reads
Installation Health is for administrators, who are never limited. An API client receives `409`
with the code `plan_limit_reached` and the reason `integration_tokens`.

## Getting more help
```

- [ ] **Step 25: Point the multi-user design's phase 3 to the four slices**

In `docs/superpowers/specs/2026-10-09-multi-user-design.md`, replace:

```markdown
3. **Plans.** Plan definitions and assignment, the four limits, a per-User sync interval in the
   scheduler, and Plan Hold. Plans implement the `SyncCadencePolicy` port
   (`application/sync/watch_ports.py`) from each Plan's shortest sync interval, whose shortest value
   is "instant" ([ADR 0036](../../adr/0036-instant-sync-through-provider-notices.md)); until then,
   `EveryUserInstant` gives every User Instant Sync and a five-minute Scheduled Sync.
```

with:

```markdown
3. **Plans.** Four slices, each of which ships alone after the first
   ([Plans design](2026-10-15-plans-design.md)): (1) Plans core: Plan definitions and assignment,
   the Default Plan, the rule, Connected Account, and Integration Token limits, and Instant Sync or
   a five-minute sync per Plan, through `PlanCadence`, which implements the `SyncCadencePolicy`
   port (`application/sync/watch_ports.py`) from each User's Allowance
   ([ADR 0036](../../adr/0036-instant-sync-through-provider-notices.md),
   [ADR 0038](../../adr/0038-plans-allowances-and-limits.md)); (2) sync intervals of 10 to 60
   minutes in the scheduler; (3) the manual-run limit; (4) Plan Hold.
```

- [ ] **Step 26: Add the release notes (`CHANGELOG.md`, `## [Unreleased]`)**

Replace the first two lines of the `### Added` list:

```markdown
### Added

- Instant Sync: with a public HTTPS address in `CALENDAR_SYNC_PUBLIC_URL` that Google and Microsoft
```

with:

```markdown
### Added

- Plans let an administrator limit how much each person uses
  ([ADR 0038](docs/adr/0038-plans-allowances-and-limits.md)). Under **Settings → Administration →
  Plans**, an administrator adds Plans, each with how many rules may sync, how many calendar
  accounts and Integration Tokens a person may have, and whether their calendars sync instantly or
  every 5 minutes; chooses a default plan; and turns Plans on with **Limit people with plans**.
  **Change plan** on a person's page gives them a Plan of their own. Plans are off by default, and
  while they are off nothing changes. Administrators are never limited, and under **Only me**
  Plans stay hidden. Once Plans are on, starting a rule, connecting a new calendar account, and
  issuing a token respect the person's Plan: each control says so at the limit and links to
  **Settings → Your account → Your plan**, which shows what the Plan allows and how much of it is
  in use. Reauthorization is never refused. A lowered rule limit refuses new Starts and stops
  nothing: rules beyond it keep syncing, and existing calendar accounts and tokens keep working.
  Returning to setup turns Plans off and keeps their definitions. Rule details in the API gain
  `can_start` and `rule_limit`. Migration 33 adds the `plans` table and the Plan columns; rolling
  back to an earlier release works with the same database, which ignores them and limits nobody,
  and after upgrading again, Plans are as the administrator left them.
- Instant Sync: with a public HTTPS address in `CALENDAR_SYNC_PUBLIC_URL` that Google and Microsoft
```

Replace the heading of the `### Changed` list and the first line of its first bullet, which
describes how Activity leaves out a repeated skip:

```markdown
### Changed

- Activity no longer lists a skip that repeats the event's previous entry when the provider sent a
```

with:

```markdown
### Changed

- **Replace calendars…** creates the new draft rule in the same step that begins the previous
  rule's removal, once that rule's run ends, instead of before it. A duplicate relationship found
  meanwhile, or a calendar account that is gone, now leaves the previous rule as it was and
  creates no draft, and a removal that fails after it began keeps the new draft. With Plans on,
  the new draft keeps the previous rule's place when that rule counted, so it can start whatever
  the limit.
- Activity no longer lists a skip that repeats the event's previous entry when the provider sent a
```

- [ ] **Step 27: Run every documentation check**

Run:

```sh
.venv/bin/pytest tests/test_ubiquitous_language.py tests/test_no_em_dashes.py tests/test_instant_sync_docs.py tests/test_troubleshooting_anchors.py -q
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy
.venv/bin/lint-imports
.venv/bin/python - <<'EOF'
import re
from pathlib import Path

for name in (
    "CONTEXT.md",
    "AGENTS.md",
    "README.md",
    "CHANGELOG.md",
    "docs/licensing.md",
    "docs/architecture.md",
    "docs/instant-sync.md",
    "docs/data-ownership.md",
    "docs/self-hosting.md",
    "docs/domain-model.md",
    "docs/troubleshooting.md",
    "docs/superpowers/specs/2026-10-09-multi-user-design.md",
):
    path = Path(name)
    for target in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", path.read_text(encoding="utf-8")):
        if "://" not in target and not target.startswith("mailto:"):
            if not (path.parent / target).resolve().exists():
                print(f"{name}: no such file {target}")
EOF
git diff --stat
```

Expected: every test passes; `ruff format --check .` reports every file already formatted;
`ruff check .` prints `All checks passed!`; `mypy` prints `Success: no issues found`;
`lint-imports` reports every contract `KEPT`; the link check prints nothing; `git diff --stat`
lists exactly the twelve files of this step's link check.

Also open `docs/instant-sync.md`, `docs/troubleshooting.md`, and `docs/self-hosting.md` in a
Markdown preview and read each changed section once: the site renders these three
(`site/src/docs/pages.ts`), and every link in them must still read correctly.

- [ ] **Step 28: Commit**

```sh
git add CONTEXT.md AGENTS.md README.md CHANGELOG.md docs/licensing.md docs/architecture.md \
  docs/instant-sync.md docs/data-ownership.md docs/self-hosting.md docs/domain-model.md \
  docs/troubleshooting.md docs/superpowers/specs/2026-10-09-multi-user-design.md
git commit -F - <<'EOF'
Explain Plans in the glossary, the guides, and the release notes

CONTEXT.md refines Plan and adds Default Plan and Allowance. The README
and the licensing page say what the Hosted Service's Plans may limit and
what they never limit. The guides explain Plans to administrators, Your
plan and each limit to everyone, what Plans store and what
administrators see, and the place a Rule Replacement keeps. The
changelog announces Plans, that a lowered rule limit refuses new Starts
and stops nothing, and the new order of Replace calendars.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 20: Quality gates

This task writes no feature code. It runs every gate of contract section 4 "Commands" on the
finished branch, plus the repository rules no tool checks, confirms the static bundle matches the
web source, fixes what fails in the files of the task that owns it, and reports any check that
could not run. Its "tests" are the gates themselves, so its steps check rather than write a test
first.

**Files:**
- Create: none
- Modify: only files a failing gate points at, inside the task that owns them (the table in
  Step 9). The two mechanical fixes touch `web/openapi.json`, `web/src/lib/api-schema.ts`, and
  `src/calendar_sync/interfaces/api/static/`.
- Test: every test of the repository (`tests/`, `web/src/**/*.test.ts(x)`)

**Interfaces:**
- Consumes: every name tasks 1 to 19 produce; the commands of contract section 4; the branch's
  merge base with `origin/main`.
- Produces: a branch on which `ruff format --check .`, `ruff check .`, `mypy`, `lint-imports`,
  `pytest --cov --cov-fail-under=80`, `pnpm audit --audit-level=high`, `pnpm run api:check`,
  `typecheck`, `lint`, `doctor`, `knip`, `test`, `build`, and `gitleaks` all pass, and a short
  report of each result for the hand-off message.

- [ ] **Step 1: Start from a clean, complete branch**

Run:

```sh
git status --porcelain
BASE=$(git merge-base origin/main HEAD); echo "$BASE"
git log --oneline "$BASE"..HEAD
ls src/calendar_sync/domain/plans.py \
  src/calendar_sync/application/sync/rule_insertion.py \
  src/calendar_sync/application/identity/plans.py \
  src/calendar_sync/application/operations/own_plan.py \
  src/calendar_sync/infrastructure/persistence/0033_plans.sql \
  src/calendar_sync/infrastructure/persistence/plans.py \
  src/calendar_sync/interfaces/api/plan_payload.py \
  src/calendar_sync/interfaces/api/routes/plans.py \
  tests/plans.py \
  tests/domain/test_plans.py tests/domain/test_rule_places.py \
  tests/adapters/test_plans_schema.py tests/adapters/test_plans_store.py \
  tests/adapters/test_plan_races.py tests/adapters/test_account_limit.py \
  tests/adapters/test_oauth_outcomes.py tests/adapters/test_plans_api.py \
  tests/application/test_plan_cadence.py tests/application/test_plans.py \
  tests/application/test_plan_limits.py tests/application/test_own_plan.py \
  web/src/lib/plans.ts web/src/lib/plans.test.ts web/src/lib/use-own-plan.ts \
  web/src/lib/use-plans.ts web/src/components/your-plan-link.tsx \
  web/src/features/settings-plans.tsx web/src/features/plan-editor.tsx \
  web/src/features/settings-own-plan.tsx web/src/features/person-plan.tsx \
  web/src/features/settings-plans.test.tsx web/src/features/settings-own-plan.test.tsx \
  docs/adr/0038-plans-allowances-and-limits.md
```

Expected: `git status --porcelain` prints nothing; the log lists the commits of tasks 1 to 19
after the four planning commits (`Design Plans: ...`, `Count keep-choice releases ...`,
`Plan the first part of Plans: ...`, and `Number Plans after main: ...`); `ls` lists
every path and prints no `No such file or directory`. A missing path means its task is not done:
finish that task first. If the local `origin/main` is stale, run `git fetch origin main` first.

- [ ] **Step 2: Run the backend gate**

Run, one at a time:

```sh
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy
.venv/bin/lint-imports
.venv/bin/pytest --cov --cov-report=term-missing --cov-fail-under=80
```

Expected:
- `ruff format --check .`: every file already formatted (this includes Python blocks in
  `docs/*.md` and `docs/adr/*.md`).
- `ruff check .`: `All checks passed!`
- `mypy`: `Success: no issues found in N source files`.
- `lint-imports`: every contract `KEPT`, `0 broken`.
- `pytest`: no failures, no errors, and `Required test coverage of 80% reached. Total coverage:`
  with a value of at least 80.00%. This run includes `tests/test_openapi_contract.py`,
  `tests/test_architecture.py`, `tests/test_no_em_dashes.py`, `tests/test_ubiquitous_language.py`,
  `tests/test_dev_preview.py`, `tests/test_instant_sync_docs.py`, and
  `tests/test_troubleshooting_anchors.py`.

- [ ] **Step 3: Run the Review Focus and race modules on their own, several times**

The real-thread races must not be flaky. Run:

```sh
for run in 1 2 3 4 5; do
  .venv/bin/pytest tests/adapters/test_plan_races.py tests/adapters/test_account_limit.py \
    tests/application/test_plan_limits.py tests/application/test_integration_tokens.py \
    tests/adapters/test_integration_tokens.py tests/application/test_own_plan.py \
    tests/adapters/test_plans_api.py tests/adapters/test_plans_store.py \
    tests/application/test_plans.py tests/domain/test_plans.py \
    tests/application/test_plan_cadence.py -q || { echo "run $run failed"; break; }
done
```

Expected: five passing runs and no `run N failed` line. These modules carry contract section 6:
Reauthorization at the limit (task 11), an administrator demoted while over the limit (tasks 8,
9, 12), Plans toggled or lowered while a Start is in flight and the two-request races (tasks 8, 9,
11), a malformed Plan key (tasks 1, 4, 13), a User on the Default Plan when the default changes
(tasks 4, 7, 13), and the fail-open cadence readers (task 5). A failure that appears in only some
runs is a race bug in the task that owns the module: fix it there, never by adding a sleep or a
retry to the test.

- [ ] **Step 4: Check the OpenAPI schema and the generated types**

Run:

```sh
(cd web && pnpm install --frozen-lockfile)
.venv/bin/python scripts/export_openapi.py
(cd web && pnpm run api:types)
git status --porcelain -- web/openapi.json web/src/lib/api-schema.ts
(cd web && pnpm run api:check)
```

Expected: `git status --porcelain` prints nothing (the committed files already match the routes,
as `tests/test_openapi_contract.py` also proved in Step 2), and `api:check` exits 0. If either file
shows as modified, apply fix A of Step 9.

- [ ] **Step 5: Run the frontend gate**

Run, one at a time:

```sh
cd web
pnpm install --frozen-lockfile
pnpm audit --audit-level=high
pnpm run api:check
pnpm run typecheck
pnpm run lint
pnpm run doctor
pnpm run knip
pnpm run test
cd ..
```

Expected: every command exits 0. `lint` reports no warning (it runs with `--max-warnings 0`);
`doctor` reports no warning; `knip` reports no unused file, export, or dependency; `test` reports
every Vitest file passing, including `src/i18n/catalog.test.ts` (no unused English key, every
`settings.plans.interval.*` value known). `pnpm audit` needs the network: if it cannot reach the
registry, record "pnpm audit could not run: no network" for the report and go on.

- [ ] **Step 6: Confirm the static bundle matches the web source**

The bundle embeds the commit it was built from, so a plain rebuild always differs by that hash.
Rebuild with the commit the committed bundle names, which must reproduce it byte for byte:

```sh
SHA=$(grep -o 'calendar-ghost/tree/[0-9a-f]\{40\}' src/calendar_sync/interfaces/api/static/assets/index-*.js | head -1 | cut -d/ -f3)
echo "bundle built from $SHA"
git merge-base --is-ancestor "$SHA" HEAD && echo "ancestor of HEAD"
(cd web && GITHUB_SHA="$SHA" pnpm run build)
git status --porcelain -- src/calendar_sync/interfaces/api/static
```

Expected: one 40-character SHA, `ancestor of HEAD`, a build that exits 0 (the warning about
chunks larger than 500 kB is expected), and no output from `git status --porcelain`. Output there
means some web change after the last rebuild was committed without one: restore the tree with
`git checkout -- src/calendar_sync/interfaces/api/static && git clean -fdq -- src/calendar_sync/interfaces/api/static`,
then apply fix B of Step 9.

- [ ] **Step 7: Check the repository rules no tool enforces alone**

Run:

```sh
BASE=$(git merge-base origin/main HEAD)
git diff "$BASE"..HEAD -- pyproject.toml | grep -n "ignore_imports"
git diff "$BASE"..HEAD -- tests/test_architecture.py
git diff "$BASE"..HEAD -- src | grep -nE "^\+.*noqa: .*(C901|PLR0912|PLR0913|PLR0915)"
git diff "$BASE"..HEAD -- web/src | grep -n "^+.*eslint-disable"
grep -rn "HTTPException(" src/calendar_sync/interfaces | grep -v "problems.py"
git log "$BASE"..HEAD --format=%B | .venv/bin/python -c "import sys; text = sys.stdin.read(); print('em dash in a commit message' if chr(0x2014) in text else 'no em dash')"
for commit in $(git log --format=%H "$BASE"..HEAD); do
  git log -1 --format=%B "$commit" | grep -q "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>" || echo "no attribution: $commit"
done
git log "$BASE"..HEAD --format=%s | grep -nE "^(feat|fix|chore|docs|refactor|test)(\(|:)"
git diff --name-only "$BASE"..HEAD -- web/openapi.json web/src/lib/api-schema.ts
```

Expected:
- the first five commands print nothing: no `ignore_imports` entry added, `WIDE_DATACLASSES`
  unchanged, no new `noqa` for the complexity rules in `src/`, no new `eslint-disable`, and no
  bare `HTTPException` outside `problems.py`;
- the Python one-liner prints `no em dash`;
- the attribution loop prints nothing;
- the conventional-prefix check prints nothing;
- the last command lists both `web/openapi.json` and `web/src/lib/api-schema.ts` (they change
  together, tasks 9 and 13).

A finding here is fixed in the owning task's files (Step 9) and the commit that introduced it is
followed by a fixing commit; never rewrite published history. A commit message without the
attribution line or with a conventional prefix cannot be fixed without rewriting history: report
it instead (Step 10).

- [ ] **Step 8: Scan for secrets**

Run:

```sh
gitleaks version
gitleaks git . --log-opts="$(git merge-base origin/main HEAD)..HEAD" --redact --verbose --no-banner
gitleaks git . --redact --no-banner
```

Expected: `8.30.1`, then `no leaks found` from both scans. The first scan is what CI's `secrets`
job runs on a pull request, and finishes in under a second; the second covers the whole history,
as AGENTS.md asks, and keeps every core busy for about 14 minutes on a laptop (2104 commits, 8.7 GB
on 2026-10-15), so run it in the background and wait for it (give it a timeout of at least 30
minutes). If `gitleaks` is not installed, record "gitleaks could not run: not installed" for the
report. A finding in a synthetic test fixture may be allowlisted in `.gitleaks.toml` only with a
comment saying it is synthetic; any other finding blocks the hand-off.

- [ ] **Step 9: Fix what failed, in the task that owns it**

Find the owner from the failing file:

| Failing file or check | Owning task |
| --- | --- |
| `domain/plans.py`, `domain/access.py`, `tests/domain/test_plans.py` | 1 |
| `domain/model.py`, `tests/domain/test_rule_places.py` | 2 |
| `0033_plans.sql`, `migrations.py`, `persistence/sqlite.py`, `memory.py`, `memory_installation.py`, `users.py`, `tests/contracts/persistence.py`, `docs/deployment.md` | 3 |
| `persistence/plans.py`, `connections.py`, `installation.py`, `registration.py`, `tests/identity_fakes.py`, `tests/users.py`, `tests/plans.py`, `test_plans_store.py` | 4 |
| `watch_ports.py`, `instant_sync.py`, `installation_hints.py`, the cadence tests | 5 |
| `problems.py`, `common.json` `apiError.*`, `test_api_problems.py` | 6 |
| `application/identity/plans.py`, `tests/application/test_plans.py` | 7 |
| `integration_tokens.py` (application and infrastructure), `routes/integrations.py`, token tests | 8 |
| `rules.py` (`EnableSyncRule`, `GetSyncRuleDetails`), `routes/rules.py`, `test_plan_limits.py`, `RuleDetailResponse` | 9 |
| `rule_insertion.py`, `removal.py`, `ReplaceSyncRuleCalendars`, `test_remove_sync_rule.py`, CONTEXT **Rule Replacement** | 10 |
| `accounts.py`, `oauth.py`, `routes/accounts.py`, `oauth-redirect.ts`, `navigation.ts`, `test_account_limit.py`, `test_oauth_outcomes.py` | 11 |
| `own_plan.py`, `operator_overview.py`, `scripts/dev_preview.py`, `test_own_plan.py`, `test_operator_overview.py` | 12 |
| `schemas.py`, `plan_payload.py`, `routes/plans.py`, `routes/users.py`, `app.py`, `test_plans_api.py`, `test_api_authorization.py`, `test_schema_enums.py` | 13 |
| `lib/api.ts`, `lib/plans.ts`, `lib/use-own-plan.ts`, `lib/use-plans.ts`, `your-plan-link.tsx`, `catalog.test.ts` | 14 |
| `settings-plans.tsx`, `plan-editor.tsx`, `settings-plans.test.tsx` | 15 |
| `person-plan.tsx`, `person-actions.tsx`, `person-page.tsx`, `use-people.ts` | 16 |
| `settings-own-plan.tsx`, `settings-own-plan.test.tsx` | 17 |
| `rule-preview-footer.tsx`, `connect-account.tsx`, `settings-accounts.tsx`, `overview.tsx`, `settings-integrations.tsx`, `rule-commands.tsx`, `rule-policy-editor.tsx`, `settings-account-row.tsx` | 18 |
| any doc, ADR, `CONTEXT.md`, `AGENTS.md`, `CHANGELOG.md`, `test_ubiquitous_language.py` | 19 |
| `bootstrap/container.py` | the task whose wiring fails (contract section 3.14) |

Fix the cause in that task's files, as that task's text in this plan states, then rerun the
failing command and every later step of this task from Step 2. Commit each fix on its own, with a
message in this repository's style that says what the fix does for people, a short body naming
the failing gate, and the attribution trailer.

Two failures have a mechanical fix:

**Fix A: stale OpenAPI schema or types.**

```sh
.venv/bin/python scripts/export_openapi.py
(cd web && pnpm run api:types)
.venv/bin/pytest tests/test_openapi_contract.py -q
(cd web && pnpm run api:check && pnpm run typecheck)
git add web/openapi.json web/src/lib/api-schema.ts
git commit -F - <<'EOF'
Regenerate the Web API types from the Plans routes

The committed OpenAPI schema and the frontend types it generates no
longer matched the routes, which the OpenAPI contract test and
api:check reported.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
```

**Fix B: the static bundle does not match the web source.**

```sh
(cd web && pnpm run build)
git status --porcelain -- src/calendar_sync/interfaces/api/static
git add -A src/calendar_sync/interfaces/api/static
git commit -F - <<'EOF'
Rebuild the Web UI so it serves the current Plans screens

A web change was committed without rebuilding the static bundle, so the
installed app would not have shown it.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
```

Then rerun Step 6 with the new embedded SHA: it must print nothing.

- [ ] **Step 10: Run CI's plain build, and leave no hash-only change behind**

CI's `frontend` job ends with a plain `pnpm run build`. Run it, then drop the result, because it
differs from the committed bundle only by the embedded commit hash, and a hash-only rebuild is
never committed:

```sh
(cd web && pnpm run build)
git checkout -- src/calendar_sync/interfaces/api/static
git clean -fdq -- src/calendar_sync/interfaces/api/static
git status --porcelain
```

Expected: the build exits 0, and `git status --porcelain` prints nothing.

If Docker is available, also build the image as AGENTS.md asks for release-facing changes
(migration 33 is one):

```sh
docker compose build
```

Expected: the build finishes with the image tagged. If Docker is not available, record "docker
compose build could not run: Docker not available" for the report; CI's `docker` job builds both
architectures on the pull request.

- [ ] **Step 11: Report**

There is nothing to commit in this step: `git status --porcelain` prints nothing. Hand off with a
short report in the final message (not a file), one line per check, in this order: ruff format,
ruff check, mypy, lint-imports, pytest with the total coverage percentage, the five race runs,
OpenAPI export and `api:check`, `pnpm audit`, typecheck, lint, doctor, knip, Vitest, the bundle
reproduction (with the SHA it was built from), the repository-rule checks, both gitleaks scans,
and the Docker build. For each: passed, fixed (with the fixing commit's short hash and owning
task), or could not run (with why). List every commit message that lacks the attribution line or
uses a conventional prefix, if Step 7 found any.

