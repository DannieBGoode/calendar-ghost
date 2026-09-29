"""Code and documentation use the glossary's terms, not the ones `CONTEXT.md` says to avoid."""

import re
from pathlib import Path

import pytest

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
# Compiled assets, and implementation plans kept as a record of how past work was planned.
UNSEARCHED = (
    REPOSITORY / "src/calendar_sync/interfaces/api/static",
    REPOSITORY / "docs/superpowers/plans",
)


def _term_pattern(term: str) -> str:
    """A term as prose, an identifier in any case style, or wrapped across lines, with plurals."""
    *leading, last = term.split()
    plural = f"(?i:{last[:-1]})(?i:y|ies)" if last.endswith("y") else f"(?i:{last})(?i:e?s)?"
    words = [f"(?i:{word})" for word in leading] + [plural]
    # A term starts after a non-letter or at a camelCase boundary, and ends before a lowercase
    # letter, so "syncPairs" and "SYNC_PAIR" match while "async pairing" does not.
    return r"(?:(?<![A-Za-z])|(?<=[a-z])(?=[A-Z]))" + r"[\s_-]*".join(words) + r"(?![a-z])"


AVOIDED_PATTERN = re.compile("|".join(_term_pattern(term) for term in AVOIDED))


def avoided_terms_in(text: str) -> list[tuple[int, str]]:
    """Line number and wording of each avoided term in `text`."""
    return [
        (text.count("\n", 0, match.start()) + 1, " ".join(match.group().split()))
        for match in AVOIDED_PATTERN.finditer(text)
    ]


def _searched_files() -> list[Path]:
    files = [path for path in REPOSITORY.glob("*.md") if path not in EXEMPT]
    for root in SEARCHED:
        files.extend(
            path
            for path in (REPOSITORY / root).rglob("*")
            if path.suffix in SUFFIXES
            and path.is_file()
            and path not in EXEMPT
            and not any(path.is_relative_to(skipped) for skipped in UNSEARCHED)
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


@pytest.mark.parametrize(
    "text",
    [
        "a sync pair",
        "Sync Pairs",
        "sync_pair = None",
        "SYNC_PAIRS",
        "class SyncPair:",
        "mySyncPair",
        "sync-pair",
        "the sync\n  pair",
        "two event copies",
        "EventCopies",
        "target calendars",
    ],
)
def test_avoided_terms_are_found_in_any_spelling(text: str) -> None:
    assert avoided_terms_in(text)


@pytest.mark.parametrize(
    "text",
    ["async pairing", "sync pairing", "resync pair", "event copyright", "retarget calendar"],
)
def test_words_that_merely_contain_an_avoided_term_are_allowed(text: str) -> None:
    assert not avoided_terms_in(text)


def test_code_and_documentation_do_not_use_avoided_terms() -> None:
    found = [
        f"{path.relative_to(REPOSITORY)}:{line}: {wording}"
        for path in _searched_files()
        for line, wording in avoided_terms_in(path.read_text(encoding="utf-8"))
    ]

    assert not found, "Use the CONTEXT.md term instead:\n" + "\n".join(found)
