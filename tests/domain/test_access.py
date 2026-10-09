from datetime import UTC, datetime, timedelta

import pytest

from calendar_sync.domain.access import (
    InvalidEmail,
    LastAdministrator,
    OnlyMeNeedsOneUser,
    RegistrationPolicy,
    Role,
    User,
    UserId,
    UserState,
    email_address,
    link_expiry,
    require_another_administrator,
    require_registration_change,
)

CREATED = datetime(2026, 10, 1, tzinfo=UTC)


def _user(email: str | None = "person@example.test", role: Role = Role.USER) -> User:
    return User(UserId("user-1"), email, role, UserState.ACTIVE, CREATED)


@pytest.mark.parametrize(
    ("raw", "kept"),
    [
        ("person@example.test", "person@example.test"),
        ("  Person@Example.TEST ", "person@example.test"),
        ("first.last+tag@sub.example.test", "first.last+tag@sub.example.test"),
    ],
)
def test_an_email_address_is_kept_trimmed_and_in_lower_case(raw: str, kept: str) -> None:
    assert email_address(raw) == kept


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "person",
        "@example.test",
        "person@",
        "person@example",
        "a b@example.test",
        "a@b@example.test",
        "person\n@example.test",
        f"{'a' * 250}@example.test",
    ],
)
def test_an_invalid_email_address_is_refused(raw: str) -> None:
    with pytest.raises(InvalidEmail):
        email_address(raw)


def test_a_user_without_an_email_must_add_one() -> None:
    assert _user(email=None).needs_email
    assert not _user().needs_email


def test_only_the_installation_administrator_role_administers() -> None:
    assert _user(role=Role.INSTALLATION_ADMINISTRATOR).administers
    assert not _user(role=Role.USER).administers


def test_a_user_who_adds_an_email_keeps_everything_else() -> None:
    added = _user(email=None).with_email("person@example.test")

    assert added == _user()


def test_only_me_is_the_default_registration_policy() -> None:
    assert RegistrationPolicy.default() is RegistrationPolicy.ONLY_ME


@pytest.mark.parametrize("users", [1, 2, 5])
def test_invitation_only_may_be_chosen_whatever_the_users(users: int) -> None:
    require_registration_change(RegistrationPolicy.INVITATION_ONLY, users)


def test_only_me_may_be_chosen_again_only_while_no_other_user_exists() -> None:
    require_registration_change(RegistrationPolicy.ONLY_ME, 1)

    with pytest.raises(OnlyMeNeedsOneUser):
        require_registration_change(RegistrationPolicy.ONLY_ME, 2)


def test_only_invitation_only_lets_people_join() -> None:
    assert RegistrationPolicy.INVITATION_ONLY.lets_people_join
    assert not RegistrationPolicy.ONLY_ME.lets_people_join


def test_a_link_lasts_seven_days() -> None:
    assert link_expiry(CREATED) == CREATED + timedelta(days=7)


def _administrators(*states: UserState) -> list[User]:
    return [
        User(
            UserId(f"admin-{index}"),
            f"a{index}@example.test",
            Role.INSTALLATION_ADMINISTRATOR,
            state,
            CREATED,
        )
        for index, state in enumerate(states)
    ]


def test_the_last_administrator_keeps_the_role() -> None:
    sole = _administrators(UserState.ACTIVE)
    with pytest.raises(LastAdministrator):
        require_another_administrator(sole, sole[0].id)

    pair = _administrators(UserState.ACTIVE, UserState.ACTIVE)
    require_another_administrator(pair, pair[0].id)


def test_a_disabled_administrator_does_not_count_as_another() -> None:
    users = _administrators(UserState.ACTIVE, UserState.DISABLED)

    with pytest.raises(LastAdministrator):
        require_another_administrator(users, users[0].id)
