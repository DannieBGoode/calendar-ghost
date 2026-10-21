"""The in-memory unit of work and SQLite honor the persistence contract."""

from datetime import datetime
from pathlib import Path

import pytest

from calendar_sync.domain.access import UserId
from calendar_sync.domain.accounts import ConnectedAccountState, ProviderKind
from calendar_sync.domain.model import ConnectedAccountId, SyncRuleId
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.persistence.health import SqliteIncidentRepository
from calendar_sync.infrastructure.persistence.installation import (
    SqliteInstallationUnitOfWorkFactory,
)
from calendar_sync.infrastructure.persistence.memory import (
    InMemoryIncidentRepository,
    InMemoryUnitOfWorkFactory,
    raise_instant_request,
)
from calendar_sync.infrastructure.persistence.migrations import initialize_database
from calendar_sync.infrastructure.persistence.sqlite.unit_of_work import SqliteUnitOfWorkFactory
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
            # As SQLite's accounts, which the contract's helpers connect as Google accounts.
            state.providers[account_id] = ProviderKind.GOOGLE
            state.authorized_at[account_id] = NOW

        def disconnect(account_id: ConnectedAccountId, user: UserId) -> None:
            database.for_user(user).state.accounts[account_id] = ConnectedAccountState.DISCONNECTED

        # The accounts the contract's rules use, recorded as the SQLite harness records them.
        for account in RULE_ACCOUNTS:
            connect(ConnectedAccountId(account), USER)

        def request_run(user: UserId, rule_id: SyncRuleId, at: datetime) -> None:
            raise_instant_request(database.for_user(user).state, rule_id, at)

        def prefer(user: UserId, wanted: bool) -> None:
            off = database.database.instant_sync_off
            if wanted:
                off.discard(user)
            else:
                off.add(user)

        def issue_token(user: UserId, revoked: bool) -> None:
            tokens = database.database.unrevoked_tokens
            tokens[user] = tokens.get(user, 0) + (0 if revoked else 1)

        return PersistenceHarness(
            database.for_user,
            connect=connect,
            disconnect=disconnect,
            disable=database.database.disabled.add,
            installation=database.installation(),
            incidents=lambda user: InMemoryIncidentRepository(database.database, user),
            request_run=request_run,
            prefer=prefer,
            issue_token=issue_token,
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

        def request_run(user: UserId, rule_id: SyncRuleId, at: datetime) -> None:
            # As the Watch Notice inbox raises it: a handled request starts waiting again.
            with transaction(database) as connection:
                connection.execute(
                    """
                    INSERT INTO instant_sync_requests (
                        rule_id, user_id, requested_seq, handled_seq, first_requested_at,
                        last_requested_at
                    ) VALUES (?, ?, 1, 0, ?, ?)
                    ON CONFLICT (rule_id) DO UPDATE SET
                        first_requested_at = CASE WHEN requested_seq = handled_seq
                            THEN excluded.first_requested_at
                            ELSE MIN(first_requested_at, excluded.first_requested_at) END,
                        requested_seq = requested_seq + 1,
                        last_requested_at = MAX(last_requested_at, excluded.last_requested_at)
                    """,
                    (rule_id.value, user.value, at.isoformat(), at.isoformat()),
                )

        def prefer(user: UserId, wanted: bool) -> None:
            with transaction(database) as connection:
                connection.execute(
                    "UPDATE users SET instant_sync = ? WHERE id = ?", (int(wanted), user.value)
                )

        def issue_token(user: UserId, revoked: bool) -> None:
            with transaction(database) as connection:
                number = connection.execute("SELECT COUNT(*) FROM integration_tokens").fetchone()[0]
                connection.execute(
                    """
                    INSERT INTO integration_tokens (
                        id, user_id, name, token_hash, scopes, created_at, revoked_at
                    ) VALUES (?, ?, 'Monitor', ?, 'status:read', ?, ?)
                    """,
                    (
                        f"token-{number}",
                        user.value,
                        f"hash-{number}",
                        NOW.isoformat(),
                        NOW.isoformat() if revoked else None,
                    ),
                )

        return PersistenceHarness(
            # Source Observations are sealed, so the store needs a History Cipher to keep them.
            SqliteUnitOfWorkFactory(
                database, history=HistoryCipher(CredentialCipher.generate_key())
            ).for_user,
            connect=connect,
            disconnect=disconnect,
            disable=disable,
            installation=SqliteInstallationUnitOfWorkFactory(database),
            incidents=lambda user: SqliteIncidentRepository(database, user),
            request_run=request_run,
            prefer=prefer,
            issue_token=issue_token,
        )
