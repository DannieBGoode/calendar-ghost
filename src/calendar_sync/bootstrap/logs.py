"""The service's own log lines: one per record, on standard error, timestamped in UTC.

Only the `calendar_sync` logger is configured. Uvicorn keeps its own access and error logging,
and other libraries keep Python's defaults.
"""

from __future__ import annotations

import logging
import sys
from datetime import UTC, datetime

LOGGER = "calendar_sync"
HANDLER = "calendar_sync.stderr"
FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


class _UtcFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__(FORMAT)

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:  # noqa: ARG002
        return datetime.fromtimestamp(record.created, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def configure_logging(level: str) -> None:
    """Write `calendar_sync` records at `level` and above to standard error.

    Calling it again changes the level without adding a second handler, so no line is doubled.
    """
    logger = logging.getLogger(LOGGER)
    logger.setLevel(level.strip().upper())
    if not any(handler.get_name() == HANDLER for handler in logger.handlers):
        handler = logging.StreamHandler(sys.stderr)
        handler.set_name(HANDLER)
        handler.setFormatter(_UtcFormatter())
        logger.addHandler(handler)
    # Written here only, even when something else configures the root logger.
    logger.propagate = False
