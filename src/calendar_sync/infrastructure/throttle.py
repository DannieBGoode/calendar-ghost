"""Failed sign-ins counted in memory, per key, over a sliding window."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
from threading import Lock

from calendar_sync.application.ports import Clock

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
                recent = self._recent(key, now)
                recent.append(now)
                self._failures[key] = recent

    def succeeded(self, keys: tuple[str, ...]) -> None:
        with self._guard:
            for key in keys:
                if key.startswith("email:"):
                    self._failures.pop(key, None)

    def _wait(self, key: str, now: datetime) -> float:
        recent = self._recent(key, now)
        limit = self._limits.get(key.partition(":")[0], min(self._limits.values()))
        if len(recent) < limit:
            return 0.0
        # The oldest failure that keeps the count at the limit leaves the window first.
        return (recent[-limit] + self._window - now).total_seconds()

    def _recent(self, key: str, now: datetime) -> deque[datetime]:
        """The key's failures still in the window; a key with none left is forgotten."""
        recent = self._failures.get(key, deque())
        while recent and recent[0] <= now - self._window:
            recent.popleft()
        if not recent:
            self._failures.pop(key, None)
        return recent
