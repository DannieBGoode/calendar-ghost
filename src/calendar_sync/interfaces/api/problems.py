"""Error responses: an English detail for API clients and logs, and a code the Web UI translates.

Every error body is `{"detail": ..., "code": ..., "params": {...}}` (ADR 0026). Codes name the
condition, never the HTTP status, and never change once shipped.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.utils import is_body_allowed_for_status_code
from starlette.exceptions import HTTPException as StarletteHTTPException

from calendar_sync.application.errors import (
    AccountAccessCheckFailed,
    ActivityEventNotFound,
    ActivityRuleRemoved,
    AdminAlreadyConfigured,
    AuthorizationFailed,
    AuthorizationNotConfigured,
    ConnectedAccountDisconnected,
    ConnectedAccountMustBeDisconnected,
    ConnectedAccountNotFound,
    ConnectedAccountRequired,
    DuplicateDirectionalRelationship,
    EventInspectionUnavailable,
    FileLoggingOff,
    InvalidActivityAge,
    InvalidAuthorizationState,
    InvalidIntegrationTokenName,
    NotACalendarChange,
    PasswordPolicyViolation,
    ProviderFailure,
    RemovalInterrupted,
    RemovalRequiresAuthorization,
    RemovalRequiresProvider,
    ReplacementInterrupted,
    RuleNotExecutable,
    RuleNotFound,
    StorageBusy,
)
from calendar_sync.domain.errors import DomainValidationError, InvalidStateTransition

type ParamValue = str | int | None


class ApiProblem(HTTPException):
    """An HTTPException with a code, so code that catches FastAPI's exceptions still sees it."""

    def __init__(
        self,
        status_code: int,
        code: str,
        detail: str,
        params: Mapping[str, ParamValue] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(status_code, detail, headers=dict(headers) if headers else None)
        self.code = code
        self.params: dict[str, ParamValue] = dict(params or {})


def problem(
    status_code: int,
    code: str,
    detail: str,
    /,
    *,
    headers: Mapping[str, str] | None = None,
    **params: ParamValue,
) -> ApiProblem:
    return ApiProblem(status_code, code, detail, params, headers)


# Looked up along each exception's MRO, so a subclass inherits its parent's code.
_CODES: dict[type[Exception], str] = {
    RuleNotFound: "rule_not_found",
    RuleNotExecutable: "rule_not_executable",
    DuplicateDirectionalRelationship: "duplicate_relationship",
    NotACalendarChange: "not_a_calendar_change",
    RemovalRequiresProvider: "removal_requires_provider",
    RemovalRequiresAuthorization: "removal_requires_authorization",
    RemovalInterrupted: "removal_interrupted",
    ReplacementInterrupted: "replacement_interrupted",
    ProviderFailure: "provider_failed",
    AdminAlreadyConfigured: "setup_complete",
    PasswordPolicyViolation: "password_policy",
    ConnectedAccountNotFound: "account_not_found",
    ConnectedAccountDisconnected: "account_disconnected",
    ConnectedAccountRequired: "account_required",
    ConnectedAccountMustBeDisconnected: "account_must_be_disconnected",
    AuthorizationNotConfigured: "authorization_not_configured",
    InvalidAuthorizationState: "invalid_authorization_state",
    AuthorizationFailed: "authorization_failed",
    AccountAccessCheckFailed: "account_access_check_failed",
    ActivityEventNotFound: "source_event_not_found",
    ActivityRuleRemoved: "activity_rule_removed",
    EventInspectionUnavailable: "event_inspection_unavailable",
    InvalidActivityAge: "invalid_activity_age",
    StorageBusy: "storage_busy",
    FileLoggingOff: "file_logging_off",
    InvalidIntegrationTokenName: "invalid_integration_token_name",
    DomainValidationError: "invalid_rule",
    # Every rejected lifecycle change (enable, pause, policy edit) with a message naming the state.
    InvalidStateTransition: "invalid_state_transition",
}


def failure_params(failure: ProviderFailure) -> dict[str, ParamValue]:
    """Which provider failed and how, for a message that names them."""
    return {
        "provider": failure.provider.value if failure.provider else None,
        "kind": failure.kind.value,
    }


def _removal_params(removal: RemovalInterrupted) -> dict[str, ParamValue]:
    return {
        "processed": removal.processed,
        "remaining": removal.remaining,
        "total": removal.processed + removal.remaining,
        **failure_params(removal.failure),
    }


def _params(error: Exception) -> dict[str, ParamValue]:
    if isinstance(error, ReplacementInterrupted):
        return {
            "replacement_rule_id": error.replacement_rule_id.value,
            **_removal_params(error.removal),
        }
    if isinstance(error, RemovalInterrupted):
        return _removal_params(error)
    if isinstance(error, ProviderFailure):
        return failure_params(error)
    return {}


def problem_from(status_code: int, error: Exception, *, fallback: str | None = None) -> ApiProblem:
    """The problem for a use-case failure, keeping its English message as the detail.

    `fallback` is the code for exceptions the table does not name; without it they are a bug.
    """
    code = next((_CODES[kind] for kind in type(error).__mro__ if kind in _CODES), fallback)
    if code is None:
        raise TypeError(f"no error code for {type(error).__name__}")
    return ApiProblem(status_code, code, str(error), _params(error))


# Codes for errors raised outside the routes, such as Starlette's own; routes always name theirs.
_STATUS_CODES = {
    400: "bad_request",
    401: "session_required",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    410: "gone",
    422: "invalid_request",
    424: "dependency_failed",
    503: "service_unavailable",
}
_UNLISTED_STATUS = "request_failed"


async def _http_problem(_request: Request, error: Exception) -> Response:
    assert isinstance(error, StarletteHTTPException)
    if not is_body_allowed_for_status_code(error.status_code):
        return Response(status_code=error.status_code, headers=error.headers)
    if isinstance(error, ApiProblem):
        code, params = error.code, error.params
    else:
        code, params = _STATUS_CODES.get(error.status_code, _UNLISTED_STATUS), {}
    return JSONResponse(
        {"detail": error.detail, "code": code, "params": params},
        status_code=error.status_code,
        headers=error.headers,
    )


async def _validation_problem(_request: Request, error: Exception) -> JSONResponse:
    """FastAPI's list of errors stays the detail; params name the first one for the Web UI."""
    assert isinstance(error, RequestValidationError)
    errors = list(error.errors())
    params: dict[str, Any] = {}
    if errors:
        first = errors[0]
        params = {"field": str(first["loc"][-1]), "reason": first["type"]}
        context = first.get("ctx") or {}
        params |= {key: context[key] for key in ("min_length", "max_length") if key in context}
    return JSONResponse(
        {"detail": jsonable_encoder(errors), "code": "invalid_request", "params": params},
        status_code=422,
    )


def install_problem_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, _http_problem)
    app.add_exception_handler(RequestValidationError, _validation_problem)
