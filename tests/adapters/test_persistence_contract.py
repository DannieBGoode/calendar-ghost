"""The in-memory unit of work and SQLite honor the persistence contract."""

import sqlite3
from pathlib import Path

import pytest

from calendar_sync.application.ports import ConnectedAccountState
from calendar_sync.domain.access import UserId
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
from tests.users import OTHER_USER, RULE_ACCOUNTS, USER, add_account, add_user


class TestInMemoryUnitOfWork(PersistenceContract):
    @pytest.fixture
    def harness(self) -> PersistenceHarness:
        database = InMemoryUnitOfWorkFactory()

        def connect(account_id: ConnectedAccountId, user: UserId) -> None:
            state = database.for_user(user).state
            state.accounts[account_id] = ConnectedAccountState.CONNECTED
            state.authorized_at[account_id] = NOW

        def disconnect(account_id: ConnectedAccountId, user: UserId) -> None:
            database.for_user(user).state.accounts[account_id] = ConnectedAccountState.DISCONNECTED

        return PersistenceHarness(
            database.for_user,
            connect=connect,
            disconnect=disconnect,
            disable=database.database.disabled.add,
            refused=(KeyError, ValueError),
        )


class TestSqliteUnitOfWork(PersistenceContract):
    @pytest.fixture
    def harness(self, tmp_path: Path) -> PersistenceHarness:
        database = tmp_path / "calendar-sync.db"
        initialize_database(database)
        # The accounts the contract's rules use; SQLite refuses a rule without its accounts.
        for account in RULE_ACCOUNTS:
            add_account(database, account, USER)
        add_user(database, OTHER_USER)

        def connect(account_id: ConnectedAccountId, user: UserId) -> None:
            add_account(database, account_id.value, user)
            with transaction(database) as connection:
                connection.execute(
                    "UPDATE connected_accounts SET state = 'connected' "
                    "WHERE id = ? AND user_id = ?",
                    (account_id.value, user.value),
                )

        def disconnect(account_id: ConnectedAccountId, user: UserId) -> None:
            with transaction(database) as connection:
                connection.execute(
                    "UPDATE connected_accounts SET state = 'disconnected' "
                    "WHERE id = ? AND user_id = ?",
                    (account_id.value, user.value),
                )

        def disable(user: UserId) -> None:
            with transaction(database) as connection:
                connection.execute(
                    "UPDATE users SET state = 'disabled' WHERE id = ?", (user.value,)
                )

        return PersistenceHarness(
            # Source Observations are sealed, so the store needs a History Cipher to keep them.
            SqliteUnitOfWorkFactory(
                database, history=HistoryCipher(CredentialCipher.generate_key())
            ).for_user,
            connect=connect,
            disconnect=disconnect,
            disable=disable,
            refused=(sqlite3.IntegrityError,),
        )
