"""Giving many people each their own Plan, or the Default Plan, at once (ADR 0038, the catalog).

The Plans are given through `PlanAssignments`, all or none. Who would be over a limit, and who is
once it is given, comes from the Operator Overview, the one reader that counts other Users'
records (ADR 0029), so a dry run says it before anyone confirms.
"""

from __future__ import annotations

import logging
from collections.abc import Collection, Mapping
from dataclasses import dataclass

from calendar_sync.application.identity.administration import require_administrator
from calendar_sync.application.identity.ports import (
    AssignmentChange,
    PlanAssignments,
    UserDirectory,
)
from calendar_sync.application.operations.operator_overview import OperatorOverview, PersonPlan
from calendar_sync.application.shared.ports import Clock
from calendar_sync.domain.access import User, UserId
from calendar_sync.domain.plans import (
    AssignmentSource,
    InvalidAssignment,
    InvalidAssignmentReason,
    PlanKey,
    require_assignable,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PlanMove:
    """One person a Plan is given to, or would be in a dry run."""

    user: User
    before: PersonPlan
    """Their Plan before, as their page showed it."""
    after: PersonPlan
    """Their Plan after, as their page shows it now, or would in a dry run: the Plan they have
    and each of its limits they are over."""


@dataclass(slots=True)
class AssignPlans:
    """Give each of up to 100 people their own Plan, or None for the Default Plan, at once, all
    or none, as one Plan for everyone or as Undo gives each back theirs. Giving the Default Plan
    does as None does, so they follow it.

    With a dry run it writes nothing and answers the same, read now. Allowed while Plans are
    off, as giving one person a Plan is; administrators keep the Plan they are given, and no
    Plan limits them while they administer.
    """

    users: UserDirectory
    overview: OperatorOverview
    assignments: PlanAssignments
    clock: Clock

    def execute(
        self, actor: UserId, plans: Mapping[UserId, PlanKey | None], *, dry_run: bool = False
    ) -> tuple[PlanMove, ...]:
        """Each person `plans` names, in the order named. Raises InvalidAssignment for nobody,
        more than 100 people, or someone who is not a User, and PlanNotFound when one of the
        Plans does not exist; either way nobody is given anything."""
        require_administrator(self.users, actor)
        found = self._people(plans)
        before = self.overview.plans_of(actor, found)
        if dry_run:
            after = self.overview.plans_given(actor, found, plans)
        else:
            self._assign(actor, plans)
            after = self.overview.plans_of(actor, found)
        return tuple(PlanMove(user, before[user.id], after[user.id]) for user in found)

    def _people(self, people: Collection[UserId]) -> list[User]:
        require_assignable(len(people))
        found = [self.users.get(person) for person in people]
        known = [user for user in found if user is not None]
        if len(known) != len(people):
            raise unknown_people()
        return known

    def _assign(self, actor: UserId, plans: Mapping[UserId, PlanKey | None]) -> None:
        change = AssignmentChange(AssignmentSource.ADMINISTRATOR, actor, self.clock.now())
        # Raises PlanNotFound; False when someone was deleted since they were read.
        if not self.assignments.assign_all(plans, change):
            raise unknown_people()
        for user, plan in plans.items():
            logged = plan.value if plan is not None else None
            logger.info("plan assigned user=%s plan=%s by=%s", user.value, logged, actor.value)


def unknown_people() -> InvalidAssignment:
    """The refusal for someone named who is not a User, or no longer is, such as a malformed
    identifier."""
    return InvalidAssignment(
        InvalidAssignmentReason.UNKNOWN_PEOPLE, "someone named is not a user here"
    )
