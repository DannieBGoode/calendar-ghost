"""Users for tests, and SQLite units of work that already hold what their rules need."""

import secrets
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from fastapi.testclient import TestClient

from calendar_sync.application.identity.ports import PasswordHasher, Sessions, UserDirectory
from calendar_sync.application.identity.sign_in import SetUpInstallation
from calendar_sync.application.shared.ports import Clock, IdGenerator
from calendar_sync.application.sync.ports import UnitOfWorkFactory
from calendar_sync.domain.access import UserId
from calendar_sync.domain.accounts import ConnectedAccountState
from calendar_sync.domain.model import ConnectedAccountId, SyncRule
from calendar_sync.infrastructure.clock import SystemClock
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.persistence.memory import (
    InMemoryUnitOfWorkFactory,
    InMemoryUserUnitOfWorkFactory,
)
from calendar_sync.infrastructure.persistence.sqlite.unit_of_work import SqliteUnitOfWorkFactory
from calendar_sync.infrastructure.persistence.users import SqliteSessions, SqliteUserDirectory
from calendar_sync.infrastructure.security import HistoryCipher, ScryptPasswords, token_hash
from tests.helpers import NOW

USER = UserId("user-1")
OTHER_USER = UserId("user-2")
RULE_ACCOUNTS = ("personal-account", "work-account")
"""The accounts `tests.helpers.rule()` uses; a rule's accounts must be its User's."""


def add_user(
    database: Path,
    user: UserId = USER,
    *,
    email: str | None = None,
    role: str = "installation_administrator",
    state: str = "active",
) -> UserId:
    """Record a User, unless one with this identifier exists already."""
    with transaction(database) as connection:
        connection.execute(
            """
            INSERT INTO users (id, email, password_hash, role, state, created_at)
            VALUES (?, ?, 'scrypt$unusable', ?, ?, ?)
            ON CONFLICT(id) DO NOTHING
            """,
            (user.value, email or f"{user.value}@example.test", role, state, NOW.isoformat()),
        )
    return user


def limited_user(
    database: Path, user: UserId = OTHER_USER, *, plan: str | None = None, email: str | None = None
) -> UserId:
    """A User Plans can limit: role `user`, with `plan` as their own Plan when given (it must
    exist). `add_user` records an Installation Administrator, whom no Plan limits."""
    add_user(database, user, email=email, role="user")
    if plan is not None:
        with transaction(database) as connection:
            connection.execute("UPDATE users SET plan_key = ? WHERE id = ?", (plan, user.value))
    return user


def add_account(
    database: Path, account_id: str, user: UserId = USER, *, state: str = "connected"
) -> None:
    """Record a Connected Account without credentials, as authorizing it would."""
    add_user(database, user)
    with transaction(database) as connection:
        connection.execute(
            """
            INSERT INTO connected_accounts (
                id, user_id, provider, display_name, email, encrypted_credentials, state,
                created_at, updated_at
            ) VALUES (?, ?, 'google', 'Synthetic', ?, x'', ?, ?, ?)
            ON CONFLICT(id) DO NOTHING
            """,
            (
                account_id,
                user.value,
                f"{account_id}@example.test",
                state,
                NOW.isoformat(),
                NOW.isoformat(),
            ),
        )


def sqlite_units(
    database: Path,
    clock: Clock | None = None,
    history: HistoryCipher | None = None,
    *,
    user: UserId = USER,
    accounts: Sequence[str] = RULE_ACCOUNTS,
) -> UnitOfWorkFactory:
    """`user`'s units of work over `database`, with the User and `accounts` recorded."""
    add_user(database, user)
    for account in accounts:
        add_account(database, account, user)
    return SqliteUnitOfWorkFactory(database, clock or SystemClock(), history).for_user(user)


def rule_accounts(*rules: SyncRule) -> tuple[str, ...]:
    """The accounts `rules` name, each once, for `memory_units` or `sqlite_units` to record."""
    return tuple(
        dict.fromkeys(
            endpoint.connected_account_id.value
            for each in rules
            for endpoint in (each.source, each.destination)
        )
    )


def memory_units(
    database: InMemoryUnitOfWorkFactory | None = None,
    *,
    user: UserId = USER,
    accounts: Sequence[str] = RULE_ACCOUNTS,
) -> InMemoryUserUnitOfWorkFactory:
    """`user`'s in-memory units of work, with `accounts` recorded as connected, as `sqlite_units`
    records them: the store refuses a rule whose accounts are not its User's."""
    units = (database or InMemoryUnitOfWorkFactory()).for_user(user)
    for account in accounts:
        units.state.accounts.setdefault(
            ConnectedAccountId(account), ConnectedAccountState.CONNECTED
        )
    return units


ADMIN_EMAIL = "admin@example.test"
ADMIN_PASSWORD = "correct horse battery staple"


class _Adapters(Protocol):
    """What setting up the first User needs, as `Adapters` provides it."""

    @property
    def users(self) -> UserDirectory: ...
    @property
    def passwords(self) -> PasswordHasher: ...
    @property
    def sessions(self) -> Sessions: ...
    @property
    def ids(self) -> IdGenerator: ...
    @property
    def clock(self) -> Clock: ...


def administrator(adapters: _Adapters) -> UserId:
    """The installation's first User, set up as the Web API would when there is none yet."""
    if adapters.users.count() == 0:
        SetUpInstallation(
            adapters.users, adapters.passwords, adapters.sessions, adapters.ids, adapters.clock
        ).execute(ADMIN_EMAIL, ADMIN_PASSWORD)
    return adapters.users.list()[0].id


def first_user(database: Path) -> UserId:
    """The first User of an installation, set up through `administrator` or the Web API."""
    users = SqliteUserDirectory(database)
    if users.count() == 0:
        SetUpInstallation(
            users, ScryptPasswords(), SqliteSessions(database, SystemClock()), _Ids(), SystemClock()
        ).execute(ADMIN_EMAIL, ADMIN_PASSWORD)
    return users.list()[0].id


class _Ids:
    def new(self) -> str:
        return str(uuid4())


def sign_in(client: TestClient) -> None:
    """Sign the client in as the first User, setting the installation up if it is not yet."""
    credentials = {"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    if client.get("/api/v1/setup").json()["administrator_configured"]:
        response = client.post("/api/v1/session", json=credentials)
    else:
        response = client.post("/api/v1/setup/admin", json=credentials)
    assert response.status_code == 200, response.text


def session_for(database: Path, user: UserId) -> str:
    """A live session of `user`, as signing in would give them."""
    token = secrets.token_urlsafe(32)
    with transaction(database) as connection:
        connection.execute(
            """
            INSERT INTO user_sessions (token_hash, user_id, created_at, expires_at)
            VALUES (?, ?, '2026-01-01T00:00:00+00:00', '9999-01-01T00:00:00+00:00')
            """,
            (token_hash(token), user.value),
        )
    return token
