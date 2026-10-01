"""The service writes its own log lines to standard error at the configured level."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from pathlib import Path

import pytest

from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.logs import HANDLER, LOGGER, configure_logging
from calendar_sync.interfaces.api.app import create_app


@pytest.fixture
def service_logger() -> Iterator[logging.Logger]:
    """The service logger, restored afterwards so other tests capture its records as before."""
    logger = logging.getLogger(LOGGER)
    handlers, level, propagate = list(logger.handlers), logger.level, logger.propagate
    yield logger
    logger.handlers[:] = handlers
    logger.setLevel(level)
    logger.propagate = propagate


def own_handlers(logger: logging.Logger) -> list[logging.Handler]:
    return [handler for handler in logger.handlers if handler.get_name() == HANDLER]


def test_lines_are_written_once_to_stderr_with_a_utc_timestamp(
    service_logger: logging.Logger, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging("info")
    configure_logging("INFO")

    logging.getLogger("calendar_sync.application.sync_run").info("run started rule=r1 run=ab12")
    logging.getLogger("calendar_sync.application.sync_run").debug("google call op=events.get")

    assert len(own_handlers(service_logger)) == 1
    err = capsys.readouterr().err
    assert re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z INFO calendar_sync\.application\.sync_run "
        r"run started rule=r1 run=ab12\n",
        err,
    )


def test_calling_again_changes_the_level(
    service_logger: logging.Logger, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging("INFO")
    configure_logging("debug")

    logging.getLogger("calendar_sync.infrastructure.google").debug("google call op=events.get")

    assert service_logger.level == logging.DEBUG
    assert len(own_handlers(service_logger)) == 1
    assert capsys.readouterr().err.count("google call op=events.get") == 1


def test_uvicorn_logging_is_left_alone(service_logger: logging.Logger) -> None:
    uvicorn = logging.getLogger("uvicorn.error")
    before = (list(uvicorn.handlers), uvicorn.level, uvicorn.propagate)

    configure_logging("WARNING")

    assert (list(uvicorn.handlers), uvicorn.level, uvicorn.propagate) == before


def test_an_unknown_level_stops_the_service_from_starting(service_logger: logging.Logger) -> None:
    with pytest.raises(ValueError, match="VERBOSE"):
        configure_logging("verbose")


def test_the_service_configures_logging_from_its_settings(
    service_logger: logging.Logger, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CALENDAR_SYNC_DATABASE_PATH", str(tmp_path / "calendar-sync.db"))
    monkeypatch.setenv("CALENDAR_SYNC_LOG_LEVEL", "DEBUG")
    monkeypatch.delenv("CALENDAR_SYNC_MASTER_KEY", raising=False)

    create_app()

    assert service_logger.level == logging.DEBUG
    assert len(own_handlers(service_logger)) == 1


def test_log_directory_defaults_beside_the_database_and_can_be_turned_off(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CALENDAR_SYNC_DATABASE_PATH", str(tmp_path / "data" / "sync.db"))
    monkeypatch.delenv("CALENDAR_SYNC_LOG_DIR", raising=False)
    assert Settings.from_environment().log_directory == tmp_path / "data" / "logs"

    monkeypatch.setenv("CALENDAR_SYNC_LOG_DIR", str(tmp_path / "elsewhere"))
    assert Settings.from_environment().log_directory == tmp_path / "elsewhere"

    monkeypatch.setenv("CALENDAR_SYNC_LOG_DIR", "")
    assert Settings.from_environment().log_directory is None
