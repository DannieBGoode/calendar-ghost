"""What each User's runs cost the installation, counted for the Operator Overview (ADR 0030).

Only counts are kept: how many calls each provider received per User and UTC day, never what a
call asked for. Days older than `PROVIDER_CALL_DAYS` are discarded by the scheduler.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, timedelta

from calendar_sync.application.ports import Clock, ProviderCallTally, UnitOfWorkFactory

logger = logging.getLogger(__name__)

PROVIDER_CALL_DAYS = 30
"""How many UTC days of provider calls are kept and shown, today included."""


def first_counted_day(today: date) -> date:
    """The oldest UTC day whose provider calls are still kept and shown."""
    return today - timedelta(days=PROVIDER_CALL_DAYS - 1)


def record_provider_calls(
    unit_of_work: UnitOfWorkFactory, clock: Clock, calls: ProviderCallTally
) -> None:
    """Add a finished run's calls to its User's counts for today, in UTC.

    Counting is best-effort: a failure to record never replaces what the run itself raised or
    returned, so it is only logged.
    """
    if not calls.providers:
        return
    today = clock.now().astimezone(UTC).date()
    try:
        with unit_of_work() as uow:
            for provider, counts in calls.providers.items():
                uow.provider_calls.add(today, provider, counts)
            uow.commit()
    except Exception:
        logger.exception("Could not record a run's provider calls")
