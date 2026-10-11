"""A provider's Retry-After hint, as seconds the retry helper waits.

Every provider adapter reads the header the same way (RFC 9110 section 10.2.3): a number of
seconds, or an HTTP date counted down from the injected clock.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

# Retries wait in-process while holding the rule lock, so a longer provider hint is bounded; the
# attempt then fails again and the rule's normal failure handling takes over.
MAX_RETRY_AFTER_SECONDS = 60


def retry_after_seconds(value: str | None, now: datetime) -> int | None:
    """The seconds a Retry-After value asks for, at most MAX_RETRY_AFTER_SECONDS; None when it is
    missing or unreadable."""
    if not isinstance(value, str) or not value.strip():
        return None
    if value.strip().isdigit():
        seconds = int(value.strip())
    else:
        try:
            moment = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        seconds = max(0, math.ceil((moment - now).total_seconds()))
    return min(seconds, MAX_RETRY_AFTER_SECONDS)
