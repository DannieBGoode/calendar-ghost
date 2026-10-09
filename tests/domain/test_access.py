from datetime import UTC, datetime

import pytest

from calendar_sync.domain.access import (
    InvalidEmail,
    Role,
    User,
    UserId,
    UserState,
    email_address,
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
