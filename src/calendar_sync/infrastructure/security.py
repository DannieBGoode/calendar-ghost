from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from calendar_sync.application.errors import AdminAlreadyConfigured, PasswordPolicyViolation
from calendar_sync.application.ports import AdministratorSession


class SqliteAdminAuth:
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path

    def is_configured(self) -> bool:
        with self._connect() as connection:
            return (
                connection.execute(
                    "SELECT 1 FROM installation_admin WHERE singleton = 1"
                ).fetchone()
                is not None
            )

    def create_admin(self, password: str) -> None:
        if len(password) < 12:
            raise PasswordPolicyViolation("password must contain at least 12 characters")
        salt = secrets.token_bytes(16)
        derived = _derive_password(password, salt)
        encoded = "scrypt$" + base64.urlsafe_b64encode(salt + derived).decode()
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO installation_admin(singleton, password_hash, created_at)
                    VALUES (1, ?, ?)
                    """,
                    (encoded, datetime.now(UTC).isoformat()),
                )
        except sqlite3.IntegrityError as error:
            raise AdminAlreadyConfigured("installation administrator already exists") from error

    def authenticate(self, password: str) -> AdministratorSession | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT password_hash FROM installation_admin WHERE singleton = 1"
            ).fetchone()
            if row is None or not _verify_password(password, str(row["password_hash"])):
                return None

            token = secrets.token_urlsafe(32)
            token_hash = _token_hash(token)
            now = datetime.now(UTC)
            expires = now + timedelta(days=7)
            connection.execute(
                "INSERT INTO admin_sessions(token_hash, created_at, expires_at) VALUES (?, ?, ?)",
                (token_hash, now.isoformat(), expires.isoformat()),
            )
            connection.execute(
                "DELETE FROM admin_sessions WHERE expires_at <= ?", (now.isoformat(),)
            )
            return AdministratorSession(token, expires)

    def session_is_valid(self, token: str | None) -> bool:
        if not token:
            return False
        now = datetime.now(UTC)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT expires_at FROM admin_sessions WHERE token_hash = ?",
                (_token_hash(token),),
            ).fetchone()
        return row is not None and datetime.fromisoformat(str(row["expires_at"])) > now

    def revoke(self, token: str | None) -> None:
        if not token:
            return
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM admin_sessions WHERE token_hash = ?", (_token_hash(token),)
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        return connection


def _verify_password(password: str, encoded: str) -> bool:
    algorithm, payload = encoded.split("$", maxsplit=1)
    if algorithm != "scrypt":
        return False
    raw = base64.urlsafe_b64decode(payload.encode())
    salt, expected = raw[:16], raw[16:]
    actual = _derive_password(password, salt)
    return hmac.compare_digest(actual, expected)


def _derive_password(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode(),
        salt=salt,
        n=2**15,
        r=8,
        p=1,
        dklen=32,
        maxmem=64 * 1024 * 1024,
    )


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
