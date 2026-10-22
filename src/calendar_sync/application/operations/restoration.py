"""Offline restoration contracts, independent of runtime service composition."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

from calendar_sync.application.identity.ports import PasswordHasher
from calendar_sync.application.shared.errors import ApplicationError
from calendar_sync.application.shared.ports import Clock

RestoreFailureCode = Literal[
    "key_missing",
    "key_invalid",
    "key_mismatch",
    "database_missing",
    "database_unsafe",
    "schema_incompatible",
    "integrity_failed",
    "foreign_keys_failed",
    "administrator_invalid",
    "backup_unsafe",
    "backup_failed",
    "storage_busy",
    "storage_failed",
    "database_changed",
    "usage_invalid",
    "services_not_acknowledged",
    "password_invalid",
    "password_input_failed",
]


class RestoreFailure(ApplicationError):
    """A fixed safe diagnostic with the offline command's exit status."""

    def __init__(self, code: RestoreFailureCode) -> None:
        super().__init__(code)
        self.code = code
        self.status = (
            2
            if code
            in (
                "usage_invalid",
                "services_not_acknowledged",
                "password_invalid",
                "password_input_failed",
            )
            else 1
        )


@dataclass(frozen=True)
class RestoreInspection:
    schema_version: int
    users: int
    accounts: int
    authenticated_credentials: int


@dataclass(frozen=True)
class RestorePreparation:
    backup_path: Path
    disabled_users: int
    disconnected_accounts: int
    invalidated_records: tuple[tuple[str, int], ...]


class RestoreStore(Protocol):
    def inspect(self) -> RestoreInspection: ...

    def prepare(
        self, backup_path: Path, administrator_id: str, password_hash: str, at: datetime
    ) -> RestorePreparation: ...


@dataclass
class OfflineRestore:
    store: RestoreStore
    passwords: PasswordHasher
    clock: Clock

    def inspect(self) -> RestoreInspection:
        return self.store.inspect()

    def prepare(
        self, backup_path: Path, administrator_id: str, password: str, services_stopped: bool
    ) -> RestorePreparation:
        if not services_stopped:
            raise RestoreFailure("services_not_acknowledged")
        if not 12 <= len(password) <= 256:
            raise RestoreFailure("password_invalid")
        self.store.inspect()
        password_hash = self.passwords.hash(password)
        return self.store.prepare(backup_path, administrator_id, password_hash, self.clock.now())
