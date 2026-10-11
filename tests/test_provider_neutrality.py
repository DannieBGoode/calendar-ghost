"""The core never names a provider, and nothing outside a provider's package branches on one.

Only a Provider Kind's own definition names a provider in the domain, application, and
interfaces, apart from the routes kept for earlier clients. Everything else about a provider
reaches the core through its descriptor (ADR 0022), so adding a provider needs a new package and
one line of composition, and no change here.
"""

import ast
import re
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "calendar_sync"
CORE = ("domain", "application", "interfaces")
ADAPTER_PACKAGES = ("infrastructure/google", "infrastructure/microsoft")
# ProviderKind's own definition, and the routes kept so earlier clients keep working.
NAMING_ALLOWED = {"application/providers.py", "interfaces/api/routes/compatibility.py"}
PROVIDER_NAMES = re.compile(
    r"google|gmail|microsoft|outlook|office ?365|entra|azure|aadsts|graph\.microsoft|icloud",
    re.IGNORECASE,
)


def _modules(*roots: str) -> list[Path]:
    return sorted(path for root in roots for path in (PACKAGE / root).rglob("*.py"))


def _relative(path: Path) -> str:
    return path.relative_to(PACKAGE).as_posix()


@pytest.mark.parametrize("module", _modules(*CORE), ids=_relative)
def test_the_core_names_no_provider(module: Path) -> None:
    if _relative(module) in NAMING_ALLOWED:
        return
    named = [
        (number, line.strip())
        for number, line in enumerate(module.read_text().splitlines(), start=1)
        if PROVIDER_NAMES.search(line)
    ]

    assert named == []


def _outside_adapters() -> list[Path]:
    return [
        module
        for module in _modules(".")
        if not _relative(module).startswith(ADAPTER_PACKAGES)
        and _relative(module) != "application/providers.py"
    ]


@pytest.mark.parametrize("module", _outside_adapters(), ids=_relative)
def test_nothing_outside_a_providers_package_names_one_of_its_kinds(module: Path) -> None:
    # Naming a member, as in `kind is ProviderKind.EXAMPLE`, is how code would branch on it.
    members = [
        node.lineno
        for node in ast.walk(ast.parse(module.read_text()))
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "ProviderKind"
        and node.attr.isupper()
    ]

    assert members == []


def test_the_check_finds_a_provider_name_and_a_branch() -> None:
    sample = "if account.provider is ProviderKind.EXAMPLE:  # Outlook only\n    pass\n"
    tree = ast.parse(sample)

    assert PROVIDER_NAMES.search(sample)
    assert any(
        isinstance(node, ast.Attribute) and node.attr == "EXAMPLE" for node in ast.walk(tree)
    )
