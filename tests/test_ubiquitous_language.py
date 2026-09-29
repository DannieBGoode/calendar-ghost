"""Code and documentation use the glossary's terms, not the ones `CONTEXT.md` says to avoid."""

import re
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
GLOSSARY = REPOSITORY / "CONTEXT.md"

# Avoided terms that always name the wrong concept. Many other avoided terms, such as "user" or
# "pause rule", are also ordinary English or interface labels, so they are left to review.
AVOIDED = (
    "bidirectional rule",
    "cloned event",
    "copied event",
    "downstream calendar",
    "event copy",
    "master mapping",
    "origin calendar",
    "parent mapping",
    "recurring master",
    "sync job",
    "sync pair",
    "target calendar",
    "upstream calendar",
)

SEARCHED = ("src/calendar_sync", "web/src", "docs", "scripts", "tests")
SUFFIXES = {".py", ".ts", ".tsx", ".md", ".sql", ".html"}
# The glossary and agent instructions name avoided terms in order to rule them out.
EXEMPT = {GLOSSARY, REPOSITORY / "AGENTS.md", Path(__file__).resolve()}
COMPILED = REPOSITORY / "src/calendar_sync/interfaces/api/static"


def _searched_files() -> list[Path]:
    files = [path for path in REPOSITORY.glob("*.md") if path not in EXEMPT]
    for root in SEARCHED:
        files.extend(
            path
            for path in (REPOSITORY / root).rglob("*")
            if path.suffix in SUFFIXES
            and path.is_file()
            and path not in EXEMPT
            and not path.is_relative_to(COMPILED)
            and "node_modules" not in path.parts
        )
    return files


def test_every_checked_term_is_one_the_glossary_avoids() -> None:
    avoided = {
        term.strip().lower()
        for line in GLOSSARY.read_text().splitlines()
        if line.startswith("_Avoid_:")
        for term in line.removeprefix("_Avoid_:").split(",")
    }

    assert set(AVOIDED) <= avoided, set(AVOIDED) - avoided


def test_code_and_documentation_do_not_use_avoided_terms() -> None:
    pattern = re.compile(
        r"\b(?:" + "|".join(re.escape(term) for term in AVOIDED) + r")(?:s|es)?\b", re.IGNORECASE
    )
    found = [
        f"{path.relative_to(REPOSITORY)}:{number}: {match.group()}"
        for path in _searched_files()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        for match in pattern.finditer(line)
    ]

    assert not found, "Use the CONTEXT.md term instead:\n" + "\n".join(found)
