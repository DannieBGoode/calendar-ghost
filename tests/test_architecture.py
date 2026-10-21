"""Production code stays within the bounds Ruff sets, without suppressions or loopholes."""

import ast
import dataclasses
import importlib
import inspect
import pkgutil
import re
import tomllib
from pathlib import Path

import calendar_sync.application

REPOSITORY = Path(__file__).resolve().parents[1]
SOURCE = REPOSITORY / "src" / "calendar_sync"
PYPROJECT = tomllib.loads((REPOSITORY / "pyproject.toml").read_text(encoding="utf-8"))
RUFF = PYPROJECT["tool"]["ruff"]
# Ruff reads its rule selection from `[tool.ruff.lint]`, and still from `[tool.ruff]` itself.
RUFF_TABLES = (RUFF, RUFF.get("lint", {}))

BOUNDS = ("C901", "PLR0912", "PLR0913", "PLR0915")
# A `noqa` naming a bound, or naming no rule at all, which silences every rule on its line.
SUPPRESSION = re.compile(
    r"#\s*(?:ruff\s*:\s*)?noqa(?!\s*:)|#\s*(?:ruff\s*:\s*)?noqa\s*:[^#\n]*\b(?:"
    + "|".join(BOUNDS)
    + r")\b",
    re.IGNORECASE,
)

# Dataclass use cases and services that take more constructor arguments than Ruff's max-args.
# This is debt that may only shrink: split a class to remove its entry, and never add one.
WIDE_DATACLASSES = {
    "calendar_sync.application.sync.reconciliation.ReconcileSyncRule",
    "calendar_sync.application.sync.removal.RemoveSyncRule",
    "calendar_sync.application.sync.sync_run.SyncRunContext",
    "calendar_sync.application.sync.synchronization.ExecuteSyncRule",
}


def _production_files() -> list[Path]:
    return sorted(SOURCE.rglob("*.py"))


def test_no_production_code_suppresses_a_complexity_or_argument_bound() -> None:
    found = [
        f"{path.relative_to(REPOSITORY)}:{number}"
        for path in _production_files()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if SUPPRESSION.search(line)
    ]

    assert found == [], "split the code instead of suppressing the bound"


def test_the_suppression_pattern_finds_what_it_must() -> None:
    assert SUPPRESSION.search("def run(self):  # noqa: C901")
    assert SUPPRESSION.search("def run(self):  # noqa: ARG002, PLR0913")
    assert SUPPRESSION.search("def run(self):  # noqa")
    assert SUPPRESSION.search("# ruff: noqa: PLR0915")
    assert not SUPPRESSION.search("TOKEN = 'x'  # noqa: S105")


def test_ruff_configuration_exempts_no_production_code_from_the_bounds() -> None:
    def covers(code: str) -> bool:
        return any(bound.startswith(code) for bound in BOUNDS)

    ignored = [
        code
        for table in RUFF_TABLES
        for key in ("ignore", "extend-ignore")
        for code in table.get(key, [])
        if covers(code)
    ]
    per_file = [
        (pattern, code)
        for table in RUFF_TABLES
        for key in ("per-file-ignores", "extend-per-file-ignores")
        for pattern, codes in table.get(key, {}).items()
        if not pattern.startswith("tests/")
        for code in codes
        if covers(code)
    ]

    assert ignored == []
    assert per_file == []


def test_no_other_ruff_configuration_can_override_the_bounds() -> None:
    """A `ruff.toml` or `.ruff.toml` takes precedence over `pyproject.toml` where it sits."""
    found = [
        str(path.relative_to(REPOSITORY))
        for name in ("ruff.toml", ".ruff.toml")
        for path in [REPOSITORY / name, *SOURCE.parents[0].rglob(name)]
        if path.exists()
    ]

    assert found == []


def _application_dataclasses() -> list[type]:
    package = calendar_sync.application
    classes: list[type] = []
    for info in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
        module = importlib.import_module(info.name)
        classes.extend(
            value
            for value in vars(module).values()
            if inspect.isclass(value)
            and value.__module__ == module.__name__
            and dataclasses.is_dataclass(value)
        )
    return classes


def _wide_dataclasses() -> set[str]:
    """Dataclasses with behavior whose generated constructor exceeds Ruff's max-args.

    Ruff bounds a hand-written `__init__`, not the one a dataclass generates, so a use case can
    grow past the bound unseen. Dataclasses without methods of their own are records of data,
    which the bound does not concern.
    """
    max_args = PYPROJECT["tool"]["ruff"]["lint"]["pylint"]["max-args"]
    return {
        f"{cls.__module__}.{cls.__qualname__}"
        for cls in _application_dataclasses()
        if any(
            inspect.isfunction(member) and not name.startswith("__")
            for name, member in vars(cls).items()
        )
        and sum(field.init for field in dataclasses.fields(cls)) > max_args
    }


def test_no_new_application_dataclass_takes_more_arguments_than_ruff_allows() -> None:
    assert _wide_dataclasses() - WIDE_DATACLASSES == set()


def test_the_wide_dataclass_allowlist_names_only_classes_still_too_wide() -> None:
    assert WIDE_DATACLASSES - _wide_dataclasses() == set(), "remove the entry: it was split"


def _creates_rule_locks(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "RuleLocks":
                return True
            if any(
                isinstance(keyword.value, ast.Name) and keyword.value.id == "RuleLocks"
                for keyword in node.keywords
            ):
                return True
    return False


def test_only_the_composition_root_creates_a_rule_lock_registry() -> None:
    """Rules are serialized only while every use case holds the installation's one registry."""
    creators = [
        str(path.relative_to(SOURCE))
        for path in _production_files()
        if _creates_rule_locks(ast.parse(path.read_text(encoding="utf-8")))
    ]

    assert creators == ["bootstrap/container.py"]
