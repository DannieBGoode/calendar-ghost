"""Real HTTP and SQLite boundaries with synthetic provider assertions."""

import threading
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response

from calendar_sync.application.identity.errors import SignInStorageUnavailable
from calendar_sync.bootstrap.container import Container, build_container
from calendar_sync.domain.provider_identity import ProviderClaims, ProviderIdentityKey
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.interfaces.api.app import create_app
from calendar_sync.interfaces.api.sign_in_cookies import BROWSER_COOKIE, PENDING_COOKIE
from tests.adapters.test_password_reset_api import configured, private
from tests.users import ADMIN_EMAIL, ADMIN_PASSWORD, sign_in

ORIGIN = "https://calendar.example.test"
START = "/api/v1/sign-in/google/start"
CALLBACK = "/api/v1/sign-in/google/callback"


@dataclass
class SyntheticAuthorization:
    claims: ProviderClaims
    fingerprint: str
    calls: int = 0

    def begin(self, state: str, nonce: str, verifier: str) -> str:
        assert nonce
        assert verifier
        return "https://identity.example.test/auth?" + urlencode({"state": state})

    def exchange(self, code: str, nonce: str, verifier: str) -> ProviderClaims:
        assert code
        assert nonce
        assert verifier
        self.calls += 1
        return self.claims


def ready(path: Path) -> tuple[TestClient, Container, SyntheticAuthorization]:
    container = build_container(
        configured(
            path, google_client_id="synthetic-client", google_client_secret="synthetic-secret"
        )
    )
    client = TestClient(create_app(container), base_url=ORIGIN, headers={"Origin": ORIGIN})
    sign_in(client)
    assert (
        client.put("/api/v1/settings/sign-in-providers/google", json={"enabled": True}).status_code
        == 204
    )
    runtime = container.provider_sign_in.runtime
    assert runtime
    provider = SyntheticAuthorization(
        ProviderClaims(
            ProviderIdentityKey("https://issuer.example.test", "subject"), ADMIN_EMAIL, True
        ),
        runtime.begin.providers["google"].fingerprint,
    )
    runtime.begin.providers = {"google": provider}
    runtime.complete.providers = {"google": provider}
    client.cookies.clear()
    return client, container, provider


def begin(client: TestClient, path: str = START) -> str:
    answer = client.post(path, json={})
    assert answer.status_code == 200, answer.text
    private(answer)
    return parse_qs(urlsplit(str(answer.json()["authorization_url"])).query)["state"][0]


def finish(client: TestClient, state: str, **params: str) -> Response:
    return client.get(
        CALLBACK,
        params={"state": state, "code": "synthetic-code", **params},
        follow_redirects=False,
    )


def test_callback_sets_secure_cookie_only_after_complete_response(tmp_path: Path) -> None:
    client, container, provider = ready(tmp_path / "test.db")
    state = begin(client)
    flow_cookie = client.cookies.get(BROWSER_COOKIE)
    assert flow_cookie
    answer = finish(client, state)
    assert answer.status_code == 303
    assert answer.headers["location"] == "/overview"
    private(answer)
    cookie = answer.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=lax" in cookie
    assert "Domain=" not in cookie
    assert client.get("/api/v1/session").json()["authenticated"]
    assert provider.calls == 1
    assert finish(client, state).headers["location"].endswith("unavailable")
    assert container.provider_sign_in.runtime


@pytest.mark.parametrize(
    "origin", ["", "https://evil.example.test", "https://calendar.example.test.evil.test"]
)
def test_forged_origin_refuses_before_flow_storage(tmp_path: Path, origin: str) -> None:
    path = tmp_path / "test.db"
    client, _, provider = ready(path)
    answer = client.post(START, json={}, headers={"Origin": origin})
    assert answer.status_code == 403
    assert "set-cookie" not in answer.headers
    assert provider.calls == 0
    with transaction(path) as connection:
        assert connection.execute("SELECT count(*) FROM provider_flows").fetchone()[0] == 0


@pytest.mark.parametrize(
    "query",
    [
        "state=one&state=two&code=secret",
        "state=one&code=one&code=two",
        "state=one&code=" + "x" * 4097,
        "state=" + "x" * 129 + "&code=x",
    ],
)
def test_invalid_callback_never_exchanges_or_reflects_inputs(tmp_path: Path, query: str) -> None:
    client, _, provider = ready(tmp_path / "test.db")
    begin(client)
    answer = client.get(CALLBACK + "?" + query, follow_redirects=False)
    assert answer.status_code == 303
    assert answer.headers["location"] == "/sign-in?provider_result=unavailable"
    assert "set-cookie" not in answer.headers
    assert provider.calls == 0
    private(answer)


def test_denial_consumes_state_and_ignores_return_address(tmp_path: Path) -> None:
    client, _, provider = ready(tmp_path / "test.db")
    state = begin(client)
    assert (
        finish(client, state, error="private-provider-error", return_url="https://evil.test")
        .headers["location"]
        .endswith("unavailable")
    )
    assert finish(client, state).headers["location"].endswith("unavailable")
    assert provider.calls == 0


def test_password_sign_in_cancels_in_flight_callback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "test.db"
    client, container, provider = ready(path)
    state = begin(client)
    entered, release = threading.Event(), threading.Event()

    def exchange(code: str, nonce: str, verifier: str) -> ProviderClaims:
        with transaction(path) as connection:
            connection.execute("BEGIN IMMEDIATE")
        entered.set()
        assert release.wait(5)
        return provider.claims

    monkeypatch.setattr(provider, "exchange", exchange)
    cookies = dict(client.cookies)
    from concurrent.futures import ThreadPoolExecutor

    with (
        ThreadPoolExecutor() as pool,
        TestClient(create_app(container), base_url=ORIGIN, cookies=cookies) as callback_client,
    ):
        result = pool.submit(finish, callback_client, state)
        assert entered.wait(5)
        signed = client.post(
            "/api/v1/session", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
        )
        release.set()
        assert signed.status_code == 200
        assert result.result().headers["location"].endswith("unavailable")
    assert client.get("/api/v1/session").json()["authenticated"]


def test_signed_in_browser_cannot_use_public_start_or_confirmation(tmp_path: Path) -> None:
    client, _, _ = ready(tmp_path / "test.db")
    sign_in(client)
    assert client.post(START, json={}).status_code == 401
    assert (
        client.post(
            "/api/v1/sign-in/confirm", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
        ).status_code
        == 401
    )


def test_pending_form_is_generic_and_password_proven(tmp_path: Path) -> None:
    client, _, provider = ready(tmp_path / "test.db")
    provider.claims = ProviderClaims(provider.claims.key, "untrusted@example.test", False)
    answer = finish(client, begin(client))
    assert answer.headers["location"] == "/provider-link"
    assert client.cookies.get(PENDING_COOKIE)
    assert client.get("/api/v1/sign-in/pending").json() == {"password_required": True}
    wrong = client.post(
        "/api/v1/sign-in/confirm", json={"email": "unknown@example.test", "password": "wrong"}
    )
    existing = client.post(
        "/api/v1/sign-in/confirm", json={"email": ADMIN_EMAIL, "password": "wrong"}
    )
    assert (wrong.status_code, wrong.json()) == (existing.status_code, existing.json())
    answer = client.post(
        "/api/v1/sign-in/confirm", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    assert answer.status_code == 200, answer.text
    assert answer.json()["authenticated"]
    private(answer)


def test_callback_read_failure_sets_no_cookie(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, container, _ = ready(tmp_path / "test.db")
    state = begin(client)
    monkeypatch.setattr(
        container.registrations.answers.users, "get", Mock(side_effect=SignInStorageUnavailable)
    )
    answer = finish(client, state)
    assert answer.headers["location"].endswith("unavailable")
    assert "set-cookie" not in answer.headers


@pytest.mark.parametrize(
    "body",
    [
        {"email": "private@example.test"},
        {"invitation_token": "ñ" * 50, "email": "private@example.test"},
        {"email": "x" * 255, "invitation_token": "secret"},
        {"private@example.test": "private-secret"},
    ],
)
def test_validation_redacts_inputs(tmp_path: Path, body: dict[str, str]) -> None:
    client, _, _ = ready(tmp_path / "test.db")
    answer = client.post(START, json=body)
    assert answer.status_code == 422
    assert "private@example.test" not in answer.text
    assert "private-secret" not in answer.text
    private(answer)


def test_body_and_query_are_bounded_before_work(tmp_path: Path) -> None:
    client, _, provider = ready(tmp_path / "test.db")
    assert client.post(START, content="x" * 8193).status_code == 413
    assert client.get(CALLBACK + "?state=" + "s" * 8193).status_code == 413
    assert provider.calls == 0


def test_public_availability_is_private_and_minimal(tmp_path: Path) -> None:
    client = TestClient(create_app(build_container(configured(tmp_path / "test.db"))))
    answer = client.get("/api/v1/sign-in/providers")
    assert answer.status_code == 200
    assert answer.json() == {"providers": []}
    private(answer)


@pytest.mark.parametrize(
    ("boundary", "path"), [("begin", START), ("confirmation", "/api/v1/sign-in/confirm")]
)
def test_durable_limits_run_before_session_lookup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str, path: str
) -> None:
    client, container, _ = ready(tmp_path / "test.db")
    use = container.provider_sign_in.runtime
    assert use
    from typing import Literal, cast

    for _ in range(20 if boundary == "begin" else 10):
        use.limits.admit("testclient", cast(Literal["begin", "confirmation"], boundary))
    lookup = Mock(side_effect=AssertionError("lookup before limit"))
    monkeypatch.setattr(type(container.provider_sign_in.methods.owner), "execute", lookup)
    answer = client.post(
        path, json={} if boundary == "begin" else {"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    assert answer.status_code == 429
    assert int(answer.headers["retry-after"]) > 0
    lookup.assert_not_called()


def test_callback_limit_precedes_exchange(tmp_path: Path) -> None:
    client, container, provider = ready(tmp_path / "test.db")
    state = begin(client)
    use = container.provider_sign_in.runtime
    assert use
    for _ in range(20):
        use.limits.admit("testclient", "callback")
    assert finish(client, state).headers["location"].endswith("unavailable")
    assert provider.calls == 0


def test_confirmation_needs_both_cookies_and_remains_retryable(tmp_path: Path) -> None:
    client, _, provider = ready(tmp_path / "test.db")
    provider.claims = ProviderClaims(provider.claims.key, None, False)
    finish(client, begin(client))
    token = client.cookies.get(PENDING_COOKIE)
    assert token
    client.cookies.delete(PENDING_COOKIE)
    assert client.get("/api/v1/sign-in/pending").json() == {"password_required": False}
    answer = client.post(
        "/api/v1/sign-in/confirm", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    assert answer.status_code == 401
    client.cookies.set(PENDING_COOKIE, token)
    client.cookies.delete(BROWSER_COOKIE)
    assert (
        client.post(
            "/api/v1/sign-in/confirm", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
        ).status_code
        == 401
    )


def test_flow_cookie_lifetime_and_auth_pages_are_private(tmp_path: Path) -> None:
    client, _, _ = ready(tmp_path / "test.db")
    answer = client.post(START, json={})
    cookie = answer.headers["set-cookie"]
    assert "Max-Age=600" in cookie
    for path in ("/sign-in", "/provider-link"):
        private(client.get(path))


def test_disabled_provider_cannot_start_or_exchange(tmp_path: Path) -> None:
    path = tmp_path / "test.db"
    client, _, provider = ready(path)
    state = begin(client)
    with transaction(path) as connection:
        connection.execute("UPDATE provider_sign_in_settings SET enabled=0")
    assert client.post(START, json={}).status_code == 401
    assert finish(client, state).headers["location"].endswith("unavailable")
    assert provider.calls == 0
    with transaction(path) as connection:
        connection.execute("UPDATE provider_sign_in_settings SET enabled=1")
    assert finish(client, state).headers["location"].endswith("unavailable")


def test_settings_read_failure_refuses_before_exchange(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, container, provider = ready(tmp_path / "test.db")
    state = begin(client)
    monkeypatch.setattr(
        container.provider_sign_in.settings,
        "list",
        Mock(side_effect=RuntimeError("private-storage-error")),
    )
    start = client.post(START, json={})
    assert start.status_code == 503
    assert "private-storage-error" not in start.text
    assert finish(client, state).headers["location"].endswith("unavailable")
    assert provider.calls == 0


@pytest.mark.parametrize("entry", ["setup", "invitation", "registration"])
def test_every_admission_session_cancels_browser_flow(tmp_path: Path, entry: str) -> None:
    path = tmp_path / "test.db"
    if entry == "setup":
        container = build_container(
            configured(
                path, google_client_id="synthetic-client", google_client_secret="synthetic-secret"
            )
        )
        client = TestClient(create_app(container), base_url=ORIGIN, headers={"Origin": ORIGIN})
        endpoint = "/api/v1/setup/admin"
        body = {"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    else:
        client, container, _ = ready(path)
        sign_in(client)
        if entry == "invitation":
            assert (
                client.put("/api/v1/registration", json={"policy": "invitation_only"}).status_code
                == 200
            )
            token = client.post("/api/v1/invitations").json()["token"]
            endpoint = "/api/v1/invitations/accept"
            body = {"token": token, "email": "new@example.test", "password": ADMIN_PASSWORD}
        else:
            with transaction(path) as connection:
                connection.execute(
                    "UPDATE identity_email_readiness SET fingerprint=?,tested_at=?",
                    (
                        container.registrations.check.fingerprint,
                        container.registrations.complete.clock.now().isoformat(),
                    ),
                )
            assert client.put("/api/v1/registration", json={"policy": "open"}).status_code == 200
            from tests.adapters.test_registration_api import proof

            token = proof(container)
            endpoint = "/api/v1/registrations"
            body = {"token": token, "password": ADMIN_PASSWORD}
        client.cookies.clear()
    from calendar_sync.application.identity.provider_sign_in_ports import (
        BeginIntent,
        BrowserProof,
        ProviderCallback,
    )

    use = container.provider_sign_in.runtime
    assert use
    browser = BrowserProof("b" * 43)
    use.flows.begin(BeginIntent("google", browser), "s" * 43)
    assert use.flows.consume(ProviderCallback("google", "s" * 43, "code", browser))
    client.cookies.set(BROWSER_COOKIE, browser.value)
    answer = client.post(endpoint, json=body)
    assert answer.status_code == 200, answer.text
    assert answer.json()["authenticated"]
    with transaction(path) as connection:
        assert connection.execute("SELECT count(*) FROM provider_flows").fetchone()[0] == 0
