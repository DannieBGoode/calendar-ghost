"""Every API route requires a signed-in User except the documented public ones."""

import re
import secrets
from dataclasses import replace
from pathlib import Path
from typing import Any

from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from calendar_sync.application.ports import AuditAction, AuditEntry, AuditOutcome
from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import build_adapters, build_container, compose
from calendar_sync.domain.access import UserId
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.security import CredentialCipher, token_hash
from calendar_sync.interfaces.api.app import create_app
from calendar_sync.interfaces.api.dependencies import SESSION_COOKIE, signed_in_user, status_reader
from tests.helpers import NOW, rule
from tests.users import OTHER_USER, add_user, administrator, sign_in, sqlite_units

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
        if not _requires(route.dependant, signed_in_user)
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


def _session_for(database: Path, user: UserId) -> str:
    """A live session of `user`, as signing in would give them."""
    token = secrets.token_urlsafe(32)
    with transaction(database) as connection:
        connection.execute(
            """
            INSERT INTO user_sessions (token_hash, user_id, created_at, expires_at)
            VALUES (?, ?, '2026-01-01T00:00:00+00:00', '9999-01-01T00:00:00+00:00')
            """,
            (token_hash(token), user.value),
        )
    return token


RULE_POLICY = {
    "privacy_policy": "busy_only",
    "sync_all_day_events": True,
    "tentative_events": "mark",
    "unanswered_invitations": "as_tentative",
}
ENDPOINTS = {
    "source": {"connected_account_id": "personal-account", "calendar_id": "personal-calendar"},
    "destination": {"connected_account_id": "work-account", "calendar_id": "work-calendar"},
}
# A valid request for every route that names one of a User's records, so only the record's owner
# can decide the answer.
REQUESTS: dict[tuple[str, str], dict[str, Any]] = {
    ("PATCH", "/api/v1/rules/{rule_id}"): {"json": RULE_POLICY},
    ("DELETE", "/api/v1/rules/{rule_id}"): {"params": {"projections": "detach"}},
    ("POST", "/api/v1/rules/{rule_id}/replace"): {"json": {**ENDPOINTS, "projections": "detach"}},
}


def test_every_route_answers_another_users_record_as_not_found(tmp_path: Path) -> None:
    """ADR 0029: 404, never 403, so a record's existence is not revealed to another User."""
    database = tmp_path / "test.db"
    settings = Settings(database, master_key=CredentialCipher.generate_key())
    adapters = build_adapters(settings)
    owner = administrator(adapters)
    with sqlite_units(database, user=owner)() as uow:
        uow.rules.add(rule())
        uow.audit.append(
            AuditEntry(NOW, rule().id, AuditAction.CREATE, AuditOutcome.COMPLETED, "event-1")
        )
        uow.commit()
    token = adapters.integration_tokens(owner).issue("Monitor").summary.id
    with transaction(database) as connection:
        entry = str(connection.execute("SELECT MAX(id) FROM audit_entries").fetchone()[0])
    records = {
        "rule_id": rule().id.value,
        "account_id": "personal-account",
        "entry_id": entry,
        "token_id": token,
    }
    add_user(database, OTHER_USER, role="user")
    # No scheduler, so nothing but the requests below touches the first User's rule.
    app = create_app(replace(compose(settings, adapters), scheduler=None))

    answers = {}
    with TestClient(app) as client:
        client.cookies.set(SESSION_COOKIE, _session_for(database, OTHER_USER))
        for route in app.routes:
            if (
                not isinstance(route, APIRoute)
                or not route.path.startswith("/api/")
                or "{" not in route.path
            ):
                continue
            for method in route.methods or ():
                path = route.path.format(**records)
                response = client.request(method, path, **REQUESTS.get((method, route.path), {}))
                answers[method, route.path] = response.status_code
        created = client.post("/api/v1/rules", json=ENDPOINTS).json()["code"]
        missing = client.post(
            "/api/v1/rules",
            json={
                "source": {"connected_account_id": "missing", "calendar_id": "c"},
                "destination": {"connected_account_id": "missing-too", "calendar_id": "c"},
            },
        ).json()["code"]

    assert len(answers) >= 15
    assert {status for status in answers.values()} == {404}, answers
    # A rule naming another User's accounts is refused as if they did not exist.
    assert created == missing
    with sqlite_units(database, user=owner)() as uow:
        assert uow.rules.list() == (rule(),)
