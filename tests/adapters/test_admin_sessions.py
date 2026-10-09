from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from calendar_sync.infrastructure.persistence.sqlite import initialize_database
from calendar_sync.infrastructure.security import SESSION_LIFETIME, SqliteAdminAuth

SIGNED_IN = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


@dataclass
class MovableClock:
    moment: datetime

    def now(self) -> datetime:
        return self.moment


def _signed_in(tmp_path: Path) -> tuple[SqliteAdminAuth, MovableClock, str]:
    database = tmp_path / "test.db"
    initialize_database(database)
    clock = MovableClock(SIGNED_IN)
    auth = SqliteAdminAuth(database, clock)
    auth.create_admin("synthetic-password")
    session = auth.authenticate("synthetic-password")
    assert session is not None
    return auth, clock, session.token


def test_an_admin_session_lasts_seven_days_from_sign_in(tmp_path: Path) -> None:
    auth, clock, token = _signed_in(tmp_path)

    clock.moment = SIGNED_IN + timedelta(days=7) - timedelta(seconds=1)
    assert auth.session_user(token) is not None

    clock.moment = SIGNED_IN + timedelta(days=7)
    assert auth.session_user(token) is None


def test_signing_in_again_removes_expired_sessions(tmp_path: Path) -> None:
    auth, clock, expired = _signed_in(tmp_path)
    clock.moment = SIGNED_IN + SESSION_LIFETIME

    renewed = auth.authenticate("synthetic-password")

    assert renewed is not None
    assert renewed.expires_at == SIGNED_IN + 2 * SESSION_LIFETIME
    assert auth.session_user(renewed.token) is not None
    # Moving the clock back shows the expired session was deleted, not merely out of date.
    clock.moment = SIGNED_IN
    assert auth.session_user(expired) is None
