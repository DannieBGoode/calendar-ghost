"""The OAuth callback reports only outcomes the Web UI names, and the Web UI names no other."""

import re
from pathlib import Path

from calendar_sync.interfaces.api.routes.accounts import OAUTH_OUTCOMES

OAUTH_REDIRECT = Path(__file__).resolve().parents[2] / "web" / "src" / "lib" / "oauth-redirect.ts"


def _web_outcomes() -> set[str]:
    """The values of the Web UI's `OAuthOutcome` union, from its declaration to the blank line
    that ends it."""
    source = OAUTH_REDIRECT.read_text()
    start = source.index("export type OAuthOutcome =")
    return set(re.findall(r'"([^"]+)"', source[start : source.index("\n\n", start)]))


def test_the_server_and_the_web_ui_name_the_same_oauth_outcomes() -> None:
    assert _web_outcomes() == set(OAUTH_OUTCOMES)
