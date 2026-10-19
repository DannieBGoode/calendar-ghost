"""Failed sign-ins and manual runs counted in memory, over sliding windows."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
from threading import Lock

from calendar_sync.application.shared.ports import Clock
from calendar_sync.application.sync.manual_runs import MANUAL_RUN_WINDOW, MANUAL_RUNS
from calendar_sync.domain.access import UserId

WINDOW = timedelta(minutes=15)
EMAIL_LIMIT = 5
"""Failures for one email in a window before it must wait; slows guessing one User's password."""
CLIENT_LIMIT = 20
"""Failures from one client address in a window; slows trying many emails from one place."""


class MemorySignInThrottle:
    """Kept in the one application process; a restart forgets it, which only gives attempts back."""

    def __init__(
        self,
        clock: Clock,
        *,
        window: timedelta = WINDOW,
        email_limit: int = EMAIL_LIMIT,
        client_limit: int = CLIENT_LIMIT,
    ) -> None:
        self._clock = clock
        self._window = window
        self._limits = {"email": email_limit, "client": client_limit}
        self._failures: dict[str, deque[datetime]] = {}
        self._guard = Lock()

    def wait(self, keys: tuple[str, ...]) -> float:
        now = self._clock.now()
        with self._guard:
            waits = [self._wait(key, now) for key in keys]
        return max(waits, default=0.0)

    def failed(self, keys: tuple[str, ...]) -> None:
        now = self._clock.now()
        with self._guard:
            for key in keys:
                recent = _recent(self._failures, key, now, self._window)
                recent.append(now)
                self._failures[key] = recent

    def succeeded(self, keys: tuple[str, ...]) -> None:
        with self._guard:
            for key in keys:
                if key.startswith("email:"):
                    self._failures.pop(key, None)

    def _wait(self, key: str, now: datetime) -> float:
        recent = _recent(self._failures, key, now, self._window)
        limit = self._limits.get(key.partition(":")[0], min(self._limits.values()))
        if len(recent) < limit:
            return 0.0
        # The oldest failure that keeps the count at the limit leaves the window first.
        return (recent[-limit] + self._window - now).total_seconds()


class MemoryRunThrottle:
    """Kept in the one application process; a restart forgets it, which only gives runs back."""

    def __init__(
        self, clock: Clock, *, limit: int = MANUAL_RUNS, window: timedelta = MANUAL_RUN_WINDOW
    ) -> None:
        self._clock = clock
        self._limit = limit
        self._window = window
        self._runs: dict[UserId, deque[datetime]] = {}
        self._guard = Lock()

    def admit(self, user: UserId) -> float:
        with self._guard:
            now = self._clock.now()
            recent = _recent(self._runs, user, now, self._window)
            if len(recent) >= self._limit:
                # A refused run is not recorded, so asking again never pushes the wait out. The
                # oldest run leaves the window first; a clock set back still waits at most the
                # window.
                wait = recent[0] + self._window - now
                return min(wait, self._window).total_seconds()
            recent.append(now)
            self._runs[user] = recent
            return 0.0


def _recent[K](
    entries: dict[K, deque[datetime]], key: K, now: datetime, window: timedelta
) -> deque[datetime]:
    """The key's entries still in the window; a key with none left is forgotten."""
    recent = entries.get(key, deque())
    while recent and recent[0] <= now - window:
        recent.popleft()
    if not recent:
        entries.pop(key, None)
    return recent
