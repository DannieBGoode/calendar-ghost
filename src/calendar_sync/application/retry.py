from __future__ import annotations

import random
from collections.abc import Callable

from calendar_sync.application.errors import ProviderFailure

RETRY_ATTEMPTS = 3
RETRY_JITTER_SECONDS = 0.25


def with_retries[T](
    operation: Callable[[], T],
    sleep: Callable[[float], None],
    attempts: int = RETRY_ATTEMPTS,
) -> T:
    """Run a provider operation, retrying only temporary and rate-limit failures with backoff.

    Authorization, ownership, and every other failure is raised at once, because retrying cannot
    resolve it. The last failure is raised once the attempts are used up.
    """
    for attempt in range(attempts - 1):
        try:
            return operation()
        except ProviderFailure as failure:
            if not failure.retryable:
                raise
            delay = failure.retry_after_seconds or 2**attempt
            # Backoff jitter, not a secret.
            sleep(delay + random.uniform(0, RETRY_JITTER_SECONDS))  # noqa: S311
    return operation()
