"""Short anonymous sign-up counters, isolated from password recovery allowances."""

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from datetime import datetime
from pathlib import Path

from calendar_sync.application.identity.registration_admission import (
    RegistrationGlobalThrottled,
    RegistrationNetworkThrottled,
)
from calendar_sync.application.identity.registration_ports import RegistrationStorageUnavailable
from calendar_sync.application.identity.reset_admission import ResetBoundary, ResetNetworkThrottled
from calendar_sync.application.shared.ports import Clock
from calendar_sync.domain.access import email_address
from calendar_sync.infrastructure.identity_front_gate import MemoryIdentityFrontGate, client_network
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.persistence.identity_admission_counters import (
    HOUR,
    allowance_wait,
    email_allowed,
    network_wait,
)
from calendar_sync.infrastructure.persistence.registration_proofs import purge_registration_proofs
from calendar_sync.infrastructure.security import RegistrationAdmissionDigests


class SqliteRegistrationAdmission:
    def __init__(self, database: Path, master_key: str, clock: Clock) -> None:
        self._database, self._clock = database, clock
        self._digests = RegistrationAdmissionDigests(master_key) if master_key else None
        self._gate = MemoryIdentityFrontGate(clock)

    def admit_front(self, client: str) -> None:
        with _registration_gate_errors():
            self._gate.admit(client, "request")

    def admit_durable(self, email: str, client: str) -> bool:
        normalized, network = email_address(email), client_network(client)
        keys = (
            self._digest("email", normalized),
            self._digest("network", network),
            self._digest("pair", normalized, network),
        )
        with self._transaction() as connection:
            connection.execute("BEGIN IMMEDIATE")
            now = self._clock.now().timestamp()
            _require_network(connection, "request", keys[1], now)
            wait = allowance_wait(
                connection, "registration_request_attempts", "global", (), now, HOUR, 100
            )
            if wait:
                raise RegistrationGlobalThrottled(wait)
            if not email_allowed(connection, keys, now, "registration_request_attempts"):
                return False
            connection.execute(
                "INSERT INTO registration_request_attempts "
                "(boundary, admitted_at, email_digest, network_digest, pair_digest) "
                "VALUES ('request', ?, ?, ?, ?)",
                (now, *keys),
            )
        self._maintain()
        return True

    def check_token(self, client: str, check: Callable[[], bool]) -> bool:
        def checked() -> bool:
            if self._digests is not None:
                with self._transaction() as connection:
                    _require_network(
                        connection,
                        "invalid-token",
                        self._network_digest(client),
                        self._clock.now().timestamp(),
                    )
            return check()

        with _registration_gate_errors():
            valid = self._gate.check_token(client, checked)
        if not valid and self._digests is not None:
            self._admit_boundary(client, "invalid-token")
        return valid

    def admit_completion(self, client: str) -> None:
        with _registration_gate_errors():
            self._gate.admit(client, "completion")
        if self._digests is not None:
            self._admit_boundary(client, "completion")
        self._maintain()

    def _admit_boundary(self, client: str, boundary: ResetBoundary) -> None:
        digest = self._network_digest(client)
        with self._transaction() as connection:
            connection.execute("BEGIN IMMEDIATE")
            now = self._clock.now().timestamp()
            _require_network(connection, boundary, digest, now)
            connection.execute(
                "INSERT INTO registration_request_attempts(boundary, network_digest, admitted_at) "
                "VALUES (?, ?, ?)",
                (boundary, digest, now),
            )

    def _digest(self, category: str, *values: str) -> str:
        if self._digests is None:
            raise RegistrationStorageUnavailable
        return self._digests.digest(category, *values)

    def _network_digest(self, client: str) -> str:
        return self._digest("network", client_network(client))

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            with transaction(self._database, timeout=0.1) as connection:
                yield connection
        except sqlite3.Error:
            raise RegistrationStorageUnavailable from None

    def purge(self, before: datetime, limit: int) -> int:
        if limit <= 0:
            return 0
        with self._transaction() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cutoff = min(before, self._clock.now()).timestamp() - HOUR
            return connection.execute(
                "DELETE FROM registration_request_attempts WHERE id IN ("
                "SELECT id FROM registration_request_attempts WHERE admitted_at <= ? "
                "ORDER BY admitted_at, id LIMIT ?)",
                (cutoff, min(limit, 500)),
            ).rowcount

    def _maintain(self) -> None:
        # Admission is already committed; independent half-batches cannot reject it.
        now = self._clock.now()
        with suppress(Exception):
            purge_registration_proofs(self._database, self._clock, now, 250)
        with suppress(Exception):
            self.purge(now, 250)


def _require_network(
    connection: sqlite3.Connection, boundary: ResetBoundary, digest: str, now: float
) -> None:
    wait = network_wait(connection, boundary, digest, now, "registration_request_attempts")
    if wait:
        raise RegistrationNetworkThrottled(wait)


@contextmanager
def _registration_gate_errors() -> Iterator[None]:
    try:
        yield
    except ResetNetworkThrottled as error:
        raise RegistrationNetworkThrottled(error.retry_after) from None
