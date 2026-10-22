"""Anonymous email-first joining through purpose-bound registration proofs."""

from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, Request, Response, status

from calendar_sync.application.identity.administration import LinkUnusable
from calendar_sync.application.identity.errors import (
    IncorrectCredentials,
    PasswordPolicyViolation,
    SignInStorageUnavailable,
)
from calendar_sync.application.identity.registration import (
    CheckRegistration,
    CompleteRegistration,
    RequestRegistration,
)
from calendar_sync.application.identity.registration_admission import (
    RegistrationGlobalThrottled,
    RegistrationNetworkThrottled,
)
from calendar_sync.application.identity.registration_ports import (
    RegistrationReadiness,
    RegistrationStorageUnavailable,
    RegistrationUnavailable,
)
from calendar_sync.domain.access import InvalidEmail, User, UserId
from calendar_sync.interfaces.api.dependencies import Identity, app_services, set_session_cookie
from calendar_sync.interfaces.api.problems import ApiProblem, problem_from
from calendar_sync.interfaces.api.routes.session import SignedInAnswers, signed_in
from calendar_sync.interfaces.api.schemas.identity import (
    CompleteRegistrationRequest,
    RegistrationCheckRequest,
    RegistrationCheckResponse,
    SessionResponse,
    SignUpAcceptedResponse,
    SignUpRequest,
)
from calendar_sync.interfaces.api.sign_in_cookies import browser_context


class RegistrationAvailability(Protocol):
    @property
    def readiness(self) -> RegistrationReadiness: ...


class RegistrationAnswers(SignedInAnswers, Protocol):
    def get(self, user: UserId) -> User | None: ...


class Registrations(RegistrationAvailability, Protocol):
    @property
    def answers(self) -> RegistrationAnswers: ...
    @property
    def request(self) -> RequestRegistration: ...
    @property
    def check(self) -> CheckRegistration: ...
    @property
    def complete(self) -> CompleteRegistration: ...


class RegistrationApiServices(SignedInAnswers, Protocol):
    @property
    def registrations(self) -> Registrations: ...
    @property
    def identity(self) -> Identity: ...
    @property
    def secure_cookies(self) -> bool: ...


Services = Annotated[RegistrationApiServices, Depends(app_services)]
router = APIRouter()


def _client(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def unavailable() -> ApiProblem:
    return problem_from(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        RegistrationUnavailable("Registration is temporarily unavailable"),
    )


@router.post(
    "/api/v1/registrations/request",
    response_model=SignUpAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def request_registration(
    payload: SignUpRequest, request: Request, services: Services
) -> SignUpAcceptedResponse:
    try:
        services.registrations.request.execute(
            payload.email, _client(request), payload.invitation_token
        )
    except (RegistrationNetworkThrottled, RegistrationGlobalThrottled) as error:
        raise problem_from(status.HTTP_429_TOO_MANY_REQUESTS, error) from error
    except (RegistrationUnavailable, RegistrationStorageUnavailable) as error:
        raise unavailable() from error
    except InvalidEmail as error:
        raise problem_from(status.HTTP_422_UNPROCESSABLE_CONTENT, error) from error
    return SignUpAcceptedResponse()


@router.post("/api/v1/registrations/check", response_model=RegistrationCheckResponse)
def check_registration(
    payload: RegistrationCheckRequest, request: Request, services: Services
) -> RegistrationCheckResponse:
    try:
        pending = services.registrations.check.execute(payload.token, _client(request))
    except (RegistrationNetworkThrottled, RegistrationGlobalThrottled) as error:
        raise problem_from(status.HTTP_429_TOO_MANY_REQUESTS, error) from error
    except (RegistrationUnavailable, RegistrationStorageUnavailable) as error:
        raise unavailable() from error
    return RegistrationCheckResponse(
        usable=pending is not None, email=pending.email if pending else None
    )


@router.post("/api/v1/registrations", response_model=SessionResponse)
def complete_registration(
    payload: CompleteRegistrationRequest, request: Request, services: Services, response: Response
) -> SessionResponse:
    try:
        session = services.registrations.complete.execute(
            payload.token, payload.password, _client(request), browser_context(request)
        )
        try:
            user = services.registrations.answers.get(session.user_id)
            if user is None:
                raise IncorrectCredentials("Sign in to continue")
            answer = signed_in(user, services.registrations.answers)
        except SignInStorageUnavailable:
            raise IncorrectCredentials("Sign in to continue") from None
    except (RegistrationNetworkThrottled, RegistrationGlobalThrottled) as error:
        raise problem_from(status.HTTP_429_TOO_MANY_REQUESTS, error) from error
    except (RegistrationUnavailable, RegistrationStorageUnavailable) as error:
        raise unavailable() from error
    except LinkUnusable as error:
        raise problem_from(status.HTTP_410_GONE, error) from error
    except PasswordPolicyViolation as error:
        raise problem_from(status.HTTP_422_UNPROCESSABLE_CONTENT, error) from error
    except IncorrectCredentials as error:
        # Admission committed; recover at sign-in after a session failure or credential race.
        raise problem_from(status.HTTP_401_UNAUTHORIZED, error) from error
    set_session_cookie(response, session.token, services.secure_cookies)
    return answer
