"""Users and failed sign-ins as the installation stores them."""

import sqlite3
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from calendar_sync.application.errors import EmailTaken
from calendar_sync.domain.access import RegistrationPolicy, Role, User, UserId, UserState
from calendar_sync.infrastructure.persistence.registration import (
    SqliteInvitations,
    SqlitePasswordResetLinks,
    SqliteRegistrationSettings,
)
from calendar_sync.infrastructure.persistence.sqlite import initialize_database
from calendar_sync.infrastructure.persistence.users import SqliteUserDirectory
from calendar_sync.infrastructure.throttle import MemorySignInThrottle
from tests.adapters.test_user_migration import (
    OWNED_TABLES,
    database_at_version,
    seed_single_administrator,
)

NOW = datetime(2026, 10, 9, 9, 0, tzinfo=UTC)
FIRST = User(
    UserId("first"), "first@example.test", Role.INSTALLATION_ADMINISTRATOR, UserState.ACTIVE, NOW
)
SECOND = User(
    UserId("second"), "second@example.test", Role.USER, UserState.ACTIVE, NOW + timedelta(1)
)


@dataclass
class MovableClock:
    moment: datetime

    def now(self) -> datetime:
        return self.moment


def _users(tmp_path: Path) -> SqliteUserDirectory:
    database = tmp_path / "test.db"
    initialize_database(database)
    return SqliteUserDirectory(database)


def test_only_the_first_user_is_added_as_the_first(tmp_path: Path) -> None:
    users = _users(tmp_path)

    assert users.add_first(FIRST, "hash-1")
    assert not users.add_first(SECOND, "hash-2")
    assert users.list() == (FIRST,)
    assert users.password_hash(FIRST.id) == "hash-1"


def test_users_are_found_by_id_and_email_and_keep_what_is_saved(tmp_path: Path) -> None:
    users = _users(tmp_path)
    users.add(FIRST, "hash-1")
    users.add(SECOND, "hash-2")
    changed = replace(SECOND, state=UserState.DISABLED, language="de", notify_by_email=False)

    users.save(changed)
    users.record_sign_in(SECOND.id, NOW)

    assert users.by_email("second@example.test") == replace(changed, last_sign_in_at=NOW)
    assert users.get(UserId("missing")) is None
    assert users.count() == 2
    assert [user.id for user in users.list()] == [FIRST.id, SECOND.id]


def test_one_email_signs_in_one_user_whatever_its_case(tmp_path: Path) -> None:
    users = _users(tmp_path)
    users.add(FIRST, "hash-1")

    with pytest.raises(EmailTaken):
        users.add(replace(SECOND, email="FIRST@example.test"), "hash-2")
    users.add(SECOND, "hash-2")
    with pytest.raises(EmailTaken):
        users.save(replace(SECOND, email="first@example.test"))
    assert users.get(SECOND.id) == SECOND


def test_only_a_user_without_an_email_is_found_as_one(tmp_path: Path) -> None:
    users = _users(tmp_path)
    users.add(FIRST, "hash-1")
    assert users.without_email() is None

    upgraded = replace(SECOND, email=None)
    users.add(upgraded, "hash-2")

    assert users.without_email() == upgraded


def test_an_email_once_added_cannot_be_removed(tmp_path: Path) -> None:
    users = _users(tmp_path)
    users.add(FIRST, "hash-1")

    with pytest.raises(Exception, match="keeps an email"):
        users.save(replace(FIRST, email=None))


def test_failed_sign_ins_for_one_email_wait_until_the_window_moves_on() -> None:
    clock = MovableClock(NOW)
    throttle = MemorySignInThrottle(clock, email_limit=2, client_limit=10)
    keys = ("email:first@example.test", "client:10.0.0.1")
    throttle.failed(keys)
    clock.moment = NOW + timedelta(minutes=5)
    throttle.failed(keys)

    assert throttle.wait(keys) == timedelta(minutes=10).total_seconds()
    assert throttle.wait(("email:second@example.test", "client:10.0.0.2")) == 0
    clock.moment = NOW + timedelta(minutes=15)
    assert throttle.wait(keys) == 0


def test_a_client_failing_for_many_emails_waits_and_a_success_forgets_only_the_email() -> None:
    clock = MovableClock(NOW)
    throttle = MemorySignInThrottle(clock, email_limit=2, client_limit=3)
    for number in range(3):
        throttle.failed((f"email:user-{number}@example.test", "client:10.0.0.1"))

    assert throttle.wait(("email:new@example.test", "client:10.0.0.1")) > 0
    throttle.succeeded(("email:user-0@example.test", "client:10.0.0.1"))
    assert throttle.wait(("email:user-0@example.test", "client:10.0.0.2")) == 0
    assert throttle.wait(("email:other@example.test", "client:10.0.0.1")) > 0


def _database(tmp_path: Path) -> Path:
    database = tmp_path / "test.db"
    initialize_database(database)
    return database


class SequentialIds:
    def __init__(self) -> None:
        self.issued = 0

    def new(self) -> str:
        self.issued += 1
        return f"link-{self.issued}"


def test_new_installations_start_with_only_me_and_keep_the_chosen_policy(tmp_path: Path) -> None:
    settings = SqliteRegistrationSettings(_database(tmp_path))
    assert settings.policy() is RegistrationPolicy.ONLY_ME

    settings.set_policy(RegistrationPolicy.INVITATION_ONLY)

    assert settings.policy() is RegistrationPolicy.INVITATION_ONLY


def test_an_invitation_adds_one_user_once_and_only_its_hash_is_stored(tmp_path: Path) -> None:
    database = _database(tmp_path)
    users = SqliteUserDirectory(database)
    users.add(FIRST, "hash-1")
    invitations = SqliteInvitations(database, SequentialIds())
    link = invitations.issue(FIRST.id, NOW)

    assert invitations.usable(link.token, NOW)
    with pytest.raises(EmailTaken):
        invitations.accept(link.token, replace(SECOND, email=FIRST.email), "hash-2", NOW)
    assert invitations.usable(link.token, NOW)
    assert invitations.accept(link.token, SECOND, "hash-2", NOW)
    third = replace(SECOND, id=UserId("third"), email="third@example.test")
    assert not invitations.accept(link.token, third, "hash-3", NOW)
    assert users.get(third.id) is None

    assert users.get(SECOND.id) == SECOND
    assert invitations.pending(NOW) == ()
    with sqlite3.connect(database) as connection:
        assert link.token not in repr(connection.execute("SELECT * FROM invitations").fetchall())


def test_invitations_expire_after_seven_days_and_can_be_revoked(tmp_path: Path) -> None:
    database = _database(tmp_path)
    SqliteUserDirectory(database).add(FIRST, "hash-1")
    invitations = SqliteInvitations(database, SequentialIds())
    first = invitations.issue(FIRST.id, NOW)
    second = invitations.issue(FIRST.id, NOW + timedelta(days=1))

    assert [pending.id for pending in invitations.pending(NOW + timedelta(days=7))] == [second.id]
    assert invitations.revoke(second.id, NOW + timedelta(days=2))
    assert not invitations.revoke(second.id, NOW + timedelta(days=2))
    assert not invitations.usable(second.token, NOW + timedelta(days=2))
    assert not invitations.revoke(first.id, NOW + timedelta(days=8))


def test_a_reset_link_sets_the_password_once_and_a_newer_one_replaces_it(tmp_path: Path) -> None:
    database = _database(tmp_path)
    users = SqliteUserDirectory(database)
    users.add(FIRST, "hash-1")
    links = SqlitePasswordResetLinks(database, SequentialIds())
    earlier = links.issue(FIRST.id, FIRST.id, NOW)
    later = links.issue(FIRST.id, FIRST.id, NOW)

    assert links.owner(earlier.token, NOW) is None
    assert links.reset(later.token, "new-hash", NOW) == FIRST.id
    assert links.reset(later.token, "newer-hash", NOW) is None
    assert users.password_hash(FIRST.id) == "new-hash"
    assert links.owner(links.issue(FIRST.id, FIRST.id, NOW).token, NOW + timedelta(days=7)) is None


def test_deleting_a_user_removes_every_record_they_own(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    database_at_version(database, 20)
    seed_single_administrator(database)
    initialize_database(database)
    users = SqliteUserDirectory(database)
    upgraded = users.list()[0]
    users.add(SECOND, "hash-2")

    users.delete(upgraded.id)

    with sqlite3.connect(database) as connection:
        for table in OWNED_TABLES:
            rows = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            assert rows == (0,), table
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert users.list() == (SECOND,)
