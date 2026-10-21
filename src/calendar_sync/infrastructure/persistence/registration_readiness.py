"""Read current operational Open readiness without looking up any User."""

import sqlite3
from pathlib import Path

from calendar_sync.application.identity.identity_email import IdentityEmailSetup
from calendar_sync.application.identity.registration_ports import (
    OpenRegistrationStatus,
    RegistrationStorageUnavailable,
)
from calendar_sync.domain.access import RegistrationPolicy
from calendar_sync.infrastructure.persistence.connections import transaction


def readiness_status(
    connection: sqlite3.Connection, fingerprint: str | None
) -> OpenRegistrationStatus:
    row = connection.execute(
        "SELECT fingerprint, tested_at FROM identity_email_readiness WHERE singleton = 1"
    ).fetchone()
    if row is None:
        raise RegistrationStorageUnavailable
    if fingerprint is None:
        return OpenRegistrationStatus(False, "identity_email_not_configured")
    if row["fingerprint"] != fingerprint or row["tested_at"] is None:
        return OpenRegistrationStatus(False, "identity_email_not_tested")
    return OpenRegistrationStatus(True, None)


class SqliteRegistrationReadiness:
    def __init__(self, database: Path, setup: IdentityEmailSetup) -> None:
        self._database = database
        self._setup = setup

    def status(self) -> OpenRegistrationStatus:
        try:
            with transaction(self._database, timeout=0.1) as connection:
                return readiness_status(connection, self._setup.fingerprint)
        except sqlite3.Error:
            raise RegistrationStorageUnavailable from None

    def public_available(self) -> bool:
        try:
            with transaction(self._database, timeout=0.1) as connection:
                connection.execute("BEGIN")
                row = connection.execute(
                    "SELECT registration_policy FROM installation_settings WHERE singleton = 1"
                ).fetchone()
                return bool(
                    row is not None
                    and row[0] == RegistrationPolicy.OPEN.value
                    and readiness_status(connection, self._setup.fingerprint).available
                )
        except (sqlite3.Error, RegistrationStorageUnavailable):
            return False
