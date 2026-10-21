"""Migration 38 preserves settings and makes Open an administrator's atomic choice."""

from dataclasses import replace
from itertools import product
from pathlib import Path

import pytest

from calendar_sync.application.identity.administration import AdministratorRequired
from calendar_sync.application.identity.identity_email import IdentityEmailSetup
from calendar_sync.application.identity.registration_ports import (
    OpenRegistrationUnavailable,
    RegistrationStorageUnavailable,
)
from calendar_sync.domain.access import RegistrationPolicy, UserState
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.persistence.migrations import MigrationFailed, initialize_database
from calendar_sync.infrastructure.persistence.registration import SqliteRegistrationSettings
from calendar_sync.infrastructure.persistence.registration_readiness import (
    SqliteRegistrationReadiness,
)
from calendar_sync.infrastructure.persistence.users import SqliteUserDirectory
from tests.adapters.test_user_migration import database_at_version
from tests.adapters.test_users_store import FIRST, NOW, MovableClock


@pytest.mark.parametrize(
    ("policy", "plans", "default"),
    product(("only_me", "invitation_only"), (0, 1), (None, "family")),
)
def test_fresh_upgrade_restart_preserves_settings_and_users(
    tmp_path: Path, policy: str, plans: int, default: str | None
) -> None:
    database = tmp_path / "upgrade.db"
    database_at_version(database, 37)
    SqliteUserDirectory(database).add(FIRST, "retained-hash")
    with transaction(database) as connection:
        connection.execute(
            "INSERT INTO plans (key, name, sync_interval, created_at, updated_at) "
            "VALUES ('family', 'Family', 'instant', ?, ?)",
            (NOW.isoformat(), NOW.isoformat()),
        )
        connection.execute(
            "UPDATE installation_settings SET registration_policy = ?, "
            "plans_enabled = ?, default_plan_key = ?",
            (policy, plans, default),
        )
    initialize_database(database)
    initialize_database(database)
    assert SqliteUserDirectory(database).get(FIRST.id) == FIRST
    assert SqliteUserDirectory(database).password_hash(FIRST.id) == "retained-hash"
    with transaction(database) as connection:
        assert tuple(connection.execute("SELECT * FROM installation_settings").fetchone()) == (
            1,
            policy,
            plans,
            default,
        )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        foreign_key = connection.execute(
            "PRAGMA foreign_key_list(installation_settings)"
        ).fetchone()
        assert foreign_key[2] == "plans"
        assert foreign_key[3] == "default_plan_key"
    fresh = tmp_path / "fresh.db"
    initialize_database(fresh)
    assert (
        SqliteRegistrationSettings(fresh, MovableClock(NOW)).policy() is RegistrationPolicy.ONLY_ME
    )


def test_migration_failure_is_atomic(tmp_path: Path) -> None:
    database = tmp_path / "broken.db"
    database_at_version(database, 37)
    with transaction(database) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("UPDATE installation_settings SET default_plan_key = 'absent'")
    with pytest.raises(MigrationFailed):
        initialize_database(database)
    with transaction(database) as connection:
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 37
        assert (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE name = 'registration_proofs'"
            ).fetchone()
            is None
        )
        assert (
            "'open'"
            not in connection.execute(
                "SELECT sql FROM sqlite_master WHERE name = 'installation_settings'"
            ).fetchone()[0]
        )
        assert (
            connection.execute("SELECT default_plan_key FROM installation_settings").fetchone()[0]
            == "absent"
        )
    with transaction(database) as connection:
        connection.execute("UPDATE installation_settings SET default_plan_key = NULL")
    initialize_database(database)


def test_open_readiness_and_authority_checked_with_policy_write(tmp_path: Path) -> None:
    database = tmp_path / "settings.db"
    initialize_database(database)
    users = SqliteUserDirectory(database)
    users.add(FIRST, "hash")
    settings = SqliteRegistrationSettings(database, MovableClock(NOW))
    for fingerprint, reason in (
        (None, "identity_email_not_configured"),
        ("current", "identity_email_not_tested"),
    ):
        with pytest.raises(OpenRegistrationUnavailable) as error:
            settings.set_policy(RegistrationPolicy.OPEN, actor=FIRST.id, fingerprint=fingerprint)
        assert error.value.reason == reason
        assert settings.policy() is RegistrationPolicy.ONLY_ME
    with transaction(database) as connection:
        connection.execute(
            "UPDATE identity_email_readiness SET fingerprint = 'current', tested_at = ?",
            (NOW.isoformat(),),
        )
    readiness = SqliteRegistrationReadiness(database, IdentityEmailSetup("current", None))
    assert readiness.status().available
    assert not readiness.public_available()
    settings.set_policy(RegistrationPolicy.OPEN, actor=FIRST.id, fingerprint="current")
    assert readiness.public_available()
    users.add(replace(FIRST, id=type(FIRST.id)("other"), email="other@example.test"), "hash")
    users.set_state(FIRST.id, UserState.DISABLED)
    with pytest.raises(AdministratorRequired):
        settings.set_policy(RegistrationPolicy.INVITATION_ONLY, actor=FIRST.id, fingerprint=None)
    assert settings.policy() is RegistrationPolicy.OPEN
    with transaction(database) as connection:
        connection.execute("DROP TABLE identity_email_readiness")
    assert not readiness.public_available()
    with pytest.raises(RegistrationStorageUnavailable):
        readiness.status()
    unconfigured = SqliteRegistrationReadiness(database, IdentityEmailSetup(None, None))
    with pytest.raises(RegistrationStorageUnavailable):
        unconfigured.status()
