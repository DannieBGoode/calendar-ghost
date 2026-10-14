"""Outlook change notifications through Microsoft Graph subscriptions (ADR 0036).

Graph documents event subscriptions only for a whole mailbox, `me/events`. Delegated permissions
cannot watch a calendar that another mailbox shares, so one subscription covers every calendar
the signed-in mailbox owns, and a shared calendar is not watched. Before it answers 201, Graph
validates the notification URL and the lifecycle URL, which is the same address, so a created
subscription proves Graph reached the installation. A subscription lasts at most 10,080 minutes
and is renewed in place. Graph refuses a second one for the same resource and change types with
409. Such a subscription is adopted only when its notification URL names this registration
exactly, and an unidentified subscription is never deleted. Graph's message text is never kept
(ADR 0034).

Sources, checked 2026-10-14:
- Create subscription:
  https://learn.microsoft.com/en-us/graph/api/subscription-post-subscriptions?view=graph-rest-1.0
- Webhook delivery, validation, renewal, and deletion:
  https://learn.microsoft.com/en-us/graph/change-notifications-delivery-webhooks
- Lifecycle notifications:
  https://learn.microsoft.com/en-us/graph/change-notifications-lifecycle-events
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from threading import Lock
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
from calendar_sync.domain.model import CalendarEndpoint, ConnectedAccountId
from calendar_sync.domain.watches import WatchRegistration, WatchRegistrationId, WatchScope
from calendar_sync.infrastructure.microsoft.graph import (
    GraphHttp,
    GraphRefusal,
    TokenRefusal,
    items_of,
)
from calendar_sync.infrastructure.microsoft.provider import AccessTokens, refusal_failure
from calendar_sync.infrastructure.watch_failures import (
    ACCOUNT_UNAVAILABLE,
    account_unavailable,
    watch_failure,
)

RESOURCE = "me/events"
CHANGE_TYPES = "created,updated,deleted"
# Graph's longest Outlook subscription is 10,080 minutes; asking a little less leaves room for
# clocks that disagree.
LONGEST = timedelta(minutes=10_080) - timedelta(minutes=5)
# How long who owns a calendar is remembered: about one upkeep cycle.
OWNER_MEMORY = timedelta(minutes=5)
# Answers meaning the subscription or calendar is gone.
GONE = frozenset({404, 410})
# Graph's answer to a second subscription with the same resource and change types.
CONFLICT = 409
# A notice batch holds at most this many items.
MAX_ITEMS = 100
LIFECYCLE = {
    "missed": NoticeKind.MISSED,
    "reauthorizationRequired": NoticeKind.REAUTHORIZE,
    "subscriptionRemoved": NoticeKind.REMOVED,
}


class OutlookCalendarWatcher:
    """CalendarWatcher for Outlook: one Graph subscription per signed-in mailbox."""

    def __init__(self, tokens: AccessTokens, graph: GraphHttp, clock: Clock) -> None:
        self._tokens = tokens
        self._graph = graph
        self._clock = clock
        self._owners: dict[tuple[ConnectedAccountId, str], tuple[str | None, datetime]] = {}
        # Upkeep checks several Users' calendars at once.
        self._guard = Lock()

    def scope(self, calendar: CalendarEndpoint) -> WatchScope | None:
        account = calendar.connected_account_id
        started = self._clock.now()
        try:
            mailbox = self._owner(account, "/me/calendar", started)
            owner = self._owner(account, f"/me/calendars/{calendar.calendar_id.value}", started)
        except (GraphRefusal, TokenRefusal) as error:
            raise self._failure(error, account, started) from None
        except ACCOUNT_UNAVAILABLE:
            raise account_unavailable() from None
        # A calendar another mailbox shares cannot be watched with delegated permissions.
        return WatchScope.account() if mailbox is not None and owner == mailbox else None

    def register(
        self,
        account: ConnectedAccountId,
        scope: WatchScope,
        registration_id: WatchRegistrationId,
        token: str,
        address: str,
        until: datetime,
    ) -> Receipt:
        if scope != WatchScope.account() or not _names(address, registration_id):
            raise WatchFailure(
                kind=WatchFailureKind.UNSUPPORTED,
                detail="Outlook watches a whole mailbox, at an address naming its registration",
            )
        started = self._clock.now()
        expiry = _capped(until, started)
        body = {
            "changeType": CHANGE_TYPES,
            "notificationUrl": address,
            "lifecycleNotificationUrl": address,
            "resource": RESOURCE,
            "expirationDateTime": _stamp(expiry),
            "clientState": token,
        }
        try:
            answer = self._graph.request(
                "subscriptions.create",
                "POST",
                "/subscriptions",
                self._tokens.access_token(account),
                body=body,
            )
        except (GraphRefusal, TokenRefusal) as error:
            raise self._failure(error, account, started) from None
        except ACCOUNT_UNAVAILABLE:
            raise account_unavailable() from None
        receipt = _receipt(answer, expiry)
        if receipt is None:
            raise WatchFailure(
                kind=WatchFailureKind.TEMPORARY,
                detail="Outlook did not name the subscription it created",
            )
        return receipt

    def extend(
        self, account: ConnectedAccountId, registration: WatchRegistration, until: datetime
    ) -> datetime | None:
        if registration.handle is None:
            return None
        started = self._clock.now()
        expiry = _capped(until, started)
        try:
            answer = self._graph.request(
                "subscriptions.update",
                "PATCH",
                f"/subscriptions/{registration.handle}",
                self._tokens.access_token(account),
                body={"expirationDateTime": _stamp(expiry)},
            )
        except GraphRefusal as error:
            if error.status in GONE:
                # Graph removed it: None asks upkeep for a new subscription in its place.
                return None
            raise self._failure(error, account, started) from None
        except TokenRefusal as error:
            raise self._failure(error, account, started) from None
        except ACCOUNT_UNAVAILABLE:
            raise account_unavailable() from None
        return _instant(answer.get("expirationDateTime")) or expiry

    def adopt(
        self,
        account: ConnectedAccountId,
        scope: WatchScope,
        registration_id: WatchRegistrationId,
        address: str,
    ) -> Receipt | None:
        if scope != WatchScope.account() or not _names(address, registration_id):
            return None
        started = self._clock.now()
        try:
            found = self._find(account, address)
        except (GraphRefusal, TokenRefusal) as error:
            raise self._failure(error, account, started) from None
        except ACCOUNT_UNAVAILABLE:
            raise account_unavailable() from None
        return None if found is None else _receipt(found, None)

    def stop(self, account: ConnectedAccountId, registration: WatchRegistration) -> None:
        started = self._clock.now()
        try:
            handle = registration.handle or self._lost(account, registration)
            if handle is not None:
                self._graph.request(
                    "subscriptions.delete",
                    "DELETE",
                    f"/subscriptions/{handle}",
                    self._tokens.access_token(account),
                )
        except GraphRefusal as error:
            if error.status not in GONE:
                raise self._failure(error, account, started) from None
        except TokenRefusal as error:
            raise self._failure(error, account, started) from None
        except ACCOUNT_UNAVAILABLE:
            raise account_unavailable() from None

    def _owner(self, account: ConnectedAccountId, path: str, now: datetime) -> str | None:
        """Who owns the calendar at `path`, remembered for about one upkeep cycle; None when it
        is gone."""
        key = (account, path)
        with self._guard:
            known = self._owners.get(key)
        if known is not None and now - known[1] < OWNER_MEMORY:
            return known[0]
        try:
            answer = self._graph.request(
                "calendars.get",
                "GET",
                path,
                self._tokens.access_token(account),
                params={"$select": "owner"},
            )
            owner = _address(answer.get("owner"))
        except GraphRefusal as error:
            if error.status not in GONE:
                raise
            owner = None
        with self._guard:
            # Forget answers older than a cycle, so the memory stays as small as the work.
            self._owners = {
                seen: remembered
                for seen, remembered in self._owners.items()
                if now - remembered[1] < OWNER_MEMORY
            }
            self._owners[key] = (owner, now)
        return owner

    def _find(self, account: ConnectedAccountId, address: str) -> Mapping[str, Any] | None:
        """The subscription to the mailbox's events whose notification URL is exactly
        `address`, among those this application holds for the signed-in mailbox."""
        token = self._tokens.access_token(account)
        for page in self._graph.pages("subscriptions.list", "/subscriptions", token):
            for item in items_of(page):
                if item.get("notificationUrl") == address and _resource(item) == RESOURCE:
                    return item
        return None

    def _lost(self, account: ConnectedAccountId, registration: WatchRegistration) -> str | None:
        """The subscription a registration created whose answer was lost, found only by its
        exact address, so no other subscription is ever deleted."""
        if not _names(registration.address, registration.id):
            return None
        found = self._find(account, registration.address)
        handle = None if found is None else found.get("id")
        return handle if isinstance(handle, str) and handle else None

    def _failure(
        self, error: GraphRefusal | TokenRefusal, account: ConnectedAccountId, started: datetime
    ) -> WatchFailure:
        """Microsoft's refusal as a watch failure; `started` is when the call read the account's
        access token."""
        if isinstance(error, GraphRefusal) and error.status == CONFLICT:
            return WatchFailure(
                kind=WatchFailureKind.DUPLICATE,
                detail="Outlook already holds a subscription to this mailbox's events",
            )
        if isinstance(error, GraphRefusal) and error.endpoint_refused:
            return WatchFailure(
                kind=WatchFailureKind.UNREACHABLE,
                detail="Outlook could not reach this installation's notice address",
            )
        return watch_failure(
            refusal_failure(error, account, attempted_at=started, now=self._clock.now())
        )


class OutlookNoticeReader:
    """NoticeReader for Outlook: a batch of change and lifecycle notices in a JSON body."""

    def validation_token(self, request: NoticeRequest) -> str | None:
        # Graph proves the address by asking it to echo this token, which the route answers.
        return request.query.get("validationToken") or None

    def read(
        self, registration_id: WatchRegistrationId, request: NoticeRequest
    ) -> tuple[WatchNotice, ...]:
        try:
            body = json.loads(request.body)
        except ValueError as error:
            raise MalformedNotice("the notice is not JSON") from error
        items = body.get("value") if isinstance(body, dict) else None
        if not isinstance(items, list) or not 0 < len(items) <= MAX_ITEMS:
            raise MalformedNotice("the notice is not a batch Outlook sends")
        return tuple(_notice(registration_id, item) for item in items)


def _notice(registration_id: WatchRegistrationId, item: object) -> WatchNotice:
    if not isinstance(item, Mapping):
        raise MalformedNotice("a notice in the batch is not an object")
    handle, token = item.get("subscriptionId"), item.get("clientState")
    if not (isinstance(handle, str) and handle and isinstance(token, str) and token):
        raise MalformedNotice("a notice names no subscription or carries no client state")
    event = item.get("lifecycleEvent")
    if event is None:
        return WatchNotice(registration_id, token, handle, NoticeKind.CHANGED)
    # A lifecycle event this release does not know asks for a catch-up run, as `missed` does.
    kind = LIFECYCLE.get(str(event), NoticeKind.MISSED)
    return WatchNotice(registration_id, token, handle, kind)


def _receipt(item: Mapping[str, Any], fallback: datetime | None) -> Receipt | None:
    """A subscription as upkeep records it. Graph validated its address before creating it, so
    delivery is proven."""
    handle = item.get("id")
    expires = _instant(item.get("expirationDateTime")) or fallback
    if not isinstance(handle, str) or not handle or expires is None:
        return None
    return Receipt(handle=handle, expires_at=expires, confirmed=True)


def _names(address: str, registration_id: WatchRegistrationId) -> bool:
    """Whether `address` is a notice address naming this registration, as adoption requires."""
    return address.endswith(f"/{registration_id.value}")


def _resource(item: Mapping[str, Any]) -> str:
    return str(item.get("resource") or "").strip("/").lower()


def _capped(until: datetime, now: datetime) -> datetime:
    return min(until, now + LONGEST).replace(microsecond=0)


def _stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _instant(value: object) -> datetime | None:
    """Graph's `expirationDateTime`, such as "2026-09-02T10:00:00.0000000Z"."""
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _address(owner: object) -> str | None:
    address = owner.get("address") if isinstance(owner, Mapping) else None
    return (address.strip().lower() or None) if isinstance(address, str) else None
