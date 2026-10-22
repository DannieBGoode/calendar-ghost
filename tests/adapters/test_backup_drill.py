"""The optional binary drill must fail closed without downloading any tools."""

import os
import pty
import select
import signal
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from scripts import hosted_backup_process
from scripts import verify_hosted_backups as drill


def test_drill_refuses_wrong_version_and_existing_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        subprocess, "run", Mock(return_value=Mock(returncode=0, stdout="v0.4.0", stderr=""))
    )
    with pytest.raises(drill.DrillFailure):
        drill.run_drill(Path("litestream"), tmp_path / "new")
    (tmp_path / "keep").touch()
    with pytest.raises(drill.DrillFailure):
        drill.run_drill(Path("litestream"), tmp_path)


def test_drill_reports_failed_subprocess_as_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        subprocess, "run", Mock(return_value=Mock(returncode=1, stdout="", stderr="failed"))
    )
    with pytest.raises(drill.DrillFailure):
        drill.checked(["synthetic"])


def test_drill_requires_restored_state_assertions(tmp_path: Path) -> None:
    from calendar_sync.infrastructure.security import CredentialCipher
    from scripts.hosted_backup_fixture import build_synthetic_database

    path = tmp_path / "synthetic.db"
    build_synthetic_database(path, CredentialCipher.generate_key())
    with pytest.raises(drill.DrillFailure):
        drill.verify_markers(path, ("missing",))


@pytest.mark.parametrize("status", [-15, 1])
def test_drill_fails_on_signal_exit_or_stop_timeout(status: int) -> None:
    process = Mock()
    process.wait.return_value = status
    with pytest.raises(drill.DrillFailure):
        drill.stop(process)
    process.wait.side_effect = [subprocess.TimeoutExpired("synthetic", 30), -9]
    with pytest.raises(drill.DrillFailure):
        drill.stop(process)
    process.kill.assert_called_once()


def test_drill_runs_installed_cli_with_controlling_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    writes: list[bytes] = []
    monkeypatch.setattr(
        hosted_backup_process, "installed_cli", lambda: "/synthetic/bin/calendar-ghost-restore"
    )
    monkeypatch.setattr(pty, "fork", lambda: (42, 5))
    monkeypatch.setattr(select, "select", lambda *_: ([5], [], []))
    prompts = iter([b"New administrator password: ", b"Confirm password: "])
    monkeypatch.setattr(os, "read", lambda *_: next(prompts))
    monkeypatch.setattr(os, "write", lambda _fd, value: writes.append(value))
    monkeypatch.setattr(os, "close", lambda _: None)
    statuses = iter([(0, 0), (42, 0)])
    monkeypatch.setattr(os, "waitpid", lambda *_: next(statuses))
    assert drill.prepare_cli(tmp_path / "restored.db", tmp_path / "before.db", {}) == 0
    assert writes == [b"synthetic recovery password\n"] * 2
    # The child branch executes only the installed entry, with no password in argv/env.
    monkeypatch.setattr(pty, "fork", lambda: (0, 5))
    calls: list[tuple[object, ...]] = []

    class Executed(BaseException):
        pass

    def execute(*args: object) -> None:
        calls.append(args)
        raise Executed

    monkeypatch.setattr(os, "execve", execute)
    with pytest.raises(Executed):
        drill.prepare_cli(tmp_path / "restored.db", tmp_path / "before.db", {})
    assert calls[0][0] == "/synthetic/bin/calendar-ghost-restore"
    assert "synthetic recovery password" not in str(calls)


def test_drill_starts_no_duplicate_application_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    process = Mock()
    process.wait.return_value = 0
    launch = Mock(return_value=process)
    monkeypatch.setattr(subprocess, "Popen", launch)
    monkeypatch.setattr(drill.Replication, "sync", lambda _: "{}")
    replication = drill.Replication(
        Path("/synthetic/litestream"), tmp_path, tmp_path / "source.db", "replica"
    )
    monkeypatch.setattr(Path, "exists", lambda _: True)
    replication.start()
    try:
        with pytest.raises(drill.DrillFailure, match="already running"):
            replication.start()
        assert launch.call_count == 1
        command = launch.call_args.args[0]
        assert command[:2] == ["/synthetic/litestream", "replicate"]
    finally:
        assert replication.close() == 0


def test_drill_terminal_failure_kills_and_reaps_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(hosted_backup_process, "installed_cli", lambda: "/synthetic/restore")
    monkeypatch.setattr(pty, "fork", lambda: (42, 5))
    monkeypatch.setattr(select, "select", Mock(side_effect=OSError("synthetic")))
    monkeypatch.setattr(os, "close", Mock())
    kill, reap = Mock(), Mock()
    monkeypatch.setattr(os, "kill", kill)
    monkeypatch.setattr(os, "waitpid", reap)
    with pytest.raises(OSError, match="synthetic"):
        drill.prepare_cli(tmp_path / "db", tmp_path / "backup", {})
    kill.assert_called_once_with(42, signal.SIGKILL)
    reap.assert_called_once_with(42, 0)


def test_drill_start_failure_stops_child(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    process = Mock()
    process.wait.return_value = 0
    monkeypatch.setattr(subprocess, "Popen", Mock(return_value=process))
    monkeypatch.setattr(
        drill.Replication, "_ready", Mock(side_effect=drill.DrillFailure("sync failed"))
    )
    replication = drill.Replication(
        Path("/synthetic/litestream"), tmp_path, tmp_path / "source.db", "replica"
    )
    with pytest.raises(drill.DrillFailure, match="sync failed"):
        replication.start()
    assert replication.process is None
    process.send_signal.assert_called_once_with(signal.SIGTERM)
    assert replication.log is not None
    assert replication.log.closed


def test_drill_failed_process_cannot_write_passing_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    binary = tmp_path / "binary"
    binary.write_bytes(b"synthetic")
    monkeypatch.setattr(
        subprocess,
        "run",
        Mock(
            side_effect=[
                Mock(returncode=0, stdout="0.5.17", stderr=""),
                Mock(returncode=1, stdout="", stderr=""),
            ]
        ),
    )

    def fail(*_args: object) -> None:
        drill.checked(["synthetic", "restore"])

    monkeypatch.setattr(drill, "live_compaction_experiment", fail)
    output = tmp_path / "output"
    with pytest.raises(drill.DrillFailure, match="command failed"):
        drill.run_drill(binary, output)
    assert json.loads((output / "evidence.json").read_text())["passed"] is False


def test_drill_inspection_uses_plain_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(hosted_backup_process, "installed_cli", lambda: "/synthetic/restore")
    launch = Mock(return_value=Mock(returncode=0, stdout="restore_status=inspected", stderr=""))
    monkeypatch.setattr(subprocess, "run", launch)
    terminal = Mock(side_effect=AssertionError("inspect must not allocate a terminal"))
    monkeypatch.setattr(pty, "fork", terminal)
    assert hosted_backup_process.inspect_cli(tmp_path / "restored.db", {}) == 0
    assert launch.call_args.args[0] == [
        "/synthetic/restore",
        "inspect",
        "--database",
        str(tmp_path / "restored.db"),
    ]
    terminal.assert_not_called()


@pytest.mark.parametrize("operation", ["snapshot", "export"])
@pytest.mark.parametrize(
    ("code", "error"), [(-9, ""), (1, "Error: permission denied"), (1, "Error: disk full")]
)
def test_expiry_rejects_signal_and_operational_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str, code: int, error: str
) -> None:
    from scripts import hosted_backup_retention as retention

    replication = Mock(binary=Path("/pinned"), replica=tmp_path)
    monkeypatch.setattr(
        subprocess, "run", Mock(return_value=subprocess.CompletedProcess([], code, "", error))
    )
    monkeypatch.setattr(retention, "verify_markers", Mock())
    monkeypatch.setattr(retention, "inspect_cli", Mock())

    def probe() -> None:
        if operation == "snapshot":
            retention.expired_endpoints(replication, tmp_path, {"snapshot": "21"})
        else:
            retention.verify_export(replication, tmp_path, ("initial",), "21", {})

    with pytest.raises(drill.DrillFailure, match="endpoint probe failed"):
        probe()


@pytest.mark.parametrize("operation", ["snapshot", "export"])
def test_expiry_records_pinned_unavailable_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    from scripts import hosted_backup_retention as retention

    monkeypatch.setattr(
        subprocess,
        "run",
        Mock(
            return_value=subprocess.CompletedProcess(
                [], 1, "", "Error: no matching backup files available\n"
            )
        ),
    )
    replication = Mock(binary=Path("/pinned"), replica=tmp_path)
    monkeypatch.setattr(retention, "verify_markers", Mock())
    monkeypatch.setattr(retention, "inspect_cli", Mock())
    if operation == "snapshot":
        result = retention.expired_endpoints(replication, tmp_path, {"snapshot": "21"})[0]
    else:
        result = retention.verify_export(replication, tmp_path, ("initial",), "21", {})
    assert result == {"txid": "21", "exit": 1, "reason": "endpoint_unavailable"}


@pytest.mark.parametrize("restored", [(), ("initial",), ("initial", "after-vacuum", "wrong")])
def test_retained_endpoint_requires_exact_acknowledged_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, restored: tuple[str, ...]
) -> None:
    from scripts import hosted_backup_process as process
    from scripts import hosted_backup_retention as retention

    monkeypatch.setattr(retention, "endpoints", lambda *_: {"snapshot": "21"})
    monkeypatch.setattr(retention, "checked", Mock())
    monkeypatch.setattr(retention, "inspect_cli", Mock())
    monkeypatch.setattr(
        process,
        "rows",
        lambda _path, query: (
            (("ok",),) if query.startswith("PRAGMA") else tuple((value,) for value in restored)
        ),
    )
    with pytest.raises(drill.DrillFailure, match=r"marker|content"):
        retention.restore_retained(
            Mock(replica=tmp_path),
            tmp_path,
            {"21": ("initial", "after-vacuum", "retention-00")},
            {},
        )


def test_retained_endpoint_set_must_not_be_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts import hosted_backup_retention as retention

    monkeypatch.setattr(retention, "endpoints", lambda *_: {})
    with pytest.raises(drill.DrillFailure, match="no retained"):
        retention.restore_retained(Mock(replica=tmp_path), tmp_path, {}, {})
