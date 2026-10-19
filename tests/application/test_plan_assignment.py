"""Giving many people each their own Plan at once, after a dry run that says who would be over
(ADR 0038, the catalog)."""

import logging
from collections.abc import Mapping
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
    Plan,
    PlanKey,
    PlanLimits,
    SyncInterval,
)
from calendar_sync.infrastructure.persistence.memory import InMemoryUnitOfWorkFactory
from tests.helpers import NOW
from tests.identity_fakes import MemoryPlans, MemoryUsers
from tests.plans import FAMILY, FREE, as_new, plans_on

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
PRO = Plan(PlanKey("pro"), "Pro", PlanLimits(10, 10, 10, SyncInterval.INSTANT))
UNDO = {ALICE.id: FREE.key, BOB.id: None}
"""What Undo sends once Alice, who had Free of her own, and Bob, who followed Family, have Pro."""


class FixedClock:
    def now(self) -> datetime:
        return NOW


class DeletedMeanwhile(MemoryPlans):
    """Bob is deleted by another administrator between the check and the assignment."""

    def assign_all(self, plans: Mapping[UserId, PlanKey | None], change: AssignmentChange) -> bool:
        self.users.users.pop(BOB.id, None)
        return super().assign_all(plans, change)


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
        ADMIN.id, dict.fromkeys([ALICE.id, BOB.id, ADMIN.id, AWAY.id], FREE.key), dry_run=True
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

    moves = installation.assign.execute(ADMIN.id, dict.fromkeys([ALICE.id, BOB.id], FREE.key))

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
    # Given a day earlier, so the record below can only be this assignment's.
    installation.plans.assign_all({ALICE.id: FREE.key}, replace(GIVEN, at=NOW - DAY))

    planned = installation.assign.execute(ADMIN.id, {ALICE.id: plan}, dry_run=True)
    moved = installation.assign.execute(ADMIN.id, {ALICE.id: plan})

    expected = [(ALICE.id, FREE, False, FAMILY, True, ())]
    assert _moves(planned) == expected
    assert _moves(moved) == expected
    assert installation.own_plan(ALICE) is None
    assert installation.plans.changes == {ALICE.id: GIVEN}


def test_while_plans_are_off_a_dry_run_still_says_who_would_be_over() -> None:
    installation = _installation()
    installation.plans.change_settings(False, FAMILY.key, NOW)

    (move,) = installation.assign.execute(ADMIN.id, {ALICE.id: FREE.key}, dry_run=True)

    assert move.after.allowance.basis is AllowanceBasis.PLANS_OFF
    assert (move.after.has, move.after.over) == (FREE, (ACCOUNTS_OVER,))


@pytest.mark.parametrize("dry_run", [True, False], ids=["dry run", "assignment"])
@pytest.mark.parametrize("actor", [ALICE.id, UserId("nobody")], ids=["member", "unknown"])
def test_only_an_administrator_gives_plans(actor: UserId, dry_run: bool) -> None:
    installation = _installation()
    before = installation.stored()

    with pytest.raises(AdministratorRequired):
        installation.assign.execute(actor, {BOB.id: FREE.key}, dry_run=dry_run)

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
        installation.assign.execute(ADMIN.id, dict.fromkeys(people, FREE.key), dry_run=dry_run)

    assert refused.value.reason is reason
    assert installation.stored() == before


@pytest.mark.parametrize("dry_run", [True, False], ids=["dry run", "assignment"])
def test_a_plan_that_does_not_exist_moves_nobody(dry_run: bool) -> None:
    installation = _installation()
    before = installation.stored()

    with pytest.raises(PlanNotFound):
        installation.assign.execute(ADMIN.id, {ALICE.id: PlanKey("gold")}, dry_run=dry_run)

    assert installation.stored() == before


def test_someone_deleted_meanwhile_moves_nobody() -> None:
    installation = _installation(DeletedMeanwhile)

    with pytest.raises(InvalidAssignment) as refused:
        installation.assign.execute(ADMIN.id, dict.fromkeys([ALICE.id, BOB.id], FREE.key))

    assert refused.value.reason is InvalidAssignmentReason.UNKNOWN_PEOPLE
    assert installation.own_plan(ALICE) is None
    assert installation.plans.changes == {}


def _both_given_pro(installation: Installation) -> None:
    """Alice had Free of her own and Bob followed Family, the default; a day ago both got Pro."""
    earlier = replace(GIVEN, at=NOW - DAY)
    installation.plans.add(as_new(PRO), NOW)
    installation.plans.assign_all({ALICE.id: FREE.key}, earlier)
    installation.plans.assign_all(dict.fromkeys([ALICE.id, BOB.id], PRO.key), earlier)


def test_undo_gives_each_person_back_the_plan_they_had_in_one_assignment() -> None:
    installation = _installation()
    _both_given_pro(installation)

    planned = installation.assign.execute(ADMIN.id, UNDO, dry_run=True)
    restored = installation.assign.execute(ADMIN.id, UNDO)

    expected = [
        (ALICE.id, PRO, False, FREE, False, (ACCOUNTS_OVER,)),
        (BOB.id, PRO, False, FAMILY, True, ()),
    ]
    assert _moves(planned) == expected
    assert _moves(restored) == expected
    assert [installation.own_plan(user) for user in (ALICE, BOB)] == [FREE.key, None]
    assert installation.plans.changes == {ALICE.id: GIVEN, BOB.id: GIVEN}


@pytest.mark.parametrize("dry_run", [True, False], ids=["dry run", "assignment"])
def test_an_undo_whose_plan_another_administrator_removed_restores_nobody(dry_run: bool) -> None:
    """Free was removed once nobody had it, so Bob stays on Pro too, though Family is there."""
    installation = _installation()
    _both_given_pro(installation)
    installation.plans.remove(FREE.key)
    before = installation.stored()

    # Bob, whose Plan is still there, comes first, so a write split by Plan would move him.
    with pytest.raises(PlanNotFound):
        installation.assign.execute(ADMIN.id, {BOB.id: None, ALICE.id: FREE.key}, dry_run=dry_run)

    assert installation.stored() == before
    assert [installation.own_plan(user) for user in (ALICE, BOB)] == [PRO.key, PRO.key]


def test_each_person_given_a_plan_logs_one_line_naming_only_ids(
    caplog: pytest.LogCaptureFixture,
) -> None:
    installation = _installation()

    with caplog.at_level(logging.INFO, logger=LOGGER):
        installation.assign.execute(
            ADMIN.id, dict.fromkeys([ALICE.id, BOB.id], FREE.key), dry_run=True
        )
        installation.assign.execute(ADMIN.id, dict.fromkeys([ALICE.id, BOB.id], FREE.key))
        installation.assign.execute(ADMIN.id, {ALICE.id: None})

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

    installation.assign.execute(ADMIN.id, dict.fromkeys([ADMIN.id, AWAY.id], FREE.key))
    stored = installation.users.users
    stored[AWAY.id] = replace(stored[AWAY.id], state=UserState.ACTIVE)
    (away,) = installation.assign.execute(ADMIN.id, {AWAY.id: FREE.key}, dry_run=True)

    assert [installation.own_plan(user) for user in (ADMIN, AWAY)] == [FREE.key, FREE.key]
    assert (away.before.has, away.before.on_default) == (FREE, False)
    assert away.after.over == (ACCOUNTS_OVER,)
