"""Fail-closed process control and SQLite assertions for the optional local drill."""

from __future__ import annotations

import json
import os
import pty
import select
import signal
import subprocess
import sys
import tempfile
import time
from contextlib import closing, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

from calendar_sync.infrastructure.persistence.connections import open_connection, transaction


class DrillFailure(RuntimeError):
    """Evidence cannot pass after a missing assertion or failed child process."""


def checked(
    command: list[str], *, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, capture_output=True, text=True, timeout=40, env=env)  # noqa: S603 - explicit operator-selected executable, no shell
    if result.returncode != 0:
        raise DrillFailure(f"command failed ({result.returncode}): {command[1:3]}")
    return result


def installed_cli() -> str:
    executable = Path(sys.executable).parent / "calendar-ghost-restore"
    if not executable.is_file():
        raise DrillFailure("installed calendar-ghost-restore entry missing")
    return str(executable)


def inspect_cli(database: Path, env: dict[str, str]) -> int:
    return checked([installed_cli(), "inspect", "--database", str(database)], env=env).returncode


def prepare_cli(database: Path, backup: Path, env: dict[str, str]) -> int:
    """Drive getpass through a controlling terminal, without placing a password in argv."""
    command = [
        installed_cli(),
        "prepare",
        "--database",
        str(database),
        "--backup",
        str(backup),
        "--administrator-id",
        "user-1",
        "--acknowledge-services-stopped",
    ]
    pid, descriptor = pty.fork()
    if pid == 0:
        os.execve(command[0], command, env)  # noqa: S606 - installed console entry, no shell
    deadline = time.monotonic() + 30
    prompts = 0
    output = b""
    reaped = False
    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([descriptor], [], [], 0.1)
            if ready:
                with suppress(OSError):
                    output += os.read(descriptor, 4096)
                if output.count(b": ") > prompts and prompts < 2:
                    os.write(descriptor, b"synthetic recovery password\n")
                    prompts += 1
            waited, status = os.waitpid(pid, os.WNOHANG)
            if waited:
                reaped = True
                code = os.waitstatus_to_exitcode(status)
                if code != 0 or prompts != 2:
                    raise DrillFailure(f"prepare terminal exit {code}; prompts {prompts}")
                return code
        raise DrillFailure("prepare terminal timeout")
    finally:
        os.close(descriptor)
        if not reaped:
            with suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)
            os.waitpid(pid, 0)


def stop(process: subprocess.Popen[str]) -> int:
    process.send_signal(signal.SIGTERM)
    try:
        code = process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
        raise DrillFailure("replication stop timeout") from None
    if code != 0:
        raise DrillFailure(f"replication SIGTERM exit {code}")
    return code


def rows(database: Path, query: str) -> tuple[tuple[Any, ...], ...]:
    with closing(open_connection(database, mode="ro")) as connection:
        return tuple(tuple(row) for row in connection.execute(query))


def verify_markers(database: Path, expected: tuple[str, ...]) -> None:
    if rows(database, "PRAGMA integrity_check") != (("ok",),):
        raise DrillFailure("restored integrity failed")
    if (
        tuple(row[0] for row in rows(database, "SELECT value FROM drill_markers ORDER BY rowid"))
        != expected
    ):
        raise DrillFailure("restored markers differ")


def marker(database: Path, value: str) -> None:
    with transaction(database) as connection:
        connection.execute(
            "INSERT INTO drill_markers VALUES (?,?)", (value, datetime.now(UTC).isoformat())
        )


def configuration(database: Path, replica: Path, socket: Path) -> str:
    return (
        f"socket:\n  enabled: true\n  path: {socket}\n"
        "snapshot:\n  interval: 12s\n  retention: 24s\nretention:\n  enabled: true\n"
        "l0-retention: 2s\nl0-retention-check-interval: 1s\n"
        f"dbs:\n  - path: {database}\n    replica:\n      url: file://{replica}\n"
        "      sync-interval: 1s\n"
    )


class Replication:
    def __init__(self, binary: Path, root: Path, database: Path, prefix: str) -> None:
        self.binary, self.database = binary, database
        self.replica = root / prefix
        # A private short socket directory also fits macOS's Unix socket path ceiling.
        self.socket_directory = tempfile.TemporaryDirectory(prefix="cg-backup-")
        self.socket = Path(self.socket_directory.name) / "control.sock"
        self.config = root / f"{prefix}.yml"
        self.config.write_text(configuration(database, self.replica, self.socket))
        self.process: subprocess.Popen[str] | None = None
        self.log: IO[str] | None = None

    def start(self) -> None:
        if self.process is not None:
            raise DrillFailure("replication already running")
        self.log = self.config.with_suffix(".log").open("a")
        try:
            self.process = subprocess.Popen(  # noqa: S603 - explicit pinned binary, no shell
                [str(self.binary), "replicate", "-config", str(self.config)],
                stdout=self.log,
                stderr=subprocess.STDOUT,
                text=True,
            )
            self._ready()
        except BaseException:
            self.close()
            raise

    def _ready(self) -> None:
        if self.process is None:
            raise DrillFailure("replication process missing")
        deadline = time.monotonic() + 15
        while not self.socket.exists():
            if self.process.poll() is not None or time.monotonic() > deadline:
                raise DrillFailure("replication failed to start")
            time.sleep(0.1)
        self.sync()

    def sync(self) -> str:
        response = checked(
            [
                str(self.binary),
                "sync",
                "-json",
                "-socket",
                str(self.socket),
                "-wait",
                str(self.database),
            ]
        ).stdout
        result = json.loads(response)
        if result.get("txid") != result.get("replica_txid") or not result.get("txid"):
            raise DrillFailure("sync did not confirm source and replica TXIDs")
        return response

    def close(self) -> int:
        try:
            return stop(self.process) if self.process is not None else 0
        finally:
            self.process = None
            if self.log is not None:
                self.log.close()

    def restore(self, target: Path, expected: tuple[str, ...], txid: str | None = None) -> int:
        command = [str(self.binary), "restore", "-o", str(target)]
        if txid:
            command += ["-txid", txid]
        result = checked([*command, f"file://{self.replica}"])
        verify_markers(target, expected)
        return result.returncode
