"""Users, their password hashes, and their sessions (ADR 0030)."""

from __future__ import annotations

import secrets
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from calendar_sync.application.errors import EmailTaken
from calendar_sync.application.ports import Clock, Session
from calendar_sync.domain.access import Role, User, UserId, UserState
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.security import token_hash

SESSION_LIFETIME = timedelta(days=7)
_COLUMNS = "id, email, role, state, language, notify_by_email, created_at, last_sign_in_at"


class SqliteUserDirectory:
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path

    def count(self) -> int:
        with transaction(self._database_path) as connection:
            return int(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0])

    def list(self) -> tuple[User, ...]:
        with transaction(self._database_path) as connection:
            rows = connection.execute(
                f"SELECT {_COLUMNS} FROM users ORDER BY created_at, rowid"  # noqa: S608
            ).fetchall()
        return tuple(_user(row) for row in rows)

    def get(self, user_id: UserId) -> User | None:
        return self._one("id = ?", user_id.value)

    def by_email(self, email: str) -> User | None:
        return self._one("email = ?", email)

    def without_email(self) -> User | None:
        return self._one("email IS NULL")

    def add_first(self, user: User, password_hash: str) -> bool:
        with transaction(self._database_path) as connection:
            # Held from the check to the insert, so two first-run requests cannot both succeed.
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None:
                return False
            _insert(connection, user, password_hash)
        return True

    def add(self, user: User, password_hash: str) -> None:
        with transaction(self._database_path) as connection:
            _insert(connection, user, password_hash)

    def save(self, user: User) -> None:
        try:
            with transaction(self._database_path) as connection:
                connection.execute(
                    """
                    UPDATE users SET email = ?, role = ?, state = ?, language = ?,
                        notify_by_email = ?
                    WHERE id = ?
                    """,
                    (
                        user.email,
                        user.role.value,
                        user.state.value,
                        user.language,
                        int(user.notify_by_email),
                        user.id.value,
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise _taken_or(error) from error

    def password_hash(self, user_id: UserId) -> str | None:
        with transaction(self._database_path) as connection:
            row = connection.execute(
                "SELECT password_hash FROM users WHERE id = ?", (user_id.value,)
            ).fetchone()
        return str(row[0]) if row is not None else None

    def set_password_hash(self, user_id: UserId, password_hash: str) -> None:
        with transaction(self._database_path) as connection:
            connection.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id.value)
            )

    def record_sign_in(self, user_id: UserId, at: datetime) -> None:
        with transaction(self._database_path) as connection:
            connection.execute(
                "UPDATE users SET last_sign_in_at = ? WHERE id = ?",
                (at.isoformat(), user_id.value),
            )

    def _one(self, condition: str, *values: object) -> User | None:
        with transaction(self._database_path) as connection:
            # Interpolates only the constant columns and one of this class's own conditions.
            row = connection.execute(
                f"SELECT {_COLUMNS} FROM users WHERE {condition}",  # noqa: S608
                values,
            ).fetchone()
        return _user(row) if row is not None else None


def _insert(connection: sqlite3.Connection, user: User, password_hash: str) -> None:
    try:
        connection.execute(
            """
            INSERT INTO users (
                id, email, password_hash, role, state, language, notify_by_email, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user.id.value,
                user.email,
                password_hash,
                user.role.value,
                user.state.value,
                user.language,
                int(user.notify_by_email),
                user.created_at.isoformat(),
            ),
        )
    except sqlite3.IntegrityError as error:
        raise _taken_or(error) from error


def _taken_or(error: sqlite3.IntegrityError) -> Exception:
    """EmailTaken when another User has the email; any other refusal unchanged."""
    if "UNIQUE" in str(error) and "users.email" in str(error):
        return EmailTaken("another User signs in with this email")
    return error


def _user(row: sqlite3.Row) -> User:
    signed_in = row["last_sign_in_at"]
    return User(
        id=UserId(str(row["id"])),
        email=str(row["email"]) if row["email"] is not None else None,
        role=Role(str(row["role"])),
        state=UserState(str(row["state"])),
        created_at=datetime.fromisoformat(str(row["created_at"])),
        last_sign_in_at=datetime.fromisoformat(str(signed_in)) if signed_in else None,
        language=str(row["language"]) if row["language"] is not None else None,
        notify_by_email=bool(row["notify_by_email"]),
    )


class SqliteSessions:
    """Sessions of seven days; only each token's hash is stored."""

    def __init__(self, database_path: Path, clock: Clock) -> None:
        self._database_path = database_path
        self._clock = clock

    def start(self, user_id: UserId) -> Session:
        token = secrets.token_urlsafe(32)
        now = self._clock.now()
        expires = now + SESSION_LIFETIME
        with transaction(self._database_path) as connection:
            connection.execute(
                """
                INSERT INTO user_sessions(token_hash, user_id, created_at, expires_at)
                VALUES (?, ?, ?, ?)
                """,
                (token_hash(token), user_id.value, now.isoformat(), expires.isoformat()),
            )
            connection.execute(
                "DELETE FROM user_sessions WHERE expires_at <= ?", (now.isoformat(),)
            )
        return Session(token, expires, user_id)

    def user_of(self, token: str | None) -> UserId | None:
        if not token:
            return None
        with transaction(self._database_path) as connection:
            row = connection.execute(
                """
                SELECT user_sessions.user_id, user_sessions.expires_at FROM user_sessions
                JOIN users ON users.id = user_sessions.user_id AND users.state = 'active'
                WHERE token_hash = ?
                """,
                (token_hash(token),),
            ).fetchone()
        if row is None or datetime.fromisoformat(str(row["expires_at"])) <= self._clock.now():
            return None
        return UserId(str(row["user_id"]))

    def end(self, token: str | None) -> None:
        if not token:
            return
        with transaction(self._database_path) as connection:
            connection.execute(
                "DELETE FROM user_sessions WHERE token_hash = ?", (token_hash(token),)
            )

    def end_all(self, user_id: UserId, *, keep: str | None = None) -> None:
        kept = token_hash(keep) if keep else None
        with transaction(self._database_path) as connection:
            connection.execute(
                "DELETE FROM user_sessions WHERE user_id = ? AND token_hash IS NOT ?",
                (user_id.value, kept),
            )
