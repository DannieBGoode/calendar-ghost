"""Identity email readiness is installation-wide and admission is atomic."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from calendar_sync.application.identity.administration import AdministratorRequired
from calendar_sync.application.identity.identity_email import (
    EmailTest,
    IdentityEmailStorageUnavailable,
    IdentityEmailTestThrottled,
)
from calendar_sync.domain.access import OnlyMeNeedsOneUser, Role, UserId, UserState
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.persistence.identity_email import SqliteIdentityEmailTests
from calendar_sync.infrastructure.persistence.migrations import initialize_database
from calendar_sync.infrastructure.persistence.registration import SqliteRegistrationSettings
from calendar_sync.infrastructure.persistence.users import SqliteUserDirectory
from tests.adapters.test_users_store import FIRST, NOW, SECOND
from tests.identity_email_fakes import MemoryIdentityEmailTests


class RandomIds:
    def new(self) -> str:
        return str(uuid4())


def store(tmp_path: Path) -> tuple[Path, SqliteIdentityEmailTests]:
    database = tmp_path / "identity.db"
    initialize_database(database)
    SqliteUserDirectory(database).add(FIRST, "synthetic")
    return database, SqliteIdentityEmailTests(database, RandomIds())


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
def test_identity_test_port_contract(tmp_path: Path, kind: str) -> None:
    _, sqlite_tests = store(tmp_path)
    tests = sqlite_tests if kind == "sqlite" else MemoryIdentityEmailTests({FIRST.id: FIRST})
    assert tests.tested_at("current") is None
    test = tests.admit(FIRST.id, "current", NOW)
    assert tests.record_success(test, FIRST.email or "", NOW)
    assert tests.tested_at("current") == NOW
    assert tests.tested_at("other") is None


def test_test_allowance_is_atomic_and_persists_restart(tmp_path: Path) -> None:
    database, tests = store(tmp_path)
    with ThreadPoolExecutor(max_workers=3) as pool:
        admitted = list(pool.map(lambda _: tests.admit(FIRST.id, "f", NOW), range(3)))
    assert len({test.id for test in admitted}) == 3
    reopened = SqliteIdentityEmailTests(database, RandomIds())
    with pytest.raises(IdentityEmailTestThrottled) as error:
        reopened.admit(FIRST.id, "f", NOW)
    assert error.value.retry_after == 3600
    other = replace(SECOND, role=Role.INSTALLATION_ADMINISTRATOR)
    SqliteUserDirectory(database).add(other, "synthetic")
    assert reopened.admit(other.id, "f", NOW)
    assert tests.admit(FIRST.id, "f", NOW + timedelta(hours=1))


def test_attempts_are_not_refunded_by_failed_delivery_or_setup_reset(tmp_path: Path) -> None:
    database, tests = store(tmp_path)
    for _ in range(3):
        tests.admit(FIRST.id, "f", NOW)
    SqliteRegistrationSettings(database).return_to_setup(NOW)
    with pytest.raises(IdentityEmailTestThrottled):
        tests.admit(FIRST.id, "f", NOW)


def test_clock_rollback_does_not_refund_future_attempts(tmp_path: Path) -> None:
    _, tests = store(tmp_path)
    for _ in range(3):
        tests.admit(FIRST.id, "f", NOW + timedelta(hours=1))
    with pytest.raises(IdentityEmailTestThrottled) as error:
        tests.admit(FIRST.id, "f", NOW)
    assert error.value.retry_after == 7200


def test_setup_reset_rejects_inflight_success(tmp_path: Path) -> None:
    database, tests = store(tmp_path)
    test = tests.admit(FIRST.id, "f", NOW)
    SqliteRegistrationSettings(database).return_to_setup(NOW)
    assert not tests.record_success(test, FIRST.email or "", NOW)
    assert tests.tested_at("f") is None


def test_refused_setup_reset_preserves_readiness(tmp_path: Path) -> None:
    database, tests = store(tmp_path)
    test = tests.admit(FIRST.id, "f", NOW)
    assert tests.record_success(test, FIRST.email or "", NOW)
    SqliteUserDirectory(database).add(SECOND, "synthetic")
    with pytest.raises(OnlyMeNeedsOneUser):
        SqliteRegistrationSettings(database).return_to_setup(NOW)
    assert tests.record_success(test, FIRST.email or "", NOW)
    assert tests.tested_at("f") == NOW


@pytest.mark.parametrize("change", ["email", "role", "state", "delete", "attempt", "actor"])
def test_record_success_rechecks_recipient_role_state_and_attempt(
    tmp_path: Path, change: str
) -> None:
    database, tests = store(tmp_path)
    test = tests.admit(FIRST.id, "f", NOW)
    with transaction(database) as connection:
        if change == "email":
            connection.execute("UPDATE users SET email = 'new@example.test'")
        elif change == "role":
            connection.execute("UPDATE users SET role = 'user'")
        elif change == "state":
            connection.execute("UPDATE users SET state = 'disabled'")
        elif change == "delete":
            connection.execute("DELETE FROM users")
        elif change == "attempt":
            test = replace(test, id="missing")
        else:
            test = replace(test, actor=UserId("missing"))
    assert not tests.record_success(test, FIRST.email or "", NOW)
    assert tests.tested_at("f") is None


@pytest.mark.parametrize("change", ["email", "role", "state", "delete"])
def test_ineligible_actors_cannot_admit(tmp_path: Path, change: str) -> None:
    database, tests = store(tmp_path)
    with transaction(database) as connection:
        if change == "email":
            connection.execute("DELETE FROM users")
            connection.execute(
                "INSERT INTO users(id, email, role, state, created_at, password_hash) "
                "VALUES (?, NULL, ?, ?, ?, ?)",
                (FIRST.id.value, FIRST.role.value, FIRST.state.value, NOW.isoformat(), "synthetic"),
            )
        elif change == "role":
            connection.execute("UPDATE users SET role = 'user'")
        elif change == "state":
            connection.execute("UPDATE users SET state = 'disabled'")
        else:
            connection.execute("DELETE FROM users")
    with pytest.raises(AdministratorRequired):
        tests.admit(FIRST.id, "f", NOW)


def test_identity_store_fails_closed_on_lock_and_storage_fault(tmp_path: Path) -> None:
    database, tests = store(tmp_path)
    with transaction(database) as connection:
        connection.execute("BEGIN IMMEDIATE")
        with pytest.raises(IdentityEmailStorageUnavailable):
            tests.admit(FIRST.id, "f", NOW)
    with transaction(database) as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM identity_email_test_attempts").fetchone()[0]
            == 0
        )
        connection.execute("DROP TABLE identity_email_readiness")
    with pytest.raises(IdentityEmailStorageUnavailable):
        tests.tested_at("f")


def test_identity_attempt_purge_is_bounded(tmp_path: Path) -> None:
    database, tests = store(tmp_path)
    for _ in range(3):
        tests.admit(FIRST.id, "f", NOW)
    assert tests.purge(NOW, 2) == 0
    with transaction(database) as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM identity_email_test_attempts").fetchone()[0]
            == 3
        )
    assert tests.purge(NOW + timedelta(seconds=1), 2) == 2
    with transaction(database) as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM identity_email_test_attempts").fetchone()[0]
            == 1
        )


def test_records_do_not_reveal_recipient() -> None:
    from calendar_sync.application.identity.identity_email import PreparedEmailTest

    prepared = PreparedEmailTest(EmailTest("id", FIRST.id, 0, "f"), "private@example.test")
    assert "private" not in repr(prepared)


@pytest.mark.parametrize("version", [0, 34])
def test_identity_email_migration_fresh_upgrade_and_restart(tmp_path: Path, version: int) -> None:
    from tests.adapters.test_user_migration import database_at_version

    database = tmp_path / "migration.db"
    if version:
        database_at_version(database, version)
    initialize_database(database)
    initialize_database(database)
    with transaction(database) as connection:
        assert tuple(connection.execute("SELECT * FROM identity_email_readiness").fetchone()) == (
            1,
            None,
            None,
            0,
        )
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 35


def test_identity_email_migration_rolls_back_on_fault(tmp_path: Path) -> None:
    import sqlite3
    from unittest.mock import patch

    from calendar_sync.infrastructure.persistence import migrations
    from tests.adapters.test_user_migration import database_at_version

    database = tmp_path / "migration.db"
    database_at_version(database, 34)
    from importlib.resources import files

    real_files = files

    class BrokenMigration:
        def joinpath(self, name: str) -> object:
            resource = real_files("calendar_sync.infrastructure.persistence").joinpath(name)
            if name == "0035_identity_email.sql":

                class BrokenScript:
                    def read_text(self) -> str:
                        return resource.read_text() + "\nINSERT INTO nonexistent VALUES (1);"

                return BrokenScript()
            return resource

    with (
        patch.object(migrations, "files", return_value=BrokenMigration()),
        pytest.raises(sqlite3.OperationalError),
    ):
        initialize_database(database)
    with transaction(database) as connection:
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 34
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE name = 'identity_email_readiness'"
            ).fetchone()
            is None
        )
    initialize_database(database)


def test_identity_email_schema_constraints_and_user_cascade(tmp_path: Path) -> None:
    import sqlite3

    database, tests = store(tmp_path)
    tests.admit(FIRST.id, "f", NOW)
    for statement in (
        "UPDATE identity_email_readiness SET fingerprint = 'unpaired'",
        "UPDATE identity_email_readiness SET generation = -1",
        "INSERT INTO identity_email_readiness(singleton) VALUES (2)",
        "INSERT INTO identity_email_test_attempts VALUES ('unknown', 'unknown', 'now')",
    ):
        with pytest.raises(sqlite3.IntegrityError), transaction(database) as connection:
            connection.execute(statement)
    with transaction(database) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(identity_email_test_attempts)")
        }
        assert columns == {"id", "user_id", "admitted_at"}
        connection.execute("DELETE FROM users")
        assert (
            connection.execute("SELECT COUNT(*) FROM identity_email_test_attempts").fetchone()[0]
            == 0
        )


def test_existing_readiness_survives_unrelated_user_changes(tmp_path: Path) -> None:
    database, tests = store(tmp_path)
    test = tests.admit(FIRST.id, "f", NOW)
    assert tests.record_success(test, FIRST.email or "", NOW)
    with transaction(database) as connection:
        connection.execute("UPDATE users SET email = 'changed@example.test', role = 'user'")
    assert tests.tested_at("f") == NOW


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
@pytest.mark.parametrize("change", ["email", "role", "state", "missing"])
def test_port_refuses_ineligible_actors(tmp_path: Path, kind: str, change: str) -> None:

    database, sqlite_tests = store(tmp_path)
    users = {FIRST.id: FIRST}
    tests = sqlite_tests if kind == "sqlite" else MemoryIdentityEmailTests(users)
    test = tests.admit(FIRST.id, "f", NOW)
    changed = {
        "email": replace(FIRST, email=None),
        "role": replace(FIRST, role=Role.USER),
        "state": replace(FIRST, state=UserState.DISABLED),
        "missing": None,
    }[change]
    if changed:
        users[FIRST.id] = changed
    else:
        del users[FIRST.id]
    with transaction(database) as connection:
        # Replace rather than update: migrated administrators alone may have no email.
        connection.execute("DELETE FROM users")
    if changed:
        SqliteUserDirectory(database).add(changed, "synthetic")
    with pytest.raises(AdministratorRequired):
        tests.admit(FIRST.id, "f", NOW)
    assert not tests.record_success(test, FIRST.email or "", NOW)


def test_locked_success_and_purge_preserve_state(tmp_path: Path) -> None:
    database, tests = store(tmp_path)
    test = tests.admit(FIRST.id, "f", NOW)
    with transaction(database) as connection:
        connection.execute("BEGIN IMMEDIATE")
        with pytest.raises(IdentityEmailStorageUnavailable):
            tests.record_success(test, FIRST.email or "", NOW)
        with pytest.raises(IdentityEmailStorageUnavailable):
            tests.purge(NOW + timedelta(seconds=1), 1)
    assert tests.tested_at("f") is None
    assert tests.record_success(test, FIRST.email or "", NOW)


def test_missing_readiness_row_is_a_storage_failure(tmp_path: Path) -> None:
    database, tests = store(tmp_path)
    with transaction(database) as connection:
        connection.execute("DELETE FROM identity_email_readiness")
    with pytest.raises(IdentityEmailStorageUnavailable):
        tests.tested_at("f")
    with pytest.raises(IdentityEmailStorageUnavailable):
        tests.admit(FIRST.id, "f", NOW)


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
def test_identity_email_purge_returns_deleted_count(tmp_path: Path, kind: str) -> None:
    _, sqlite_tests = store(tmp_path)
    tests = sqlite_tests if kind == "sqlite" else MemoryIdentityEmailTests({FIRST.id: FIRST})
    for _ in range(3):
        tests.admit(FIRST.id, "f", NOW)
    assert tests.purge(NOW, 500) == 0
    assert tests.purge(NOW + timedelta(seconds=1), 2) == 2
    assert tests.purge(NOW + timedelta(seconds=1), 2) == 1
    assert tests.purge(NOW + timedelta(seconds=1), 2) == 0
    assert tests.purge(NOW + timedelta(seconds=1), 0) == 0


def test_another_active_administrator_cannot_complete_an_actors_attempt(tmp_path: Path) -> None:
    database, tests = store(tmp_path)
    users = SqliteUserDirectory(database)
    users.add(SECOND, "synthetic")
    test = tests.admit(FIRST.id, "f", NOW)
    assert not tests.record_success(replace(test, actor=SECOND.id), SECOND.email or "", NOW)
    assert tests.tested_at("f") is None
