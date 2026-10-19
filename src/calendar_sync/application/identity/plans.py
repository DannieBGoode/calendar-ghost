"""What Installation Administrators do with Plans (ADR 0038): define, change, and remove them,
choose the Default Plan, and turn Plans on or off.

Each use case checks first that the actor is an active Installation Administrator. Each change
logs one line that names only ids: a Plan's key and Users' identifiers, never a name or email.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from calendar_sync.application.identity.administration import require_administrator
from calendar_sync.application.identity.errors import PlanNotFound
from calendar_sync.application.identity.ports import (
    PlanCatalog,
    PlanListing,
    PlansSetting,
    UserDirectory,
)
from calendar_sync.application.shared.ports import Clock
from calendar_sync.domain.access import UserId
from calendar_sync.domain.plans import (
    OFFERED_INTERVALS,
    NewPlan,
    Plan,
    PlanKey,
    SyncInterval,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PlansOverview:
    """Every Plan with who has it, the Plans setting, the sync intervals a Plan may offer, and
    how many people have no Plan of their own."""

    setting: PlansSetting
    plans: tuple[PlanListing, ...]
    offered: tuple[SyncInterval, ...]
    followers: int
    """Everyone with no Plan of their own, whatever their role or state: whom Make default
    moves to the Plan it makes the default."""


def _overview(catalog: PlanCatalog, setting: PlansSetting) -> PlansOverview:
    return PlansOverview(setting, tuple(catalog.plans()), OFFERED_INTERVALS, catalog.followers())


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
    """Add a Plan. Its key is the one asked for, or else one made from its name that no other
    Plan has; it never changes."""

    users: UserDirectory
    catalog: PlanCatalog
    clock: Clock

    def execute(self, actor: UserId, plan: NewPlan) -> PlanListing:
        require_administrator(self.users, actor)
        # Raises PlanKeyTaken for a key asked for that another Plan has.
        stored = self.catalog.add(plan, self.clock.now())
        logger.info("plan defined key=%s by=%s", stored.key.value, actor.value)
        return _listing(self.catalog, stored.key)


@dataclass(slots=True)
class ChangePlan:
    """Change a Plan's name and limits, keeping its key. New limits apply at once to new rules,
    accounts, and tokens, and stop nothing a User already has."""

    users: UserDirectory
    catalog: PlanCatalog
    clock: Clock

    def execute(self, actor: UserId, plan: Plan) -> PlanListing:
        require_administrator(self.users, actor)
        if self.catalog.get(plan.key) is None:
            raise PlanNotFound(f"plan {plan.key.value} does not exist")
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
    """Turn Plans on or off and choose the Default Plan. Turning Plans on with no default makes a
    Plan named "No limits" the default, so it changes nothing until someone has a smaller Plan.
    Turning Plans off is always allowed and keeps every Plan and every User's own Plan."""

    users: UserDirectory
    catalog: PlanCatalog
    clock: Clock

    def execute(self, actor: UserId, enabled: bool, default: PlanKey | None) -> PlansOverview:
        require_administrator(self.users, actor)
        # Raises PlanNotFound for a default that names no Plan, and PlansNeedDefault when
        # clearing the default with Plans on.
        setting = self.catalog.change_settings(enabled, default, self.clock.now())
        logger.info(
            "plans setting changed enabled=%s default=%s by=%s",
            setting.enabled,
            _logged(setting.default),
            actor.value,
        )
        return _overview(self.catalog, setting)
