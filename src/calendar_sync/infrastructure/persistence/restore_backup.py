"""Durable, self-contained before-change backups published without replacement."""

import os
import sqlite3
import stat
import tempfile
import time
from contextlib import closing, suppress
from pathlib import Path

from calendar_sync.application.operations.restoration import RestoreFailure
from calendar_sync.infrastructure.persistence.connections import open_connection
from calendar_sync.infrastructure.persistence.restoration import SqliteRestoreStore
from calendar_sync.infrastructure.security import CredentialCipher


def require_backup_path(source: Path, target: Path) -> None:
    try:
        parent = target.parent.absolute()
        info = parent.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o700
            or info.st_uid != os.getuid()
            or any(part.is_symlink() for part in (parent, *parent.parents))
            or target.exists()
            or target.is_symlink()
            or source.resolve() == target.resolve()
        ):
            raise RestoreFailure("backup_unsafe")
    except OSError:
        raise RestoreFailure("backup_unsafe") from None


def publish_backup(source: sqlite3.Connection, target: Path, cipher: CredentialCipher) -> None:
    temporary: Path | None = None
    published = False
    try:
        descriptor, name = tempfile.mkstemp(prefix=".calendar-ghost-restore-", dir=target.parent)
        temporary = Path(name)
        os.close(descriptor)
        _copy_database(source, temporary)
        with temporary.open("rb") as copy:
            os.fsync(copy.fileno())
        SqliteRestoreStore(temporary, cipher).inspect()
        os.link(temporary, target)
        published = True
        temporary.unlink()
        _sync_directory(target.parent)
    except (OSError, sqlite3.Error, RestoreFailure):
        if published:
            with suppress(OSError):
                target.unlink(missing_ok=True)
        raise RestoreFailure("backup_failed") from None
    finally:
        if temporary is not None:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)


def _copy_database(source: sqlite3.Connection, temporary: Path) -> None:
    deadline = time.monotonic() + 30

    def progress(_status: int, _remaining: int, _total: int) -> None:
        if time.monotonic() >= deadline:
            raise RestoreFailure("backup_failed")

    with closing(open_connection(temporary, mode="rw", timeout=0)) as destination:
        source.backup(destination, pages=128, progress=progress, sleep=0.01)
        if destination.execute("PRAGMA journal_mode=DELETE").fetchone()[0] != "delete":
            raise RestoreFailure("backup_failed")
    if any(Path(f"{temporary}{suffix}").exists() for suffix in ("-wal", "-shm")):
        raise RestoreFailure("backup_failed")


def _sync_directory(parent: Path) -> None:
    descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
