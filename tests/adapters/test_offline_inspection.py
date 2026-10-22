"""Offline inspection authenticates a snapshot without migrating or exposing its values."""

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Literal

import pytest

from calendar_sync.application.operations.restoration import RestoreFailure
from calendar_sync.infrastructure.persistence.connections import open_connection, transaction
from calendar_sync.infrastructure.persistence.migrations import initialize_database
from calendar_sync.infrastructure.persistence.restoration import SqliteRestoreStore
from calendar_sync.infrastructure.security import CredentialCipher
from tests.users import add_account, add_user


def _cipher() -> CredentialCipher:
    return CredentialCipher(CredentialCipher.generate_key())


def _database(tmp_path: Path) -> Path:
    path = tmp_path / "inspection.db"
    initialize_database(path)
    add_user(path)
    return path


def _refused(path: Path, code: str) -> None:
    with pytest.raises(RestoreFailure) as failure:
        SqliteRestoreStore(path, _cipher()).inspect()
    assert failure.value.code == code
    assert failure.value.status == 1
    assert str(failure.value) == code


def test_inspect_missing_database_does_not_create_file(tmp_path: Path) -> None:
    path = tmp_path / "absent.db"
    _refused(path, "database_missing")
    assert not path.exists()


@pytest.mark.parametrize("kind", ["directory", "symlink"])
def test_inspect_rejects_nonregular_path(tmp_path: Path, kind: str) -> None:
    path = tmp_path / "unsafe.db"
    if kind == "directory":
        path.mkdir()
    else:
        path.symlink_to(_database(tmp_path))
    _refused(path, "database_unsafe")


@pytest.mark.parametrize("change", ["middle", "latest", "future", "ledger", "column"])
def test_inspect_rejects_missing_extra_and_future_migration_versions(
    tmp_path: Path, change: str
) -> None:
    path = _database(tmp_path)
    statements = {
        "middle": "DELETE FROM schema_migrations WHERE version = 20",
        "latest": "DELETE FROM schema_migrations WHERE version = 39",
        "future": "INSERT INTO schema_migrations VALUES (40, 'synthetic')",
        "ledger": "DROP TABLE schema_migrations",
        "column": "ALTER TABLE users RENAME COLUMN credential_revision TO absent_revision",
    }
    with transaction(path) as connection:
        connection.execute(statements[change])
    before = path.read_bytes()
    _refused(path, "schema_incompatible")
    assert path.read_bytes() == before


@pytest.mark.parametrize("kind", ["damaged", "orphan"])
def test_inspect_rejects_integrity_and_foreign_key_failures(tmp_path: Path, kind: str) -> None:
    path = _database(tmp_path)
    if kind == "damaged":
        path.write_bytes(b"synthetic damaged database")
        code = "integrity_failed"
    else:
        with closing(open_connection(path)) as connection, connection:
            connection.execute("PRAGMA foreign_keys = OFF")
            connection.execute(
                "INSERT INTO sync_cursors(rule_id, user_id, cursor) "
                "VALUES ('synthetic-orphan', 'user-1', 'cursor')"
            )
        code = "foreign_keys_failed"
    _refused(path, code)


@pytest.mark.parametrize("bad", ["wrong-key", "tampered", "empty", "none"])
def test_inspect_authenticates_every_credential_without_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], bad: str
) -> None:
    path = _database(tmp_path)
    cipher = _cipher()
    for index in range(3):
        identifier = f"synthetic-{index}"
        add_account(path, identifier, state="disconnected" if index == 2 else "connected")
        sealed = cipher.encrypt("synthetic secret content")
        if index == 1:
            if bad == "wrong-key":
                sealed = _cipher().encrypt("synthetic secret content")
            elif bad == "tampered":
                sealed = sealed[:-1] + bytes([sealed[-1] ^ 1])
            elif bad == "empty":
                sealed = b""
        with transaction(path) as connection:
            connection.execute(
                "UPDATE connected_accounts SET encrypted_credentials = ? WHERE id = ?",
                (sealed, identifier),
            )
    store = SqliteRestoreStore(path, cipher)
    if bad == "none":
        result = store.inspect()
        assert (result.schema_version, result.users, result.accounts) == (39, 1, 3)
        assert result.authenticated_credentials == 3
    else:
        with pytest.raises(RestoreFailure, match=r"^key_mismatch$"):
            store.inspect()
    assert capsys.readouterr() == ("", "")


def test_inspect_empty_accounts_reports_key_unverified(tmp_path: Path) -> None:
    path = _database(tmp_path)
    with transaction(path) as connection:
        connection.execute("CREATE TABLE _litestream_lock (id INTEGER)")
        connection.execute("CREATE TABLE _litestream_seq (id INTEGER)")
    result = SqliteRestoreStore(path, _cipher()).inspect()
    assert result.accounts == result.authenticated_credentials == 0


def test_inspect_holds_one_read_snapshot_and_closes_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from calendar_sync.infrastructure.persistence import restoration

    path = _database(tmp_path)
    opened: list[sqlite3.Connection] = []
    original = restoration.open_connection

    def capture(database_path: Path, *, mode: Literal["ro"]) -> sqlite3.Connection:
        connection = original(database_path, mode=mode)
        opened.append(connection)
        return connection

    monkeypatch.setattr(restoration, "open_connection", capture)
    cipher = _cipher()
    add_account(path, "synthetic")
    with transaction(path) as connection:
        connection.execute(
            "UPDATE connected_accounts SET encrypted_credentials = ?", (cipher.encrypt("{}"),)
        )
    decrypt = cipher.decrypt

    def concurrent_write(sealed: bytes) -> str:
        assert opened[0].in_transaction
        with transaction(path) as writer:
            writer.execute("DELETE FROM connected_accounts")
        return decrypt(sealed)

    monkeypatch.setattr(cipher, "decrypt", concurrent_write)
    result = SqliteRestoreStore(path, cipher).inspect()
    assert result.accounts == result.authenticated_credentials == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        opened[0].execute("SELECT 1")

    with transaction(path) as writer:
        writer.execute("DELETE FROM schema_migrations WHERE version = 39")
    _refused(path, "schema_incompatible")
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        opened[1].execute("SELECT 1")


@pytest.mark.parametrize("stored", [12, "synthetic malformed credential"])
def test_inspect_rejects_nonblob_credentials_before_decryption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stored: int | str
) -> None:
    path = _database(tmp_path)
    add_account(path, "synthetic")
    with transaction(path) as connection:
        connection.execute("UPDATE connected_accounts SET encrypted_credentials = ?", (stored,))
    cipher = _cipher()

    def refuse_decryption(sealed: bytes) -> str:
        pytest.fail("malformed storage values must never reach decryption")

    monkeypatch.setattr(cipher, "decrypt", refuse_decryption)
    with pytest.raises(RestoreFailure, match=r"^key_mismatch$"):
        SqliteRestoreStore(path, cipher).inspect()
