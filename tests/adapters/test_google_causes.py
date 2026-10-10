"""Why Google refused a request, as a Cause read from its reason code alone (ADR 0031)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from google.auth.exceptions import RefreshError, TransportError

from calendar_sync.application.causes import Cause, CauseOwner
from calendar_sync.application.errors import (
    AccountAccessCheckFailed,
    ProviderFailure,
    ProviderFailureKind,
)
from calendar_sync.domain.model import ConnectedAccountId
from calendar_sync.infrastructure.google.oauth import (
    GoogleOAuthService,
    OAuthClientConfig,
)
from calendar_sync.infrastructure.google.provider import GoogleCalendarProvider
from calendar_sync.infrastructure.persistence.accounts import SqliteConnectedAccountStore
from calendar_sync.infrastructure.persistence.authorization_states import (
    SqliteAuthorizationStates,
)
from calendar_sync.infrastructure.persistence.sqlite import initialize_database
from calendar_sync.infrastructure.security import CredentialCipher
from tests.fake_google_calendar_api import GoogleResponse
from tests.helpers import endpoint
from tests.users import add_user

DESTINATION = endpoint("work-account", "work-calendar")
# What Google's message text might quote: no Cause, detail, or summary may carry it.
GOOGLE_MESSAGE = "Calendar private-marker-calendar@group.calendar.google.com said no"


class GoogleHttpError(Exception):
    """Shaped like googleapiclient's HttpError, with Google's JSON error body."""

    def __init__(self, status: int, body: dict[str, Any] | bytes | None) -> None:
        super().__init__(f"<HttpError {status} returned {GOOGLE_MESSAGE!r}>")
        self.resp = GoogleResponse(status, {})
        self.content = body if isinstance(body, bytes) else json.dumps(body or {}).encode()


def google_error(status: int, *reasons: str) -> GoogleHttpError:
    return GoogleHttpError(
        status,
        {
            "error": {
                "code": status,
                "message": GOOGLE_MESSAGE,
                "errors": [
                    {"domain": "global", "reason": reason, "message": GOOGLE_MESSAGE}
                    for reason in reasons
                ],
            }
        },
    )


def token_error(code: str, *, retryable: bool = False) -> RefreshError:
    # As google-auth raises it: "code: description", then the token endpoint's answer.
    return RefreshError(  # type: ignore[no-untyped-call]
        f"{code}: {GOOGLE_MESSAGE}",
        {"error": code, "error_description": GOOGLE_MESSAGE},
        retryable=retryable,
    )


def _failure_of(error: Exception) -> ProviderFailure:
    request = MagicMock()
    request.execute.side_effect = error
    events_api = MagicMock()
    events_api.list.return_value = request
    service = MagicMock()
    service.events.return_value = events_api
    provider = GoogleCalendarProvider(lambda _account: service)
    with pytest.raises(ProviderFailure) as raised:
        provider.find_projection(DESTINATION, "operation-key")
    return raised.value


@pytest.mark.parametrize(
    ("error", "cause"),
    [
        # https://cloud.google.com/resource-manager/docs/core_errors: accessNotConfigured, 403.
        (google_error(403, "accessNotConfigured"), Cause.API_DISABLED),
        # The same answer in Google's newer form: an ErrorInfo detail with SERVICE_DISABLED.
        (
            GoogleHttpError(
                403,
                {
                    "error": {
                        "code": 403,
                        "message": GOOGLE_MESSAGE,
                        "status": "PERMISSION_DENIED",
                        "details": [
                            {
                                "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                                "reason": "SERVICE_DISABLED",
                                "domain": "googleapis.com",
                            }
                        ],
                    }
                },
            ),
            Cause.API_DISABLED,
        ),
        # core_errors: dailyLimitExceeded, "A daily quota limit for the API has been reached."
        (google_error(403, "dailyLimitExceeded"), Cause.QUOTA_EXCEEDED),
        # https://developers.google.com/workspace/calendar/api/guides/errors: rate limits.
        (google_error(403, "rateLimitExceeded"), Cause.RATE_LIMITED),
        (google_error(403, "userRateLimitExceeded"), Cause.RATE_LIMITED),
        (google_error(429, "rateLimitExceeded"), Cause.RATE_LIMITED),
        (google_error(429), Cause.RATE_LIMITED),
        # Calendar's quotaExceeded is one account's Calendar usage limits, lifted by Google.
        (google_error(403, "quotaExceeded"), Cause.RATE_LIMITED),
        (google_error(403, "requiredAccessLevel"), Cause.CALENDAR_FORBIDDEN),
        (google_error(403, "forbidden"), Cause.CALENDAR_FORBIDDEN),
        (google_error(403, "forbiddenForNonOrganizer"), Cause.CALENDAR_FORBIDDEN),
        (google_error(403, "insufficientPermissions"), Cause.ACCESS_REVOKED),
        (google_error(401, "authError"), Cause.ACCESS_REVOKED),
        (google_error(404, "notFound"), Cause.CALENDAR_NOT_FOUND),
        (google_error(410, "deleted"), Cause.CALENDAR_NOT_FOUND),
        (google_error(500, "backendError"), Cause.TEMPORARY),
        (google_error(503), Cause.TEMPORARY),
        (google_error(403, "somethingNew"), Cause.UNKNOWN),
        (google_error(400, "timeRangeEmpty"), Cause.UNKNOWN),
        (GoogleHttpError(403, b"<html>not JSON</html>"), Cause.UNKNOWN),
        # RFC 6749 section 5.2 and https://developers.google.com/identity/protocols/oauth2.
        (token_error("invalid_grant"), Cause.ACCESS_REVOKED),
        (token_error("invalid_client"), Cause.OAUTH_CLIENT_INVALID),
        (token_error("unauthorized_client"), Cause.OAUTH_CLIENT_INVALID),
        (token_error("deleted_client"), Cause.OAUTH_CLIENT_INVALID),
        (token_error("admin_policy_enforced"), Cause.UNKNOWN),
        (token_error("internal_failure", retryable=True), Cause.TEMPORARY),
        (RefreshError("invalid_client"), Cause.OAUTH_CLIENT_INVALID),  # type: ignore[no-untyped-call]
        (RefreshError("not a code at all"), Cause.UNKNOWN),  # type: ignore[no-untyped-call]
        (TransportError("connection reset"), Cause.TEMPORARY),  # type: ignore[no-untyped-call]
    ],
)
def test_each_reason_google_gives_is_one_cause(error: Exception, cause: Cause) -> None:
    failure = _failure_of(error)

    assert failure.cause is cause
    assert GOOGLE_MESSAGE not in repr(failure.cause)
    assert GOOGLE_MESSAGE not in failure.summary


def test_a_refreshed_token_googles_message_never_reaches_the_failure() -> None:
    failure = _failure_of(token_error("invalid_client"))

    assert GOOGLE_MESSAGE not in failure.detail
    assert GOOGLE_MESSAGE not in repr(failure)


def test_a_used_up_daily_quota_is_retried_rather_than_lapsing_the_account() -> None:
    # Earlier releases read it as an authorization refusal; a quota resets by itself (ADR 0031).
    failure = _failure_of(google_error(403, "dailyLimitExceeded"))

    assert failure.kind is ProviderFailureKind.RATE_LIMIT
    assert failure.retryable


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (google_error(403, "accessNotConfigured"), ProviderFailureKind.AUTHORIZATION),
        (token_error("invalid_client"), ProviderFailureKind.AUTHENTICATION),
        (google_error(404, "notFound"), ProviderFailureKind.PERMANENT),
        (google_error(403, "someNewReason"), ProviderFailureKind.AUTHORIZATION),
    ],
)
def test_a_cause_does_not_change_what_the_failure_kind_decides(
    error: Exception, kind: ProviderFailureKind
) -> None:
    assert _failure_of(error).kind is kind


def test_every_cause_is_the_administrators_or_the_users() -> None:
    administrator = {cause for cause in Cause if cause.owner is CauseOwner.ADMINISTRATOR}
    user = {cause for cause in Cause if cause.owner is CauseOwner.USER}

    assert administrator == {
        Cause.API_DISABLED,
        Cause.QUOTA_EXCEEDED,
        Cause.OAUTH_CLIENT_INVALID,
    }
    assert user == set(Cause) - administrator


@pytest.mark.parametrize(
    ("error", "logged"),
    [
        (google_error(403, "somethingNew"), "reason=somethingNew"),
        (token_error("brand_new_error"), "reason=brand_new_error"),
        (google_error(400), "reason=none"),
        # Not a short token, so not repeated: it could be anything Google wrote.
        (google_error(403, "has spaces in it"), "reason=unreadable"),
        (google_error(403, "x" * 65), "reason=unreadable"),
        (google_error(403, "semi;colon"), "reason=unreadable"),
    ],
)
def test_an_unrecognized_reason_is_logged_as_a_short_token_only(
    error: Exception, logged: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="calendar_sync")

    assert _failure_of(error).cause is Cause.UNKNOWN

    lines = [record.getMessage() for record in caplog.records]
    assert any("unrecognized provider reason provider=google" in line for line in lines)
    assert any(logged in line for line in lines)
    assert not any(GOOGLE_MESSAGE in line for line in lines)


def test_a_recognized_reason_is_not_logged(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="calendar_sync")

    _failure_of(google_error(403, "accessNotConfigured"))

    assert caplog.records == []


@pytest.mark.parametrize("value", [None, "", "some_future_cause", 3])
def test_a_cause_this_release_does_not_know_reads_as_unknown(value: object) -> None:
    assert Cause.read(value) is Cause.UNKNOWN
    assert Cause.read("api_disabled") is Cause.API_DISABLED


def _oauth_with_failing_calendar_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> GoogleOAuthService:
    class StubCalendarRequest:
        def execute(self) -> dict[str, Any]:
            raise error

    service = SimpleNamespace(
        calendarList=lambda: SimpleNamespace(list=lambda **_: StubCalendarRequest())
    )
    database = tmp_path / "test.db"
    initialize_database(database)
    store = SqliteConnectedAccountStore(database, CredentialCipher(CredentialCipher.generate_key()))
    add_user(database)
    oauth = GoogleOAuthService(
        OAuthClientConfig("client-id", "client-secret", "http://localhost/callback"),
        store,
        SqliteAuthorizationStates(database),
        "verifier-key",
    )
    monkeypatch.setattr(oauth, "_credentials", lambda _: object())
    monkeypatch.setattr(
        "calendar_sync.infrastructure.google.oauth.build", lambda *args, **kwargs: service
    )
    return oauth


@pytest.mark.parametrize(
    ("error", "cause"),
    [
        (google_error(403, "accessNotConfigured"), Cause.API_DISABLED),
        (token_error("invalid_client"), Cause.OAUTH_CLIENT_INVALID),
        (google_error(401, "authError"), Cause.ACCESS_REVOKED),
        (google_error(503), Cause.TEMPORARY),
    ],
)
def test_check_access_says_why_google_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: Exception, cause: Cause
) -> None:
    oauth = _oauth_with_failing_calendar_list(tmp_path, monkeypatch, error)

    with pytest.raises(AccountAccessCheckFailed) as raised:
        oauth.verify_access(ConnectedAccountId("account-1"))

    assert raised.value.cause is cause
    assert GOOGLE_MESSAGE not in str(raised.value)


@pytest.mark.parametrize("reason", ["requiredAccessLevel", "forbidden", "forbiddenForNonOrganizer"])
def test_a_calendar_the_account_may_not_change_stops_its_rule_not_the_account(reason: str) -> None:
    # Reauthorizing cannot give an account permission on one calendar, and its other calendars
    # still work: so the rule stops for another calendar, and the account does not lapse.
    failure = _failure_of(google_error(403, reason))

    assert failure.cause is Cause.CALENDAR_FORBIDDEN
    assert failure.kind is ProviderFailureKind.PERMANENT
    assert not failure.requires_authorization
