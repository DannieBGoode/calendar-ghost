"""Users and failed sign-ins as the installation stores them."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from calendar_sync.application.errors import EmailTaken
from calendar_sync.domain.access import Role, User, UserId, UserState
from calendar_sync.infrastructure.persistence.sqlite import initialize_database
from calendar_sync.infrastructure.persistence.users import SqliteUserDirectory
from calendar_sync.infrastructure.throttle import MemorySignInThrottle

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
