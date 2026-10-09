from __future__ import annotations

from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, Response, status

from calendar_sync.application.errors import InvalidIntegrationTokenName
from calendar_sync.application.installation_health import GetInstallationHealth
from calendar_sync.application.ports import (
    IntegrationTokens,
    IntegrationTokenScope,
    IntegrationTokenSummary,
)
from calendar_sync.application.status import GetInstallationStatus
from calendar_sync.domain.access import UserId
from calendar_sync.interfaces.api.dependencies import (
    Identity,
    app_services,
    current_user,
    installation_reader,
    status_reader,
    user_services,
)
from calendar_sync.interfaces.api.problems import problem, problem_from
from calendar_sync.interfaces.api.schemas import (
    InstallationHealthResponse,
    IntegrationTokenResponse,
    IssuedIntegrationTokenResponse,
    IssueIntegrationTokenRequest,
    StatusResponse,
)
from calendar_sync.interfaces.api.status_payload import (
    installation_health_response,
    status_response,
)


class IntegrationServices(Protocol):
    """One User's tokens and Installation Status."""

    @property
    def integration_tokens(self) -> IntegrationTokens: ...
    @property
    def get_installation_status(self) -> GetInstallationStatus: ...


class StatusServices(Protocol):
    def for_user(self, user_id: UserId) -> IntegrationServices: ...
    @property
    def installation_health(self) -> GetInstallationHealth: ...
    @property
    def identity(self) -> Identity: ...


Services = Annotated[IntegrationServices, Depends(user_services)]
Installation = Annotated[StatusServices, Depends(app_services)]
Reader = Annotated[UserId, Depends(status_reader)]
HealthReader = Annotated[UserId, Depends(installation_reader)]
SignedIn = Annotated[UserId, Depends(current_user)]
ADMIN = [Depends(current_user)]
router = APIRouter()


@router.get("/api/v1/status", response_model=StatusResponse)
def installation_status(
    installation: Installation, reader: Reader, response: Response
) -> StatusResponse:
    """The Installation Status of the User the token or session belongs to (ADR 0030)."""
    response.headers["Cache-Control"] = "no-store"
    return status_response(installation.for_user(reader).get_installation_status.execute())


@router.get("/api/v1/installation/health", response_model=InstallationHealthResponse)
def installation_health(
    installation: Installation, _reader: HealthReader, response: Response
) -> InstallationHealthResponse:
    """Installation Health, for an Installation Administrator's session or installation:read
    token; it names no rule, calendar, or User (ADR 0030)."""
    response.headers["Cache-Control"] = "no-store"
    return installation_health_response(installation.installation_health.execute())


@router.get(
    "/api/v1/integration-tokens",
    response_model=list[IntegrationTokenResponse],
    dependencies=ADMIN,
)
def list_integration_tokens(services: Services) -> list[IntegrationTokenResponse]:
    return [_token(summary) for summary in services.integration_tokens.list()]


@router.post(
    "/api/v1/integration-tokens",
    response_model=IssuedIntegrationTokenResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=ADMIN,
)
def issue_integration_token(
    payload: IssueIntegrationTokenRequest,
    services: Services,
    installation: Installation,
    user: SignedIn,
    response: Response,
) -> IssuedIntegrationTokenResponse:
    response.headers["Cache-Control"] = "no-store"
    scopes = frozenset(IntegrationTokenScope(scope) for scope in payload.scopes)
    issuer = installation.identity.users.get(user)
    if IntegrationTokenScope.INSTALLATION_READ in scopes and (
        issuer is None or not issuer.administers
    ):
        raise problem(
            status.HTTP_403_FORBIDDEN,
            "administrator_required",
            "only an Installation Administrator may read Installation Health",
        )
    try:
        issued = services.integration_tokens.issue(payload.name, scopes)
    except InvalidIntegrationTokenName as error:
        raise problem_from(status.HTTP_422_UNPROCESSABLE_CONTENT, error) from error
    return IssuedIntegrationTokenResponse(**_token(issued.summary).model_dump(), token=issued.token)


@router.delete(
    "/api/v1/integration-tokens/{token_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=ADMIN,
)
def revoke_integration_token(token_id: str, services: Services) -> None:
    if not services.integration_tokens.revoke(token_id):
        raise problem(
            status.HTTP_404_NOT_FOUND, "integration_token_not_found", "integration token not found"
        )


def _token(summary: IntegrationTokenSummary) -> IntegrationTokenResponse:
    return IntegrationTokenResponse(
        id=summary.id,
        name=summary.name,
        scopes=sorted(scope.value for scope in summary.scopes),
        created_at=summary.created_at.isoformat(),
        last_used_at=summary.last_used_at.isoformat() if summary.last_used_at else None,
        revoked_at=summary.revoked_at.isoformat() if summary.revoked_at else None,
    )
