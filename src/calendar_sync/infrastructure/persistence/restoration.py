"""Read-only inspection of an existing stopped-service restoration candidate."""

import sqlite3
import stat
from contextlib import closing
from pathlib import Path

from cryptography.exceptions import InvalidTag

from calendar_sync.application.operations.restoration import RestoreFailure, RestoreInspection
from calendar_sync.infrastructure.persistence.connections import open_connection
from calendar_sync.infrastructure.persistence.migrations import supported_schema_versions
from calendar_sync.infrastructure.security import CredentialCipher


class SqliteRestoreStore:
    def __init__(self, database_path: Path, cipher: CredentialCipher) -> None:
        self._database_path = database_path
        self._cipher = cipher

    def inspect(self) -> RestoreInspection:
        _require_regular_file(self._database_path)
        try:
            with closing(open_connection(self._database_path, mode="ro")) as connection:
                connection.execute("BEGIN")
                _check_integrity(connection)
                _check_schema(connection)
                users = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
                authenticated = self._authenticate_credentials(connection)
                return RestoreInspection(
                    max(supported_schema_versions()), users, authenticated, authenticated
                )
        except sqlite3.Error as error:
            code = getattr(error, "sqlite_errorcode", 0) & 0xFF
            if code in (sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB):
                raise RestoreFailure("integrity_failed") from None
            if code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                raise RestoreFailure("storage_busy") from None
            raise RestoreFailure("storage_failed") from None
        except OSError:
            raise RestoreFailure("storage_failed") from None

    def _authenticate_credentials(self, connection: sqlite3.Connection) -> int:
        authenticated = 0
        for row in connection.execute("SELECT encrypted_credentials FROM connected_accounts"):
            try:
                self._cipher.decrypt(bytes(row[0]))
            except (InvalidTag, ValueError, TypeError, UnicodeError):
                raise RestoreFailure("key_mismatch") from None
            authenticated += 1
        return authenticated


def _require_regular_file(path: Path) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        raise RestoreFailure("database_missing") from None
    except OSError:
        raise RestoreFailure("database_unsafe") from None
    if not stat.S_ISREG(mode):
        raise RestoreFailure("database_unsafe")


def _check_integrity(connection: sqlite3.Connection) -> None:
    if [tuple(row) for row in connection.execute("PRAGMA integrity_check")] != [("ok",)]:
        raise RestoreFailure("integrity_failed")
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise RestoreFailure("foreign_keys_failed")


def _check_schema(connection: sqlite3.Connection) -> None:
    try:
        versions = frozenset(
            row[0] for row in connection.execute("SELECT version FROM schema_migrations")
        )
        connection.execute(
            "SELECT id, email, password_hash, role, state, credential_revision, email_verified "
            "FROM users LIMIT 0"
        )
        connection.execute(
            "SELECT id, user_id, encrypted_credentials FROM connected_accounts LIMIT 0"
        )
    except sqlite3.OperationalError:
        raise RestoreFailure("schema_incompatible") from None
    if versions != supported_schema_versions():
        raise RestoreFailure("schema_incompatible")
