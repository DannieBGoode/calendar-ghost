"""Short, anonymous reset admission transactions, independent of account existence."""

import sqlite3
from datetime import datetime
from pathlib import Path

from calendar_sync.application.identity.reset_admission import (
    ResetAdmissionStorageUnavailable,
    ResetBoundary,
    ResetGlobalThrottled,
    ResetNetworkThrottled,
)
from calendar_sync.application.shared.ports import Clock
from calendar_sync.domain.access import email_address
from calendar_sync.infrastructure.identity_front_gate import client_network
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.persistence.identity_admission_counters import (
    HOUR,
    allowance_wait,
    email_allowed,
    network_wait,
)
from calendar_sync.infrastructure.security import ResetAdmissionDigests


class SqliteResetAdmission:
    def __init__(self, database: Path, master_key: str, clock: Clock) -> None:
        self._database = database
        self._digests = ResetAdmissionDigests(master_key)
        self._clock = clock

    def admit(self, email: str, network: str) -> bool:
        normalized = email_address(email)
        keys = (
            self._digests.digest("email", normalized),
            self._network_digest(network),
            self._digests.digest("pair", normalized, client_network(network)),
        )
        try:
            with transaction(self._database, timeout=0.1) as connection:
                connection.execute("BEGIN IMMEDIATE")
                now = self._clock.now().timestamp()
                _require_network(connection, "request", keys[1], now)
                global_wait = allowance_wait(
                    connection, "reset_request_attempts", "global", (), now, HOUR, 100
                )
                if global_wait:
                    raise ResetGlobalThrottled(global_wait)
                if not email_allowed(connection, keys, now):
                    return False
                connection.execute(
                    "INSERT INTO reset_request_attempts "
                    "(boundary, admitted_at, email_digest, network_digest, pair_digest) "
                    "VALUES ('request', ?, ?, ?, ?)",
                    (now, *keys),
                )
            return True
        except sqlite3.Error:
            raise ResetAdmissionStorageUnavailable from None

    def check_invalid(self, network: str) -> None:
        try:
            with transaction(self._database, timeout=0.1) as connection:
                _require_network(
                    connection,
                    "invalid-token",
                    self._network_digest(network),
                    self._clock.now().timestamp(),
                )
        except sqlite3.Error:
            raise ResetAdmissionStorageUnavailable from None

    def record_invalid(self, network: str) -> None:
        self._admit_boundary(network, "invalid-token")

    def admit_completion(self, network: str) -> None:
        self._admit_boundary(network, "completion")

    def _admit_boundary(self, network: str, boundary: ResetBoundary) -> None:
        digest = self._network_digest(network)
        try:
            with transaction(self._database, timeout=0.1) as connection:
                connection.execute("BEGIN IMMEDIATE")
                now = self._clock.now().timestamp()
                _require_network(connection, boundary, digest, now)
                connection.execute(
                    "INSERT INTO reset_request_attempts(boundary, network_digest, admitted_at) "
                    "VALUES (?, ?, ?)",
                    (boundary, digest, now),
                )
                if boundary == "invalid-token":
                    _purge_attempts(connection, now, 500)
        except sqlite3.Error:
            raise ResetAdmissionStorageUnavailable from None

    def _network_digest(self, network: str) -> str:
        return self._digests.digest("network", client_network(network))

    def purge(self, before: datetime, limit: int) -> int:
        if limit <= 0:
            return 0
        try:
            with transaction(self._database, timeout=0.1) as connection:
                connection.execute("BEGIN IMMEDIATE")
                cutoff = min(before, self._clock.now())
                return _purge(connection, cutoff, min(limit, 500))
        except sqlite3.Error:
            raise ResetAdmissionStorageUnavailable from None


def _purge_attempts(connection: sqlite3.Connection, cutoff: float, limit: int) -> int:
    return connection.execute(
        "DELETE FROM reset_request_attempts WHERE id IN ("
        "SELECT id FROM reset_request_attempts WHERE admitted_at <= ? "
        "ORDER BY admitted_at, id LIMIT ?)",
        (cutoff - HOUR, limit),
    ).rowcount


def _purge(connection: sqlite3.Connection, cutoff: datetime, limit: int) -> int:
    removed = _purge_attempts(connection, cutoff.timestamp(), limit)
    remaining = limit - removed
    if remaining:
        removed += connection.execute(
            "DELETE FROM password_reset_links WHERE id IN ("
            "SELECT id FROM password_reset_links WHERE julianday(expires_at) <= julianday(?) "
            "OR julianday(used_at) <= julianday(?) OR julianday(revoked_at) <= julianday(?) "
            "ORDER BY created_at, id LIMIT ?)",
            (cutoff.isoformat(), cutoff.isoformat(), cutoff.isoformat(), remaining),
        ).rowcount
    return removed


def _require_network(
    connection: sqlite3.Connection, boundary: ResetBoundary, digest: str, now: float
) -> None:
    wait = network_wait(connection, boundary, digest, now)
    if wait:
        raise ResetNetworkThrottled(wait)
