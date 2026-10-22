"""Bound identity proof bodies and protect responses before routing or validation."""

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from calendar_sync.interfaces.api.problems import problem

BODY_LIMIT = 8192
PRIVATE_HEADERS = [(b"cache-control", b"no-store"), (b"referrer-policy", b"no-referrer")]


def reset_api(path: str) -> bool:
    return path == "/api/v1/password-resets" or path.startswith("/api/v1/password-resets/")


def email_change_api(path: str) -> bool:
    return path in {"/api/v1/account/email", "/api/v1/account/email-change"} or path.startswith(
        "/api/v1/account/email-change/"
    )


def joining_api(path: str) -> bool:
    return path == "/api/v1/registrations" or path.startswith(
        ("/api/v1/registrations/", "/api/v1/invitations/")
    )


def provider_api(path: str) -> bool:
    return (
        path.startswith(
            (
                "/api/v1/sign-in/",
                "/api/v1/account/sign-in-methods",
                "/api/v1/settings/sign-in-providers",
            )
        )
        or path == "/api/v1/account/password"
    )


def _private(path: str) -> bool:
    return (
        provider_api(path)
        or path in {"/api/v1/session", "/api/v1/setup/admin", "/sign-in", "/provider-link"}
        or reset_api(path)
        or email_change_api(path)
        or joining_api(path)
        or path
        in {
            "/password-reset",
            "/forgot-password",
            "/email-change",
            "/sign-up",
            "/verify-email",
            "/invitation",
        }
        or (path.startswith("/api/v1/users/") and path.endswith("/password-reset-links"))
    )


class IdentityBoundary:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not _private(scope["path"].rstrip("/")):
            await self.app(scope, receive, send)
            return

        async def private_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                message = dict(message)
                message["headers"] = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower() not in {b"cache-control", b"referrer-policy"}
                ] + PRIVATE_HEADERS
            await send(message)

        path = scope["path"].rstrip("/")
        if provider_api(path) and len(scope.get("query_string", b"")) > BODY_LIMIT:
            await JSONResponse(
                {"code": "request_too_large", "detail": "Query is too large", "params": {}},
                status_code=413,
            )(scope, receive, private_send)
            return
        bounded = (
            (provider_api(path) and scope["method"] in {"POST", "PUT", "DELETE"})
            or (scope["method"] == "POST" and (reset_api(path) or joining_api(path)))
            or (scope["method"] in {"POST", "PUT"} and email_change_api(path))
        )
        if bounded:
            body = await _bounded_body(receive)
            if body is None:
                failure = problem(413, "request_too_large", "Request body is too large")
                await JSONResponse(
                    {
                        "detail": failure.detail,
                        "code": failure.code,
                        "params": failure.params,
                    },
                    status_code=failure.status_code,
                    headers=failure.headers,
                )(scope, receive, private_send)
                return
            if body["type"] == "http.disconnect":
                return

            async def replay() -> Message:
                return body

            await self.app(scope, replay, private_send)
        else:
            await self.app(scope, receive, private_send)


async def _bounded_body(receive: Receive) -> Message | None:
    chunks: list[bytes] = []
    size = 0
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            return message
        chunk = message.get("body", b"")
        size += len(chunk)
        if size > BODY_LIMIT:
            return None
        if chunk:
            chunks.append(chunk)
        if not message.get("more_body", False):
            return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
