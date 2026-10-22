"""Administrator enablement checked atomically against every affected User's usable methods."""

import sqlite3
from pathlib import Path

from calendar_sync.application.identity.administration import AdministratorRequired
from calendar_sync.application.identity.provider_sign_in_ports import (
    LastSignInMethod,
    ProviderAvailability,
    ProviderSignInSetting,
)
from calendar_sync.domain.access import UserId
from calendar_sync.domain.errors import DomainValidationError
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.persistence.provider_methods import enabled_providers


def _require_remaining(
    connection: sqlite3.Connection, provider: str, enabled: frozenset[str]
) -> None:
    rows = connection.execute(
        "SELECT i.user_id, i.provider FROM provider_identities i JOIN users u ON u.id = i.user_id "
        "WHERE u.state = 'active' AND u.password_hash IS NULL AND EXISTS ("
        "SELECT 1 FROM provider_identities affected WHERE affected.user_id = u.id "
        "AND affected.provider = ?)",
        (provider,),
    ).fetchall()
    affected = {str(row[0]) for row in rows}
    remaining = {str(row[0]) for row in rows if row[1] in enabled and row[1] != provider}
    if affected - remaining:
        raise LastSignInMethod


class SqliteProviderSignInSettings:
    def __init__(self, database_path: Path, availability: tuple[ProviderAvailability, ...]) -> None:
        self._database_path = database_path
        self._availability = {item.provider: item for item in availability}

    def list(self) -> tuple[ProviderSignInSetting, ...]:
        with transaction(self._database_path, timeout=0.1) as connection:
            settings = {
                str(row[0]): bool(row[1])
                for row in connection.execute(
                    "SELECT provider, enabled FROM provider_sign_in_settings"
                )
            }
        return tuple(
            ProviderSignInSetting(
                item.provider,
                settings.get(item.provider, False),
                item.available,
                item.reason,
                item.can_verify_email,
            )
            for item in self._availability.values()
        )

    def set_enabled(self, actor: UserId, provider: str, enabled: bool) -> None:
        with transaction(self._database_path, timeout=0.1) as connection:
            connection.execute("BEGIN IMMEDIATE")
            if (
                connection.execute(
                    "SELECT 1 FROM users WHERE id = ? AND state = 'active' "
                    "AND role = 'installation_administrator'",
                    (actor.value,),
                ).fetchone()
                is None
            ):
                raise AdministratorRequired("an active Installation Administrator is required")
            item = self._availability.get(provider)
            if item is None or (enabled and not item.available):
                raise DomainValidationError("provider sign-in is unavailable")
            if not enabled:
                _require_remaining(
                    connection,
                    provider,
                    enabled_providers(connection, tuple(self._availability.values())),
                )
            connection.execute(
                "INSERT INTO provider_sign_in_settings(provider, enabled) VALUES (?, ?) "
                "ON CONFLICT(provider) DO UPDATE SET enabled = excluded.enabled",
                (provider, int(enabled)),
            )
