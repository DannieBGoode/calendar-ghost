"""What an Integration Token and its name may look like, checked before any lookup, and issuing
one within the User's Plan (ADR 0038)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from calendar_sync.application.identity.administration import AdministratorRequired
from calendar_sync.application.identity.errors import InvalidIntegrationTokenName
from calendar_sync.application.identity.ports import (
    IntegrationTokens,
    IntegrationTokenScope,
    IssuedIntegrationToken,
    UserDirectory,
)
from calendar_sync.application.sync.plan_ports import Allowances
from calendar_sync.domain.access import UserId

TOKEN_PREFIX = "cgs_"  # noqa: S105
# The prefix and 32 random bytes in unpadded URL-safe base64.
_TOKEN = re.compile(r"cgs_[A-Za-z0-9_-]{43}")
NAME_LIMIT = 80
# Control and format characters, and the line and paragraph separators that break a line.
_REFUSED_CATEGORIES = ("C", "Zl", "Zp")


def is_well_formed(token: str) -> bool:
    return _TOKEN.fullmatch(token) is not None


def token_name(raw: str) -> str:
    name = raw.strip()
    if not 1 <= len(name) <= NAME_LIMIT or any(
        unicodedata.category(character).startswith(_REFUSED_CATEGORIES) for character in name
    ):
        raise InvalidIntegrationTokenName("name must be 1 to 80 printable characters")
    return name


@dataclass(slots=True)
class IssueIntegrationToken:
    """Issue one of the User's Integration Tokens, within their Plan's token limit (ADR 0038)."""

    user: UserId
    users: UserDirectory
    tokens: IntegrationTokens
    allowances: Allowances

    def execute(
        self, name: str, scopes: frozenset[IntegrationTokenScope]
    ) -> IssuedIntegrationToken:
        if IntegrationTokenScope.INSTALLATION_READ in scopes:
            # Checked before the limit is read: Installation Health is for administrators only
            # (ADR 0030), whatever their Plan allows.
            issuer = self.users.get(self.user)
            if issuer is None or not issuer.administers:
                raise AdministratorRequired(
                    "only an Installation Administrator may read Installation Health"
                )
        # The store reads the limit once it holds its write lock. A read that raises fails the
        # issue, so a fault never admits a token past the limit.
        return self.tokens.issue(name, scopes, within=self._token_limit)

    def _token_limit(self) -> int | None:
        return self.allowances.of(self.user).limits.integration_tokens
