"""Failed sign-ins and manual runs counted in memory, over sliding windows."""

from __future__ import annotations

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
        self._failures: dict[str, list[datetime]] = {}
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
        self._runs: dict[UserId, list[datetime]] = {}
        self._swept: datetime | None = None
        self._guard = Lock()

    def admit(self, user: UserId) -> float:
        with self._guard:
            now = self._clock.now()
            self._sweep(now)
            recent = _recent(self._runs, user, now, self._window)
            if len(recent) >= self._limit:
                # A refused run is not recorded, so asking again never pushes the wait out. The
                # oldest run that keeps the count at the limit leaves the window first, within
                # the window, since no run is later than now.
                return (recent[-self._limit] + self._window - now).total_seconds()
            recent.append(now)
            self._runs[user] = recent
            return 0.0

    def _sweep(self, now: datetime) -> None:
        """Forget every User with no run left in the window, once a window, so a User who stops
        running, or is deleted, is not kept until a restart."""
        if self._swept is not None and self._swept <= now < self._swept + self._window:
            return
        for user in list(self._runs):
            _recent(self._runs, user, now, self._window)
        self._swept = now


def _recent[K](
    entries: dict[K, list[datetime]], key: K, now: datetime, window: timedelta
) -> list[datetime]:
    """The key's entries still in the window, oldest first; a key with none left is forgotten.
    An entry later than `now`, left by a clock set back, is dropped too, which only gives
    attempts back and keeps the rest in order."""
    recent = [at for at in entries.get(key, ()) if now - window < at <= now]
    if recent:
        entries[key] = recent
    else:
        entries.pop(key, None)
    return recent
