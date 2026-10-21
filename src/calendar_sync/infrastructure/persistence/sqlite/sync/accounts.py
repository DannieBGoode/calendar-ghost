from __future__ import annotations

import sqlite3
from collections.abc import Collection, Sequence
from datetime import UTC, datetime

from calendar_sync.application.shared.ports import Clock
from calendar_sync.application.sync.account_ports import DiscoveredCalendar
from calendar_sync.domain.access import UserId
from calendar_sync.domain.accounts import ConnectedAccountState, ProviderKind
from calendar_sync.domain.model import CalendarEndpoint, CalendarId, ConnectedAccountId


class SqliteConnectedAccountRecords:
    def __init__(self, connection: sqlite3.Connection, user_id: UserId) -> None:
        self._connection = connection
        self._user = user_id.value

    def state(self, account_id: ConnectedAccountId) -> ConnectedAccountState | None:
        row = self._connection.execute(
            "SELECT state FROM connected_accounts WHERE id = ? AND user_id = ?",
            (account_id.value, self._user),
        ).fetchone()
        return ConnectedAccountState(str(row["state"])) if row else None

    def lapse(self, account_id: ConnectedAccountId, *, attempted_at: datetime) -> bool:
        # One statement, so a Reauthorization cannot land between the check and the write. A
        # connected account's last update is when it was last authorized. Both times are UTC ISO
        # 8601 text, which orders as the instants do, to the microsecond; julianday would round
        # to the millisecond. The lapse keeps the start of the latest refused request.
        attempted = attempted_at.astimezone(UTC).isoformat()
        cursor = self._connection.execute(
            """
            UPDATE connected_accounts
            SET authorization_lapsed_at = MAX(COALESCE(authorization_lapsed_at, ?), ?)
            WHERE id = ? AND user_id = ? AND state = ? AND updated_at <= ?
            """,
            (
                attempted,
                attempted,
                account_id.value,
                self._user,
                ConnectedAccountState.CONNECTED.value,
                attempted,
            ),
        )
        return cursor.rowcount == 1

    def clear_lapse(self, account_id: ConnectedAccountId, *, requested_before: datetime) -> bool:
        cursor = self._connection.execute(
            """
            UPDATE connected_accounts SET authorization_lapsed_at = NULL
            WHERE id = ? AND user_id = ? AND authorization_lapsed_at <= ?
            """,
            (account_id.value, self._user, requested_before.astimezone(UTC).isoformat()),
        )
        return cursor.rowcount == 1

    def authorized(self, account_id: ConnectedAccountId) -> bool:
        row = self._connection.execute(
            """
            SELECT 1 FROM connected_accounts
            WHERE id = ? AND user_id = ? AND state = ? AND authorization_lapsed_at IS NULL
            """,
            (account_id.value, self._user, ConnectedAccountState.CONNECTED.value),
        ).fetchone()
        return row is not None

    def lapsed(self) -> dict[ConnectedAccountId, ProviderKind]:
        rows = self._connection.execute(
            """
            SELECT id, provider FROM connected_accounts
            WHERE user_id = ? AND state = ? AND authorization_lapsed_at IS NOT NULL
            ORDER BY id
            """,
            (self._user, ConnectedAccountState.CONNECTED.value),
        ).fetchall()
        return {ConnectedAccountId(str(row[0])): ProviderKind(str(row[1])) for row in rows}

    def delete_disconnected(self, account_id: ConnectedAccountId) -> bool:
        # The first write of the transaction takes SQLite's write lock until commit or rollback.
        cursor = self._connection.execute(
            "DELETE FROM connected_accounts WHERE id = ? AND user_id = ? AND state = ?",
            (account_id.value, self._user, ConnectedAccountState.DISCONNECTED.value),
        )
        if cursor.rowcount != 1:
            return False
        # The account's own Incidents, such as its Lapsed Authorization, go with it; its rules
        # take theirs when they are purged.
        self._connection.execute(
            "DELETE FROM incidents WHERE account_id = ? AND rule_id IS NULL AND user_id = ?",
            (account_id.value, self._user),
        )
        return True


class SqliteCalendarNameRepository:
    def __init__(self, connection: sqlite3.Connection, user_id: UserId, clock: Clock) -> None:
        self._connection = connection
        self._user = user_id.value
        self._clock = clock

    def remember(
        self, account_id: ConnectedAccountId, calendars: Sequence[DiscoveredCalendar]
    ) -> None:
        now = self._clock.now().isoformat()
        # Selecting from the account row records nothing for an account deleted meanwhile, or
        # for another User's.
        self._connection.executemany(
            """
            INSERT INTO calendar_names (
                connected_account_id, calendar_id, name, updated_at, user_id
            )
            SELECT id, ?, ?, ?, user_id FROM connected_accounts WHERE id = ? AND user_id = ?
            ON CONFLICT(connected_account_id, calendar_id) DO UPDATE SET
                name = excluded.name,
                updated_at = excluded.updated_at
            WHERE name != excluded.name
            """,
            [
                (calendar.id, calendar.name, now, account_id.value, self._user)
                for calendar in calendars
            ],
        )

    def names(self, endpoints: Collection[CalendarEndpoint]) -> dict[CalendarEndpoint, str]:
        wanted = set(endpoints)
        if not wanted:
            return {}
        rows = self._connection.execute(
            "SELECT connected_account_id, calendar_id, name FROM calendar_names WHERE user_id = ?",
            (self._user,),
        )
        named = (
            (
                CalendarEndpoint(
                    ConnectedAccountId(str(row["connected_account_id"])),
                    CalendarId(str(row["calendar_id"])),
                ),
                str(row["name"]),
            )
            for row in rows
        )
        return {endpoint: name for endpoint, name in named if endpoint in wanted}
