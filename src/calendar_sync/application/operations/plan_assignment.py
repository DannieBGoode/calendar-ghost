"""Giving one Plan, or the Default Plan, to many people at once (ADR 0038, the catalog).

The Plan is given through `PlanAssignments`, all or none. Who would be over a limit, and who is
once it is given, comes from the Operator Overview, the one reader that counts other Users'
records (ADR 0029), so a dry run says it before anyone confirms.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
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
    """Give one Plan, or None for the Default Plan, to up to 100 people at once, all or none.
    Giving the Default Plan does as None does, so they follow it.

    With a dry run it writes nothing and answers the same, read now. Allowed while Plans are
    off, as giving one person a Plan is; administrators keep the Plan they are given, and no
    Plan limits them while they administer.
    """

    users: UserDirectory
    overview: OperatorOverview
    assignments: PlanAssignments
    clock: Clock

    def execute(
        self,
        actor: UserId,
        people: Sequence[UserId],
        plan: PlanKey | None,
        *,
        dry_run: bool = False,
    ) -> tuple[PlanMove, ...]:
        """Each person named, once, in the order first named. Raises InvalidAssignment for
        nobody, more than 100 people, or someone who is not a User, and PlanNotFound; either
        way nobody is given anything."""
        require_administrator(self.users, actor)
        found = self._people(people)
        before = self.overview.plans_of(actor, found)
        if dry_run:
            after = self.overview.plans_given(actor, found, plan)
        else:
            self._assign(actor, found, plan)
            after = self.overview.plans_of(actor, found)
        return tuple(PlanMove(user, before[user.id], after[user.id]) for user in found)

    def _people(self, people: Sequence[UserId]) -> list[User]:
        named = list(dict.fromkeys(people))
        require_assignable(len(named))
        found = [self.users.get(person) for person in named]
        known = [user for user in found if user is not None]
        if len(known) != len(named):
            raise unknown_people()
        return known

    def _assign(self, actor: UserId, people: Sequence[User], plan: PlanKey | None) -> None:
        change = AssignmentChange(AssignmentSource.ADMINISTRATOR, actor, self.clock.now())
        # Raises PlanNotFound; False when someone was deleted since they were read.
        if not self.assignments.assign_all([user.id for user in people], plan, change):
            raise unknown_people()
        logged = plan.value if plan is not None else None
        for user in people:
            logger.info("plan assigned user=%s plan=%s by=%s", user.id.value, logged, actor.value)


def unknown_people() -> InvalidAssignment:
    """The refusal for someone named who is not a User, or no longer is, such as a malformed
    identifier."""
    return InvalidAssignment(
        InvalidAssignmentReason.UNKNOWN_PEOPLE, "someone named is not a user here"
    )
