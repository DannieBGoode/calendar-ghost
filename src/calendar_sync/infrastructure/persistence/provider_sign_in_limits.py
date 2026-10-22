"""Independent OIDC admission budgets: bounded memory first, then durable counters."""

import math
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Literal

from calendar_sync.application.identity.provider_sign_in_ports import ProviderSignInThrottled
from calendar_sync.application.identity.reset_admission import ResetBoundary, ResetNetworkThrottled
from calendar_sync.application.shared.ports import Clock
from calendar_sync.infrastructure.identity_front_gate import MemoryIdentityFrontGate, client_network
from calendar_sync.infrastructure.persistence.provider_flow_records import flow_transaction
from calendar_sync.infrastructure.security import ProviderSignInSecrets

Boundary = Literal["begin", "callback", "confirmation"]
_FRONT: dict[Boundary, ResetBoundary] = {
    "begin": "request",
    "callback": "invalid-token",
    "confirmation": "completion",
}
_LIMITS: dict[Boundary, int] = {"begin": 20, "callback": 20, "confirmation": 10}


class SqliteProviderSignInLimits:
    def __init__(
        self, database: Path, master_key: str, clock: Clock, *, capacity: int = 10_000
    ) -> None:
        self._database, self._clock = database, clock
        self._secrets = ProviderSignInSecrets(master_key)
        self._gate = MemoryIdentityFrontGate(clock, capacity=capacity)

    def admit(self, client: str, boundary: Boundary) -> None:
        try:
            self._gate.admit(client, _FRONT[boundary])
        except ResetNetworkThrottled as error:
            raise ProviderSignInThrottled(error.retry_after) from None
        digest = self._secrets.digest("admission:" + boundary, client_network(client))
        with flow_transaction(self._database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            now = self._clock.now().timestamp()
            oldest = connection.execute(
                "SELECT admitted_at FROM provider_sign_in_attempts WHERE boundary = ? "
                "AND network_digest = ? AND admitted_at > ? "
                "ORDER BY admitted_at DESC LIMIT 1 OFFSET ?",
                (boundary, digest, now - 900, _LIMITS[boundary] - 1),
            ).fetchone()
            _require_allowance(oldest[0] if oldest else None, now, 900)
            if boundary == "begin":
                oldest = connection.execute(
                    "SELECT admitted_at FROM provider_sign_in_attempts WHERE boundary = 'begin' "
                    "AND admitted_at > ? ORDER BY admitted_at DESC LIMIT 1 OFFSET 99",
                    (now - 3600,),
                ).fetchone()
                _require_allowance(oldest[0] if oldest else None, now, 3600)
            connection.execute(
                "INSERT INTO provider_sign_in_attempts(boundary, network_digest, "
                "admitted_at) VALUES (?, ?, ?)",
                (boundary, digest, now),
            )
        with suppress(Exception):
            self.purge(self._clock.now(), 250)

    def purge(self, before: datetime, limit: int) -> int:
        if limit <= 0:
            return 0
        cutoff = min(before, self._clock.now()).timestamp() - 3600
        with flow_transaction(self._database) as connection:
            return connection.execute(
                "DELETE FROM provider_sign_in_attempts WHERE id IN ("
                "SELECT id FROM provider_sign_in_attempts WHERE admitted_at <= ? "
                "ORDER BY admitted_at, id LIMIT ?)",
                (cutoff, min(limit, 250)),
            ).rowcount


def _require_allowance(oldest: float | None, now: float, window: int) -> None:
    if oldest is not None:
        raise ProviderSignInThrottled(max(1, math.ceil(oldest + window - now)))
