"""Error bodies carry a stable code beside their English detail (ADR 0026)."""

import ast
import json
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from calendar_sync.application.errors import (
    InvalidIntegrationTokenName,
    ProviderFailure,
    ProviderFailureKind,
    RemovalInterrupted,
    ReplacementInterrupted,
    RuleNotFound,
)
from calendar_sync.application.providers import ProviderKind
from calendar_sync.domain.errors import DomainValidationError, InvalidStateTransition
from calendar_sync.domain.model import SyncRuleId
from calendar_sync.interfaces.api import problems
from calendar_sync.interfaces.api.problems import install_problem_handlers, problem, problem_from

REPOSITORY = Path(__file__).resolve().parents[2]
INTERFACES = REPOSITORY / "src/calendar_sync/interfaces"
API = INTERFACES / "api"
ENGLISH_COMMON = REPOSITORY / "web/src/i18n/locales/en/common.json"


class Password(BaseModel):
    password: str = Field(min_length=12, max_length=20)


def client() -> TestClient:
    app = FastAPI()
    install_problem_handlers(app)

    @app.get("/problem")
    def raise_problem() -> None:
        raise problem(409, "storage_busy", "storage is busy", retry_after=3)

    @app.get("/plain")
    def raise_plain() -> None:
        raise HTTPException(404, "Not Found")

    @app.get("/starlette")
    def raise_starlette() -> None:
        raise StarletteHTTPException(409, "busy")

    @app.get("/not-modified")
    def raise_without_body() -> None:
        raise StarletteHTTPException(304, headers={"ETag": "v1"})

    @app.get("/allowed")
    def raise_with_headers() -> None:
        raise problem(405, "method_not_allowed", "Method Not Allowed", headers={"Allow": "GET"})

    @app.post("/password")
    def check(body: Password) -> None:
        return None

    return TestClient(app)


def test_problem_renders_code_params_and_detail() -> None:
    response = client().get("/problem")
    assert response.status_code == 409
    assert response.json() == {
        "detail": "storage is busy",
        "code": "storage_busy",
        "params": {"retry_after": 3},
    }


def test_plain_http_exception_gets_a_status_code() -> None:
    assert client().get("/plain").json() == {
        "detail": "Not Found",
        "code": "not_found",
        "params": {},
    }


def test_starlette_base_exception_gets_a_status_code() -> None:
    response = client().get("/starlette")
    assert response.status_code == 409
    assert response.json() == {"detail": "busy", "code": "conflict", "params": {}}


def test_a_status_that_allows_no_body_keeps_its_headers_and_sends_none() -> None:
    response = client().get("/not-modified")
    assert response.status_code == 304
    assert response.content == b""
    assert response.headers["ETag"] == "v1"


def test_headers_survive() -> None:
    response = client().get("/allowed")
    assert response.headers["Allow"] == "GET"
    assert response.json()["code"] == "method_not_allowed"


def test_validation_errors_name_the_first_problem() -> None:
    body = client().post("/password", json={"password": "short"}).json()
    assert body["code"] == "invalid_request"
    assert body["params"] == {"field": "password", "reason": "string_too_short", "min_length": 12}
    assert isinstance(body["detail"], list)
    assert body["detail"][0]["msg"] == "String should have at least 12 characters"


def test_validation_errors_pass_the_maximum_length() -> None:
    body = client().post("/password", json={"password": "x" * 21}).json()
    assert body["code"] == "invalid_request"
    assert body["params"] == {"field": "password", "reason": "string_too_long", "max_length": 20}


GOOGLE_LIMIT = ProviderFailure(ProviderFailureKind.RATE_LIMIT, "429", provider=ProviderKind.GOOGLE)


@pytest.mark.parametrize(
    ("error", "code", "params"),
    [
        (RuleNotFound("rule r1 does not exist"), "rule_not_found", {}),
        (GOOGLE_LIMIT, "provider_failed", {"provider": "google", "kind": "rate_limit"}),
        (
            RemovalInterrupted(2, 3, GOOGLE_LIMIT),
            "removal_interrupted",
            {
                "processed": 2,
                "remaining": 3,
                "total": 5,
                "provider": "google",
                "kind": "rate_limit",
            },
        ),
        (
            ReplacementInterrupted(SyncRuleId("r2"), RemovalInterrupted(1, 1, GOOGLE_LIMIT)),
            "replacement_interrupted",
            {
                "replacement_rule_id": "r2",
                "processed": 1,
                "remaining": 1,
                "total": 2,
                "provider": "google",
                "kind": "rate_limit",
            },
        ),
        (DomainValidationError("name must not be empty"), "invalid_rule", {}),
        (InvalidStateTransition("cannot enable"), "invalid_state_transition", {}),
        (
            InvalidIntegrationTokenName("name must be 1 to 80 printable characters"),
            "invalid_integration_token_name",
            {},
        ),
    ],
)
def test_problem_from_maps_exceptions(
    error: Exception, code: str, params: dict[str, object]
) -> None:
    mapped = problem_from(422, error)
    assert (mapped.status_code, mapped.code, mapped.params, mapped.detail) == (
        422,
        code,
        params,
        str(error),
    )


def test_problem_from_refuses_an_unmapped_exception() -> None:
    with pytest.raises(TypeError):
        problem_from(500, RuntimeError("boom"))


def test_problem_from_uses_a_fallback_code_when_given() -> None:
    assert problem_from(409, RuntimeError("busy"), fallback="conflict").code == "conflict"


def _http_exception_uses(path: Path) -> list[str]:
    """Each import or use of a name `HTTPException`, however it is imported or aliased."""
    uses = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom):
            uses += [f"import:{node.lineno}" for a in node.names if a.name == "HTTPException"]
        elif isinstance(node, ast.Attribute) and node.attr == "HTTPException":
            uses.append(f"attribute:{node.lineno}")
        elif isinstance(node, ast.Name) and node.id == "HTTPException":
            uses.append(f"name:{node.lineno}")
    return uses


def test_api_modules_raise_problems_not_bare_http_exceptions() -> None:
    """Only problems.py may build an HTTPException; every other error goes through a problem."""
    offenders = [
        f"{path.relative_to(API)}:{use}"
        for path in API.rglob("*.py")
        if path.name != "problems.py"
        for use in _http_exception_uses(path)
    ]
    assert offenders == []


def test_the_guard_sees_an_aliased_import_and_a_module_attribute(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text(
        "import fastapi\n"
        "from starlette.exceptions import HTTPException as Refusal\n"
        "raise fastapi.HTTPException(404)\n"
    )
    assert _http_exception_uses(sample) == ["import:2", "attribute:3"]


# The argument that holds the code, for each helper that sends an error body.
_CODE_ARGUMENT = {"problem": 1, "ApiProblem": 1, "available": 1, "_problem": 2}


def _literal_codes(path: Path) -> set[str]:
    codes = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        index = _CODE_ARGUMENT.get(str(name))
        if index is None or len(node.args) <= index:
            continue
        argument = node.args[index]
        if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
            codes.add(argument.value)
        elif isinstance(argument, ast.Name) and (constant := _constant(path, argument.id)):
            # A module constant, such as accounts.PROVIDER_NOT_CONFIGURED; any other name is a
            # parameter the helper passes on, such as available()'s `code`.
            codes.add(constant)
    return codes


def _constant(path: Path, name: str) -> str | None:
    for node in ast.parse(path.read_text()).body:
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)
            and isinstance(node.value, ast.Constant)
        ):
            return str(node.value.value)
    return None


def _sent_codes() -> set[str]:
    return (
        set(problems._CODES.values())
        | set(problems._STATUS_CODES.values())
        | {problems._UNLISTED_STATUS}
        | {code for path in INTERFACES.rglob("*.py") for code in _literal_codes(path)}
    )


def _english_error_messages() -> set[str]:
    return set(json.loads(ENGLISH_COMMON.read_text(encoding="utf-8"))["apiError"])


# Messages the Web UI shows when no error body arrives: a failed request, an unreadable response,
# or an unexpected error.
_CLIENT_MESSAGES = {"generic", "network", "unreadableResponse"}


def test_every_code_the_server_sends_has_an_english_message() -> None:
    """The Web UI translates `common.apiError.<code>`; a code without one shows only English."""
    sent = _sent_codes()

    assert {"rule_execution_unavailable", "integration_token_not_found"} <= sent
    assert sorted(sent - _english_error_messages()) == []


def test_every_english_error_message_names_a_code_the_server_sends() -> None:
    """The Web UI's catalog test counts every `common.apiError` message as used; this checks it.

    A message is a code, or `<code>_<reason>` for a code its `reason` param refines.
    """
    sent = _sent_codes()
    unsent = {
        message
        for message in _english_error_messages() - _CLIENT_MESSAGES
        if message not in sent and not any(message.startswith(f"{code}_") for code in sent)
    }

    assert sorted(unsent) == []
