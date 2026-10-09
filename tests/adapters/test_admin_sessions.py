from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from calendar_sync.infrastructure.persistence.sqlite import initialize_database
from calendar_sync.infrastructure.persistence.users import SESSION_LIFETIME, SqliteSessions
from tests.users import OTHER_USER, USER, add_user

SIGNED_IN = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


@dataclass
class MovableClock:
    moment: datetime

    def now(self) -> datetime:
        return self.moment


def _signed_in(tmp_path: Path) -> tuple[SqliteSessions, MovableClock, str, Path]:
    database = tmp_path / "test.db"
    initialize_database(database)
    add_user(database)
    clock = MovableClock(SIGNED_IN)
    sessions = SqliteSessions(database, clock)
    return sessions, clock, sessions.start(USER).token, database


def test_a_session_lasts_seven_days_from_sign_in(tmp_path: Path) -> None:
    sessions, clock, token, _ = _signed_in(tmp_path)

    clock.moment = SIGNED_IN + timedelta(days=7) - timedelta(seconds=1)
    assert sessions.user_of(token) == USER

    clock.moment = SIGNED_IN + timedelta(days=7)
    assert sessions.user_of(token) is None


def test_signing_in_again_removes_expired_sessions(tmp_path: Path) -> None:
    sessions, clock, expired, _ = _signed_in(tmp_path)
    clock.moment = SIGNED_IN + SESSION_LIFETIME

    renewed = sessions.start(USER)

    assert renewed.expires_at == SIGNED_IN + 2 * SESSION_LIFETIME
    assert sessions.user_of(renewed.token) == USER
    # Moving the clock back shows the expired session was deleted, not merely out of date.
    clock.moment = SIGNED_IN
    assert sessions.user_of(expired) is None


def test_ending_a_users_sessions_keeps_the_one_asked_for_and_other_users(tmp_path: Path) -> None:
    sessions, _, first, database = _signed_in(tmp_path)
    kept = sessions.start(USER)
    add_user(database, OTHER_USER)
    theirs = sessions.start(OTHER_USER)

    sessions.end_all(USER, keep=kept.token)

    assert sessions.user_of(first) is None
    assert sessions.user_of(kept.token) == USER
    assert sessions.user_of(theirs.token) == OTHER_USER


def test_a_disabled_users_session_no_longer_signs_them_in(tmp_path: Path) -> None:
    sessions, _, token, database = _signed_in(tmp_path)
    add_user(database, OTHER_USER, state="disabled")

    assert sessions.user_of(sessions.start(OTHER_USER).token) is None
    assert sessions.user_of(token) == USER
