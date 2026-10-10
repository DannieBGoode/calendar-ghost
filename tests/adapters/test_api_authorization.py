"""Every API route requires a signed-in User except the documented public ones."""

import re
from dataclasses import replace
from pathlib import Path
from typing import Any

from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from calendar_sync.application.ports import AuditAction, AuditEntry, AuditOutcome
from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import build_adapters, build_container, compose
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.security import CredentialCipher
from calendar_sync.interfaces.api.app import create_app
from calendar_sync.interfaces.api.dependencies import (
    SESSION_COOKIE,
    session_user,
    signed_in_user,
    status_reader,
)
from calendar_sync.interfaces.api.dependencies import administrator as administrator_session
from tests.helpers import NOW, rule
from tests.users import (
    OTHER_USER,
    add_user,
    administrator,
    session_for,
    sign_in,
    sqlite_units,
)

# AGENTS.md: only setup, sign-in, and the token-protected Invitation and Password Reset Links are
# public under /api/, beside the session status and sign-out, which reveal or revoke nothing
# without a session.
PUBLIC_API_ROUTES = {
    ("GET", "/api/v1/setup"),
    ("POST", "/api/v1/setup/admin"),
    ("GET", "/api/v1/session"),
    ("POST", "/api/v1/session"),
    ("DELETE", "/api/v1/session"),
    ("POST", "/api/v1/invitations/check"),
    ("POST", "/api/v1/invitations/accept"),
    ("POST", "/api/v1/password-resets/check"),
    ("POST", "/api/v1/password-resets"),
}
# Only an Installation Administrator may use these (ADR 0030).
ADMINISTRATOR_ROUTES = {
    ("GET", "/api/v1/registration"),
    ("PUT", "/api/v1/registration"),
    ("GET", "/api/v1/invitations"),
    ("POST", "/api/v1/invitations"),
    ("DELETE", "/api/v1/invitations/{invitation_id}"),
    ("GET", "/api/v1/users"),
    ("PUT", "/api/v1/users/{user_id}/role"),
    ("PUT", "/api/v1/users/{user_id}/state"),
    ("POST", "/api/v1/users/{user_id}/password-reset-links"),
    ("DELETE", "/api/v1/users/{user_id}"),
    ("GET", "/api/v1/storage"),
    ("GET", "/api/v1/storage/activity"),
    ("POST", "/api/v1/storage/activity/clear"),
    ("GET", "/api/v1/storage/logs"),
    ("DELETE", "/api/v1/storage/logs"),
}
# An Installation Administrator's routes that name a User. Anyone else is answered 404, as for a
# User who does not exist, so neither the route nor the User is revealed (ADR 0029).
USER_NAMING_ADMINISTRATOR_ROUTES = {("GET", "/api/v1/users/{user_id}/overview")}
# Readable with a session or an Integration Token (ADR 0024); Installation Health only by an
# Installation Administrator's session or installation:read token (ADR 0030).
STATUS_READER_ROUTES = {("GET", "/api/v1/status")}
INSTALLATION_READER_ROUTES = {("GET", "/api/v1/installation/health")}
TOKEN_ROUTES = STATUS_READER_ROUTES | INSTALLATION_READER_ROUTES
# Google's redirect cannot be answered with a 401, so the OAuth callback reads the session itself
# and connects an account only for the User who began the flow in this browser.
SESSION_AND_STATE_ROUTES = {("GET", "/api/v1/oauth/google/callback")}


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
    administered = {
        (method, route.path)
        for route in api_routes
        if _requires(route.dependant, administrator_session)
        for method in route.methods or ()
    }
    session_and_state = {
        (method, route.path)
        for route in api_routes
        if _requires(route.dependant, session_user)
        for method in route.methods or ()
    }
    assert len(api_routes) > len(PUBLIC_API_ROUTES)
    assert unguarded == PUBLIC_API_ROUTES | TOKEN_ROUTES | SESSION_AND_STATE_ROUTES
    assert session_and_state == SESSION_AND_STATE_ROUTES
    assert readers == STATUS_READER_ROUTES
    assert administered == ADMINISTRATOR_ROUTES


def test_an_administrator_naming_a_malformed_user_is_told_nobody_has_it(tmp_path: Path) -> None:
    """A blank identifier names nobody: 404, never a server error (review on PR 68)."""
    app = create_app(build_container(Settings(tmp_path / "test.db")))
    with TestClient(app) as client:
        sign_in(client)
        answers = {
            (method, path): client.request(
                method, path.replace("{user_id}", "%20"), json={"role": "user", "state": "active"}
            ).status_code
            for method, path in ADMINISTRATOR_ROUTES | USER_NAMING_ADMINISTRATOR_ROUTES
            if "{user_id}" in path
        }

    assert len(answers) == 5
    assert set(answers.values()) == {404}, answers


def test_a_user_who_does_not_administer_is_refused_every_administrator_route(
    tmp_path: Path,
) -> None:
    database = tmp_path / "test.db"
    app = create_app(build_container(Settings(database)))
    with TestClient(app) as client:
        sign_in(client)
        add_user(database, OTHER_USER, role="user")
        client.cookies.set(SESSION_COOKIE, session_for(database, OTHER_USER))
        answers = {
            (method, path): client.request(
                method, re.sub(r"\{[^}]+\}", "x", path), json={"policy": "only_me"}
            ).status_code
            for method, path in ADMINISTRATOR_ROUTES
        }

    assert {status for status in answers.values()} == {403}, answers


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
                if (
                    method,
                    route.path,
                ) in PUBLIC_API_ROUTES | TOKEN_ROUTES | SESSION_AND_STATE_ROUTES:
                    continue
                path = re.sub(r"\{[^}]+\}", "x", route.path)
                response = client.request(
                    method, path, headers={"Authorization": f"Bearer {token}"}, json={}
                )
                refused.append((method, route.path, response.status_code))
    assert refused
    assert {status for _, _, status in refused} == {401}, refused


def test_a_user_who_does_not_administer_finds_no_user_through_an_administrator_route(
    tmp_path: Path,
) -> None:
    database = tmp_path / "test.db"
    app = create_app(build_container(Settings(database)))
    with TestClient(app) as client:
        sign_in(client)
        administrator_id = client.get("/api/v1/session").json()["user"]["id"]
        # A malformed identifier, such as a blank one, is as unknown as a missing User.
        unknown_to_administrator = {
            (path, user): client.get(path.format(user_id=user)).status_code
            for _, path in USER_NAMING_ADMINISTRATOR_ROUTES
            for user in ("nobody", "%20")
        }
        add_user(database, OTHER_USER, role="user")
        client.cookies.set(SESSION_COOKIE, session_for(database, OTHER_USER))
        answers = {
            (path, user): client.get(path.format(user_id=user)).status_code
            for _, path in USER_NAMING_ADMINISTRATOR_ROUTES
            for user in (administrator_id, OTHER_USER.value, "nobody", "%20")
        }

    assert set(unknown_to_administrator.values()) == {404}
    assert set(answers.values()) == {404}, answers


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
        "user_id": owner.value,
    }
    add_user(database, OTHER_USER, role="user")
    # No scheduler, so nothing but the requests below touches the first User's rule.
    app = create_app(replace(compose(settings, adapters), scheduler=None))

    answers = {}
    with TestClient(app) as client:
        client.cookies.set(SESSION_COOKIE, session_for(database, OTHER_USER))
        for route in app.routes:
            if (
                not isinstance(route, APIRoute)
                or not route.path.startswith("/api/")
                or "{" not in route.path
            ):
                continue
            for method in route.methods or ():
                if (method, route.path) in ADMINISTRATOR_ROUTES:
                    # Refused before any lookup, so no record's existence shows either.
                    continue
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
