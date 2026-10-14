"""Watch Notices: where calendar providers say a watched calendar may have changed (ADR 0036).

The route is public, as providers cannot sign in. The inbox authenticates each notice by its
registration's secret token, and the answer is the same 202 for known, unknown, and refused
notices, so it shows no registration. Nothing here logs a token, handle, registration id, or body.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import PlainTextResponse
from starlette.concurrency import run_in_threadpool

from calendar_sync.application.operations.ports import InboxBusy, WatchNoticeInbox
from calendar_sync.application.sync.watch_ports import (
    NOTICE_PATH,
    MalformedNotice,
    NoticeReader,
    NoticeRequest,
)
from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.errors import DomainValidationError
from calendar_sync.domain.watches import WatchRegistrationId
from calendar_sync.interfaces.api.dependencies import app_services
from calendar_sync.interfaces.api.problems import ApiProblem, problem

NOTICE_BODY_LIMIT = 65_536
"""The largest notice body read; a provider's batch of notices is far smaller."""
VALIDATION_TOKEN_LIMIT = 1_024
"""The longest validation token echoed back."""


class Waking(Protocol):
    def wake(self) -> None: ...


class NoticeServices(Protocol):
    @property
    def watch_inbox(self) -> WatchNoticeInbox | None: ...
    @property
    def notice_readers(self) -> Mapping[str, tuple[ProviderKind, NoticeReader]]: ...
    @property
    def instant_dispatcher(self) -> Waking | None: ...
    @property
    def instant_sync_address(self) -> str | None: ...


Services = Annotated[NoticeServices, Depends(app_services)]
router = APIRouter()


@router.post(
    NOTICE_PATH + "/{provider_slug}/{registration_id}",
    status_code=status.HTTP_202_ACCEPTED,
    response_class=Response,
    # Providers call it, not the Web UI, whose API types come from the schema.
    include_in_schema=False,
)
async def watch_notice(
    provider_slug: str, registration_id: str, request: Request, services: Services
) -> Response:
    """Record a provider's Watch Notices, so the rules they concern run soon."""
    inbox, address = services.watch_inbox, services.instant_sync_address
    found = services.notice_readers.get(provider_slug)
    if inbox is None or address is None or found is None:
        # As for any unknown API path: an installation that cannot hear notices has no route.
        raise problem(status.HTTP_404_NOT_FOUND, "not_found", "Not Found")
    provider, reader = found
    headers, query = dict(request.headers), dict(request.query_params)
    # A provider validating the address waits only seconds, and its body is never a notice.
    token = reader.validation_token(NoticeRequest(headers, query, b""))
    if token is not None:
        # Text the caller chose, so a browser must not read it as anything else.
        return PlainTextResponse(
            token[:VALIDATION_TOKEN_LIMIT], headers={"X-Content-Type-Options": "nosniff"}
        )
    body = await _body(request)
    try:
        registration = WatchRegistrationId(registration_id)
    except DomainValidationError:
        # A blank identifier names no registration, so it is answered as an unknown one.
        return _accepted()
    try:
        notices = reader.read(registration, NoticeRequest(headers, query, body))
    except MalformedNotice:
        raise problem(
            status.HTTP_400_BAD_REQUEST, "malformed_notice", "not a notice this provider sends"
        ) from None
    try:
        # On AnyIO's worker threads, apart from the event loop's default ones, which long requests
        # such as Sync now or a preview can fill while a provider waits only seconds for the answer.
        requested = await run_in_threadpool(
            inbox.record, notices, provider, address, datetime.now(UTC)
        )
    except InboxBusy:
        # Providers retry a 5xx answer, so the notice is not lost.
        raise problem(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "inbox_busy",
            "notices cannot be recorded right now; try again",
        ) from None
    if requested and services.instant_dispatcher is not None:
        services.instant_dispatcher.wake()
    return _accepted()


async def _body(request: Request) -> bytes:
    """The body, read only up to NOTICE_BODY_LIMIT, so a larger one is never held whole."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > NOTICE_BODY_LIMIT:
        raise _too_large()
    body = bytearray()
    async for chunk in request.stream():
        # Checked before keeping the chunk, so one large chunk is never held.
        if len(body) + len(chunk) > NOTICE_BODY_LIMIT:
            raise _too_large()
        body.extend(chunk)
    return bytes(body)


def _too_large() -> ApiProblem:
    return problem(
        status.HTTP_413_CONTENT_TOO_LARGE, "notice_too_large", "a notice body is at most 64 KB"
    )


def _accepted() -> Response:
    return Response(status_code=status.HTTP_202_ACCEPTED)
