"""Who may read Installation Status: the one decision the status API and MCP share."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from calendar_sync.application.ports import (
    AdministratorAccess,
    IntegrationTokenAuthentication,
    IntegrationTokenScope,
)
from calendar_sync.domain.access import UserId


class StatusAccess(Enum):
    GRANTED = "granted"
    UNAUTHENTICATED = "unauthenticated"
    FORBIDDEN = "forbidden"


@dataclass(frozen=True, slots=True)
class StatusPrincipal:
    result: StatusAccess
    user: UserId | None = None
    """The User whose Installation Status is read, when access is granted."""


def status_access(
    tokens: IntegrationTokenAuthentication,
    administrator: AdministratorAccess,
    authorization: str | None,
    session: str | None,
) -> StatusPrincipal:
    """A present Authorization header decides alone, so a broken token is never hidden."""
    if authorization is not None:
        scheme, _, credential = authorization.partition(" ")
        summary = tokens.authenticate(credential.strip()) if scheme.lower() == "bearer" else None
        if summary is None:
            return StatusPrincipal(StatusAccess.UNAUTHENTICATED)
        if summary.scope is not IntegrationTokenScope.STATUS_READ:
            return StatusPrincipal(StatusAccess.FORBIDDEN)
        return StatusPrincipal(StatusAccess.GRANTED, summary.owner)
    user = administrator.session_user(session) if session is not None else None
    if user is not None:
        return StatusPrincipal(StatusAccess.GRANTED, user)
    return StatusPrincipal(StatusAccess.UNAUTHENTICATED)
