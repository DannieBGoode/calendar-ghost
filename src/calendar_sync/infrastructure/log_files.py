"""The service's own rotating log files, next to its database unless configured elsewhere.

They hold the same lines as standard error, so no event content reaches them either. At most
`backups + 1` files of `max_bytes` exist: the oldest file is deleted when the current one fills.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from calendar_sync.application.ports import LogUsage

FILE_NAME = "calendar-sync.log"
CHUNK_BYTES = 64 * 1024
# Lines start with the UTC time the stderr formatter writes, e.g. 2026-10-01T18:04:12Z.
TIMESTAMP_LENGTH = len("2026-10-01T18:04:12Z")

logger = logging.getLogger(__name__)


class RotatingLogFiles:
    def __init__(self, directory: Path, max_bytes: int = 5 * 1024 * 1024, backups: int = 4) -> None:
        self._directory = directory
        self._max_bytes = max_bytes
        self._backups = backups
        self._handler: RotatingFileHandler | None = None

    @property
    def directory(self) -> Path:
        return self._directory

    def handler(self) -> logging.Handler:
        """The handler writing the current file; raises OSError if the directory is unusable."""
        if self._handler is None:
            self._directory.mkdir(parents=True, exist_ok=True)
            self._handler = RotatingFileHandler(
                self._directory / FILE_NAME,
                maxBytes=self._max_bytes,
                backupCount=self._backups,
                encoding="utf-8",
            )
        return self._handler

    def files(self) -> list[Path]:
        """Existing log files, oldest first. Names are fixed; nothing comes from a request."""
        current = self._directory / FILE_NAME
        rotated = [
            current.with_name(f"{FILE_NAME}.{number}") for number in range(self._backups, 0, -1)
        ]
        return [path for path in (*rotated, current) if path.is_file()]

    def usage(self) -> LogUsage:
        paths = self.files()
        sizes = [_size(path) for path in paths]
        return LogUsage(
            bytes=sum(sizes),
            files=len(paths),
            oldest_at=next((at for path in paths if (at := _first_time(path))), None),
            newest_at=next((at for path in reversed(paths) if (at := _last_time(path))), None),
        )

    def chunks(self) -> Iterator[bytes]:
        for path in self.files():
            try:
                with path.open("rb") as file:
                    while chunk := file.read(CHUNK_BYTES):
                        yield chunk
            except FileNotFoundError:
                continue

    def purge(self) -> None:
        handler = self._handler
        if handler is not None:
            handler.acquire()
        try:
            for path in self.files():
                if path.name == FILE_NAME and handler is not None and handler.stream is not None:
                    handler.stream.seek(0)
                    handler.stream.truncate()
                else:
                    path.unlink(missing_ok=True)
        finally:
            if handler is not None:
                handler.release()
        logger.info("logs purged")


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def _parse(line: bytes) -> datetime | None:
    try:
        stamp = line[:TIMESTAMP_LENGTH].decode()
        return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except (UnicodeDecodeError, ValueError):
        return None


def _first_time(path: Path) -> datetime | None:
    try:
        with path.open("rb") as file:
            return _parse(file.readline())
    except FileNotFoundError:
        return None


def _last_time(path: Path) -> datetime | None:
    try:
        with path.open("rb") as file:
            file.seek(0, 2)
            size = file.tell()
            file.seek(max(0, size - 4096))
            lines = file.read().splitlines()
    except FileNotFoundError:
        return None
    return next((at for line in reversed(lines) if (at := _parse(line))), None)
