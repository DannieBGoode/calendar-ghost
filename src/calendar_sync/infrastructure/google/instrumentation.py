"""Counts and times Google calls for the run that makes them.

Each measured context keeps its own tally in a context variable, so runs on different threads
never share one: the scheduler and the Web API run each rule's work on a worker thread, and the
calls a run makes happen on that thread. Log lines carry the operation name, the HTTP status, and
the duration only, never a request's parameters, so no calendar, event, or account reaches them.
"""

from __future__ import annotations

import logging
from contextlib import AbstractContextManager
from contextvars import ContextVar, Token

from calendar_sync.application.ports import ProviderCallTally

logger = logging.getLogger(__name__)

# A call this slow is reported even when debug logging is off.
SLOW_CALL_SECONDS = 10.0

_current: ContextVar[ProviderCallTally | None] = ContextVar("google_call_tally", default=None)


class GoogleCallStats:
    """ProviderCallStats for the Google adapter."""

    def measure(self) -> AbstractContextManager[ProviderCallTally]:
        return _Measuring(ProviderCallTally())


class _Measuring(AbstractContextManager[ProviderCallTally]):
    # Not @contextmanager: its exit assigns __traceback__ on the exception, which frozen
    # slotted dataclass errors such as RemovalInterrupted reject.
    def __init__(self, tally: ProviderCallTally) -> None:
        self._tally = tally
        self._token: Token[ProviderCallTally | None] | None = None

    def __enter__(self) -> ProviderCallTally:
        self._token = _current.set(self._tally)
        return self._tally

    def __exit__(self, *_: object) -> None:
        assert self._token is not None
        _current.reset(self._token)


def record_call(operation: str, status: int | None, seconds: float, *, rate_limited: bool) -> None:
    """Add one finished Google call to the current run's tally, and log it.

    `status` is None when no HTTP answer arrived, such as when Google could not be reached.
    """
    tally = _current.get()
    if tally is not None:
        tally.calls += 1
        tally.seconds += seconds
        tally.slowest_seconds = max(tally.slowest_seconds, seconds)
        if rate_limited:
            tally.rate_limited += 1
        if status is not None and status >= 500:
            tally.server_errors += 1
    shown = "none" if status is None else str(status)
    logger.debug("google call op=%s status=%s took=%dms", operation, shown, round(seconds * 1000))
    if seconds >= SLOW_CALL_SECONDS:
        logger.warning("slow google call op=%s status=%s took=%.1fs", operation, shown, seconds)


def record_token_refresh() -> None:
    """Count one access token renewal toward the current run, if a run is measuring."""
    tally = _current.get()
    if tally is not None:
        tally.token_refreshes += 1
