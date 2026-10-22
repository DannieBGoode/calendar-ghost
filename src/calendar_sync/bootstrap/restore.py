"""Offline composition: no application container, API lifespan, or runtime worker."""

import os
from pathlib import Path

from calendar_sync.application.operations.restoration import OfflineRestore, RestoreFailure
from calendar_sync.infrastructure.clock import SystemClock
from calendar_sync.infrastructure.persistence.restoration import SqliteRestoreStore
from calendar_sync.infrastructure.security import (
    CredentialCipher,
    InvalidMasterKey,
    ScryptPasswords,
)
from calendar_sync.interfaces.restore import run as run_interface


def _service(path: Path) -> OfflineRestore:
    key = os.environ.get("CALENDAR_SYNC_MASTER_KEY")
    if not key:
        raise RestoreFailure("key_missing")
    try:
        cipher = CredentialCipher(key)
    except InvalidMasterKey:
        raise RestoreFailure("key_invalid") from None
    return OfflineRestore(SqliteRestoreStore(path, cipher), ScryptPasswords(), SystemClock())


def run() -> int:
    return run_interface(None, _service)
