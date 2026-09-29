from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from calendar_sync.application.errors import AdminAlreadyConfigured, PasswordPolicyViolation
from calendar_sync.application.ports import AdministratorSession, Clock
from calendar_sync.infrastructure.scheduling import SystemClock

SESSION_LIFETIME = timedelta(days=7)


class InvalidMasterKey(ValueError):
    pass


class CredentialCipher:
    """Encrypts provider credentials at rest with the Installation Master Key."""

    def __init__(self, encoded_key: str) -> None:
        try:
            key = base64.urlsafe_b64decode(encoded_key.encode())
        except Exception as error:
            raise InvalidMasterKey("master key must be URL-safe base64") from error
        if len(key) != 32:
            raise InvalidMasterKey("master key must decode to exactly 32 bytes")
        self._cipher = AESGCM(key)

    def encrypt(self, plaintext: str) -> bytes:
        nonce = secrets.token_bytes(12)
        return nonce + self._cipher.encrypt(nonce, plaintext.encode(), None)

    def decrypt(self, ciphertext: bytes) -> str:
        nonce, encrypted = ciphertext[:12], ciphertext[12:]
        return self._cipher.decrypt(nonce, encrypted, None).decode()

    @staticmethod
    def generate_key() -> str:
        return base64.urlsafe_b64encode(AESGCM.generate_key(bit_length=256)).decode()


class SqliteAdminAuth:
    def __init__(self, database_path: Path, clock: Clock | None = None) -> None:
        self._database_path = database_path
        self._clock = clock or SystemClock()

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
                    (encoded, self._clock.now().isoformat()),
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
            now = self._clock.now()
            expires = now + SESSION_LIFETIME
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
        now = self._clock.now()
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
