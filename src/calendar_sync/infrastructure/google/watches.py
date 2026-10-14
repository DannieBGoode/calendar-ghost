"""Google Calendar push channels: one channel watches one calendar (ADR 0036).

`events.watch` opens a channel whose id is the registration id Calendar Ghost chose. The channel
carries the registration's secret token and delivers to its notice address. Google cannot renew a
channel, only replace it, so `extend` answers None. Stopping one with `channels.stop` needs its id
and Google's `resourceId`, which the handle keeps. A notice is headers only, never event content:
the channel id, its token, and the resource state. The state is `sync` when the channel starts,
and `exists` or `not_exists` after a change.

Sources, checked 2026-10-14:
- Push notifications: https://developers.google.com/workspace/calendar/api/guides/push
- events.watch: https://developers.google.com/workspace/calendar/api/v3/reference/events/watch
- channels.stop: https://developers.google.com/workspace/calendar/api/v3/reference/channels/stop
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from calendar_sync.application.shared.ports import Clock
from calendar_sync.application.sync.watch_ports import (
    MalformedNotice,
    NoticeKind,
    NoticeRequest,
    Receipt,
    WatchFailure,
    WatchFailureKind,
    WatchNotice,
)
from calendar_sync.domain.model import CalendarEndpoint, CalendarId, ConnectedAccountId
from calendar_sync.domain.providers import ProviderFailureKind
from calendar_sync.domain.watches import WatchRegistration, WatchRegistrationId, WatchScope
from calendar_sync.infrastructure.google.causes import http_reasons
from calendar_sync.infrastructure.google.provider import (
    GoogleServiceFactory,
    google_failure,
    send,
    status_code,
)
from calendar_sync.infrastructure.watch_failures import (
    ACCOUNT_UNAVAILABLE,
    account_unavailable,
    watch_failure,
)

# How a watch scope names one calendar (domain/watches.py).
CALENDAR_SCOPE = "calendar:"
# Reasons Google gives when it will not deliver to the notice address: the address is not https,
# or Google does not accept its certificate or domain. Only the installation's administrator can
# fix them, so the address counts as unreachable, never as a refusal of the account.
UNREACHABLE_REASONS = frozenset({"push.webhookUrlNotHttps", "push.webhookUrlUnauthorized"})
# The calendar offers no push channel, as some calendars Google publishes itself do not.
UNSUPPORTED_REASONS = frozenset({"pushNotSupportedForRequestedResource"})
# Answers to channels.stop meaning the channel is already gone.
GONE = frozenset({404, 410})
STATES = {
    "sync": NoticeKind.STARTED,
    "exists": NoticeKind.CHANGED,
    "not_exists": NoticeKind.CHANGED,
}


@dataclass(frozen=True, slots=True)
class _Handle:
    """What stopping a channel needs: its id and the resourceId Google gave it."""

    channel: str
    resource: str

    def encode(self) -> str:
        return json.dumps({"channel": self.channel, "resource": self.resource})

    @classmethod
    def decode(cls, value: str | None) -> _Handle | None:
        try:
            raw = json.loads(value or "")
            return cls(str(raw["channel"]), str(raw["resource"]))
        except (ValueError, KeyError, TypeError):
            return None


class GoogleCalendarWatcher:
    """CalendarWatcher for Google Calendar: one push channel per watched calendar."""

    def __init__(
        self,
        service_for: GoogleServiceFactory,
        clock: Clock,
        timer: Callable[[], float] = time.monotonic,
    ) -> None:
        self._service_for = service_for
        self._clock = clock
        # Seconds from an arbitrary start, for timing calls; the clock tells wall time.
        self._timer = timer

    def scope(self, calendar: CalendarEndpoint) -> WatchScope | None:
        # Google watches any calendar the account can read, one channel each.
        return WatchScope.calendar(calendar.calendar_id)

    def register(
        self,
        account: ConnectedAccountId,
        scope: WatchScope,
        registration_id: WatchRegistrationId,
        token: str,
        address: str,
        until: datetime,
    ) -> Receipt:
        calendar = _calendar_of(scope)
        body = {
            "id": registration_id.value,
            "type": "web_hook",
            "address": address,
            "token": token,
            "expiration": _milliseconds(until),
        }
        started = self._clock.now()
        try:
            request = (
                self._service_for(account).events().watch(calendarId=calendar.value, body=body)
            )
            answer = send("events.watch", request, self._timer)
        except ACCOUNT_UNAVAILABLE as error:
            raise account_unavailable() from error
        except Exception as error:
            raise self._failure(error, account, started) from error
        return _receipt(answer, registration_id, until)

    def extend(
        self,
        # Google cannot renew a channel: None asks upkeep for a replacement with a new id and
        # token, so nothing here is read.
        account: ConnectedAccountId,  # noqa: ARG002
        registration: WatchRegistration,  # noqa: ARG002
        until: datetime,  # noqa: ARG002
    ) -> datetime | None:
        return None

    def adopt(
        self,
        # Google never refuses a second channel on one calendar, so there is nothing to adopt.
        account: ConnectedAccountId,  # noqa: ARG002
        scope: WatchScope,  # noqa: ARG002
        registration_id: WatchRegistrationId,  # noqa: ARG002
        address: str,  # noqa: ARG002
    ) -> Receipt | None:
        return None

    def stop(self, account: ConnectedAccountId, registration: WatchRegistration) -> None:
        handle = _Handle.decode(registration.handle)
        if handle is None:
            # Without Google's resourceId a channel cannot be stopped; it ends at its expiry.
            return
        started = self._clock.now()
        try:
            request = (
                self._service_for(account)
                .channels()
                .stop(body={"id": handle.channel, "resourceId": handle.resource})
            )
            send("channels.stop", request, self._timer)
        except ACCOUNT_UNAVAILABLE as error:
            raise account_unavailable() from error
        except Exception as error:
            if status_code(error) in GONE:
                return
            raise self._failure(error, account, started) from error

    def _failure(
        self, error: Exception, account: ConnectedAccountId, started: datetime
    ) -> WatchFailure:
        """Google's refusal as a watch failure; `started` is when the call read the account's
        credentials."""
        reasons = http_reasons(error)
        if reasons & UNREACHABLE_REASONS:
            return WatchFailure(
                kind=WatchFailureKind.UNREACHABLE,
                detail="Google Calendar will not deliver notices to this installation's address",
            )
        if reasons & UNSUPPORTED_REASONS:
            return WatchFailure(
                kind=WatchFailureKind.UNSUPPORTED,
                detail="Google Calendar cannot watch this calendar",
            )
        failure = google_failure(error, account, attempted_at=started, now=self._clock.now())
        if failure.kind is ProviderFailureKind.PERMANENT and status_code(error) is None:
            # No answer arrived, as when the network failed: nothing refused the watch.
            return WatchFailure(
                kind=WatchFailureKind.TEMPORARY, detail="Google Calendar could not be reached"
            )
        return watch_failure(failure)


class GoogleNoticeReader:
    """NoticeReader for Google: one notice per request, in its headers."""

    def validation_token(self, request: NoticeRequest) -> str | None:  # noqa: ARG002
        # Google never asks the notice address to prove itself.
        return None

    def read(
        self, registration_id: WatchRegistrationId, request: NoticeRequest
    ) -> tuple[WatchNotice, ...]:
        headers = request.headers
        if headers.get("x-goog-channel-id") != registration_id.value:
            raise MalformedNotice("the notice names another channel than its address does")
        token = headers.get("x-goog-channel-token")
        kind = STATES.get(headers.get("x-goog-resource-state", ""))
        if not token or kind is None:
            raise MalformedNotice("the notice is not one Google Calendar sends")
        # Google's sync notice may arrive before events.watch answers, so no notice names the
        # handle: the registration id and its token identify the channel.
        return (WatchNotice(registration_id, token, None, kind),)


def _calendar_of(scope: WatchScope) -> CalendarId:
    """The one calendar a scope names; Google watches nothing wider."""
    calendar = scope.key.removeprefix(CALENDAR_SCOPE)
    if calendar == scope.key or not calendar:
        raise WatchFailure(
            kind=WatchFailureKind.UNSUPPORTED,
            detail="Google Calendar watches one calendar at a time",
        )
    return CalendarId(calendar)


def _receipt(
    answer: Mapping[str, Any], registration_id: WatchRegistrationId, until: datetime
) -> Receipt:
    resource = answer.get("resourceId")
    if answer.get("id") != registration_id.value or not isinstance(resource, str) or not resource:
        # Without its resourceId the channel could never be stopped; it ends at its expiry.
        raise WatchFailure(
            kind=WatchFailureKind.TEMPORARY,
            detail="Google Calendar did not identify the channel it opened",
        )
    # Google may shorten what was asked for; only its sync notice proves delivery.
    return Receipt(
        handle=_Handle(registration_id.value, resource).encode(),
        expires_at=_instant(answer.get("expiration")) or until,
    )


def _milliseconds(moment: datetime) -> int:
    return round(moment.timestamp() * 1000)


def _instant(value: object) -> datetime | None:
    """Google's expiry: milliseconds since the epoch, as a string."""
    try:
        return datetime.fromtimestamp(int(str(value)) / 1000, UTC)
    except (TypeError, ValueError, OverflowError, OSError):
        return None
