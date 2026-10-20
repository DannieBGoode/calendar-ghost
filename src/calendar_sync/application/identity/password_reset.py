"""Narrow email recovery preparation, used outside the anonymous request path."""

from dataclasses import dataclass, field
from typing import Protocol

from calendar_sync.application.identity.ports import IssuedLink


@dataclass(frozen=True, slots=True)
class PreparedPasswordReset:
    recipient: str = field(repr=False)
    link: IssuedLink = field(repr=False)


class SelfServicePasswordResets(Protocol):
    def issue_for_email(self, email: str) -> PreparedPasswordReset | None:
        """Issue an active User a one-hour proof bound to their current credential.

        Earlier delivered links remain usable. Eligibility and the clock are read under the
        write lock. Unknown and disabled addresses return None.
        """
        ...
