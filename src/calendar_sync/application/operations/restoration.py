"""Offline restoration contracts, independent of runtime service composition."""

from dataclasses import dataclass
from typing import Literal, Protocol

from calendar_sync.application.shared.errors import ApplicationError

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


class RestoreStore(Protocol):
    def inspect(self) -> RestoreInspection: ...
