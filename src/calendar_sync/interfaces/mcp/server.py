from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Protocol

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from calendar_sync import __version__
from calendar_sync.application.errors import RuleNotFound
from calendar_sync.application.installation_health import GetInstallationHealth
from calendar_sync.application.ports import (
    IntegrationTokenAuthentication,
    IntegrationTokenScope,
    RuleRunOutcome,
    Sessions,
    UserDirectory,
)
from calendar_sync.application.rules import GetSyncRuleDetails
from calendar_sync.application.status import GetInstallationStatus
from calendar_sync.domain.access import UserId
from calendar_sync.domain.model import SyncRuleId
from calendar_sync.interfaces.access import StatusAccess, status_access
from calendar_sync.interfaces.api.status_payload import (
    installation_health_response,
    status_response,
)

INSTRUCTIONS = """\
Calendar Ghost synchronizes calendars one way, from a source calendar to a destination calendar,
following Directional Sync Rules. This server is read-only: it reports health and never changes
rules or calendars.

Call get_status first. Its `status` is one of:
- stalled: scheduled synchronization stopped running. The administrator restarts the service.
- stopped: a rule writes nothing until the administrator acts, usually by reauthorizing a
  calendar account in Settings.
- review: something needs a look: an incident, blocked events in Activity, or a rule not synced
  in over a day.
- waiting: the calendar provider is limiting or failing requests; rules retry by themselves.
- paused, setup, healthy: nothing needs attention.
`needs_attention` is true only for stalled, stopped, and review. `problems` lists each problem,
most urgent first. Call get_rule with a rule id or its "Source → Destination" name for its last
run. Events already synced stay where they are while a rule is stopped.

get_status and get_rule answer for the User the token belongs to. An Installation
Administrator's token with the installation:read scope may also call get_installation_health:
incidents about the installation itself, and how many Users are in each status. It names no rule,
calendar, or person.
"""
READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True)


_READER = "calendar_ghost_reader"
"""Where the gate leaves the token's owner in the request scope for the tools to read."""
_SCOPES = "calendar_ghost_scopes"
"""Where the gate leaves what the token may read."""
_ANY_SCOPE = frozenset(IntegrationTokenScope)


class McpUserServices(Protocol):
    @property
    def get_installation_status(self) -> GetInstallationStatus: ...
    @property
    def get_sync_rule_details(self) -> GetSyncRuleDetails: ...


class McpIdentity(Protocol):
    @property
    def sessions(self) -> Sessions: ...
    @property
    def users(self) -> UserDirectory: ...


class McpServices(Protocol):
    @property
    def identity(self) -> McpIdentity: ...
    @property
    def installation_health(self) -> GetInstallationHealth: ...
    @property
    def token_authentication(self) -> IntegrationTokenAuthentication: ...
    def for_user(self, user_id: UserId) -> McpUserServices: ...


class McpEndpoint:
    """The `/mcp` route. Each application lifespan runs a fresh SDK server, because a session
    manager runs only once and tests start the same app more than once."""

    def __init__(self, services: McpServices) -> None:
        self.app = McpGate(self, services)
        self._services = services
        self.inner: ASGIApp | None = None

    @asynccontextmanager
    async def running(self) -> AsyncIterator[None]:
        inner, session_manager = _sdk_app(self._services)
        async with session_manager.run():
            self.inner = inner
            try:
                yield
            finally:
                self.inner = None


def build_mcp(services: McpServices) -> McpEndpoint:
    return McpEndpoint(services)


def _sdk_app(services: McpServices) -> tuple[ASGIApp, StreamableHTTPSessionManager]:
    server = MCPServer(name="calendar-ghost", instructions=INSTRUCTIONS, version=__version__)

    @server.tool(annotations=READ_ONLY)
    def get_status(ctx: Context) -> dict[str, Any]:
        """Installation Status: the verdict, each problem, and every rule's state."""
        reader = services.for_user(_reader(ctx, IntegrationTokenScope.STATUS_READ))
        return status_response(reader.get_installation_status.execute()).model_dump(mode="json")

    @server.tool(annotations=READ_ONLY)
    def get_rule(rule: str, ctx: Context) -> dict[str, Any]:
        """One rule by id or "Source → Destination" name, with its last runs and problem."""
        reader = services.for_user(_reader(ctx, IntegrationTokenScope.STATUS_READ))
        status = status_response(reader.get_installation_status.execute())
        matches = [item for item in status.rules if rule in {item.id, item.name}]
        if len(matches) != 1:
            reason = "matches more than one rule" if matches else "matches no rule"
            raise ToolError(f"'{rule}' {reason}. Call get_status to see each rule's id.")
        found = matches[0]
        try:
            details = reader.get_sync_rule_details.execute(SyncRuleId(found.id))
        except RuleNotFound as error:
            raise ToolError("That rule was removed. Call get_status again.") from error
        return {
            "rule": found.model_dump(mode="json"),
            "last_sync": _outcome(details.last_sync),
            "last_reconciliation": _outcome(details.last_reconciliation),
        }

    @server.tool(annotations=READ_ONLY)
    def get_installation_health(ctx: Context) -> dict[str, Any]:
        """Installation Health: incidents about the installation itself, and how many Users are
        in each status. For an Installation Administrator's token with installation:read."""
        reader = services.identity.users.get(_reader(ctx, IntegrationTokenScope.INSTALLATION_READ))
        if reader is None or not reader.administers:
            raise ToolError("Only an Installation Administrator's token reads Installation Health.")
        health = services.installation_health.execute()
        return installation_health_response(health).model_dump(mode="json")

    # Stateless JSON: no per-client session to keep in the single process. The Host allowlist is
    # off because every request carries a bearer token a rebinding page cannot supply (ADR 0024).
    sdk = server.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    endpoint: ASGIApp = sdk.routes[0].endpoint  # type: ignore[attr-defined]
    return endpoint, server.session_manager


def _reader(ctx: Context, scope: IntegrationTokenScope) -> UserId:
    """The User whose token the gate accepted for this request, if it carries `scope`."""
    state = getattr(ctx.request_context.request, "state", None)
    reader = getattr(state, _READER, None)
    if not isinstance(reader, UserId):
        raise ToolError("This request carries no accepted token.")
    if scope not in getattr(state, _SCOPES, frozenset()):
        raise ToolError(f"This tool needs a token with the {scope.value} scope.")
    return reader


def _outcome(outcome: RuleRunOutcome | None) -> dict[str, Any] | None:
    if outcome is None:
        return None
    return {
        "completed_at": outcome.completed_at.isoformat(),
        "succeeded": outcome.succeeded,
        "full_run": outcome.full_run,
        "created": outcome.created,
        "updated": outcome.updated,
        "deleted": outcome.deleted,
        "conflicts": outcome.conflicts,
        "drift": outcome.drift,
        "failure_kind": outcome.failure_kind,
    }


class McpGate:
    """Refuses before the SDK sees a request: bearer tokens only, and POST only."""

    def __init__(self, endpoint: McpEndpoint, services: McpServices) -> None:
        self._endpoint = endpoint
        self._services = services

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Starlette's Headers keeps the first of repeated headers, as /api/v1/status does.
        access = await run_in_threadpool(
            status_access,
            self._services.token_authentication,
            self._services.identity.sessions,
            Headers(scope=scope).get("authorization"),
            None,
            _ANY_SCOPE,
        )
        if access.result is StatusAccess.UNAUTHENTICATED:
            await _problem(
                send,
                401,
                "credentials_required",
                "valid credentials required",
                [(b"www-authenticate", b"Bearer")],
            )
            return
        if access.result is StatusAccess.FORBIDDEN:
            await _problem(send, 403, "insufficient_scope", "token lacks the required scope")
            return
        # Stateless mode has no stream to resume, and a GET would hold one open.
        if scope["method"] != "POST":
            await _problem(
                send, 405, "method_not_allowed", "method not allowed", [(b"allow", b"POST")]
            )
            return
        inner = self._endpoint.inner
        if inner is None:
            await _problem(send, 503, "mcp_not_running", "the MCP server is starting or stopping")
            return
        # The SDK hands its tools a Request over this scope, so they read whose status to answer.
        state = scope.setdefault("state", {})
        state[_READER], state[_SCOPES] = access.user, access.scopes
        await inner(scope, receive, send)


class McpNotFound:
    async def __call__(self, _scope: Scope, _receive: Receive, send: Send) -> None:
        await _problem(send, 404, "not_found", "not found")


async def _problem(
    send: Send,
    status: int,
    code: str,
    detail: str,
    headers: list[tuple[bytes, bytes]] | None = None,
) -> None:
    """An HTTP error body shaped like every Web API error (ADR 0026), before MCP is involved."""
    body = {"detail": detail, "code": code, "params": {}}
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json"), *(headers or [])],
        }
    )
    await send({"type": "http.response.body", "body": json.dumps(body).encode()})
