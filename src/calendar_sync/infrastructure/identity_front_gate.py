"""Bounded, process-local protection before anonymous identity storage access."""

import ipaddress
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from threading import Lock

from calendar_sync.application.identity.reset_admission import ResetBoundary, ResetNetworkThrottled
from calendar_sync.application.shared.ports import Clock

WINDOW = timedelta(minutes=15)
LIMITS: dict[ResetBoundary, int] = {"request": 20, "invalid-token": 20, "completion": 10}
NETWORK_CAPACITY = 10_000


def client_network(value: str) -> str:
    """Use only the server-resolved client, never a forwarded header here.

    Missing/malformed clients share one key. IPv4-mapped IPv6 cannot acquire a second quota.
    Canonical /64 keys are accepted so normalization is idempotent at adapter boundaries.
    """
    if "%" in value:
        return "unknown"
    try:
        if "/" in value:
            network = ipaddress.ip_network(value, strict=True)
            if isinstance(network, ipaddress.IPv6Network) and network.prefixlen == 64:
                return str(network)
            return "unknown"
        address = ipaddress.ip_address(value)
    except ValueError:
        return "unknown"
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped:
            return str(address.ipv4_mapped)
        return str(ipaddress.ip_network(f"{address}/64", strict=False))
    return str(address)


@dataclass(slots=True)
class _Network:
    allocated_at: datetime
    attempts: dict[ResetBoundary, list[datetime]] = field(default_factory=dict)

    def expires_at(self) -> datetime:
        return (
            max([self.allocated_at, *(at for rows in self.attempts.values() for at in rows)])
            + WINDOW
        )


class MemoryIdentityFrontGate:
    def __init__(self, clock: Clock, *, capacity: int = NETWORK_CAPACITY) -> None:
        if capacity < 1:
            raise ValueError("network capacity must be positive")
        self._clock = clock
        self._capacity = min(capacity, NETWORK_CAPACITY)
        self._networks: dict[str, _Network] = {}
        self._guard = Lock()
        self._next_sweep: datetime | None = None

    def admit(self, network: str, boundary: ResetBoundary) -> None:
        with self._guard:
            now = self._clock.now()
            entry = self._require(network, boundary, now)
            entry.attempts.setdefault(boundary, []).append(now)

    def check_token(self, network: str, check: Callable[[], bool]) -> bool:
        with self._guard:
            self._require(network, "invalid-token", self._clock.now())
        # Neither SQLite reads nor the proof callback may hold the shared inventory mutex.
        if check():
            return True
        # Recheck under the mutex: concurrent callbacks may have consumed the remaining quota.
        self.admit(network, "invalid-token")
        return False

    def _require(self, network: str, boundary: ResetBoundary, now: datetime) -> _Network:
        key = client_network(network)
        entry = self._networks.get(key)
        if entry is None:
            self._expire(now)
            if len(self._networks) >= self._capacity:
                # The cached sweep deadline avoids scanning a full inventory on every refusal.
                assert self._next_sweep is not None
                wait = self._next_sweep - now
                raise ResetNetworkThrottled(max(1, math.ceil(wait.total_seconds())))
            entry = self._networks[key] = _Network(now)
        recent = [at for at in entry.attempts.get(boundary, ()) if at > now - WINDOW]
        entry.attempts[boundary] = recent
        limit = LIMITS[boundary]
        if len(recent) >= limit:
            wait = recent[-limit] + WINDOW - now
            raise ResetNetworkThrottled(max(1, math.ceil(wait.total_seconds())))
        return entry

    def _expire(self, now: datetime) -> None:
        if self._next_sweep is not None and now < self._next_sweep:
            return
        for key in [key for key, entry in self._networks.items() if entry.expires_at() <= now]:
            del self._networks[key]
        self._next_sweep = min(
            (entry.expires_at() for entry in self._networks.values()), default=now + WINDOW
        )
