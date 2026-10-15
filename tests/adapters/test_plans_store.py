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
