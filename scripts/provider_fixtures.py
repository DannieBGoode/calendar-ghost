"""Turn recorded Google Calendar and Microsoft Graph answers into synthetic test fixtures.

    .venv/bin/python scripts/provider_fixtures.py RECORDED.json FIXTURE.json

Live provider checks (docs/development.md) record real answers to learn their exact shape, and
real provider responses are never committed (AGENTS.md). This keeps every key, type, date, status,
and recurrence rule, and replaces what names a person, an account, or a provider's item: item
identifiers, version stamps, email addresses, people's names, and links' query strings. Each
distinct value gets one stable placeholder, so two fields that named the same item, such as an
occurrence's `seriesMasterId` and its master's `id`, still name the same placeholder. Event text is
kept, so record synthetic test events only.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

# Keys whose values identify a provider's item or calendar.
ITEM_KEYS = frozenset(
    {
        "id",
        "seriesMasterId",
        "iCalUId",
        "iCalUID",
        "uid",
        "recurringEventId",
        "transactionId",
        "occurrenceId",
        "calendarId",
    }
)
# Keys whose values are a version stamp of an item.
VERSION_KEYS = frozenset({"changeKey", "@odata.etag", "etag"})
# Keys naming a person rather than an item.
NAME_KEYS = frozenset({"name", "displayName"})
# An email address; Graph's own annotations, such as `calendar@odata.navigationLink`, are not.
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+(?:%40|@)(?!odata\.)[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Any other long opaque token, such as a calendar id inside a link or a hashed key.
TOKEN = re.compile(r"[A-Za-z0-9_+/=-]{32,}")
# Text that names a test calendar or event is kept: the checks create only those.
TEST_PREFIX = "CG "


class Sanitizer:
    """Replaces identifying values with placeholders, the same one for the same value."""

    def __init__(self) -> None:
        self.items: dict[str, str] = {}
        self.versions: dict[str, str] = {}
        self.emails: dict[str, str] = {}
        self.names: dict[str, str] = {}
        self.tokens: dict[str, str] = {}

    def sanitize(self, recorded: Any) -> Any:
        self._collect(recorded)
        return self._replace(recorded, key=None)

    def _collect(self, value: Any, key: str | None = None) -> None:
        if isinstance(value, dict):
            for child_key, child in value.items():
                self._collect(child, child_key)
        elif isinstance(value, list):
            for child in value:
                self._collect(child, key)
        elif isinstance(value, str) and value:
            if key in ITEM_KEYS:
                self.items.setdefault(value, f"item-{len(self.items) + 1}")
            elif key in VERSION_KEYS:
                self.versions.setdefault(value, f"version-{len(self.versions) + 1}")

    def _replace(self, value: Any, key: str | None) -> Any:
        if isinstance(value, dict):
            return {
                child_key: self._replace(child, child_key) for child_key, child in value.items()
            }
        if isinstance(value, list):
            return [self._replace(child, key) for child in value]
        if not isinstance(value, str):
            return value
        if key in VERSION_KEYS:
            return self.versions.get(value, value)
        if key in NAME_KEYS and not value.startswith(TEST_PREFIX) and "@" not in value:
            return self.names.setdefault(value, f"Person {len(self.names) + 1}")
        return self._text(value)

    def _text(self, value: str) -> str:
        # Longest first, so an identifier that contains another is replaced whole.
        for original in sorted(self.items, key=len, reverse=True):
            if original in value:
                value = value.replace(original, self.items[original])
        for original, placeholder in self.versions.items():
            value = value.replace(original, placeholder)
        value = EMAIL.sub(self._email, value)
        value = TOKEN.sub(
            lambda m: self.tokens.setdefault(m.group(0), f"token-{len(self.tokens) + 1}"), value
        )
        if value.startswith(("http://", "https://")):
            parts = urlsplit(value)
            query = "&".join(
                f"{pair.split('=', 1)[0]}=redacted" if "=" in pair else pair
                for pair in parts.query.split("&")
                if pair
            )
            value = urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))
        return value

    def _email(self, match: re.Match[str]) -> str:
        address = match.group(0).replace("%40", "@")
        if address.endswith("@example.test"):
            return address
        domain = (
            "group.calendar.example.test"
            if address.endswith("group.calendar.google.com")
            else "example.test"
        )
        return self.emails.setdefault(address, f"address-{len(self.emails) + 1}@{domain}")


def main(recorded_path: str, fixture_path: str) -> None:
    recorded = json.loads(Path(recorded_path).read_text())
    fixture = Sanitizer().sanitize(recorded)
    Path(fixture_path).write_text(json.dumps(fixture, indent=1, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2])
