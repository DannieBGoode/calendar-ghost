"""Google push channels: one per calendar, opened under the registration's id and token, never
renewed or adopted, stopped by id and resourceId, and refused without Google's words (ADR 0036)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest
from google.auth.exceptions import RefreshError, TransportError

from calendar_sync.application.sync.errors import (
    ConnectedAccountDisconnected,
    ConnectedAccountNotFound,
)
from calendar_sync.application.sync.watch_ports import (
    MalformedNotice,
    NoticeKind,
    NoticeRequest,
    Receipt,
    WatchFailure,
    WatchFailureKind,
    WatchNotice,
    notice_address,
)
from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.model import CalendarId, ConnectedAccountId
from calendar_sync.domain.watches import (
    CalendarWatchId,
    RegistrationState,
    WatchRegistration,
    WatchRegistrationId,
    WatchScope,
)
from calendar_sync.infrastructure.google.watches import GoogleCalendarWatcher, GoogleNoticeReader
from calendar_sync.infrastructure.provider_calls import ContextProviderCallStats
from tests.adapters.google.test_provider import FixedClock, request_raising, request_returning
from tests.helpers import NOW, endpoint

ACCOUNT = ConnectedAccountId("account-family")
CALENDAR = endpoint("account-family", "family@example.test")
SCOPE = WatchScope.calendar(CALENDAR.calendar_id)
REGISTRATION = WatchRegistrationId("0123456789abcdef0123456789abcdef")
TOKEN = "synthetic-channel-token"
ADDRESS = notice_address("https://ghost.example.test", "google", REGISTRATION)
UNTIL = NOW + timedelta(days=3)
HANDLE = json.dumps({"channel": REGISTRATION.value, "resource": "resource-1"})


def watcher(service: MagicMock) -> GoogleCalendarWatcher:
    return GoogleCalendarWatcher(lambda _account: service, FixedClock(NOW))


def opened(expiration: datetime = UNTIL, **answer: Any) -> dict[str, Any]:
    """Google's answer to events.watch, which gives the expiry in milliseconds, as a string."""
    return {
        "kind": "api#channel",
        "id": REGISTRATION.value,
        "resourceId": "resource-1",
        "resourceUri": "https://www.googleapis.com/calendar/v3/calendars/family/events",
        "token": TOKEN,
        "expiration": str(round(expiration.timestamp() * 1000)),
        **answer,
    }


def registration(handle: str | None = HANDLE) -> WatchRegistration:
    return WatchRegistration(
        id=REGISTRATION,
        watch_id=CalendarWatchId("watch-1"),
        state=RegistrationState.LIVE,
        address=ADDRESS,
        token_hash="synthetic-hash",
        created_at=NOW,
        requested_until=UNTIL,
        handle=handle,
    )


def register(google: GoogleCalendarWatcher, scope: WatchScope = SCOPE) -> Receipt:
    return google.register(ACCOUNT, scope, REGISTRATION, TOKEN, ADDRESS, UNTIL)


def test_every_calendar_is_watched_on_its_own() -> None:
    google = watcher(MagicMock())

    assert google.scope(CALENDAR) == WatchScope.calendar(CalendarId("family@example.test"))


def test_a_channel_names_the_registration_and_points_at_its_address() -> None:
    service = MagicMock()
    service.events.return_value.watch.return_value = request_returning(
        opened(NOW + timedelta(days=2))
    )

    receipt = register(watcher(service))

    service.events.return_value.watch.assert_called_once_with(
        calendarId="family@example.test",
        body={
            "id": REGISTRATION.value,
            "type": "web_hook",
            "address": ADDRESS,
            "token": TOKEN,
            "expiration": round(UNTIL.timestamp() * 1000),
        },
    )
    # Google may shorten a channel's life, so its own expiry is kept. Only its sync notice
    # proves delivery.
    assert receipt == Receipt(HANDLE, NOW + timedelta(days=2), confirmed=False)


def test_a_channel_google_did_not_identify_is_not_recorded() -> None:
    service = MagicMock()
    service.events.return_value.watch.return_value = request_returning(opened(resourceId=None))

    with pytest.raises(WatchFailure) as raised:
        register(watcher(service))

    assert raised.value.kind is WatchFailureKind.TEMPORARY


def test_a_scope_wider_than_one_calendar_is_not_watched() -> None:
    service = MagicMock()

    with pytest.raises(WatchFailure) as raised:
        register(watcher(service), WatchScope.account())

    assert raised.value.kind is WatchFailureKind.UNSUPPORTED
    assert service.mock_calls == []


def test_a_channel_is_replaced_rather_than_renewed_and_never_adopted() -> None:
    service = MagicMock()
    google = watcher(service)

    assert google.extend(ACCOUNT, registration(), UNTIL) is None
    assert google.adopt(ACCOUNT, SCOPE, REGISTRATION, ADDRESS) is None
    assert service.mock_calls == []


def test_stopping_a_channel_names_its_id_and_resource() -> None:
    service = MagicMock()
    service.channels.return_value.stop.return_value = request_returning({})

    watcher(service).stop(ACCOUNT, registration())

    service.channels.return_value.stop.assert_called_once_with(
        body={"id": REGISTRATION.value, "resourceId": "resource-1"}
    )


@pytest.mark.parametrize("status", [404, 410])
def test_a_channel_already_gone_is_stopped(status: int) -> None:
    service = MagicMock()
    service.channels.return_value.stop.return_value = request_raising(status)

    watcher(service).stop(ACCOUNT, registration())


def test_a_channel_without_a_handle_is_left_to_expire() -> None:
    service = MagicMock()

    watcher(service).stop(ACCOUNT, registration(None))

    assert service.mock_calls == []


def test_a_stop_google_could_not_answer_is_reported() -> None:
    service = MagicMock()
    service.channels.return_value.stop.return_value = request_raising(503)

    with pytest.raises(WatchFailure) as raised:
        watcher(service).stop(ACCOUNT, registration())

    assert raised.value.kind is WatchFailureKind.TEMPORARY


@pytest.mark.parametrize(
    ("status", "reason", "kind"),
    [
        (401, None, WatchFailureKind.UNAUTHORIZED),
        (403, "insufficientPermissions", WatchFailureKind.UNAUTHORIZED),
        # A bare refusal may concern this calendar alone, so it never lapses the account.
        (403, None, WatchFailureKind.UNSUPPORTED),
        (403, "forbidden", WatchFailureKind.UNSUPPORTED),
        (403, "rateLimitExceeded", WatchFailureKind.RATE_LIMITED),
        (429, None, WatchFailureKind.RATE_LIMITED),
        (400, "pushNotSupportedForRequestedResource", WatchFailureKind.UNSUPPORTED),
        (400, "push.webhookUrlNotHttps", WatchFailureKind.UNREACHABLE),
        # Google answers 401 when it refuses the address, which is no refusal of the account.
        (401, "push.webhookUrlUnauthorized", WatchFailureKind.UNREACHABLE),
        (400, "somethingNew", WatchFailureKind.UNSUPPORTED),
        (503, None, WatchFailureKind.TEMPORARY),
    ],
)
def test_refusals_are_classed_for_upkeep_without_googles_words(
    status: int, reason: str | None, kind: WatchFailureKind
) -> None:
    service = MagicMock()
    service.events.return_value.watch.return_value = request_raising(status, reason=reason)

    with pytest.raises(WatchFailure) as raised:
        register(watcher(service))

    assert raised.value.kind is kind
    assert "synthetic Google" not in raised.value.detail


def _carries_no_provider_error(failure: WatchFailure) -> bool:
    """Whether a traceback of `failure` would show no provider error, whose text may quote the
    request: a token, a registration address."""
    return failure.__cause__ is None and failure.__suppress_context__


def test_a_watch_failure_carries_no_provider_error_along() -> None:
    service = MagicMock()
    service.events.return_value.watch.return_value = request_raising(401)
    service.channels.return_value.stop.return_value = request_raising(503)
    google = watcher(service)

    for call in (lambda: register(google), lambda: google.stop(ACCOUNT, registration())):
        with pytest.raises(WatchFailure) as raised:
            call()
        assert _carries_no_provider_error(raised.value)


def test_a_refused_account_lapses_from_when_its_credentials_were_read() -> None:
    service = MagicMock()
    service.events.return_value.watch.return_value = request_raising(401)

    with pytest.raises(WatchFailure) as raised:
        register(watcher(service))

    lapse = raised.value.failure
    assert lapse is not None
    assert lapse.account_id == ACCOUNT
    assert lapse.provider is ProviderKind.GOOGLE
    assert lapse.attempted_at == NOW


def test_a_rate_limit_carries_googles_retry_after() -> None:
    service = MagicMock()
    service.events.return_value.watch.return_value = request_raising(
        429, headers={"Retry-After": "30"}
    )

    with pytest.raises(WatchFailure) as raised:
        register(watcher(service))

    assert raised.value.retry_after_seconds == 30


def test_credentials_google_no_longer_accepts_are_unauthorized() -> None:
    def refused(_account: ConnectedAccountId) -> Any:
        raise RefreshError("invalid_grant: revoked")  # type: ignore[no-untyped-call]

    with pytest.raises(WatchFailure) as raised:
        register(GoogleCalendarWatcher(refused, FixedClock(NOW)))

    assert raised.value.kind is WatchFailureKind.UNAUTHORIZED


def test_a_token_endpoint_google_could_not_reach_is_temporary() -> None:
    def unreachable(_account: ConnectedAccountId) -> Any:
        raise TransportError("connection reset")  # type: ignore[no-untyped-call]

    with pytest.raises(WatchFailure) as raised:
        register(GoogleCalendarWatcher(unreachable, FixedClock(NOW)))

    assert raised.value.kind is WatchFailureKind.TEMPORARY


@pytest.mark.parametrize(
    "gone",
    [
        ConnectedAccountNotFound("connected account account-family does not exist"),
        ConnectedAccountDisconnected("connected account account-family needs reauthorization"),
    ],
)
def test_an_account_without_credentials_is_unavailable_not_unsupported(gone: Exception) -> None:
    def unavailable(_account: ConnectedAccountId) -> Any:
        raise gone

    google = GoogleCalendarWatcher(unavailable, FixedClock(NOW))

    for call in (lambda: register(google), lambda: google.stop(ACCOUNT, registration())):
        with pytest.raises(WatchFailure) as raised:
            call()
        assert raised.value.kind is WatchFailureKind.ACCOUNT_UNAVAILABLE
        assert "account-family" not in raised.value.detail
        assert _carries_no_provider_error(raised.value)


def test_a_request_that_got_no_answer_is_temporary() -> None:
    request = MagicMock()
    request.execute.side_effect = OSError("network down")
    service = MagicMock()
    service.events.return_value.watch.return_value = request

    with pytest.raises(WatchFailure) as raised:
        register(watcher(service))

    assert raised.value.kind is WatchFailureKind.TEMPORARY


def test_watch_calls_count_toward_provider_calls() -> None:
    service = MagicMock()
    service.events.return_value.watch.return_value = request_returning(opened())
    service.channels.return_value.stop.return_value = request_returning({})
    google = watcher(service)

    with ContextProviderCallStats().measure() as tally:
        register(google)
        google.stop(ACCOUNT, registration())

    assert tally.providers[ProviderKind.GOOGLE].calls == 2


def notice(headers: dict[str, str]) -> NoticeRequest:
    return NoticeRequest(headers, {}, b"")


def channel_headers(state: str) -> dict[str, str]:
    return {
        "x-goog-channel-id": REGISTRATION.value,
        "x-goog-channel-token": TOKEN,
        "x-goog-resource-id": "resource-1",
        "x-goog-resource-state": state,
        "x-goog-message-number": "1",
    }


@pytest.mark.parametrize(
    ("state", "kind"),
    [
        ("sync", NoticeKind.STARTED),
        ("exists", NoticeKind.CHANGED),
        ("not_exists", NoticeKind.CHANGED),
    ],
)
def test_each_resource_state_is_a_notice_without_a_handle(state: str, kind: NoticeKind) -> None:
    # The sync notice may arrive before events.watch answers, so no notice names a handle.
    assert GoogleNoticeReader().read(REGISTRATION, notice(channel_headers(state))) == (
        WatchNotice(REGISTRATION, TOKEN, None, kind),
    )


@pytest.mark.parametrize(
    "headers",
    [
        {**channel_headers("exists"), "x-goog-channel-id": "another-channel"},
        {**channel_headers("exists"), "x-goog-channel-token": ""},
        {key: value for key, value in channel_headers("exists").items() if "token" not in key},
        {**channel_headers("exists"), "x-goog-resource-state": "unexpected"},
        {key: value for key, value in channel_headers("exists").items() if "state" not in key},
    ],
)
def test_a_notice_google_would_not_send_is_malformed(headers: dict[str, str]) -> None:
    with pytest.raises(MalformedNotice):
        GoogleNoticeReader().read(REGISTRATION, notice(headers))


def test_google_never_asks_the_address_to_prove_itself() -> None:
    request = NoticeRequest({}, {"validationToken": "opaque"}, b"")

    assert GoogleNoticeReader().validation_token(request) is None
