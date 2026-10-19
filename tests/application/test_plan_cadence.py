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
"""A `5_minutes` Plan's cadence: no Instant Sync, and a poll every five minutes."""
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
    plans.assign_all({MEMBER: FAMILY.key}, change)
    if not on:
        plans.change_settings(False, FREE.key, NOW)
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

    # A User the batch leaves out gets the default cadence, which is instant.
    assert cadences_of(policy, [MEMBER, OTHER]) == {MEMBER: DEFAULT_CADENCE, OTHER: DEFAULT_CADENCE}
    assert policy.read_alone == []


def test_cadences_of_reads_each_user_alone_when_the_batch_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    policy = Unsteady(unreadable=frozenset({MEMBER}))

    with caplog.at_level("WARNING", logger=LOGGER):
        cadences = cadences_of(policy, [MEMBER, OTHER])

    assert cadences == {MEMBER: DEFAULT_CADENCE, OTHER: SCHEDULED_ONLY}
    assert policy.read_alone == [MEMBER, OTHER]
    # Only the error's class: its text could quote the database's own words.
    assert "RuntimeError" in caplog.text
    assert "database is locked" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_with_plans_unreadable_every_user_gets_the_default_cadence() -> None:
    assert cadences_of(PlanCadence(BrokenAllowances()), [MEMBER, OTHER]) == {
        MEMBER: DEFAULT_CADENCE,
        OTHER: DEFAULT_CADENCE,
    }


def test_with_plans_off_everyone_may_sync_instantly_in_one_read() -> None:
    assert cadences_of(EveryUserInstant(), [MEMBER, OTHER]) == {
        MEMBER: DEFAULT_CADENCE,
        OTHER: DEFAULT_CADENCE,
    }
