from __future__ import annotations

import sqlite3
from pathlib import Path

from calendar_sync.application.errors import (
    ConnectedAccountDisconnected,
    ConnectedAccountNotFound,
)
from calendar_sync.application.ports import (
    Clock,
    ConnectedAccount,
    ConnectedAccountState,
    IdGenerator,
)
from calendar_sync.application.providers import ProviderKind
from calendar_sync.domain.model import ConnectedAccountId
from calendar_sync.infrastructure.identifiers import UuidIdGenerator
from calendar_sync.infrastructure.scheduling import SystemClock
from calendar_sync.infrastructure.security import CredentialCipher


class SqliteConnectedAccountStore:
    """Connected Accounts with their provider credentials, encrypted by the Master Key."""

    def __init__(
        self,
        database_path: Path,
        cipher: CredentialCipher,
        clock: Clock | None = None,
        ids: IdGenerator | None = None,
    ) -> None:
        self._database_path = database_path
        self._cipher = cipher
        self._clock = clock or SystemClock()
        self._ids = ids or UuidIdGenerator()

    def list(self) -> tuple[ConnectedAccount, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, provider, display_name, email, state, avatar_url, updated_at
                FROM connected_accounts ORDER BY email
                """
            ).fetchall()
        return tuple(_account_from_row(row) for row in rows)

    def get(self, account_id: ConnectedAccountId) -> ConnectedAccount | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, provider, display_name, email, state, avatar_url, updated_at
                FROM connected_accounts WHERE id = ?
                """,
                (account_id.value,),
            ).fetchone()
        return _account_from_row(row) if row is not None else None

    def is_connected(self, account_id: ConnectedAccountId) -> bool:
        account = self.get(account_id)
        return account is not None and account.state is ConnectedAccountState.CONNECTED

    def save(
        self,
        display_name: str,
        email: str,
        credential_json: str,
        *,
        provider: ProviderKind,
        avatar_url: str | None = None,
    ) -> ConnectedAccount:
        """Connect an account, or reauthorize the one with this provider and email."""
        now = self._clock.now().isoformat()
        account_id = self._ids.new()
        encrypted = self._cipher.encrypt(credential_json)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO connected_accounts (
                    id, provider, display_name, email, avatar_url, encrypted_credentials,
                    state, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'connected', ?, ?)
                ON CONFLICT(provider, email) DO UPDATE SET
                    display_name = excluded.display_name,
                    avatar_url = excluded.avatar_url,
                    encrypted_credentials = excluded.encrypted_credentials,
                    state = 'connected',
                    updated_at = excluded.updated_at
                """,
                (account_id, provider.value, display_name, email, avatar_url, encrypted, now, now),
            )
            row = connection.execute(
                """
                SELECT id, provider, display_name, email, state, avatar_url, updated_at
                FROM connected_accounts WHERE provider = ? AND email = ?
                """,
                (provider.value, email),
            ).fetchone()
        assert row is not None
        return _account_from_row(row)

    def provider_of(self, account_id: ConnectedAccountId) -> ProviderKind | None:
        """The provider a Connected or Disconnected Account belongs to; None if it doesn't exist."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT provider FROM connected_accounts WHERE id = ?", (account_id.value,)
            ).fetchone()
        return ProviderKind(str(row["provider"])) if row is not None else None

    def credential_json(self, account_id: ConnectedAccountId) -> str:
        """The decrypted credentials of a connected account; never log or persist them."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT encrypted_credentials, state FROM connected_accounts WHERE id = ?",
                (account_id.value,),
            ).fetchone()
        if row is None:
            raise ConnectedAccountNotFound(f"connected account {account_id.value} does not exist")
        if str(row["state"]) != ConnectedAccountState.CONNECTED.value:
            raise ConnectedAccountDisconnected(
                "this Google account is disconnected; reauthorize it from Settings"
            )
        return self._cipher.decrypt(bytes(row["encrypted_credentials"]))

    def replace_credentials(
        self, account_id: ConnectedAccountId, expected_json: str, credential_json: str
    ) -> bool:
        """Keep refreshed credentials, unless the account was reauthorized or disconnected since.

        It is not an authorization, so the account's authorization time stays as it was.
        """
        encrypted = self._cipher.encrypt(credential_json)
        with self._connect() as connection:
            # Held from the read to the write, so a reauthorization cannot land in between.
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT encrypted_credentials, state FROM connected_accounts WHERE id = ?",
                (account_id.value,),
            ).fetchone()
            if (
                row is None
                or str(row["state"]) != ConnectedAccountState.CONNECTED.value
                or self._cipher.decrypt(bytes(row["encrypted_credentials"])) != expected_json
            ):
                return False
            connection.execute(
                "UPDATE connected_accounts SET encrypted_credentials = ? WHERE id = ?",
                (encrypted, account_id.value),
            )
        return True

    def disconnect(self, account_id: ConnectedAccountId) -> ConnectedAccount:
        now = self._clock.now().isoformat()
        cleared_credentials = self._cipher.encrypt("{}")
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, provider, display_name, email, avatar_url FROM connected_accounts
                WHERE id = ?
                """,
                (account_id.value,),
            ).fetchone()
            if row is None:
                raise ConnectedAccountNotFound(
                    f"connected account {account_id.value} does not exist"
                )
            connection.execute(
                """
                UPDATE connected_accounts
                SET encrypted_credentials = ?, state = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    cleared_credentials,
                    ConnectedAccountState.DISCONNECTED.value,
                    now,
                    account_id.value,
                ),
            )
        return ConnectedAccount(
            ConnectedAccountId(str(row["id"])),
            str(row["display_name"]),
            str(row["email"]),
            ConnectedAccountState.DISCONNECTED,
            _optional_text(row["avatar_url"]),
            provider=ProviderKind(str(row["provider"])),
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        return connection


def _account_from_row(row: sqlite3.Row) -> ConnectedAccount:
    state = ConnectedAccountState(str(row["state"]))
    # Only connecting, reauthorizing, and disconnecting write the row, so a connected account's
    # last update is when it was last authorized.
    connected = state is ConnectedAccountState.CONNECTED
    return ConnectedAccount(
        ConnectedAccountId(str(row["id"])),
        str(row["display_name"]),
        str(row["email"]),
        state,
        _optional_text(row["avatar_url"]),
        str(row["updated_at"]) if connected else None,
        provider=ProviderKind(str(row["provider"])),
    )


def _optional_text(value: object) -> str | None:
    return value.strip() or None if isinstance(value, str) else None
