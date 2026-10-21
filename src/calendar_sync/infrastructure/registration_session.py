"""Translate registration response read faults without changing ordinary identity recovery."""

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from calendar_sync.application.identity.errors import SignInStorageUnavailable
from calendar_sync.application.identity.ports import UserDirectory
from calendar_sync.application.operations.instant_sync import InstantSyncStatus
from calendar_sync.domain.access import User, UserId
from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.model import ConnectedAccountId
from calendar_sync.domain.watches import Availability
from calendar_sync.infrastructure.persistence.connections import transaction


@dataclass(frozen=True, slots=True)
class RegistrationSessionReads:
    users: UserDirectory
    status: InstantSyncStatus
    sends_email: bool

    @property
    def instant_sync_status(self) -> Self:
        return self

    def get(self, user: UserId) -> User | None:
        try:
            return self.users.get(user)
        except sqlite3.Error:
            raise SignInStorageUnavailable from None

    def availability(self, user: UserId) -> Availability:
        try:
            return self.status.availability(user)
        except sqlite3.Error:
            raise SignInStorageUnavailable from None


@dataclass(frozen=True, slots=True)
class RegistrationProviderKinds:
    """Provider Kinds for account IDs from the signed-in User's scoped watches only.

    Like provider routing, this reads metadata alone, with no access to credentials.
    """

    database: Path

    def provider_of(self, account: ConnectedAccountId) -> ProviderKind | None:
        with transaction(self.database, timeout=0.1) as connection:
            row = connection.execute(
                "SELECT provider FROM connected_accounts WHERE id = ?", (account.value,)
            ).fetchone()
        return ProviderKind(str(row["provider"])) if row is not None else None
