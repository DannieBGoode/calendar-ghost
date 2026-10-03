"""Who may read Installation Status: the one decision the status API and MCP share."""

from __future__ import annotations

from enum import Enum

from calendar_sync.application.ports import (
    AdministratorAccess,
    IntegrationTokens,
    IntegrationTokenScope,
)


class StatusAccess(Enum):
    GRANTED = "granted"
    UNAUTHENTICATED = "unauthenticated"
    FORBIDDEN = "forbidden"


def status_access(
    tokens: IntegrationTokens,
    administrator: AdministratorAccess,
    authorization: str | None,
    session: str | None,
) -> StatusAccess:
    """A present Authorization header decides alone, so a broken token is never hidden."""
    if authorization is not None:
        scheme, _, credential = authorization.partition(" ")
        summary = tokens.authenticate(credential.strip()) if scheme.lower() == "bearer" else None
        if summary is None:
            return StatusAccess.UNAUTHENTICATED
        if summary.scope is not IntegrationTokenScope.STATUS_READ:
            return StatusAccess.FORBIDDEN
        return StatusAccess.GRANTED
    if session is not None and administrator.session_is_valid(session):
        return StatusAccess.GRANTED
    return StatusAccess.UNAUTHENTICATED
