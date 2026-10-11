import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials

from calendar_sync.application.errors import AccountAccessCheckFailed, ConnectedAccountDisconnected
from calendar_sync.application.providers import ProviderKind
from calendar_sync.infrastructure.google.oauth import GoogleOAuthService
from calendar_sync.infrastructure.oauth import OAuthClientConfig
from calendar_sync.infrastructure.persistence.accounts import SqliteConnectedAccountStore
from calendar_sync.infrastructure.persistence.authorization_states import (
    SqliteAuthorizationStates,
)
from calendar_sync.infrastructure.persistence.sqlite import initialize_database
from calendar_sync.infrastructure.provider_calls import ContextProviderCallStats
from calendar_sync.infrastructure.security import CredentialCipher
from tests.users import USER, add_user

CLIENT = OAuthClientConfig(
    "synthetic-client", "synthetic-secret", "http://localhost:8000/api/v1/oauth/google/callback"
)


def _stored(token: str, expiry: datetime) -> str:
    return json.dumps(
        {
            "token": token,
            "refresh_token": "synthetic-refresh-token",
            "client_id": "synthetic-client",
            "client_secret": "synthetic-secret",
            "token_uri": "https://oauth2.googleapis.com/token",
            # google-auth keeps expiry as naive UTC.
            "expiry": expiry.astimezone(UTC).replace(tzinfo=None).isoformat() + "Z",
        }
    )


def _store(tmp_path: Path) -> SqliteConnectedAccountStore:
    database = tmp_path / "test.db"
    initialize_database(database)
    add_user(database)
    return SqliteConnectedAccountStore(database, CredentialCipher(CredentialCipher.generate_key()))


def _oauth(tmp_path: Path, store: SqliteConnectedAccountStore) -> GoogleOAuthService:
    return GoogleOAuthService(
        CLIENT, store, SqliteAuthorizationStates(tmp_path / "test.db"), "synthetic-master-key"
    )


@pytest.fixture
def built(monkeypatch: pytest.MonkeyPatch) -> list[Credentials]:
    """The credentials each built Calendar service was given."""
    given: list[Credentials] = []

    def build(*_: Any, credentials: Credentials, **__: Any) -> object:
        given.append(credentials)
        return object()

    monkeypatch.setattr("calendar_sync.infrastructure.google.oauth.build", build)
    return given


@pytest.fixture
def refreshes(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Each token refresh, answered by Google with a new access token valid for an hour."""
    issued: list[str] = []

    def refresh(self: Credentials, _request: object) -> None:
        issued.append(f"refreshed-token-{len(issued) + 1}")
        self.token = issued[-1]
        self.expiry = (datetime.now(UTC) + timedelta(hours=1)).replace(tzinfo=None)

    monkeypatch.setattr(Credentials, "refresh", refresh)
    return issued


def test_a_valid_stored_token_is_used_without_refreshing(
    tmp_path: Path, built: list[Credentials], refreshes: list[str]
) -> None:
    store = _store(tmp_path)
    account = store.for_user(USER).save(
        "Work",
        "work@example.test",
        _stored("valid-token", datetime.now(UTC) + timedelta(hours=1)),
        provider=ProviderKind.GOOGLE,
    )

    _oauth(tmp_path, store).service_for(account.id)

    assert refreshes == []
    assert built[0].token == "valid-token"


def test_an_expired_token_is_refreshed_once_and_kept_for_later_requests(
    tmp_path: Path, built: list[Credentials], refreshes: list[str]
) -> None:
    store = _store(tmp_path)
    account = store.for_user(USER).save(
        "Work",
        "work@example.test",
        _stored("old-token", datetime.now(UTC) - timedelta(hours=2)),
        provider=ProviderKind.GOOGLE,
    )
    oauth = _oauth(tmp_path, store)

    oauth.service_for(account.id)
    oauth.service_for(account.id)

    assert refreshes == ["refreshed-token-1"]
    assert [item.token for item in built] == ["refreshed-token-1", "refreshed-token-1"]
    stored = json.loads(store.credential_json(account.id))
    assert stored["token"] == "refreshed-token-1"
    assert stored["refresh_token"] == "synthetic-refresh-token"
    # A restart reads the kept token too, instead of refreshing again.
    _oauth(tmp_path, store).service_for(account.id)
    assert refreshes == ["refreshed-token-1"]


def test_a_failed_refresh_keeps_the_stored_credentials(
    tmp_path: Path, built: list[Credentials], monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    expired = _stored("old-token", datetime.now(UTC) - timedelta(hours=2))
    account = store.for_user(USER).save(
        "Work", "work@example.test", expired, provider=ProviderKind.GOOGLE
    )

    def refresh(self: Credentials, _request: object) -> None:
        raise RefreshError("invalid_grant")  # type: ignore[no-untyped-call]

    monkeypatch.setattr(Credentials, "refresh", refresh)

    with pytest.raises(RefreshError):
        _oauth(tmp_path, store).service_for(account.id)

    assert store.credential_json(account.id) == expired
    assert built == []


def test_kept_credentials_never_replace_a_newer_authorization(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = _stored("old-token", datetime.now(UTC) - timedelta(hours=2))
    account = store.for_user(USER).save(
        "Work", "work@example.test", first, provider=ProviderKind.GOOGLE
    )
    reauthorized = _stored("reauthorized-token", datetime.now(UTC) + timedelta(hours=1))
    store.for_user(USER).save(
        "Work", "work@example.test", reauthorized, provider=ProviderKind.GOOGLE
    )

    kept = store.replace_credentials(account.id, first, '{"token": "refreshed"}')

    assert kept is False
    assert store.credential_json(account.id) == reauthorized


def test_kept_credentials_do_not_reconnect_a_disconnected_account(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = _stored("old-token", datetime.now(UTC) - timedelta(hours=2))
    account = store.for_user(USER).save(
        "Work", "work@example.test", first, provider=ProviderKind.GOOGLE
    )
    store.for_user(USER).disconnect(account.id)

    assert store.replace_credentials(account.id, "{}", '{"token": "refreshed"}') is False
    assert store.replace_credentials(account.id, first, '{"token": "refreshed"}') is False
    assert store.for_user(USER).is_connected(account.id) is False


def test_keeping_a_refreshed_token_is_not_a_reauthorization(tmp_path: Path) -> None:
    # Activity offers rule recovery only once access was renewed by the person, so a routine
    # refresh must not move the account's authorization time.
    store = _store(tmp_path)
    first = _stored("old-token", datetime.now(UTC) - timedelta(hours=2))
    account = store.for_user(USER).save(
        "Work", "work@example.test", first, provider=ProviderKind.GOOGLE
    )

    assert store.replace_credentials(account.id, first, '{"token": "refreshed"}') is True

    kept = store.for_user(USER).get(account.id)
    assert kept is not None
    assert kept.authorized_at == account.authorized_at
    assert store.credential_json(account.id) == '{"token": "refreshed"}'


def test_a_token_refresh_is_counted_toward_the_run_and_logged_without_the_token(
    tmp_path: Path,
    built: list[Credentials],
    refreshes: list[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = _store(tmp_path)
    account = store.for_user(USER).save(
        "Work",
        "work@example.test",
        _stored("old-token", datetime.now(UTC) - timedelta(hours=2)),
        provider=ProviderKind.GOOGLE,
    )
    oauth = _oauth(tmp_path, store)

    with (
        caplog.at_level("INFO", logger="calendar_sync"),
        ContextProviderCallStats().measure() as tally,
    ):
        oauth.service_for(account.id)
        oauth.service_for(account.id)

    assert tally.token_refreshes == 1
    assert f"account={account.id.value}" in caplog.text
    assert "token" not in caplog.text.replace("access token", "")
    assert "work@example.test" not in caplog.text


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            RefreshError("invalid_grant"),  # type: ignore[no-untyped-call]
            "Google authorization has expired; reauthorize this account",
        ),
        (
            RefreshError("token endpoint returned 503", retryable=True),  # type: ignore[no-untyped-call]
            "Google Calendar access could not be verified; try again",
        ),
    ],
)
def test_an_access_check_whose_token_refresh_fails_explains_what_to_do(
    tmp_path: Path,
    built: list[Credentials],
    monkeypatch: pytest.MonkeyPatch,
    error: RefreshError,
    expected: str,
) -> None:
    store = _store(tmp_path)
    account = store.for_user(USER).save(
        "Work",
        "work@example.test",
        _stored("old-token", datetime.now(UTC) - timedelta(hours=2)),
        provider=ProviderKind.GOOGLE,
    )

    def refresh(self: Credentials, _request: object) -> None:
        raise error

    monkeypatch.setattr(Credentials, "refresh", refresh)

    with pytest.raises(AccountAccessCheckFailed, match=expected):
        _oauth(tmp_path, store).verify_access(account.id)
    assert built == []


def test_an_access_check_of_a_disconnected_account_still_says_it_is_disconnected(
    tmp_path: Path, built: list[Credentials]
) -> None:
    store = _store(tmp_path)
    account = store.for_user(USER).save(
        "Work",
        "work@example.test",
        _stored("token", datetime.now(UTC) + timedelta(hours=1)),
        provider=ProviderKind.GOOGLE,
    )
    store.for_user(USER).disconnect(account.id)

    with pytest.raises(ConnectedAccountDisconnected):
        _oauth(tmp_path, store).verify_access(account.id)
