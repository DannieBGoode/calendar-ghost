"""Administrator-only identity email readiness and bounded test admission."""

from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, Response

from calendar_sync.application.identity.administration import AdministratorRequired
from calendar_sync.application.identity.identity_email import (
    IdentityEmailNotConfigured,
    IdentityEmailQueueBusy,
    IdentityEmailStorageUnavailable,
    IdentityEmailTestThrottled,
    RequestIdentityEmailTest,
    ShowIdentityEmail,
)
from calendar_sync.domain.access import UserId
from calendar_sync.interfaces.api.dependencies import administrator, app_services
from calendar_sync.interfaces.api.problems import ApiProblem, problem_from
from calendar_sync.interfaces.api.schemas.identity import (
    IdentityEmailResponse,
)


class IdentityEmail(Protocol):
    @property
    def show(self) -> ShowIdentityEmail: ...
    @property
    def request_test(self) -> RequestIdentityEmailTest: ...


class IdentityEmailApiServices(Protocol):
    @property
    def identity_email(self) -> IdentityEmail: ...


Services = Annotated[IdentityEmailApiServices, Depends(app_services)]
Administrator = Annotated[UserId, Depends(administrator)]
router = APIRouter()
NO_STORE = {"Cache-Control": "no-store"}
_ERRORS = (
    IdentityEmailNotConfigured,
    IdentityEmailQueueBusy,
    IdentityEmailStorageUnavailable,
    IdentityEmailTestThrottled,
    AdministratorRequired,
)


def _failure(error: Exception) -> ApiProblem:
    status = 429 if isinstance(error, IdentityEmailTestThrottled) else 503
    if isinstance(error, AdministratorRequired):
        status = 403
    answer = problem_from(status, error)
    answer.headers = {**(answer.headers or {}), **NO_STORE}
    return answer


@router.get("/api/v1/identity-email", response_model=IdentityEmailResponse)
def identity_email(
    services: Services, actor: Administrator, response: Response
) -> IdentityEmailResponse:
    response.headers.update(NO_STORE)
    try:
        result = services.identity_email.show.execute(actor)
    except _ERRORS as error:
        raise _failure(error) from None
    return IdentityEmailResponse.model_validate(result, from_attributes=True)


@router.post("/api/v1/identity-email/test", status_code=202, response_class=Response)
def test_identity_email(services: Services, actor: Administrator) -> Response:
    try:
        services.identity_email.request_test.execute(actor)
    except _ERRORS as error:
        raise _failure(error) from None
    return Response(status_code=202, headers=NO_STORE)
