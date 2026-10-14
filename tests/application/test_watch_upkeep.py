"""Watch upkeep across Users: who may have watches, in what order, within one call budget."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import TracebackType
from typing import Self, cast

import pytest

from calendar_sync.application.operations.instant_sync import UPKEEP_BUDGET, WatchUpkeep
from calendar_sync.application.operations.ports import (
    InstallationUnitOfWorkFactory,
    InstantSyncOwner,
)
from calendar_sync.application.sync.instant_sync import CallBudget, UpkeepWatches
from calendar_sync.domain.access import UserId
from calendar_sync.domain.cadence import SCHEDULED_EVERY, SyncCadence
from tests.fake_calendar import FixedClock
from tests.helpers import NOW
from tests.users import OTHER_USER, USER

ADDRESS = "https://ghost.example.test"
THIRD_USER = UserId("user-3")

Visit = tuple[UserId, bool, str | None]


class Owners:
    """The installation-wide unit of work, as far as watch upkeep reads it."""

    def __init__(self, *owners: InstantSyncOwner) -> None:
        self.owners = list(owners)

    def __call__(self) -> Self:
        return self

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def commit(self) -> None:
        return None

    def instant_sync_owners(self) -> tuple[InstantSyncOwner, ...]:
        return tuple(self.owners)


class Cadences:
    """Each User's Sync Cadence; Users named here have no Instant Sync in their Plan."""

    def __init__(self, *scheduled_only: UserId) -> None:
        self.scheduled_only = set(scheduled_only)

    def cadence(self, user: UserId) -> SyncCadence:
        return SyncCadence(instant=user not in self.scheduled_only, poll_every=SCHEDULED_EVERY)


class Upkeep:
    """One User's watch upkeep: it records each visit and spends `cost` provider calls."""

    def __init__(self, user: UserId, visits: list[Visit], cost: int, failing: bool) -> None:
        self.user, self.visits, self.cost, self.failing = user, visits, cost, failing

    def execute(self, *, allowed: bool, address: str | None, budget: CallBudget) -> None:
        self.visits.append((self.user, allowed, address))
        if self.failing:
            raise RuntimeError("synthetic provider outage")
        budget.spend(self.cost)


def _owner(
    user: UserId,
    *,
    wanted: bool = True,
    disabled: bool = False,
    next_due: datetime | None = None,
) -> InstantSyncOwner:
    return InstantSyncOwner(user=user, wanted=wanted, disabled=disabled, next_due=next_due)


def _upkeep(
    owners: Owners,
    visits: list[Visit],
    *,
    cost: int = 0,
    failing: frozenset[UserId] = frozenset(),
    missing: frozenset[UserId] = frozenset(),
    cadence: Cadences | None = None,
    address: str | None = ADDRESS,
) -> WatchUpkeep:
    def upkeep_for(user: UserId) -> UpkeepWatches | None:
        if user in missing:
            return None
        return cast(UpkeepWatches, Upkeep(user, visits, cost, user in failing))

    return WatchUpkeep(
        cast(InstallationUnitOfWorkFactory, owners),
        upkeep_for,
        cadence or Cadences(),
        address,
        FixedClock(),
    )


@pytest.mark.parametrize(
    ("owner", "cadence", "address", "allowed"),
    [
        (_owner(USER), Cadences(), ADDRESS, True),
        (_owner(USER), Cadences(), None, False),
        (_owner(USER, disabled=True), Cadences(), ADDRESS, False),
        (_owner(USER, wanted=False), Cadences(), ADDRESS, False),
        (_owner(USER), Cadences(USER), ADDRESS, False),
    ],
    ids=["allowed", "no public address", "disabled", "turned off", "not in plan"],
)
def test_a_user_may_have_watches_only_when_everything_allows_instant_sync(
    owner: InstantSyncOwner, cadence: Cadences, address: str | None, allowed: bool
) -> None:
    visits: list[Visit] = []

    _upkeep(Owners(owner), visits, cadence=cadence, address=address).run()

    # A User who may not have watches is still visited, so the watches they have stop.
    assert visits == [(USER, allowed, address)]


def test_a_cycle_goes_by_due_work_and_the_next_resumes_where_the_budget_ran_out() -> None:
    owners = Owners(
        # A User with nothing planned yet is missing coverage, so goes first.
        _owner(USER, next_due=None),
        _owner(OTHER_USER, next_due=NOW - timedelta(hours=1)),
        _owner(THIRD_USER, next_due=NOW + timedelta(hours=1)),
    )
    visits: list[Visit] = []
    upkeep = _upkeep(owners, visits, cost=2)
    cycles = []

    for _ in range(3):
        visits.clear()
        upkeep.run(budget=3)
        cycles.append([user for user, _, _ in visits])

    # The Users a cycle never reached go first in the next, then the User it stopped on.
    assert cycles == [[USER, OTHER_USER], [THIRD_USER, OTHER_USER], [USER, OTHER_USER]]


def test_two_users_with_large_backlogs_take_turns() -> None:
    visits: list[Visit] = []
    # Each User alone could spend a whole cycle's budget.
    upkeep = _upkeep(Owners(_owner(USER), _owner(OTHER_USER)), visits, cost=5)
    cycles = []

    for _ in range(4):
        visits.clear()
        upkeep.run(budget=3)
        cycles.append([user for user, _, _ in visits])

    assert cycles == [[USER], [OTHER_USER], [USER], [OTHER_USER]]


def test_a_cycle_with_budget_to_spare_visits_every_user() -> None:
    owners = Owners(_owner(USER), _owner(OTHER_USER), _owner(THIRD_USER))
    visits: list[Visit] = []

    _upkeep(owners, visits, cost=2).run()

    assert UPKEEP_BUDGET == 200
    assert [user for user, _, _ in visits] == [USER, OTHER_USER, THIRD_USER]


def test_one_users_failing_upkeep_holds_up_nobody_else(caplog: pytest.LogCaptureFixture) -> None:
    visits: list[Visit] = []
    owners = Owners(_owner(USER), _owner(OTHER_USER))

    with caplog.at_level("ERROR", logger="calendar_sync.application.operations.instant_sync"):
        _upkeep(owners, visits, failing=frozenset({USER})).run()

    assert [user for user, _, _ in visits] == [USER, OTHER_USER]
    assert "Upkeep of a User's watches failed; trying again next cycle" in caplog.text
    assert USER.value not in caplog.text


def test_users_no_provider_can_watch_for_are_skipped() -> None:
    visits: list[Visit] = []

    _upkeep(Owners(_owner(USER), _owner(OTHER_USER)), visits, missing=frozenset({USER})).run()

    assert visits == [(OTHER_USER, True, ADDRESS)]
