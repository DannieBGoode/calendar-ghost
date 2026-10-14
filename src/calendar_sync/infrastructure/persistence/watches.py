"""SQLite storage of each User's Calendar Watches, Watch Registrations, and Instant Sync Requests.

Every change of a registration's state names the state it leaves, in one statement, so a writer
that comes late changes nothing: a receipt for a registration no longer being created never brings
it back, and upkeep clears a renewal request only while it still holds the time upkeep read.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

from calendar_sync.application.sync.watch_ports import PendingRequest, Receipt
from calendar_sync.domain.access import UserId
from calendar_sync.domain.model import CalendarId, ConnectedAccountId, SyncRuleId
from calendar_sync.domain.watches import (
    CREATION_DEADLINE,
    CalendarWatch,
    CalendarWatchId,
    RegistrationState,
    WatchRegistration,
    WatchRegistrationId,
    WatchScope,
)
from calendar_sync.infrastructure.persistence.refusals import refusals


def stored_time(value: datetime) -> str:
    """UTC ISO 8601 text, which orders as the instants do, to the microsecond."""
    return value.astimezone(UTC).isoformat()


def _stored(value: datetime | None) -> str | None:
    return None if value is None else stored_time(value)


def _read(value: object) -> datetime | None:
    return None if value is None else datetime.fromisoformat(str(value))


class SqliteCalendarWatchRepository:
    def __init__(self, connection: sqlite3.Connection, user_id: UserId) -> None:
        self._connection = connection
        self._user = user_id.value

    def list(self) -> Sequence[CalendarWatch]:
        coverage: dict[str, set[CalendarId]] = {}
        for row in self._connection.execute(
            "SELECT watch_id, calendar_id FROM watch_coverage WHERE user_id = ?", (self._user,)
        ):
            covered = coverage.setdefault(str(row["watch_id"]), set())
            covered.add(CalendarId(str(row["calendar_id"])))
        rows = self._connection.execute(
            "SELECT * FROM calendar_watches WHERE user_id = ? ORDER BY id", (self._user,)
        ).fetchall()
        return tuple(
            watch_from_row(row, frozenset(coverage.get(str(row["id"]), ()))) for row in rows
        )

    def registrations(self) -> Sequence[WatchRegistration]:
        rows = self._connection.execute(
            """
            SELECT * FROM watch_registrations WHERE user_id = ?
            ORDER BY watch_id, created_at, id
            """,
            (self._user,),
        ).fetchall()
        return tuple(registration_from_row(row) for row in rows)

    def add(self, watch: CalendarWatch) -> None:
        # The reference to the account names this User, so another User's account is refused.
        with refusals():
            self._connection.execute(
                """
                INSERT INTO calendar_watches (
                    id, user_id, account_id, scope_key, retry_at, failures
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    watch.id.value,
                    self._user,
                    watch.account.value,
                    watch.scope.key,
                    _stored(watch.retry_at),
                    watch.failures,
                ),
            )
        self.set_coverage(watch.id, watch.coverage)

    def set_coverage(self, watch_id: CalendarWatchId, coverage: frozenset[CalendarId]) -> None:
        owned = (watch_id.value, self._user)
        self._connection.execute(
            "DELETE FROM watch_coverage WHERE watch_id = ? AND user_id = ?", owned
        )
        # Selecting from the watch records nothing for another User's.
        self._connection.executemany(
            """
            INSERT INTO watch_coverage (watch_id, user_id, calendar_id)
            SELECT id, user_id, ? FROM calendar_watches WHERE id = ? AND user_id = ?
            """,
            [
                (calendar.value, *owned)
                for calendar in sorted(coverage, key=lambda calendar: calendar.value)
            ],
        )

    def set_retry(
        self, watch_id: CalendarWatchId, retry_at: datetime | None, failures: int
    ) -> None:
        self._connection.execute(
            "UPDATE calendar_watches SET retry_at = ?, failures = ? WHERE id = ? AND user_id = ?",
            (_stored(retry_at), failures, watch_id.value, self._user),
        )

    def remove(self, watch_id: CalendarWatchId) -> None:
        # Its coverage and registrations refer to it with ON DELETE CASCADE.
        self._connection.execute(
            "DELETE FROM calendar_watches WHERE id = ? AND user_id = ?",
            (watch_id.value, self._user),
        )

    def add_registration(self, registration: WatchRegistration) -> None:
        # The reference to the watch names this User, so another User's watch is refused.
        with refusals():
            self._connection.execute(
                """
                INSERT INTO watch_registrations (
                    id, watch_id, user_id, state, address, token_hash, created_at,
                    requested_until, handle, expires_at, confirmed_at, renew_at,
                    renew_requested_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    registration.id.value,
                    registration.watch_id.value,
                    self._user,
                    registration.state.value,
                    registration.address,
                    registration.token_hash,
                    stored_time(registration.created_at),
                    stored_time(registration.requested_until),
                    registration.handle,
                    _stored(registration.expires_at),
                    _stored(registration.confirmed_at),
                    _stored(registration.renew_at),
                    _stored(registration.renew_requested_at),
                ),
            )

    def record_receipt(
        self,
        registration_id: WatchRegistrationId,
        receipt: Receipt,
        renew_at: datetime,
        at: datetime,
    ) -> bool:
        # A notice may have confirmed it before the provider answered; that confirmation stands.
        cursor = self._connection.execute(
            """
            UPDATE watch_registrations SET
                state = :live, handle = :handle, expires_at = :expires_at, renew_at = :renew_at,
                confirmed_at = CASE WHEN :confirmed THEN COALESCE(confirmed_at, :at)
                    ELSE confirmed_at END
            WHERE id = :id AND user_id = :user AND state = :creating
            """,
            {
                "live": RegistrationState.LIVE.value,
                "handle": receipt.handle,
                "expires_at": stored_time(receipt.expires_at),
                "renew_at": stored_time(renew_at),
                "confirmed": receipt.confirmed,
                "at": stored_time(at),
                "id": registration_id.value,
                "user": self._user,
                "creating": RegistrationState.CREATING.value,
            },
        )
        return cursor.rowcount == 1

    def record_extension(
        self,
        registration_id: WatchRegistrationId,
        expires_at: datetime,
        renew_at: datetime,
        seen_request: datetime | None,
    ) -> bool:
        # A renewal the provider asked for after upkeep read `seen_request` is kept for the next.
        cursor = self._connection.execute(
            """
            UPDATE watch_registrations SET
                expires_at = ?, renew_at = ?,
                renew_requested_at = CASE WHEN renew_requested_at IS ? THEN NULL
                    ELSE renew_requested_at END
            WHERE id = ? AND user_id = ? AND state = ?
            """,
            (
                stored_time(expires_at),
                stored_time(renew_at),
                _stored(seen_request),
                registration_id.value,
                self._user,
                RegistrationState.LIVE.value,
            ),
        )
        return cursor.rowcount == 1

    def retire(self, registration_id: WatchRegistrationId) -> bool:
        cursor = self._connection.execute(
            "UPDATE watch_registrations SET state = ? WHERE id = ? AND user_id = ? AND state = ?",
            (
                RegistrationState.RETIRING.value,
                registration_id.value,
                self._user,
                RegistrationState.LIVE.value,
            ),
        )
        return cursor.rowcount == 1

    def abandon(self, registration_id: WatchRegistrationId) -> bool:
        # From any state; whether this User has the registration.
        cursor = self._connection.execute(
            "UPDATE watch_registrations SET state = ? WHERE id = ? AND user_id = ?",
            (RegistrationState.ABANDONED.value, registration_id.value, self._user),
        )
        return cursor.rowcount == 1

    def delete_registration(self, registration_id: WatchRegistrationId) -> None:
        self._connection.execute(
            "DELETE FROM watch_registrations WHERE id = ? AND user_id = ?",
            (registration_id.value, self._user),
        )


class SqliteInstantSyncRequestRepository:
    """One User's Instant Sync Requests. The Watch Notice inbox raises them outside any unit of
    work; a unit of work reads and acknowledges them."""

    def __init__(self, connection: sqlite3.Connection, user_id: UserId) -> None:
        self._connection = connection
        self._user = user_id.value

    def pending(self) -> Sequence[PendingRequest]:
        rows = self._connection.execute(
            """
            SELECT * FROM instant_sync_requests
            WHERE user_id = ? AND requested_seq > handled_seq
            ORDER BY rule_id
            """,
            (self._user,),
        ).fetchall()
        return tuple(request_from_row(row) for row in rows)

    def acknowledge(self, rule_id: SyncRuleId, seq: int, ran_at: datetime) -> None:
        # One statement that never lowers what was handled: a notice during the run raised
        # requested_seq past `seq`, so another run follows.
        self._connection.execute(
            """
            UPDATE instant_sync_requests SET handled_seq = MAX(handled_seq, ?), last_run_at = ?
            WHERE rule_id = ? AND user_id = ?
            """,
            (seq, stored_time(ran_at), rule_id.value, self._user),
        )


def watch_from_row(
    row: sqlite3.Row, coverage: frozenset[CalendarId] = frozenset()
) -> CalendarWatch:
    return CalendarWatch(
        id=CalendarWatchId(str(row["id"])),
        account=ConnectedAccountId(str(row["account_id"])),
        scope=WatchScope(str(row["scope_key"])),
        coverage=coverage,
        retry_at=_read(row["retry_at"]),
        failures=int(row["failures"]),
    )


def registration_from_row(row: sqlite3.Row) -> WatchRegistration:
    return WatchRegistration(
        id=WatchRegistrationId(str(row["id"])),
        watch_id=CalendarWatchId(str(row["watch_id"])),
        state=RegistrationState(str(row["state"])),
        address=str(row["address"]),
        token_hash=str(row["token_hash"]),
        created_at=datetime.fromisoformat(str(row["created_at"])),
        requested_until=datetime.fromisoformat(str(row["requested_until"])),
        handle=None if row["handle"] is None else str(row["handle"]),
        expires_at=_read(row["expires_at"]),
        confirmed_at=_read(row["confirmed_at"]),
        renew_at=_read(row["renew_at"]),
        renew_requested_at=_read(row["renew_requested_at"]),
    )


def request_from_row(row: sqlite3.Row) -> PendingRequest:
    return PendingRequest(
        rule_id=SyncRuleId(str(row["rule_id"])),
        requested_seq=int(row["requested_seq"]),
        handled_seq=int(row["handled_seq"]),
        first_requested_at=datetime.fromisoformat(str(row["first_requested_at"])),
        last_requested_at=datetime.fromisoformat(str(row["last_requested_at"])),
        last_run_at=_read(row["last_run_at"]),
    )


def upkeep_due(
    watches: Iterable[CalendarWatch], registrations: Iterable[WatchRegistration]
) -> datetime | None:
    """When upkeep next has work for one User's watches; None when nothing is planned."""
    retries = (watch.retry_at for watch in watches)
    moments = [moment for moment in retries if moment is not None]
    moments.extend(moment for registration in registrations for moment in _due(registration))
    return min(moments, default=None)


def _due(registration: WatchRegistration) -> tuple[datetime, ...]:
    """A creation deadline, a renewal asked for or planned, or the end of the registration, after
    which upkeep deletes it (`WatchRegistration.gone`)."""
    if registration.state is RegistrationState.CREATING:
        return (registration.created_at + CREATION_DEADLINE,)
    if registration.state is RegistrationState.LIVE:
        asked, planned, ends = (
            registration.renew_requested_at,
            registration.renew_at,
            registration.expires_at,
        )
        return tuple(moment for moment in (asked, planned, ends) if moment is not None)
    return (registration.expires_at or registration.requested_until,)
