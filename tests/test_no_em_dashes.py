"""No tracked file uses an em dash; write with a period, comma, colon, or parentheses instead."""

import subprocess
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parents[1]
EM_DASH = "\u2014"
# Third-party code can contain the character, so the lockfile and the compiled bundle are skipped.
SKIPPED = ("web/package-lock.json", "src/calendar_sync/interfaces/api/static/")
BINARY_SUFFIXES = {".png", ".svg", ".woff2", ".ico", ".jpg"}


def tracked_text_files() -> list[Path]:
    # A source tarball has no git history to say which files are tracked, so the check skips.
    if not (REPOSITORY / ".git").exists():
        pytest.skip("not a git checkout")
    try:
        names = subprocess.run(
            ["git", "ls-files"],  # noqa: S607
            cwd=REPOSITORY,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git cannot list the tracked files")
    return [
        REPOSITORY / name
        for name in names
        if not name.startswith(SKIPPED) and Path(name).suffix not in BINARY_SUFFIXES
    ]


def test_no_tracked_file_uses_an_em_dash() -> None:
    found = []
    for path in tracked_text_files():
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        found += [
            f"{path.relative_to(REPOSITORY)}:{number}"
            for number, line in enumerate(text.splitlines(), start=1)
            if EM_DASH in line
        ]
    assert found == []
