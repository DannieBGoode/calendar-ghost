"""Every API route requires a signed-in User except the documented public ones."""

import re
from pathlib import Path

from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import build_container
from calendar_sync.interfaces.api.app import create_app
from calendar_sync.interfaces.api.dependencies import current_user, status_reader
from tests.users import sign_in

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
# Readable with an administrator session or an Integration Token (ADR 0024).
STATUS_READER_ROUTES = {("GET", "/api/v1/status")}


def _requires(dependant: Dependant, guard: object) -> bool:
    return any(sub.call is guard or _requires(sub, guard) for sub in dependant.dependencies)


def test_every_non_public_api_route_requires_a_signed_in_user(tmp_path: Path) -> None:
    app = create_app(build_container(Settings(tmp_path / "test.db")))
    api_routes = [
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/api/")
    ]
    unguarded = {
        (method, route.path)
        for route in api_routes
        if not _requires(route.dependant, current_user)
        for method in route.methods or ()
    }
    readers = {
        (method, route.path)
        for route in api_routes
        if _requires(route.dependant, status_reader)
        for method in route.methods or ()
    }
    assert len(api_routes) > len(PUBLIC_API_ROUTES)
    assert unguarded == PUBLIC_API_ROUTES | STATUS_READER_ROUTES
    assert readers == STATUS_READER_ROUTES


def test_an_integration_token_is_refused_by_every_other_api_route(tmp_path: Path) -> None:
    app = create_app(build_container(Settings(tmp_path / "test.db")))
    with TestClient(app) as client:
        sign_in(client)
        token = client.post("/api/v1/integration-tokens", json={"name": "Probe"}).json()["token"]
        client.cookies.clear()
        refused = []
        for route in app.routes:
            if not isinstance(route, APIRoute) or not route.path.startswith("/api/"):
                continue
            for method in route.methods or ():
                if (method, route.path) in PUBLIC_API_ROUTES | STATUS_READER_ROUTES:
                    continue
                path = re.sub(r"\{[^}]+\}", "x", route.path)
                response = client.request(
                    method, path, headers={"Authorization": f"Bearer {token}"}, json={}
                )
                refused.append((method, route.path, response.status_code))
    assert refused
    assert {status for _, _, status in refused} == {401}, refused
