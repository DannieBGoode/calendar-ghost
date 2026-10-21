"""Purpose-separated email-change allowances with a bounded memory front gate."""

import math
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from datetime import datetime
from pathlib import Path

from calendar_sync.application.identity.email_change_admission import (
    EmailChangeStorageUnavailable,
    EmailChangeThrottled,
)
from calendar_sync.application.identity.reset_admission import ResetBoundary, ResetNetworkThrottled
from calendar_sync.application.shared.ports import Clock
from calendar_sync.domain.access import UserId
from calendar_sync.infrastructure.identity_front_gate import (
    LIMITS,
    NETWORK_CAPACITY,
    MemoryIdentityFrontGate,
    client_network,
)
from calendar_sync.infrastructure.persistence.email_change_records import email_change_transaction
from calendar_sync.infrastructure.security import EmailChangeAdmissionDigests


def admit_issuance(
    connection: sqlite3.Connection, user_id: UserId, digest: str, now: datetime
) -> None:
    at = now.timestamp()
    user = connection.execute(
        "SELECT admitted_at FROM email_change_attempts WHERE user_id = ? AND admitted_at > ? "
        "ORDER BY admitted_at DESC LIMIT 1 OFFSET 4",
        (user_id.value, at - 3600),
    ).fetchone()
    target = connection.execute(
        "SELECT admitted_at FROM email_change_attempts WHERE target_digest = ? AND admitted_at > ? "
        "ORDER BY admitted_at DESC LIMIT 1",
        (digest, at - 60),
    ).fetchone()
    wait = max(_wait(user, at, 3600), _wait(target, at, 60))
    if wait:
        raise EmailChangeThrottled(wait)
    connection.execute(
        "INSERT INTO email_change_attempts(user_id, target_digest, admitted_at) VALUES (?, ?, ?)",
        (user_id.value, digest, at),
    )


def _wait(row: sqlite3.Row | None, at: float, window: int) -> int:
    return max(1, math.ceil(float(row[0]) + window - at)) if row else 0


@contextmanager
def _front_errors() -> Iterator[None]:
    try:
        yield
    except ResetNetworkThrottled as error:
        raise EmailChangeThrottled(error.retry_after) from None


class EmailChangeAdmission:
    def __init__(
        self, database: Path, master_key: str, clock: Clock, *, capacity: int = NETWORK_CAPACITY
    ) -> None:
        self._database = database
        self._digests = EmailChangeAdmissionDigests(master_key) if master_key else None
        self._clock = clock
        self._front = MemoryIdentityFrontGate(clock, capacity=capacity)
        self._capacity = min(capacity, NETWORK_CAPACITY)

    def admit_request(self, network: str) -> None:
        self._admit(network, "request")

    def admit_completion(self, network: str) -> None:
        self._admit(network, "completion")

    def _admit(self, network: str, boundary: ResetBoundary) -> None:
        with _front_errors():
            self._front.admit(network, boundary)
        self._durable(network, boundary, record=True)
        self._cleanup()

    def check_token(self, network: str, check: Callable[[], bool]) -> bool:
        def checked() -> bool:
            self._durable(network, "invalid-token", record=False)
            if check():
                return True
            self._durable(network, "invalid-token", record=True)
            self._cleanup()
            return False

        with _front_errors():
            return self._front.check_token(network, checked)

    def _durable(self, network: str, boundary: ResetBoundary, *, record: bool) -> None:
        if self._digests is None:
            return
        digest = self._digests.digest("network", client_network(network))
        with email_change_transaction(self._database) as connection:
            if record:
                connection.execute("BEGIN IMMEDIATE")
            at = self._clock.now().timestamp()
            row = connection.execute(
                "SELECT admitted_at FROM email_change_network_attempts WHERE boundary = ? "
                "AND network_digest = ? AND admitted_at > ? ORDER BY admitted_at "
                "DESC LIMIT 1 OFFSET ?",
                (boundary, digest, at - 900, LIMITS[boundary] - 1),
            ).fetchone()
            wait = _wait(row, at, 900)
            if wait:
                raise EmailChangeThrottled(wait)
            if record:
                self._require_capacity(connection, digest, at)
                connection.execute(
                    "INSERT INTO email_change_network_attempts(boundary, "
                    "network_digest, admitted_at) VALUES (?, ?, ?)",
                    (boundary, digest, at),
                )

    def _require_capacity(self, connection: sqlite3.Connection, digest: str, at: float) -> None:
        known = connection.execute(
            "SELECT 1 FROM email_change_network_attempts WHERE network_digest = "
            "? AND admitted_at > ? LIMIT 1",
            (digest, at - 900),
        ).fetchone()
        if known:
            return
        count = connection.execute(
            "SELECT COUNT(DISTINCT network_digest) FROM "
            "email_change_network_attempts WHERE admitted_at > ?",
            (at - 900,),
        ).fetchone()[0]
        if count >= self._capacity:
            raise EmailChangeThrottled(900)

    def _cleanup(self) -> None:
        # A maintenance failure cannot undo an already admitted operation.
        with suppress(EmailChangeStorageUnavailable):
            self.purge(self._clock.now(), 500)

    def purge(self, before: datetime, limit: int) -> int:
        if limit <= 0:
            return 0
        with email_change_transaction(self._database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            at = min(before, self._clock.now()).timestamp()
            limit = min(limit, 500)
            removed = connection.execute(
                "DELETE FROM email_change_network_attempts WHERE id IN ("
                "SELECT id FROM email_change_network_attempts "
                "WHERE admitted_at <= ? ORDER BY admitted_at LIMIT ?)",
                (at - 900, limit),
            ).rowcount
            removed += connection.execute(
                "DELETE FROM email_change_attempts WHERE id IN ("
                "SELECT id FROM email_change_attempts "
                "WHERE admitted_at <= ? ORDER BY admitted_at LIMIT ?)",
                (at - 3600, limit - removed),
            ).rowcount
            return removed
