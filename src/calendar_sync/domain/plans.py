"""Plans: named limits an Installation Administrator defines and assigns (ADR 0028, ADR 0038).

An Allowance is what one User may use now. Plans are off by default, and then nothing limits
anyone; Installation Administrators are never limited. Everything here is a value or a pure
decision: the stores that keep Plans and the use cases that check limits call it.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Container
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from calendar_sync.domain.cadence import DEFAULT_CADENCE, SCHEDULED_EVERY, SyncCadence
from calendar_sync.domain.errors import DomainError, DomainValidationError

if TYPE_CHECKING:
    from calendar_sync.domain.model import SyncRule

PLAN_KEY_LIMIT = 32
"""The longest Plan key."""
PLAN_NAME_LIMIT = 60
"""The longest Plan name."""
COUNT_LIMIT = 10_000
"""The largest number any limit of a Plan may be."""
# 1 to 32 lower-case letters, digits, and hyphens, starting with a letter or digit.
_PLAN_KEY = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
# What a key made from a name turns into one hyphen: every run of anything but a letter or digit.
_NOT_IN_KEY = re.compile(r"[^a-z0-9]+")
_FALLBACK_KEY = "plan"
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
    """A Plan's stable key: set when the Plan is defined, from its name unless one is asked for,
    and never renamed, so billing can name it later."""

    value: str

    def __post_init__(self) -> None:
        if _PLAN_KEY.fullmatch(self.value) is None:
            raise InvalidPlan(
                InvalidPlanReason.KEY,
                "a plan key is 1 to 32 lower-case letters, digits, and hyphens, "
                "starting with a letter or digit",
            )


def plan_key_from(name: str, taken: Container[str]) -> PlanKey:
    """The key a new Plan named `name` gets: its letters and digits in lower case, accents
    dropped, with one hyphen for each run of anything else, at most 32 characters, or "plan" when
    nothing is left. When a Plan in `taken` has it, "-2", "-3", and so on is added, shortening
    the rest so the key still fits."""
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    made = _NOT_IN_KEY.sub("-", plain.lower()).strip("-")
    base = made[:PLAN_KEY_LIMIT].rstrip("-") or _FALLBACK_KEY
    key, number = base, 1
    while key in taken:
        number += 1
        suffix = f"-{number}"
        key = base[: PLAN_KEY_LIMIT - len(suffix)].rstrip("-") + suffix
    return PlanKey(key)


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
        _require_name(self.name)


@dataclass(frozen=True, slots=True)
class NewPlan:
    """A Plan an administrator adds, before it has its key: the key asked for, if any, or one the
    store makes from the name, so no other Plan has it."""

    name: str
    limits: PlanLimits
    key: PlanKey | None = None
    """The key asked for; None makes one from the name."""

    def __post_init__(self) -> None:
        _require_name(self.name)

    def keyed(self, taken: Container[str]) -> Plan:
        """The Plan to store: with the key asked for, or else with one made from the name that
        no key in `taken` is."""
        key = self.key if self.key is not None else plan_key_from(self.name, taken)
        return Plan(key, self.name, self.limits)


def _require_name(name: str) -> None:
    if not _printable(name):
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
    """Plans are never on without a Default Plan, so every User has a Plan: the default cannot be
    cleared while Plans are on, or as they turn on."""


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


NO_LIMITS_PLAN = NewPlan("No limits", NO_LIMITS)
"""The Plan made the Default Plan when Plans turn on with none. It limits nobody, so turning
Plans on changes nothing until an administrator gives someone a smaller Plan. It is an ordinary
Plan: it can be renamed and changed."""


def needs_no_limits_plan(enabled: bool, default: PlanKey | None, chosen: PlanKey | None) -> bool:
    """Whether setting Plans to `enabled` with `default` first makes NO_LIMITS_PLAN the default:
    Plans turn on, and neither the change nor the installation (`chosen`) names a default.

    Raises PlansNeedDefault when the change would clear the `chosen` default with Plans on.
    Turning Plans off is always allowed, with or without a default.
    """
    if not enabled or default is not None:
        return False
    if chosen is not None:
        raise PlansNeedDefault(
            "plans cannot be on without a default plan; choose another default instead"
        )
    return True


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


def may_start(before: SyncRule, counting_after: int, limit: int | None) -> bool:
    """Whether a Start fits the rule limit. A rule that keeps a place always starts, because its
    Start does not change the count; any other starts while `counting_after`, the rules that
    count once it runs, stays within `limit`."""
    return limit is None or before.keeps_place or counting_after <= limit
