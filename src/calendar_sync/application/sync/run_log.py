"""What runs write to the service log: identifiers, counts, and durations, never event content.

Log lines name a rule and a run by their internal identifiers only. Event titles, descriptions,
calendar identifiers, account emails, and provider payloads never reach them.
"""

from __future__ import annotations

import traceback
from contextlib import AbstractContextManager, nullcontext
from datetime import timedelta

from calendar_sync.application.sync.run_ports import ProviderCallTally


class UntalliedProviderCalls:
    """ProviderCallStats for providers that do not measure their calls, such as test fakes."""

    def measure(self) -> AbstractContextManager[ProviderCallTally]:
        return nullcontext(ProviderCallTally())


def duration(elapsed: timedelta) -> str:
    """A run's duration as a stopwatch reads it: 45s, 3m02s, 1h02m03s."""
    seconds = max(0, int(elapsed.total_seconds()))
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{seconds:02d}s"
    if minutes:
        return f"{minutes}m{seconds:02d}s"
    return f"{seconds}s"


def call_summary(calls: ProviderCallTally) -> str:
    """How a run's provider calls went, for its closing line."""
    return (
        f"provider_calls={calls.calls} token_refreshes={calls.token_refreshes} "
        f"rate_limited={calls.rate_limited} server_errors={calls.server_errors} "
        f"slowest_call={calls.slowest_seconds:.1f}s"
    )


# How many of Calendar Ghost's own functions a failure's site names, innermost last.
SITE_DEPTH = 2


def failure_site(error: BaseException) -> str:
    """Where a failure was raised, as the last of Calendar Ghost's own functions it passed
    through, such as `provider.update_projection>provider._refuse_exception_guests`.

    It names code, never data, so a log tells which check failed without any event content.
    The innermost cause that passed through Calendar Ghost's code is the most precise.
    """
    sites = ""
    current: BaseException | None = error
    while current is not None:
        own = [
            f"{frame.f_globals.get('__name__', '').rsplit('.', 1)[-1]}.{frame.f_code.co_name}"
            for frame, _ in traceback.walk_tb(current.__traceback__)
            if str(frame.f_globals.get("__name__", "")).startswith("calendar_sync.")
        ]
        if own:
            sites = ">".join(own[-SITE_DEPTH:])
        current = current.__cause__
    return sites or "unknown"
