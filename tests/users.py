"""Users for tests, and SQLite units of work that already hold what their rules need."""

from collections.abc import Sequence
from pathlib import Path

from fastapi.testclient import TestClient

from calendar_sync.application.ports import AdministratorAccess, Clock, UnitOfWorkFactory
from calendar_sync.domain.access import UserId
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.persistence.sqlite import SqliteUnitOfWorkFactory
from calendar_sync.infrastructure.scheduling import SystemClock
from calendar_sync.infrastructure.security import HistoryCipher, SqliteAdminAuth
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


ADMIN_PASSWORD = "correct horse battery staple"


def administrator(access: AdministratorAccess) -> UserId:
    """The installation's first User, created as setup would when there is none yet."""
    if not access.is_configured():
        access.create_admin(ADMIN_PASSWORD)
    session = access.authenticate(ADMIN_PASSWORD)
    assert session is not None
    return session.user_id


def first_user(database: Path) -> UserId:
    """The first User of an installation set up through `administrator` or the Web API."""
    return administrator(SqliteAdminAuth(database))


def sign_in(client: TestClient) -> None:
    """Sign the client in as the first User, setting the installation up if it is not yet."""
    if client.get("/api/v1/setup").json()["administrator_configured"]:
        response = client.post("/api/v1/session", json={"password": ADMIN_PASSWORD})
    else:
        response = client.post("/api/v1/setup/admin", json={"password": ADMIN_PASSWORD})
    assert response.status_code == 200, response.text
