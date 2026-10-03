from __future__ import annotations

import asyncio
import mimetypes
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Protocol

import uvicorn
from fastapi import FastAPI, HTTPException, status
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import URL
from starlette.routing import Match, Route
from starlette.types import Receive, Scope, Send

from calendar_sync import __version__
from calendar_sync.bootstrap.container import Container, service_container
from calendar_sync.interfaces.api.routes import (
    accounts,
    activity,
    health,
    incidents,
    integrations,
    rules,
    session,
    setup,
    storage,
)
from calendar_sync.interfaces.mcp.server import McpNotFound, McpServices, build_mcp

# python:3.12-slim has no /etc/mime.types entry for woff2, so StaticFiles would otherwise serve
# the bundled fonts as text/plain there; register it explicitly so the type is correct everywhere.
mimetypes.add_type("font/woff2", ".woff2")


class ApiServices(
    session.SessionServices,
    accounts.AccountServices,
    activity.ActivityServices,
    incidents.IncidentServices,
    integrations.IntegrationServices,
    rules.RuleServices,
    storage.StorageServices,
    McpServices,
    Protocol,
):
    """Everything the routers read from the composed container."""


def create_app(container: Container | None = None) -> FastAPI:
    resolved = container or service_container()
    # Typed so mypy proves the container provides what every router reads from it.
    services: ApiServices = resolved
    mcp = build_mcp(services)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        scheduler_task: asyncio.Task[None] | None = None
        if resolved.scheduler is not None:
            scheduler_task = asyncio.create_task(resolved.scheduler.run_forever())
        try:
            async with mcp.running():
                yield
        finally:
            if scheduler_task is not None:
                scheduler_task.cancel()
                with suppress(asyncio.CancelledError):
                    await scheduler_task

    app = FastAPI(
        title="Calendar Ghost",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.state.container = services
    # Added flat rather than through include_router, which newer FastAPI versions nest, so
    # app.routes lists every API route for UnknownApiPath and the authorization test.
    for module in (
        health,
        setup,
        session,
        activity,
        accounts,
        rules,
        incidents,
        storage,
        integrations,
    ):
        app.router.routes.extend(module.router.routes)

    # One exact route, ahead of the API fallback and the Web UI catch-all (ADR 0023).
    app.router.routes.append(Route("/mcp", mcp.app, include_in_schema=False))
    app.router.routes.append(Route("/mcp/{path:path}", McpNotFound(), include_in_schema=False))

    # Registered after every API route so an unknown API path is a JSON error for any method
    # instead of falling through to the web page.
    app.router.routes.append(Route("/api", UnknownApiPath(), include_in_schema=False))
    app.router.routes.append(Route("/api/{path:path}", UnknownApiPath(), include_in_schema=False))
    _serve_web_ui(app)
    return app


def _serve_web_ui(app: FastAPI) -> None:
    static_directory = Path(__file__).with_name("static")
    if not static_directory.exists():
        return
    static_root = static_directory.resolve()
    assets = static_directory / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def frontend(full_path: str) -> FileResponse:
        index = static_root / "index.html"
        requested = (static_root / full_path).resolve()
        if (
            full_path
            and requested.is_file()
            and requested.is_relative_to(static_root)
            and not requested.samefile(index)
        ):
            return FileResponse(requested)
        # Revalidate the page on every load so an upgrade replaces it and its asset hashes.
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


class UnknownApiPath:
    """ASGI endpoint, rather than a function, so its route accepts every HTTP method.

    Its full match outranks what Starlette's router would otherwise do for a known route: the
    trailing-slash redirect and the 405 for a wrong method. Both are restored here.
    """

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        router = scope["app"].router
        api_routes = [
            route
            for route in router.routes
            if isinstance(route, Route)
            and route.path.startswith("/api/")
            and not isinstance(route.endpoint, UnknownApiPath)
        ]
        path = scope["path"]
        if router.redirect_slashes:
            redirect_scope = {
                **scope,
                "path": path.rstrip("/") if path.endswith("/") else path + "/",
            }
            if any(route.matches(redirect_scope)[0] is not Match.NONE for route in api_routes):
                await RedirectResponse(str(URL(scope=redirect_scope)))(scope, receive, send)
                return
        allowed = {
            method
            for route in api_routes
            if route.matches(scope)[0] is Match.PARTIAL
            for method in route.methods or ()
        }
        if allowed:
            raise HTTPException(
                status.HTTP_405_METHOD_NOT_ALLOWED,
                "Method Not Allowed",
                headers={"Allow": ", ".join(sorted(allowed))},
            )
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")


def run() -> None:
    uvicorn.run(
        "calendar_sync.interfaces.api.app:create_app",
        factory=True,
        # The container publishes this port; Compose decides which host interface exposes it.
        host="0.0.0.0",  # noqa: S104
        port=8000,
    )
