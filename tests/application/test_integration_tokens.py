import pytest

from calendar_sync.application.errors import InvalidIntegrationTokenName
from calendar_sync.application.integration_tokens import is_well_formed, token_name

VALID = "cgs_" + "A" * 43


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        (VALID, True),
        ("cgs_" + "a-_9" * 10 + "abc", True),
        ("cgs_" + "A" * 42, False),
        ("cgs_" + "A" * 44, False),
        ("cgx_" + "A" * 43, False),
        ("cgs_" + "A" * 42 + "=", False),
        ("cgs_" + "A" * 42 + "\n", False),
        ("", False),
        ("x" * 10_000, False),
    ],
)
def test_only_the_exact_token_format_is_well_formed(token: str, expected: bool) -> None:
    assert is_well_formed(token) is expected


def test_names_are_trimmed() -> None:
    assert token_name("  Uptime Kuma  ") == "Uptime Kuma"


@pytest.mark.parametrize(
    "name",
    ["", "   ", "x" * 81, "Kuma\nadmin", "Kuma\x1b[31m", "Kuma\u2028admin", "Kuma\u2029admin"],
)
def test_names_must_be_short_printable_text(name: str) -> None:
    with pytest.raises(InvalidIntegrationTokenName):
        token_name(name)
