from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from calendar_sync.application.errors import AdminAlreadyConfigured, PasswordPolicyViolation
from calendar_sync.application.ports import AdministratorSession, Clock
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.scheduling import SystemClock

SESSION_LIFETIME = timedelta(days=7)


class InvalidMasterKey(ValueError):
    pass


def _master_key_bytes(encoded_key: str) -> bytes:
    try:
        key = base64.urlsafe_b64decode(encoded_key.encode())
    except Exception as error:
        raise InvalidMasterKey("master key must be URL-safe base64") from error
    if len(key) != 32:
        raise InvalidMasterKey("master key must decode to exactly 32 bytes")
    return key


class CredentialCipher:
    """Encrypts provider credentials at rest with the Installation Master Key."""

    def __init__(self, encoded_key: str) -> None:
        self._cipher = AESGCM(_master_key_bytes(encoded_key))

    def encrypt(self, plaintext: str) -> bytes:
        nonce = secrets.token_bytes(12)
        return nonce + self._cipher.encrypt(nonce, plaintext.encode(), None)

    def decrypt(self, ciphertext: bytes) -> str:
        nonce, encrypted = ciphertext[:12], ciphertext[12:]
        return self._cipher.decrypt(nonce, encrypted, None).decode()

    @staticmethod
    def generate_key() -> str:
        return base64.urlsafe_b64encode(AESGCM.generate_key(bit_length=256)).decode()


class HistoryCipher:
    """Seals Source Observations and Source Change values (ADR 0017).

    Its key is derived from the Installation Master Key for this purpose only, and each value is
    bound to the record it belongs to, so a value copied to another event does not open.
    """

    _VERSION = b"\x01"

    def __init__(self, encoded_master_key: str) -> None:
        key = HKDF(
            algorithm=SHA256(), length=32, salt=None, info=b"calendar-sync source history v1"
        ).derive(_master_key_bytes(encoded_master_key))
        self._cipher = AESGCM(key)

    def seal(self, plaintext: str, context: str) -> bytes:
        nonce = secrets.token_bytes(12)
        associated = self._VERSION + context.encode()
        return self._VERSION + nonce + self._cipher.encrypt(nonce, plaintext.encode(), associated)

    def open(self, sealed: bytes, context: str) -> str | None:
        """The value, or None when it was sealed under another key, record, or version."""
        version, nonce, encrypted = sealed[:1], sealed[1:13], sealed[13:]
        if version != self._VERSION or len(nonce) != 12:
            return None
        try:
            plaintext = self._cipher.decrypt(nonce, encrypted, version + context.encode())
        except InvalidTag:
            return None
        return plaintext.decode()


class SqliteAdminAuth:
    def __init__(self, database_path: Path, clock: Clock | None = None) -> None:
        self._database_path = database_path
        self._clock = clock or SystemClock()

    def is_configured(self) -> bool:
        with transaction(self._database_path) as connection:
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
            with transaction(self._database_path) as connection:
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
        with transaction(self._database_path) as connection:
            row = connection.execute(
                "SELECT password_hash FROM installation_admin WHERE singleton = 1"
            ).fetchone()
            if row is None or not _verify_password(password, str(row["password_hash"])):
                return None

            token = secrets.token_urlsafe(32)
            hashed = token_hash(token)
            now = self._clock.now()
            expires = now + SESSION_LIFETIME
            connection.execute(
                "INSERT INTO admin_sessions(token_hash, created_at, expires_at) VALUES (?, ?, ?)",
                (hashed, now.isoformat(), expires.isoformat()),
            )
            connection.execute(
                "DELETE FROM admin_sessions WHERE expires_at <= ?", (now.isoformat(),)
            )
            return AdministratorSession(token, expires)

    def session_is_valid(self, token: str | None) -> bool:
        if not token:
            return False
        now = self._clock.now()
        with transaction(self._database_path) as connection:
            row = connection.execute(
                "SELECT expires_at FROM admin_sessions WHERE token_hash = ?",
                (token_hash(token),),
            ).fetchone()
        return row is not None and datetime.fromisoformat(str(row["expires_at"])) > now

    def revoke(self, token: str | None) -> None:
        if not token:
            return
        with transaction(self._database_path) as connection:
            connection.execute(
                "DELETE FROM admin_sessions WHERE token_hash = ?", (token_hash(token),)
            )


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


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
