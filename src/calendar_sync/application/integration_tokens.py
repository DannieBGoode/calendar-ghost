"""What an Integration Token and its name may look like; checked before any lookup."""

from __future__ import annotations

import re
import unicodedata

from calendar_sync.application.errors import InvalidIntegrationTokenName

TOKEN_PREFIX = "cgs_"  # noqa: S105
# The prefix and 32 random bytes in unpadded URL-safe base64.
_TOKEN = re.compile(r"cgs_[A-Za-z0-9_-]{43}")
NAME_LIMIT = 80


def is_well_formed(token: str) -> bool:
    return _TOKEN.fullmatch(token) is not None


def token_name(raw: str) -> str:
    name = raw.strip()
    if not 1 <= len(name) <= NAME_LIMIT or any(
        unicodedata.category(character).startswith("C") for character in name
    ):
        raise InvalidIntegrationTokenName("name must be 1 to 80 printable characters")
    return name
