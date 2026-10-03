from __future__ import annotations

from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, HTTPException, Response, status

from calendar_sync.application.errors import InvalidIntegrationTokenName
from calendar_sync.application.ports import IntegrationTokens, IntegrationTokenSummary
from calendar_sync.application.status import GetInstallationStatus
from calendar_sync.interfaces.api.dependencies import (
    app_services,
    require_admin,
    require_status_reader,
)
from calendar_sync.interfaces.api.schemas import (
    IntegrationTokenResponse,
    IssuedIntegrationTokenResponse,
    IssueIntegrationTokenRequest,
    StatusResponse,
)
from calendar_sync.interfaces.api.status_payload import status_response


class IntegrationServices(Protocol):
    @property
    def integration_tokens(self) -> IntegrationTokens: ...
    @property
    def get_installation_status(self) -> GetInstallationStatus: ...


Services = Annotated[IntegrationServices, Depends(app_services)]
ADMIN = [Depends(require_admin)]
router = APIRouter()


@router.get(
    "/api/v1/status",
    response_model=StatusResponse,
    dependencies=[Depends(require_status_reader)],
)
def installation_status(services: Services, response: Response) -> StatusResponse:
    response.headers["Cache-Control"] = "no-store"
    return status_response(services.get_installation_status.execute())


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
    payload: IssueIntegrationTokenRequest, services: Services
) -> IssuedIntegrationTokenResponse:
    try:
        issued = services.integration_tokens.issue(payload.name)
    except InvalidIntegrationTokenName as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    return IssuedIntegrationTokenResponse(**_token(issued.summary).model_dump(), token=issued.token)


@router.delete(
    "/api/v1/integration-tokens/{token_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=ADMIN,
)
def revoke_integration_token(token_id: str, services: Services) -> None:
    if not services.integration_tokens.revoke(token_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "integration token not found")


def _token(summary: IntegrationTokenSummary) -> IntegrationTokenResponse:
    return IntegrationTokenResponse(
        id=summary.id,
        name=summary.name,
        scope=summary.scope.value,
        created_at=summary.created_at.isoformat(),
        last_used_at=summary.last_used_at.isoformat() if summary.last_used_at else None,
        revoked_at=summary.revoked_at.isoformat() if summary.revoked_at else None,
    )
