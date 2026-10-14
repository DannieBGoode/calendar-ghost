"""Every User's Watch Notices, recorded where they land (ADR 0029, amended by ADR 0036).

Besides the installation-wide unit of work, this is the one reader that crosses Users. It reads
and writes only Watch Registrations, Instant Sync Requests, and Delivery Evidence, in one short
write transaction per request, and makes no provider call. A notice proves itself by its
registration's secret token, compared by hash in constant time; one that does not changes nothing.
"""

from __future__ import annotations

import hmac
import sqlite3
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path

from calendar_sync.application.operations.ports import InboxBusy
from calendar_sync.application.sync.watch_ports import NoticeKind, WatchNotice
from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.model import SyncRuleState
from calendar_sync.domain.watches import DeliveryEvidence, RegistrationState, token_hash
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.persistence.watches import stored_time

INBOX_LOCK_WAIT_SECONDS = 1.0
"""How long a notice waits for another writer before the provider is asked to send it again."""
EVIDENCE_REFRESH = timedelta(minutes=1)
"""How often notices refresh a provider's success evidence, so a busy calendar rarely writes it."""
_BUSY = frozenset({"SQLITE_BUSY", "SQLITE_LOCKED"})


def presents(notice: WatchNotice, stored_hash: str, stored_handle: str | None) -> bool:
    """Whether `notice` presents its registration's token, and its handle when both have one; a
    registration still being created has no handle yet. Both compare in constant time."""
    token = hmac.compare_digest(token_hash(notice.token).encode(), stored_hash.encode())
    handle = (
        notice.handle is None
        or stored_handle is None
        or hmac.compare_digest(notice.handle.encode(), stored_handle.encode())
    )
    return token and handle


class SqliteWatchNoticeInbox:
    def __init__(self, database_path: Path, lock_wait: float = INBOX_LOCK_WAIT_SECONDS) -> None:
        self._database_path = database_path
        self._lock_wait = lock_wait

    def record(
        self,
        notices: Sequence[WatchNotice],
        provider: ProviderKind,
        address_base: str,
        at: datetime,
    ) -> int:
        try:
            with transaction(self._database_path, timeout=self._lock_wait) as connection:
                # The write lock first, so what is read is what is written.
                connection.execute("BEGIN IMMEDIATE")
                return _record(connection, notices, provider, address_base, at)
        except sqlite3.OperationalError as error:
            if error.sqlite_errorname not in _BUSY:
                raise
            raise InboxBusy("the store stayed locked; the notice is to be sent again") from error


def _record(
    connection: sqlite3.Connection,
    notices: Sequence[WatchNotice],
    provider: ProviderKind,
    address_base: str,
    at: datetime,
) -> int:
    requested, delivered = 0, False
    # A batch may repeat one notice; it counts once.
    for notice in dict.fromkeys(notices):
        found = _authentic(connection, notice, provider)
        if found is None:
            continue
        # Only a notice sent to the current address proves that the provider reaches it.
        delivered = delivered or str(found["address"]).startswith(f"{address_base}/")
        requested += _apply(connection, found, notice.kind, stored_time(at))
    if delivered:
        _refresh_success(connection, provider, address_base, at)
    return requested


def _authentic(
    connection: sqlite3.Connection, notice: WatchNotice, provider: ProviderKind
) -> sqlite3.Row | None:
    """The registration `notice` names, when the notice proves itself and the registration is
    `provider`'s and not abandoned. An abandoned one is recognized and ignored."""
    row: sqlite3.Row | None = connection.execute(
        """
        SELECT registration.id, registration.user_id, registration.watch_id,
            registration.token_hash, registration.handle, registration.address
        FROM watch_registrations registration
        JOIN calendar_watches watch
            ON watch.id = registration.watch_id AND watch.user_id = registration.user_id
        JOIN connected_accounts account
            ON account.id = watch.account_id AND account.user_id = watch.user_id
        WHERE registration.id = ? AND registration.state != ? AND account.provider = ?
        """,
        (notice.registration_id.value, RegistrationState.ABANDONED.value, provider.value),
    ).fetchone()
    if row is None or not presents(notice, str(row["token_hash"]), row["handle"]):
        return None
    return row


def _apply(connection: sqlite3.Connection, found: sqlite3.Row, kind: NoticeKind, at: str) -> int:
    """What one authentic notice does, by kind; how many rule requests it raised."""
    owned = (str(found["id"]), str(found["user_id"]))
    if kind is NoticeKind.STARTED:
        connection.execute(
            """
            UPDATE watch_registrations SET confirmed_at = COALESCE(confirmed_at, ?)
            WHERE id = ? AND user_id = ?
            """,
            (at, *owned),
        )
        return 0
    if kind is NoticeKind.REAUTHORIZE:
        # The latest time, so upkeep that read an earlier one keeps this request for later.
        connection.execute(
            """
            UPDATE watch_registrations
            SET renew_requested_at = MAX(COALESCE(renew_requested_at, ?), ?)
            WHERE id = ? AND user_id = ?
            """,
            (at, at, *owned),
        )
        return 0
    if kind is NoticeKind.REMOVED:
        # A live registration retires. One still being created is abandoned, so the receipt
        # that arrives later cannot make a subscription the provider removed live.
        connection.execute(
            """
            UPDATE watch_registrations
            SET state = CASE state WHEN :live THEN :retiring ELSE :abandoned END
            WHERE id = :id AND user_id = :user AND state IN (:live, :creating)
            """,
            {
                "live": RegistrationState.LIVE.value,
                "retiring": RegistrationState.RETIRING.value,
                "abandoned": RegistrationState.ABANDONED.value,
                "creating": RegistrationState.CREATING.value,
                "id": owned[0],
                "user": owned[1],
            },
        )
    # A change, a missed notice, or a removal: what the provider did not say is caught up on.
    return _request_runs(connection, str(found["watch_id"]), owned[1], at)


def _request_runs(connection: sqlite3.Connection, watch_id: str, user: str, at: str) -> int:
    """Raise the request of each enabled rule of the watch's User whose Source Calendar the watch
    covers, in one statement. A request already handled starts waiting again from `at`.

    Notices of concurrent requests commit in any order, so neither time goes back: a pending
    request keeps the earliest time it waits since and the latest time it was raised."""
    return connection.execute(
        """
        INSERT INTO instant_sync_requests (
            rule_id, user_id, requested_seq, handled_seq, first_requested_at, last_requested_at
        )
        SELECT rule.id, rule.user_id, 1, 0, :at, :at
        FROM sync_rules rule
        JOIN calendar_watches watch
            ON watch.user_id = rule.user_id AND watch.account_id = rule.source_account_id
        JOIN watch_coverage coverage
            ON coverage.watch_id = watch.id AND coverage.user_id = watch.user_id
            AND coverage.calendar_id = rule.source_calendar_id
        WHERE watch.id = :watch AND rule.user_id = :user AND rule.state = :enabled
        ON CONFLICT (rule_id) DO UPDATE SET
            first_requested_at = CASE WHEN requested_seq = handled_seq
                THEN excluded.first_requested_at
                ELSE MIN(first_requested_at, excluded.first_requested_at) END,
            requested_seq = requested_seq + 1,
            last_requested_at = MAX(last_requested_at, excluded.last_requested_at)
        WHERE user_id = excluded.user_id
        """,
        {"at": at, "watch": watch_id, "user": user, "enabled": SyncRuleState.ENABLED.value},
    ).rowcount


def _refresh_success(
    connection: sqlite3.Connection, provider: ProviderKind, address: str, at: datetime
) -> None:
    """Record that `provider` reached `address`, at most once a minute unless a failure was
    recorded since the last success."""
    connection.execute(
        """
        INSERT INTO delivery_evidence (provider, address, last_success_at) VALUES (?, ?, ?)
        ON CONFLICT (provider, address) DO UPDATE SET
            last_success_at = MAX(
                COALESCE(last_success_at, excluded.last_success_at), excluded.last_success_at
            )
        WHERE last_success_at IS NULL OR last_success_at <= ?
            OR last_failure_at >= last_success_at
        """,
        (provider.value, address, stored_time(at), stored_time(at - EVIDENCE_REFRESH)),
    )


class SqliteDeliveryEvidenceLog:
    """Whether each provider reached each public address: installation data, no User's."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path

    def succeeded(self, provider: ProviderKind, address: str, at: datetime) -> None:
        with transaction(self._database_path) as connection:
            connection.execute(
                """
                INSERT INTO delivery_evidence (provider, address, last_success_at)
                VALUES (?, ?, ?)
                ON CONFLICT (provider, address) DO UPDATE SET
                    last_success_at = MAX(
                        COALESCE(last_success_at, excluded.last_success_at),
                        excluded.last_success_at
                    )
                """,
                (provider.value, address, stored_time(at)),
            )

    def failed(self, provider: ProviderKind, address: str, at: datetime) -> None:
        with transaction(self._database_path) as connection:
            connection.execute(
                """
                INSERT INTO delivery_evidence (provider, address, last_failure_at)
                VALUES (?, ?, ?)
                ON CONFLICT (provider, address) DO UPDATE SET
                    last_failure_at = MAX(
                        COALESCE(last_failure_at, excluded.last_failure_at),
                        excluded.last_failure_at
                    )
                """,
                (provider.value, address, stored_time(at)),
            )

    def evidence(self, address: str) -> dict[ProviderKind, DeliveryEvidence]:
        with transaction(self._database_path) as connection:
            rows = connection.execute(
                """
                SELECT provider, last_success_at, last_failure_at FROM delivery_evidence
                WHERE address = ? ORDER BY provider
                """,
                (address,),
            ).fetchall()
        found: dict[ProviderKind, DeliveryEvidence] = {}
        for row in rows:
            # A provider a later release recorded and this one does not know is left out.
            provider = ProviderKind.recorded(row["provider"])
            if provider is not None:
                found[provider] = DeliveryEvidence(
                    provider,
                    address,
                    last_success_at=_moment(row["last_success_at"]),
                    last_failure_at=_moment(row["last_failure_at"]),
                )
        return found


def _moment(value: object) -> datetime | None:
    return None if value is None else datetime.fromisoformat(str(value))
