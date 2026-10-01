import logging
import threading
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from calendar_sync.bootstrap.logs import configure_logging
from calendar_sync.domain.model import ProjectionContent, TransformationPolicy
from calendar_sync.infrastructure.log_files import RotatingLogFiles
from tests.fake_calendar import FakeCalendars, enabled_rule_factory, sync_use_case
from tests.helpers import endpoint, event, rule, series


@pytest.fixture(autouse=True)
def _restore_logger() -> Iterator[None]:
    logger = logging.getLogger("calendar_sync")
    handlers, level, propagate = list(logger.handlers), logger.level, logger.propagate
    # Each test configures from scratch, so its stderr handler writes to the captured stream.
    logger.handlers[:] = []
    yield
    for handler in logger.handlers:
        if handler not in handlers:
            handler.close()
    logger.handlers[:] = handlers
    logger.setLevel(level)
    logger.propagate = propagate


def _line(at: str, message: str) -> str:
    return f"{at} INFO calendar_sync.test {message}\n"


def test_records_reach_the_file_formatted_like_standard_error(tmp_path: Path) -> None:
    files = RotatingLogFiles(tmp_path / "logs")
    configure_logging("INFO", files)

    logging.getLogger("calendar_sync.test").info("run finished rule=r1 in 2s")

    text = (tmp_path / "logs" / "calendar-sync.log").read_text()
    assert text.endswith("INFO calendar_sync.test run finished rule=r1 in 2s\n")
    assert text[:20].endswith("Z")  # 2026-10-01T18:04:12Z


def test_rotation_keeps_at_most_four_older_files_and_drops_the_oldest(tmp_path: Path) -> None:
    files = RotatingLogFiles(tmp_path / "logs", max_bytes=200, backups=4)
    configure_logging("INFO", files)
    logger = logging.getLogger("calendar_sync.test")

    for number in range(60):
        logger.info("line %03d %s", number, "x" * 40)

    names = sorted(path.name for path in (tmp_path / "logs").iterdir())
    assert names == [
        "calendar-sync.log",
        "calendar-sync.log.1",
        "calendar-sync.log.2",
        "calendar-sync.log.3",
        "calendar-sync.log.4",
    ]
    everything = b"".join(files.chunks()).decode()
    assert "line 059" in everything
    assert "line 000" not in everything


def test_usage_counts_bytes_and_reads_the_first_and_last_line_times(tmp_path: Path) -> None:
    directory = tmp_path / "logs"
    directory.mkdir()
    (directory / "calendar-sync.log.1").write_text(
        _line("2026-09-12T08:00:00Z", "old") + _line("2026-09-13T08:00:00Z", "older")
    )
    (directory / "calendar-sync.log").write_text(_line("2026-10-01T18:04:12Z", "new"))
    files = RotatingLogFiles(directory)

    usage = files.usage()

    assert usage.files == 2
    assert usage.bytes == sum(path.stat().st_size for path in directory.iterdir())
    assert usage.oldest_at == datetime(2026, 9, 12, 8, tzinfo=UTC)
    assert usage.newest_at == datetime(2026, 10, 1, 18, 4, 12, tzinfo=UTC)


def test_usage_of_no_logs_is_empty(tmp_path: Path) -> None:
    usage = RotatingLogFiles(tmp_path / "logs").usage()

    assert (usage.bytes, usage.files, usage.oldest_at, usage.newest_at) == (0, 0, None, None)


def test_chunks_stream_the_oldest_file_first(tmp_path: Path) -> None:
    directory = tmp_path / "logs"
    directory.mkdir()
    (directory / "calendar-sync.log.2").write_text("first\n")
    (directory / "calendar-sync.log.1").write_text("second\n")
    (directory / "calendar-sync.log").write_text("third\n")

    assert b"".join(RotatingLogFiles(directory).chunks()) == b"first\nsecond\nthird\n"


def test_a_file_rotated_away_during_a_download_is_skipped(tmp_path: Path) -> None:
    directory = tmp_path / "logs"
    directory.mkdir()
    (directory / "calendar-sync.log.2").write_text("first\n")
    (directory / "calendar-sync.log.1").write_text("gone\n")
    (directory / "calendar-sync.log").write_text("kept\n")
    chunks = RotatingLogFiles(directory).chunks()
    # The download has listed the files and is streaming the oldest one when rotation removes
    # a file it has not opened yet.
    assert next(chunks) == b"first\n"
    (directory / "calendar-sync.log.1").unlink()

    assert b"".join(chunks) == b"kept\n"


def test_purge_empties_every_file_and_logging_continues(tmp_path: Path) -> None:
    files = RotatingLogFiles(tmp_path / "logs", max_bytes=200, backups=4)
    configure_logging("INFO", files)
    logger = logging.getLogger("calendar_sync.test")
    for number in range(30):
        logger.info("before purge %03d %s", number, "x" * 40)

    files.purge()
    logger.info("after purge")

    text = b"".join(files.chunks()).decode()
    assert "before purge" not in text
    assert "logs purged" in text
    assert text.endswith("after purge\n")
    assert [path.name for path in (tmp_path / "logs").iterdir()] == ["calendar-sync.log"]


def test_purge_while_another_thread_logs_raises_nothing(tmp_path: Path) -> None:
    files = RotatingLogFiles(tmp_path / "logs", max_bytes=2_000, backups=4)
    configure_logging("INFO", files)
    logger = logging.getLogger("calendar_sync.test")
    stop = threading.Event()

    def keep_logging() -> None:
        while not stop.is_set():
            logger.info("concurrent %s", "x" * 40)

    writer = threading.Thread(target=keep_logging)
    writer.start()
    try:
        for _ in range(20):
            files.purge()
    finally:
        stop.set()
        writer.join()
    logger.info("still writing")

    assert b"".join(files.chunks()).decode().endswith("still writing\n")


def test_an_unwritable_log_directory_leaves_standard_error_logging_working(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    blocked = tmp_path / "logs"
    blocked.write_text("a file where the directory should be")

    configure_logging("INFO", RotatingLogFiles(blocked))
    logging.getLogger("calendar_sync.test").info("service started")

    errors = capsys.readouterr().err
    assert "file logging is off" in errors
    assert "service started" in errors


def test_no_event_content_reaches_the_log_files(tmp_path: Path) -> None:
    files = RotatingLogFiles(tmp_path / "logs")
    assert configure_logging("DEBUG", files)
    family = endpoint("account-family", "family@example.com")
    work = endpoint("account-work", "work.calendar@example.org")
    secret_rule = replace(
        rule(),
        source=family,
        destination=work,
        transformation=TransformationPolicy(ProjectionContent.DETAILS),
    )
    calendars = FakeCalendars()
    calendars.put(event("dentist", calendar=family, title="Dentist with Dr. Secretface"))
    calendars.put(series("therapy", calendar=family, title="Therapy session Wednesdays"))
    execute = sync_use_case(enabled_rule_factory(secret_rule), calendars)

    execute.execute(secret_rule.id)
    execute.execute(secret_rule.id, full=True)

    text = b"".join(files.chunks()).decode()
    assert "run finished" in text
    for content in (
        "Secretface",
        "Therapy session",
        "Sensitive description",
        "Sensitive location",
        "family@example.com",
        "work.calendar@example.org",
        "dentist",
        "therapy",
    ):
        assert content not in text


# Regression: Codex review P2 — log files that are links could expose or truncate other files
# Found by /codex review on 2026-10-01
def test_a_rotated_log_that_links_outside_the_directory_is_never_served(tmp_path: Path) -> None:
    directory = tmp_path / "logs"
    directory.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("not a log\n")
    (directory / "calendar-sync.log.1").symlink_to(secret)
    (directory / "calendar-sync.log").write_text("kept\n")
    files = RotatingLogFiles(directory)

    assert b"".join(files.chunks()) == b"kept\n"
    assert files.usage().files == 1
    files.purge()
    assert secret.read_text() == "not a log\n"


def test_a_current_log_that_is_a_link_turns_file_logging_off(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = tmp_path / "logs"
    directory.mkdir()
    target = tmp_path / "elsewhere.txt"
    target.write_text("")
    (directory / "calendar-sync.log").symlink_to(target)

    assert configure_logging("INFO", RotatingLogFiles(directory)) is False
    logging.getLogger("calendar_sync.test").info("service started")

    assert target.read_text() == ""
    assert "file logging is off" in capsys.readouterr().err
