"""The in-memory unit of work and SQLite honor the persistence contract."""

import sqlite3
from pathlib import Path

import pytest

from calendar_sync.application.ports import ConnectedAccountState
from calendar_sync.domain.model import ConnectedAccountId
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.persistence.memory import InMemoryUnitOfWorkFactory
from calendar_sync.infrastructure.persistence.sqlite import (
    SqliteUnitOfWorkFactory,
    initialize_database,
)
from calendar_sync.infrastructure.security import CredentialCipher, HistoryCipher
from tests.contracts.persistence import PersistenceContract, PersistenceHarness
from tests.helpers import NOW


class TestInMemoryUnitOfWork(PersistenceContract):
    @pytest.fixture
    def harness(self) -> PersistenceHarness:
        factory = InMemoryUnitOfWorkFactory()

        def connect(account_id: ConnectedAccountId) -> None:
            factory.state.accounts[account_id] = ConnectedAccountState.CONNECTED

        def disconnect(account_id: ConnectedAccountId) -> None:
            factory.state.accounts[account_id] = ConnectedAccountState.DISCONNECTED

        return PersistenceHarness(
            factory,
            connect_account=connect,
            disconnect_account=disconnect,
            refused=(KeyError, ValueError),
        )


class TestSqliteUnitOfWork(PersistenceContract):
    @pytest.fixture
    def harness(self, tmp_path: Path) -> PersistenceHarness:
        database = tmp_path / "calendar-sync.db"
        initialize_database(database)

        def connect(account_id: ConnectedAccountId) -> None:
            with transaction(database) as connection:
                connection.execute(
                    """
                    INSERT INTO connected_accounts (
                        id, provider, display_name, email, encrypted_credentials, state,
                        created_at, updated_at
                    ) VALUES (?, 'google', 'Synthetic', ?, x'', 'connected', ?, ?)
                    """,
                    (
                        account_id.value,
                        f"{account_id.value}@example.test",
                        NOW.isoformat(),
                        NOW.isoformat(),
                    ),
                )

        def disconnect(account_id: ConnectedAccountId) -> None:
            with transaction(database) as connection:
                connection.execute(
                    "UPDATE connected_accounts SET state = 'disconnected' WHERE id = ?",
                    (account_id.value,),
                )

        return PersistenceHarness(
            # Source Observations are sealed, so the store needs a History Cipher to keep them.
            SqliteUnitOfWorkFactory(
                database, history=HistoryCipher(CredentialCipher.generate_key())
            ),
            connect_account=connect,
            disconnect_account=disconnect,
            refused=(sqlite3.IntegrityError,),
        )
