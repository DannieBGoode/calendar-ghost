"""Users and failed sign-ins as the installation stores them."""

import sqlite3
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from calendar_sync.application.errors import EmailTaken
from calendar_sync.application.ports import IssuedLink, UserPage, UserQuery, UserSort
from calendar_sync.domain.access import (
    LastAdministrator,
    OnlyMeNeedsOneUser,
    RegistrationPolicy,
    Role,
    User,
    UserId,
    UserState,
)
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
from tests.identity_fakes import MemoryUsers

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


def test_users_are_searched_filtered_sorted_and_paged(tmp_path: Path) -> None:
    users = _users(tmp_path)
    people = [
        FIRST,
        SECOND,
        User(
            UserId("third"),
            "robin@example.test",
            Role.USER,
            UserState.DISABLED,
            NOW + timedelta(2),
            NOW + timedelta(5),
        ),
        User(
            UserId("fourth"),
            "dana@home.test",
            Role.USER,
            UserState.ACTIVE,
            NOW + timedelta(3),
            NOW + timedelta(4),
        ),
        User(
            UserId("fifth"),
            "under_score@example.test",
            Role.USER,
            UserState.ACTIVE,
            NOW + timedelta(4),
        ),
    ]
    for number, person in enumerate(people):
        users.add(person, f"hash-{number}")
        if person.last_sign_in_at is not None:
            users.record_sign_in(person.id, person.last_sign_in_at)

    def emails(query: UserQuery) -> list[str | None]:
        return [user.email for user in users.find(query).users]

    assert users.find(UserQuery(limit=2)) == UserPage((FIRST, SECOND), total=5)
    assert users.find(UserQuery(search="robin")).users == (people[2],)
    assert emails(UserQuery(offset=4)) == ["under_score@example.test"]
    assert emails(UserQuery(search="EXAMPLE")) == [
        "first@example.test",
        "second@example.test",
        "robin@example.test",
        "under_score@example.test",
    ]
    assert emails(UserQuery(search="_")) == ["under_score@example.test"]
    assert emails(UserQuery(role=Role.INSTALLATION_ADMINISTRATOR)) == ["first@example.test"]
    assert emails(UserQuery(state=UserState.DISABLED)) == ["robin@example.test"]
    assert emails(UserQuery(sort=UserSort.EMAIL, descending=True, limit=2)) == [
        "under_score@example.test",
        "second@example.test",
    ]
    # People who never signed in come last, whichever way the list is sorted.
    assert emails(UserQuery(sort=UserSort.LAST_SIGN_IN, descending=True))[:2] == [
        "robin@example.test",
        "dana@home.test",
    ]
    assert emails(UserQuery(sort=UserSort.LAST_SIGN_IN))[-1] == "under_score@example.test"
    assert users.find(UserQuery(search="nobody")) == UserPage((), total=0)


def test_users_are_found_by_id_and_email_and_keep_what_is_saved(tmp_path: Path) -> None:
    users = _users(tmp_path)
    users.add(FIRST, "hash-1")
    users.add(SECOND, "hash-2")
    changed = replace(SECOND, state=UserState.DISABLED, notify_by_email=False)

    users.set_state(SECOND.id, UserState.DISABLED)
    users.set_notification_email(SECOND.id, False)
    users.record_sign_in(SECOND.id, NOW)

    assert users.by_email("second@example.test") == replace(changed, last_sign_in_at=NOW)
    assert users.get(UserId("missing")) is None
    assert users.count() == 2
    assert [user.id for user in users.list()] == [FIRST.id, SECOND.id]


def test_a_users_email_and_incident_emails_change_without_touching_role_or_state(
    tmp_path: Path,
) -> None:
    users = _users(tmp_path)
    users.add(FIRST, "hash-1")
    users.add(replace(SECOND, role=Role.INSTALLATION_ADMINISTRATOR), "hash-2")
    # An Installation Administrator demotes the User after the Web UI read them.
    with sqlite3.connect(tmp_path / "test.db") as connection:
        connection.execute("UPDATE users SET role = 'user' WHERE id = ?", (SECOND.id.value,))

    users.set_email(SECOND.id, "renamed@example.test")
    users.set_notification_email(SECOND.id, False)

    assert users.get(SECOND.id) == replace(
        SECOND, email="renamed@example.test", notify_by_email=False
    )
    with pytest.raises(EmailTaken):
        users.set_email(SECOND.id, "first@example.test")


@pytest.fixture(params=["sqlite", "memory"])
def directory(request: pytest.FixtureRequest, tmp_path: Path) -> SqliteUserDirectory | MemoryUsers:
    """Both User Directories, so the application tests' stand-in keeps SQLite's rules."""
    return _users(tmp_path) if request.param == "sqlite" else MemoryUsers()


OTHER_ADMIN = replace(SECOND, role=Role.INSTALLATION_ADMINISTRATOR)


def test_two_administrators_demoting_each_other_at_once_leave_one(
    directory: SqliteUserDirectory | MemoryUsers,
) -> None:
    directory.add(FIRST, "hash-1")
    directory.add(OTHER_ADMIN, "hash-2")

    # Each passed the use case's check while the other still administered; the second write
    # is checked again in the same transaction and refused.
    directory.set_role(FIRST.id, Role.USER)
    with pytest.raises(LastAdministrator):
        directory.set_role(OTHER_ADMIN.id, Role.USER)
    with pytest.raises(LastAdministrator):
        directory.set_state(OTHER_ADMIN.id, UserState.DISABLED)
    with pytest.raises(LastAdministrator):
        directory.delete(OTHER_ADMIN.id)

    assert directory.get(OTHER_ADMIN.id) == OTHER_ADMIN
    assert directory.get(FIRST.id) == replace(FIRST, role=Role.USER)


def test_roles_and_states_change_while_an_administrator_remains(
    directory: SqliteUserDirectory | MemoryUsers,
) -> None:
    directory.add(FIRST, "hash-1")
    directory.add(SECOND, "hash-2")

    directory.set_state(SECOND.id, UserState.DISABLED)
    directory.set_role(SECOND.id, Role.INSTALLATION_ADMINISTRATOR)
    # A disabled administrator does not count, so the active one keeps the role.
    with pytest.raises(LastAdministrator):
        directory.set_role(FIRST.id, Role.USER)
    directory.set_state(SECOND.id, UserState.ACTIVE)
    directory.set_role(FIRST.id, Role.USER)

    assert directory.get(SECOND.id) == OTHER_ADMIN
    assert directory.get(FIRST.id) == replace(FIRST, role=Role.USER)


def test_the_last_administrator_is_deleted_only_as_the_last_user(
    directory: SqliteUserDirectory | MemoryUsers,
) -> None:
    directory.add(FIRST, "hash-1")
    directory.add(SECOND, "hash-2")

    with pytest.raises(LastAdministrator):
        directory.delete(FIRST.id)
    directory.delete(SECOND.id)
    directory.delete(FIRST.id)

    assert directory.count() == 0


def test_one_email_signs_in_one_user_whatever_its_case(tmp_path: Path) -> None:
    users = _users(tmp_path)
    users.add(FIRST, "hash-1")

    with pytest.raises(EmailTaken):
        users.add(replace(SECOND, email="FIRST@example.test"), "hash-2")
    users.add(SECOND, "hash-2")
    with pytest.raises(EmailTaken):
        users.set_email(SECOND.id, "first@example.test")
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

    with (
        pytest.raises(sqlite3.IntegrityError, match="keeps an email"),
        sqlite3.connect(tmp_path / "test.db") as connection,
    ):
        connection.execute("UPDATE users SET email = NULL WHERE id = ?", (FIRST.id.value,))


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


def _issued(invitations: SqliteInvitations, created_by: UserId, at: datetime) -> IssuedLink:
    link = invitations.issue(created_by, at)
    assert link is not None
    return link


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


def test_only_me_is_refused_in_one_step_with_the_change_while_another_user_exists(
    tmp_path: Path,
) -> None:
    """An invitation accepted after the administrator's check still stops Only Me."""
    database = _database(tmp_path)
    users = SqliteUserDirectory(database)
    users.add(FIRST, "hash-1")
    settings = SqliteRegistrationSettings(database)
    settings.set_policy(RegistrationPolicy.INVITATION_ONLY)
    users.add(SECOND, "hash-2")

    with pytest.raises(OnlyMeNeedsOneUser):
        settings.set_policy(RegistrationPolicy.ONLY_ME)
    assert settings.policy() is RegistrationPolicy.INVITATION_ONLY
    users.delete(SECOND.id)
    settings.set_policy(RegistrationPolicy.ONLY_ME)
    assert settings.policy() is RegistrationPolicy.ONLY_ME


def test_no_invitation_is_issued_once_nobody_may_join_or_its_creator_left(
    tmp_path: Path,
) -> None:
    """The policy and the creator are read in one step with the insert, so an invitation issued
    while the last User leaves cannot outlive the return to setup."""
    database = _database(tmp_path)
    users = SqliteUserDirectory(database)
    users.add(FIRST, "hash-1")
    users.add(SECOND, "hash-2")
    settings = SqliteRegistrationSettings(database)
    invitations = SqliteInvitations(database, SequentialIds())

    closed = invitations.issue(FIRST.id, NOW)
    settings.set_policy(RegistrationPolicy.INVITATION_ONLY)
    not_an_administrator = invitations.issue(SECOND.id, NOW)
    users.delete(SECOND.id)
    gone = invitations.issue(SECOND.id, NOW)

    assert (closed, not_an_administrator, gone) == (None, None, None)
    assert invitations.pending(NOW) == ()


def test_an_invitation_is_refused_once_nobody_may_join(tmp_path: Path) -> None:
    """The policy is read in one step with the acceptance, so Only Me chosen after the person
    opened their link still stops them."""
    database = _database(tmp_path)
    users = SqliteUserDirectory(database)
    users.add(FIRST, "hash-1")
    settings = SqliteRegistrationSettings(database)
    settings.set_policy(RegistrationPolicy.INVITATION_ONLY)
    invitations = SqliteInvitations(database, SequentialIds())
    link = _issued(invitations, FIRST.id, NOW)
    settings.set_policy(RegistrationPolicy.ONLY_ME)

    assert not invitations.accept(link.token, SECOND, "hash-2", NOW)
    assert users.get(SECOND.id) is None


def test_an_invitation_is_refused_once_everyone_left(tmp_path: Path) -> None:
    """The last User leaving returns the installation to setup; nobody joins it meanwhile."""
    database = _database(tmp_path)
    users = SqliteUserDirectory(database)
    users.add(FIRST, "hash-1")
    SqliteRegistrationSettings(database).set_policy(RegistrationPolicy.INVITATION_ONLY)
    invitations = SqliteInvitations(database, SequentialIds())
    link = _issued(invitations, FIRST.id, NOW)
    users.delete(FIRST.id)

    assert not invitations.accept(link.token, SECOND, "hash-2", NOW)
    assert users.count() == 0


def test_an_invitation_adds_one_user_once_and_only_its_hash_is_stored(tmp_path: Path) -> None:
    database = _database(tmp_path)
    users = SqliteUserDirectory(database)
    users.add(FIRST, "hash-1")
    SqliteRegistrationSettings(database).set_policy(RegistrationPolicy.INVITATION_ONLY)
    invitations = SqliteInvitations(database, SequentialIds())
    link = _issued(invitations, FIRST.id, NOW)

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
    SqliteRegistrationSettings(database).set_policy(RegistrationPolicy.INVITATION_ONLY)
    invitations = SqliteInvitations(database, SequentialIds())
    first = _issued(invitations, FIRST.id, NOW)
    second = _issued(invitations, FIRST.id, NOW + timedelta(days=1))

    assert [pending.id for pending in invitations.pending(NOW + timedelta(days=7))] == [second.id]
    assert invitations.revoke(second.id, NOW + timedelta(days=2))
    assert not invitations.revoke(second.id, NOW + timedelta(days=2))
    assert not invitations.usable(second.token, NOW + timedelta(days=2))
    assert not invitations.revoke(first.id, NOW + timedelta(days=8))


def test_returning_to_setup_chooses_only_me_and_revokes_every_invitation_in_one_step(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    users = SqliteUserDirectory(database)
    users.add(FIRST, "hash-1")
    settings = SqliteRegistrationSettings(database)
    settings.set_policy(RegistrationPolicy.INVITATION_ONLY)
    invitations = SqliteInvitations(database, SequentialIds())
    first = _issued(invitations, FIRST.id, NOW)
    second = _issued(invitations, FIRST.id, NOW)
    later = NOW + timedelta(hours=1)
    users.add(SECOND, "hash-2")

    # Refused while someone else is here, and refused whole: nothing is half done.
    with pytest.raises(OnlyMeNeedsOneUser):
        settings.return_to_setup(later)
    assert settings.policy() is RegistrationPolicy.INVITATION_ONLY
    assert len(invitations.pending(later)) == 2

    users.delete(SECOND.id)
    settings.return_to_setup(later)

    assert settings.policy() is RegistrationPolicy.ONLY_ME
    assert invitations.pending(later) == ()
    assert not invitations.usable(first.token, later)
    assert not invitations.usable(second.token, later)


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
    # Another administrator remains, so the first may go.
    users.add(OTHER_ADMIN, "hash-2")

    users.delete(upgraded.id)

    with sqlite3.connect(database) as connection:
        for table in OWNED_TABLES:
            rows = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            assert rows == (0,), table
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert users.list() == (OTHER_ADMIN,)
