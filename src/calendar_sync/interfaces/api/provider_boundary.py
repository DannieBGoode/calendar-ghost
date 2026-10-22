"""Trusted cookies, exact Origin, and safe failures shared by provider sign-in routes."""

import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated, Protocol

from fastapi import Depends, Request, Response

from calendar_sync.application.identity.administration import AdministratorRequired, UserNotFound
from calendar_sync.application.identity.errors import (
    IncorrectCredentials,
    IncorrectPassword,
    PasswordPolicyViolation,
    SignInThrottled,
)
from calendar_sync.application.identity.provider_links import ConfirmProviderLink
from calendar_sync.application.identity.provider_sign_in import (
    BeginProviderSignIn,
    CompleteProviderSignIn,
)
from calendar_sync.application.identity.provider_sign_in_ports import (
    BrowserProof,
    LastSignInMethod,
    LinkOwner,
    ProviderFlows,
    ProviderMethods,
    ProviderSignInLimits,
    ProviderSignInRefused,
    ProviderSignInSettings,
    ProviderSignInThrottled,
    ProviderSignInUnavailable,
)
from calendar_sync.application.identity.sign_in_methods import (
    ResolveProviderOwner,
    SetOwnPassword,
    UnlinkProviderIdentity,
)
from calendar_sync.domain.errors import DomainValidationError
from calendar_sync.interfaces.api.dependencies import SESSION_COOKIE, app_services
from calendar_sync.interfaces.api.problems import ApiProblem, problem, problem_from
from calendar_sync.interfaces.api.routes.registration import Registrations
from calendar_sync.interfaces.api.sign_in_cookies import (
    BROWSER_COOKIE,
    cookie_proof,
)


class ProviderRuntime(Protocol):
    @property
    def begin(self) -> BeginProviderSignIn: ...
    @property
    def complete(self) -> CompleteProviderSignIn: ...
    @property
    def confirm(self) -> ConfirmProviderLink: ...
    @property
    def flows(self) -> ProviderFlows: ...
    @property
    def limits(self) -> ProviderSignInLimits: ...


class ProviderMethodsServices(Protocol):
    @property
    def methods(self) -> ProviderMethods: ...
    @property
    def owner(self) -> ResolveProviderOwner: ...
    @property
    def unlink(self) -> UnlinkProviderIdentity: ...
    @property
    def set_password(self) -> SetOwnPassword: ...


class ProviderServices(Protocol):
    @property
    def origin(self) -> str | None: ...
    @property
    def secure(self) -> bool: ...
    @property
    def settings(self) -> ProviderSignInSettings: ...
    @property
    def methods(self) -> ProviderMethodsServices: ...
    @property
    def runtime(self) -> ProviderRuntime | None: ...


class ProviderApiServices(Protocol):
    @property
    def provider_sign_in(self) -> ProviderServices: ...
    @property
    def registrations(self) -> Registrations: ...


Services = Annotated[ProviderApiServices, Depends(app_services)]


def require_origin(request: Request, services: ProviderServices) -> None:
    if services.origin is None or request.headers.get("origin") != services.origin:
        raise problem(403, "origin_required", "The configured Origin is required")


def browser_proof(request: Request, *, fresh: bool = False) -> BrowserProof:
    value = cookie_proof(request, BROWSER_COOKIE)
    if value is None and fresh:
        value = secrets.token_urlsafe(32)
    if value is None:
        raise ProviderSignInRefused
    return BrowserProof(value)


def set_proof(response: Response, name: str, value: str, secure: bool) -> None:
    response.set_cookie(
        name, value, max_age=600, httponly=True, secure=secure, samesite="lax", path="/"
    )


def resolve_owner(request: Request, services: ProviderServices) -> LinkOwner | None:
    return services.methods.owner.execute(request.cookies.get(SESSION_COOKIE))


def require_anonymous(request: Request, services: ProviderServices) -> None:
    if resolve_owner(request, services) is not None:
        raise ProviderSignInRefused


def runtime(services: ProviderServices) -> ProviderRuntime:
    if services.runtime is None:
        raise ProviderSignInUnavailable
    return services.runtime


def client(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@contextmanager
def provider_errors() -> Iterator[None]:
    try:
        yield
    except ApiProblem:
        raise
    except (ProviderSignInThrottled, SignInThrottled) as error:
        raise problem_from(429, error) from None
    except (ProviderSignInRefused, IncorrectCredentials) as error:
        raise problem_from(401, error) from None
    except (LastSignInMethod, IncorrectPassword) as error:
        raise problem_from(409, error) from None
    except UserNotFound as error:
        raise problem_from(404, error) from None
    except AdministratorRequired as error:
        raise problem_from(403, error) from None
    except PasswordPolicyViolation as error:
        raise problem_from(422, error) from None
    except DomainValidationError:
        raise problem_from(422, ProviderSignInUnavailable()) from None
    except Exception:
        # Public storage/transport failures expose neither provider diagnostics nor inputs.
        raise problem_from(503, ProviderSignInUnavailable()) from None
