from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


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


class ScryptPasswords:
    """Password hashes with scrypt and a random salt; only the hash is stored."""

    def hash(self, password: str) -> str:
        return hash_password(password)

    def verify(self, password: str, hashed: str) -> bool:
        return _verify_password(password, hashed)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = _derive_password(password, salt)
    return "scrypt$" + base64.urlsafe_b64encode(salt + derived).decode()


def _verify_password(password: str, encoded: str) -> bool:
    algorithm, _, payload = encoded.partition("$")
    try:
        raw = base64.urlsafe_b64decode(payload.encode())
    except ValueError:
        return False
    salt, expected = raw[:16], raw[16:]
    if algorithm != "scrypt" or len(salt) != 16 or not expected:
        return False
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
