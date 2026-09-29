"""Every API route requires an administrator session except the documented public ones."""

from pathlib import Path

from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import build_container
from calendar_sync.interfaces.api.app import create_app
from calendar_sync.interfaces.api.dependencies import require_admin

# AGENTS.md: only setup, login, and the state-protected OAuth callback are public under /api/,
# beside the session status and logout, which reveal or revoke nothing without a session.
PUBLIC_API_ROUTES = {
    ("GET", "/api/v1/setup"),
    ("POST", "/api/v1/setup/admin"),
    ("GET", "/api/v1/session"),
    ("POST", "/api/v1/session"),
    ("DELETE", "/api/v1/session"),
    ("GET", "/api/v1/oauth/google/callback"),
}


def _requires_admin(dependant: Dependant) -> bool:
    return any(sub.call is require_admin or _requires_admin(sub) for sub in dependant.dependencies)


def test_every_non_public_api_route_requires_an_administrator(tmp_path: Path) -> None:
    app = create_app(build_container(Settings(tmp_path / "test.db")))
    api_routes = [
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/api/")
    ]
    unguarded = {
        (method, route.path)
        for route in api_routes
        if not _requires_admin(route.dependant)
        for method in route.methods or ()
    }

    assert len(api_routes) > len(PUBLIC_API_ROUTES)
    assert unguarded == PUBLIC_API_ROUTES
