"""The service's own log lines: one per record, on standard error, timestamped in UTC.

Only the `calendar_sync` logger is configured. Uvicorn keeps its own access and error logging,
and other libraries keep Python's defaults.
"""

from __future__ import annotations

import logging
import sys
from datetime import UTC, datetime

from calendar_sync.infrastructure.log_files import RotatingLogFiles

LOGGER = "calendar_sync"
HANDLER = "calendar_sync.stderr"
FILE_HANDLER = "calendar_sync.file"
FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


class _UtcFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__(FORMAT)

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:  # noqa: ARG002
        return datetime.fromtimestamp(record.created, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def configure_logging(level: str, files: RotatingLogFiles | None = None) -> bool:
    """Write `calendar_sync` records at `level` and above to standard error, and to `files`.

    Calling it again changes the level without adding a second handler, so no line is doubled. A
    log directory that cannot be used turns file logging off with one warning; the service runs.
    Returns whether records reach `files`, so Settings never offers files nothing writes to.
    """
    logger = logging.getLogger(LOGGER)
    logger.setLevel(level.strip().upper())
    if not any(handler.get_name() == HANDLER for handler in logger.handlers):
        handler = logging.StreamHandler(sys.stderr)
        handler.set_name(HANDLER)
        handler.setFormatter(_UtcFormatter())
        logger.addHandler(handler)
    if files is not None and not any(h.get_name() == FILE_HANDLER for h in logger.handlers):
        try:
            file_handler = files.handler()
        except OSError as error:
            logger.warning(
                "file logging is off: %s cannot be used (%s)",
                files.directory,
                error.__class__.__name__,
            )
        else:
            file_handler.set_name(FILE_HANDLER)
            file_handler.setFormatter(_UtcFormatter())
            logger.addHandler(file_handler)
    # Written here only, even when something else configures the root logger.
    logger.propagate = False
    return files is not None and any(h.get_name() == FILE_HANDLER for h in logger.handlers)
