"""The service's own log lines: one per record, on standard error, timestamped in UTC.

The `calendar_sync` logger writes application records. A Uvicorn access filter hides Watch Notice
identifiers and sign-in query strings, and authentication transport debug output is suppressed.
Uvicorn retains its handlers and other libraries keep Python's defaults.
"""

from __future__ import annotations

import logging
import sys
from datetime import UTC, datetime

from calendar_sync.application.sync.watch_ports import NOTICE_PATH
from calendar_sync.infrastructure.log_files import RotatingLogFiles

LOGGER = "calendar_sync"
HANDLER = "calendar_sync.stderr"
FILE_HANDLER = "calendar_sync.file"
FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
ACCESS_LOGGER = "uvicorn.access"


class _UtcFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__(FORMAT)

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:  # noqa: ARG002
        return datetime.fromtimestamp(record.created, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class NoticePathFilter(logging.Filter):
    """Keeps registrations out of Uvicorn's access log. A Watch Notice's path names its
    registration, which no log line may (ADR 0036), so the line keeps only the provider's slug:
    `/api/v1/watch-notices/<slug>/…`, without the registration or a query. Provider sign-in
    paths retain their route only, never authorization codes or states."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) > 2:
            path = str(args[2])
            if path.startswith("/api/v1/sign-in/"):
                record.args = (*args[:2], path.split("?", 1)[0], *args[3:])
            if path.startswith(NOTICE_PATH + "/"):
                slug = path[len(NOTICE_PATH) + 1 :].split("/", 1)[0].split("?", 1)[0]
                record.args = (*args[:2], f"{NOTICE_PATH}/{slug}/…", *args[3:])
        return True


def configure_logging(level: str, files: RotatingLogFiles | None = None) -> bool:
    """Write `calendar_sync` records at `level` and above to standard error, and to `files`.

    Calling it again changes the level without adding a second handler, so no line is doubled; new
    `files` replace the earlier ones. A log directory that cannot be used turns file logging off
    with one warning; the service runs.
    Returns whether records reach `files`, so Settings never offers files nothing writes to.
    """
    logger = logging.getLogger(LOGGER)
    logger.setLevel(level.strip().upper())
    if not any(handler.get_name() == HANDLER for handler in logger.handlers):
        handler = logging.StreamHandler(sys.stderr)
        handler.set_name(HANDLER)
        handler.setFormatter(_UtcFormatter())
        logger.addHandler(handler)
    _hide_notice_paths()
    _quiet_auth_transport()
    attached = _write_to(logger, files)
    # Written here only, even when something else configures the root logger.
    logger.propagate = False
    return attached


def _hide_notice_paths() -> None:
    """Filter Uvicorn's access log once, however often logging is configured."""
    access = logging.getLogger(ACCESS_LOGGER)
    if not any(isinstance(each, NoticePathFilter) for each in access.filters):
        access.addFilter(NoticePathFilter())


def _write_to(logger: logging.Logger, files: RotatingLogFiles | None) -> bool:
    """Write to `files` alone, detaching earlier ones even if `files` is unusable; whether it is.

    No `files`, or an unusable directory, leaves no file handler, so nothing keeps writing where
    Settings can no longer read or purge.
    """
    file_handler = _handler_for(logger, files) if files is not None else None
    for earlier in [h for h in logger.handlers if h.get_name() == FILE_HANDLER]:
        if earlier is not file_handler:
            logger.removeHandler(earlier)
            earlier.close()
    if file_handler is None:
        return False
    if file_handler not in logger.handlers:
        file_handler.set_name(FILE_HANDLER)
        file_handler.setFormatter(_UtcFormatter())
        logger.addHandler(file_handler)
    return True


def _handler_for(logger: logging.Logger, files: RotatingLogFiles) -> logging.Handler | None:
    try:
        return files.handler()
    except OSError as error:
        logger.warning(
            "file logging is off: %s cannot be used (%s)",
            files.directory,
            error.__class__.__name__,
        )
        return None


def _quiet_auth_transport() -> None:
    """Authentication libraries must never emit token bodies or callback query strings."""
    roots = ("authlib", "requests", "urllib3")
    names = set(roots) | {
        name
        for name in logging.Logger.manager.loggerDict
        if name.startswith(tuple(root + "." for root in roots))
    }
    for name in names:
        logging.getLogger(name).setLevel(logging.WARNING)
