"""Giving one Plan to many people at once, after a dry run that says who would be over
(ADR 0038, the catalog)."""

import logging
from collections.abc import Collection
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

import pytest

from calendar_sync.application.identity.administration import AdministratorRequired
from calendar_sync.application.identity.errors import PlanNotFound
from calendar_sync.application.identity.ports import AssignmentChange
from calendar_sync.application.operations.operator_overview import OperatorOverview, UserStatuses
from calendar_sync.application.operations.plan_assignment import AssignPlans, PlanMove
from calendar_sync.application.sync.locking import RuleLocks
from calendar_sync.domain.access import Role, User, UserId, UserState
from calendar_sync.domain.accounts import ConnectedAccountState
from calendar_sync.domain.model import ConnectedAccountId
from calendar_sync.domain.plans import (
    AllowanceBasis,
    AssignmentSource,
    InvalidAssignment,
    InvalidAssignmentReason,
    LimitedResource,
    OverLimit,
    PlanKey,
)
from calendar_sync.infrastructure.persistence.memory import InMemoryUnitOfWorkFactory
from tests.helpers import NOW
from tests.identity_fakes import MemoryPlans, MemoryUsers
from tests.plans import FAMILY, FREE, plans_on

LOGGER = "calendar_sync.application.operations.plan_assignment"
DAY = timedelta(days=1)
ADMIN = User(
    UserId("admin"), "admin@example.test", Role.INSTALLATION_ADMINISTRATOR, UserState.ACTIVE, NOW
)
ALICE = User(UserId("alice"), "alice@example.test", Role.USER, UserState.ACTIVE, NOW + DAY)
BOB = User(UserId("bob"), "bob@example.test", Role.USER, UserState.ACTIVE, NOW + 2 * DAY)
AWAY = User(UserId("away"), "away@example.test", Role.USER, UserState.DISABLED, NOW + 3 * DAY)
# Free allows 1 calendar account; Alice and the disabled person have 2, Bob 1.
ACCOUNTS = {ALICE: ("alice-1", "alice-2"), BOB: ("bob-1",), AWAY: ("away-1", "away-2")}
ACCOUNTS_OVER = OverLimit(LimitedResource.CONNECTED_ACCOUNTS, in_use=2, allowed=1)
GIVEN = AssignmentChange(AssignmentSource.ADMINISTRATOR, ADMIN.id, NOW)


class FixedClock:
    def now(self) -> datetime:
        return NOW


class DeletedMeanwhile(MemoryPlans):
    """Bob is deleted by another administrator between the check and the assignment."""

    def assign_all(
        self, users: Collection[UserId], plan: PlanKey | None, change: AssignmentChange
    ) -> bool:
        self.users.users.pop(BOB.id, None)
        return super().assign_all(users, plan, change)


@dataclass(frozen=True)
class Installation:
    users: MemoryUsers
    plans: MemoryPlans
    assign: AssignPlans

    def stored(self) -> tuple[object, ...]:
        """Every User and how their own Plan was last set, to show nothing changed."""
        return dict(self.users.users), dict(self.plans.changes)

    def own_plan(self, user: User) -> PlanKey | None:
        stored = self.users.get(user.id)
        assert stored is not None
        return stored.plan


def _installation(store: type[MemoryPlans] = MemoryPlans) -> Installation:
    """Plans on with Family as the default, which everyone has, and Free."""
    units = InMemoryUnitOfWorkFactory()
    users = MemoryUsers()
    for user in (ADMIN, ALICE, BOB, AWAY):
        users.add(user, "hash")
    for owner, accounts in ACCOUNTS.items():
        state = units.for_user(owner.id).state
        for account in accounts:
            state.accounts[ConnectedAccountId(account)] = ConnectedAccountState.CONNECTED
    plans = store(users=users)
    plans_on(plans, FAMILY, FREE)
    clock = FixedClock()
    overview = OperatorOverview(
        users,
        UserStatuses(units.installation(), RuleLocks(), clock, None),
        units.installation(),
        clock,
        plans,
        plans,
        plans,
    )
    return Installation(users, plans, AssignPlans(users, overview, plans, clock))


def _moves(moves: tuple[PlanMove, ...]) -> list[tuple[object, ...]]:
    """Who moved, from which Plan to which, and what they are over after."""
    return [
        (
            move.user.id,
            move.before.has,
            move.before.on_default,
            move.after.has,
            move.after.on_default,
            move.after.over,
        )
        for move in moves
    ]


def test_a_dry_run_says_what_each_person_would_have_and_be_over_and_gives_nothing() -> None:
    installation = _installation()
    before = installation.stored()

    moves = installation.assign.execute(
        ADMIN.id, [ALICE.id, BOB.id, ADMIN.id, AWAY.id], FREE.key, dry_run=True
    )

    # No Plan limits an administrator or a disabled person, so neither is ever over.
    assert _moves(moves) == [
        (ALICE.id, FAMILY, True, FREE, False, (ACCOUNTS_OVER,)),
        (BOB.id, FAMILY, True, FREE, False, ()),
        (ADMIN.id, FAMILY, True, FREE, False, ()),
        (AWAY.id, FAMILY, True, FREE, False, ()),
    ]
    assert installation.stored() == before


def test_giving_a_plan_moves_everyone_at_once_and_records_who_gave_it_and_when() -> None:
    installation = _installation()

    moves = installation.assign.execute(ADMIN.id, [ALICE.id, BOB.id], FREE.key)

    assert [installation.own_plan(user) for user in (ALICE, BOB)] == [FREE.key, FREE.key]
    assert installation.plans.changes == {ALICE.id: GIVEN, BOB.id: GIVEN}
    # The answer is read after the change, as People shows it now.
    assert _moves(moves) == [
        (ALICE.id, FAMILY, True, FREE, False, (ACCOUNTS_OVER,)),
        (BOB.id, FAMILY, True, FREE, False, ()),
    ]
    assert [(move.after.assigned_by, move.after.assigned_at) for move in moves] == [
        (ADMIN.email, NOW),
        (ADMIN.email, NOW),
    ]
    assert [move.after.allowance.basis for move in moves] == [AllowanceBasis.PLAN] * 2


@pytest.mark.parametrize("plan", [None, FAMILY.key], ids=["none", "the default"])
def test_none_or_the_default_returns_people_to_the_default_plan(plan: PlanKey | None) -> None:
    """Giving the default means following it, so they move with it when it changes."""
    installation = _installation()
    installation.assign.execute(ADMIN.id, [ALICE.id], FREE.key)

    planned = installation.assign.execute(ADMIN.id, [ALICE.id], plan, dry_run=True)
    moved = installation.assign.execute(ADMIN.id, [ALICE.id], plan)

    expected = [(ALICE.id, FREE, False, FAMILY, True, ())]
    assert _moves(planned) == expected
    assert _moves(moved) == expected
    assert installation.own_plan(ALICE) is None
    assert installation.plans.changes == {ALICE.id: GIVEN}


def test_while_plans_are_off_a_dry_run_still_says_who_would_be_over() -> None:
    installation = _installation()
    installation.plans.change_settings(False, FAMILY.key, NOW)

    (move,) = installation.assign.execute(ADMIN.id, [ALICE.id], FREE.key, dry_run=True)

    assert move.after.allowance.basis is AllowanceBasis.PLANS_OFF
    assert (move.after.has, move.after.over) == (FREE, (ACCOUNTS_OVER,))


@pytest.mark.parametrize("dry_run", [True, False], ids=["dry run", "assignment"])
@pytest.mark.parametrize("actor", [ALICE.id, UserId("nobody")], ids=["member", "unknown"])
def test_only_an_administrator_gives_plans(actor: UserId, dry_run: bool) -> None:
    installation = _installation()
    before = installation.stored()

    with pytest.raises(AdministratorRequired):
        installation.assign.execute(actor, [BOB.id], FREE.key, dry_run=dry_run)

    assert installation.stored() == before


@pytest.mark.parametrize("dry_run", [True, False], ids=["dry run", "assignment"])
@pytest.mark.parametrize(
    ("people", "reason"),
    [
        pytest.param([], InvalidAssignmentReason.NO_PEOPLE, id="nobody"),
        pytest.param(
            [UserId(f"user-{number}") for number in range(101)],
            InvalidAssignmentReason.TOO_MANY,
            id="more than a hundred",
        ),
        pytest.param(
            [ALICE.id, UserId("nobody")],
            InvalidAssignmentReason.UNKNOWN_PEOPLE,
            id="someone who is not a user",
        ),
    ],
)
def test_an_assignment_to_nobody_too_many_or_someone_unknown_moves_nobody(
    people: list[UserId], reason: InvalidAssignmentReason, dry_run: bool
) -> None:
    installation = _installation()
    before = installation.stored()

    with pytest.raises(InvalidAssignment) as refused:
        installation.assign.execute(ADMIN.id, people, FREE.key, dry_run=dry_run)

    assert refused.value.reason is reason
    assert installation.stored() == before


@pytest.mark.parametrize("dry_run", [True, False], ids=["dry run", "assignment"])
def test_a_plan_that_does_not_exist_moves_nobody(dry_run: bool) -> None:
    installation = _installation()
    before = installation.stored()

    with pytest.raises(PlanNotFound):
        installation.assign.execute(ADMIN.id, [ALICE.id], PlanKey("gold"), dry_run=dry_run)

    assert installation.stored() == before


def test_each_person_named_more_than_once_is_given_the_plan_once() -> None:
    installation = _installation()

    moves = installation.assign.execute(ADMIN.id, [BOB.id] * 150 + [ALICE.id, BOB.id], FREE.key)

    assert [move.user.id for move in moves] == [BOB.id, ALICE.id]


def test_someone_deleted_meanwhile_moves_nobody() -> None:
    installation = _installation(DeletedMeanwhile)

    with pytest.raises(InvalidAssignment) as refused:
        installation.assign.execute(ADMIN.id, [ALICE.id, BOB.id], FREE.key)

    assert refused.value.reason is InvalidAssignmentReason.UNKNOWN_PEOPLE
    assert installation.own_plan(ALICE) is None
    assert installation.plans.changes == {}


def test_each_person_given_a_plan_logs_one_line_naming_only_ids(
    caplog: pytest.LogCaptureFixture,
) -> None:
    installation = _installation()

    with caplog.at_level(logging.INFO, logger=LOGGER):
        installation.assign.execute(ADMIN.id, [ALICE.id, BOB.id], FREE.key, dry_run=True)
        installation.assign.execute(ADMIN.id, [ALICE.id, BOB.id], FREE.key)
        installation.assign.execute(ADMIN.id, [ALICE.id], None)

    # A dry run writes nothing, so it logs nothing.
    assert [record.getMessage() for record in caplog.records if record.name == LOGGER] == [
        "plan assigned user=alice plan=free by=admin",
        "plan assigned user=bob plan=free by=admin",
        "plan assigned user=alice plan=None by=admin",
    ]
    assert "example.test" not in caplog.text


def test_a_disabled_person_and_an_administrator_keep_what_they_were_given() -> None:
    """Their Plan is stored, and limits them once they are active and stop administering."""
    installation = _installation()

    installation.assign.execute(ADMIN.id, [ADMIN.id, AWAY.id], FREE.key)
    stored = installation.users.users
    stored[AWAY.id] = replace(stored[AWAY.id], state=UserState.ACTIVE)
    (away,) = installation.assign.execute(ADMIN.id, [AWAY.id], FREE.key, dry_run=True)

    assert [installation.own_plan(user) for user in (ADMIN, AWAY)] == [FREE.key, FREE.key]
    assert (away.before.has, away.before.on_default) == (FREE, False)
    assert away.after.over == (ACCOUNTS_OVER,)
