"""What runs write to the service log: identifiers, counts, and durations, never event content.

Log lines name a rule and a run by their internal identifiers only. Event titles, descriptions,
calendar identifiers, account emails, and provider payloads never reach them.
"""

from __future__ import annotations

from contextlib import AbstractContextManager, nullcontext
from datetime import timedelta

from calendar_sync.application.ports import ProviderCallTally


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
        f"google_calls={calls.calls} token_refreshes={calls.token_refreshes} "
        f"rate_limited={calls.rate_limited} server_errors={calls.server_errors} "
        f"slowest_call={calls.slowest_seconds:.1f}s"
    )
