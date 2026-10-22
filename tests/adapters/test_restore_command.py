"""The installed offline terminal boundary hides secrets and returns useful statuses."""

import os
import pty
import select
import subprocess
import sys
import sysconfig
import time
from pathlib import Path

import pytest

from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.persistence.migrations import initialize_database
from calendar_sync.infrastructure.security import CredentialCipher
from tests.users import add_account, add_user

MARKER = "SYNTHETIC_SECRET_MARKER"
RESTORE_COMMAND = str(Path(sysconfig.get_path("scripts")) / "calendar-ghost-restore")


@pytest.fixture(autouse=True)
def outside_checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise the installed entry without a checkout-local virtual environment."""
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def candidate(tmp_path: Path) -> tuple[Path, dict[str, str], Path]:
    path = tmp_path / "restored.db"
    initialize_database(path)
    add_user(path, email=f"{MARKER}@example.test")
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    env = {**os.environ, "CALENDAR_SYNC_MASTER_KEY": CredentialCipher.generate_key()}
    return path, env, private / "before.db"


def invoke(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed executable and synthetic test arguments
        [RESTORE_COMMAND, *args],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def terminal(args: list[str], env: dict[str, str], answers: tuple[bytes, bytes]) -> tuple[int, str]:
    pid, fd = pty.fork()
    if pid == 0:
        try:
            os.execve(  # noqa: S606 - fixed executable and synthetic test arguments
                RESTORE_COMMAND, ["calendar-ghost-restore", *args], env
            )
        except OSError:
            os._exit(127)
    output = b""
    deadline = time.monotonic() + 15
    prompts = 0
    try:
        while time.monotonic() < deadline:
            if select.select([fd], [], [], 0.1)[0]:
                try:
                    data = os.read(fd, 65536)
                except OSError:
                    break
                if not data:
                    break
                output += data
                while prompts < 2 and output.endswith(
                    (b"New administrator password: ", b"Confirm administrator password: ")[prompts]
                ):
                    os.write(fd, answers[prompts])
                    prompts += 1
        else:
            os.kill(pid, 9)
            pytest.fail("terminal command timed out")
    finally:
        os.close(fd)
    _, status = os.waitpid(pid, 0)
    return os.waitstatus_to_exitcode(status), output.decode()


def prepare_args(path: Path, backup: Path) -> list[str]:
    return [
        "prepare",
        "--database",
        str(path),
        "--backup",
        str(backup),
        "--administrator-id",
        "user-1",
        "--acknowledge-services-stopped",
    ]


def test_installed_restore_entry_exit_codes(candidate: tuple[Path, dict[str, str], Path]) -> None:
    path, env, backup = candidate
    result = invoke(["inspect", "--database", str(path)], env)
    assert result.returncode == 0
    assert "key_unverified" in result.stdout
    assert "key_authenticated" not in result.stdout
    assert invoke(["inspect", "--database", str(path.parent / "missing")], env).returncode == 1
    assert invoke(["--password", MARKER], env).returncode == 2
    status, output = terminal(prepare_args(path, backup), env, (b"fresh password\n",) * 2)
    assert status == 0, output
    assert backup.exists()
    assert "prepared" in output
    assert "fresh password" not in output
    assert MARKER not in output


@pytest.mark.parametrize(
    "answers",
    [
        (b"fresh password\n", b"different password\n"),
        (b"short\n", b"short\n"),
        (b"x" * 257 + b"\n", b"x" * 257 + b"\n"),
        (b"\x04", b"\x04"),
        (b"\x03", b"\x03"),
    ],
)
def test_prepare_prompt_is_hidden_and_requires_confirmation(
    candidate: tuple[Path, dict[str, str], Path], answers: tuple[bytes, bytes]
) -> None:
    path, env, backup = candidate
    before = path.read_bytes()
    status, output = terminal(prepare_args(path, backup), env, answers)
    assert status == 2, output
    assert not backup.exists()
    assert path.read_bytes() == before


def test_nonterminal_and_secret_arguments_are_safe(
    candidate: tuple[Path, dict[str, str], Path],
) -> None:
    path, env, backup = candidate
    result = invoke(prepare_args(path, backup), env)
    assert result.returncode == 2
    assert "password_input_failed" in result.stderr
    result = invoke(["--password", MARKER], env)
    assert result.returncode == 2
    assert MARKER not in result.stdout + result.stderr
    assert not backup.exists()


@pytest.mark.parametrize("fault", ["key", "corrupt", "field"])
def test_restore_output_contains_only_safe_status_and_counts(
    candidate: tuple[Path, dict[str, str], Path], fault: str
) -> None:
    path, env, backup = candidate
    if fault == "key":
        env["CALENDAR_SYNC_MASTER_KEY"] = MARKER
    elif fault == "corrupt":
        path.write_text(MARKER)
    else:
        with transaction(path) as connection:
            connection.execute("PRAGMA ignore_check_constraints=ON")
            connection.execute("UPDATE users SET role=?", (MARKER,))
    if fault == "field":
        status, output = terminal(prepare_args(path, backup), env, (b"fresh password\n",) * 2)
        assert status == 1
        assert MARKER not in output
        assert "schema_incompatible" in output
        return
    result = invoke(["inspect", "--database", str(path)], env)
    assert result.returncode == 1
    assert MARKER not in result.stdout + result.stderr
    assert "Traceback" not in result.stderr


def test_restore_command_starts_no_runtime_or_network_adapter(
    candidate: tuple[Path, dict[str, str], Path],
) -> None:
    path, env, backup = candidate
    script = """
import socket, sys, threading
socket.socket = lambda *a, **k: (_ for _ in ()).throw(AssertionError("network"))
from calendar_sync.bootstrap.restore import run
database, backup = sys.argv[1:]
sys.argv = ["restore", "inspect", "--database", database]
assert run() == 0
import getpass
getpass.getpass = lambda prompt: "fresh password"
sys.argv = ["restore", "prepare", "--database", database, "--backup", backup,
            "--administrator-id", "user-1", "--acknowledge-services-stopped"]
assert run() == 0
for name in sys.modules:
    assert not any(part in name for part in (
        "interfaces.api", "infrastructure.google", "infrastructure.microsoft",
        "infrastructure.scheduler", "infrastructure.notifications", "instant_sync")), name
assert len(threading.enumerate()) == 1
"""
    result = subprocess.run(  # noqa: S603 - fixed executable and synthetic test arguments
        [sys.executable, "-c", script, str(path), str(backup)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("fault", ["administrator", "backup", "acknowledgement"])
def test_prepare_failure_diagnostics_hide_operator_values(
    candidate: tuple[Path, dict[str, str], Path], fault: str
) -> None:
    path, env, backup = candidate
    args = prepare_args(path, backup)
    if fault == "administrator":
        args[args.index("user-1")] = MARKER
    elif fault == "backup":
        backup.write_text(MARKER)
    else:
        args.remove("--acknowledge-services-stopped")
        result = invoke(args, env)
        assert result.returncode == 2
        assert "services_not_acknowledged" in result.stderr
        assert "password:" not in result.stderr
        return
    status, output = terminal(args, env, (b"fresh password\n",) * 2)
    assert status == 1
    assert MARKER not in output
    assert "Traceback" not in output


def test_inspection_authenticates_credentials_without_disclosing_them(
    candidate: tuple[Path, dict[str, str], Path],
) -> None:
    path, env, _ = candidate
    add_account(path, "synthetic-account")
    cipher = CredentialCipher(env["CALENDAR_SYNC_MASTER_KEY"])
    with transaction(path) as connection:
        connection.execute(
            "UPDATE connected_accounts SET encrypted_credentials=?",
            (cipher.encrypt(MARKER),),
        )
    args = ["inspect", "--database", str(path)]
    result = invoke(args, env)
    assert result.returncode == 0
    assert "key_authenticated" in result.stdout
    assert MARKER not in result.stdout + result.stderr
    env["CALENDAR_SYNC_MASTER_KEY"] = CredentialCipher.generate_key()
    result = invoke(args, env)
    assert result.returncode == 1
    assert result.stderr.strip() == "key_mismatch"
    assert MARKER not in result.stdout + result.stderr
    del env["CALENDAR_SYNC_MASTER_KEY"]
    assert invoke(args, env).stderr.strip() == "key_missing"


def test_prepare_lock_contention_has_safe_diagnostic(
    candidate: tuple[Path, dict[str, str], Path],
) -> None:
    path, env, backup = candidate
    with transaction(path) as connection:
        connection.execute("UPDATE users SET email=email")
        status, output = terminal(prepare_args(path, backup), env, (b"fresh password\n",) * 2)
    assert status == 1
    assert "storage_busy" in output
    assert MARKER not in output
    assert "Traceback" not in output


def test_invalid_terminal_encoding_is_a_safe_input_failure(
    candidate: tuple[Path, dict[str, str], Path],
) -> None:
    path, env, backup = candidate
    before = path.read_bytes()
    status, output = terminal(prepare_args(path, backup), env, (b"\xff\n", b"unused password\n"))
    assert status == 2, output
    assert "password_input_failed" in output
    assert "Traceback" not in output
    assert "UnicodeDecodeError" not in output
    assert "unused password" not in output
    assert not backup.exists()
    assert path.read_bytes() == before
