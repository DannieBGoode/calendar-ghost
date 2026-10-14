"""Graph subscriptions in fake mailboxes, as Graph v1.0 documents them (ADR 0036).

A subscription belongs to the mailbox that created it, which alone lists, renews, or deletes it.
Creating one first validates its notification and lifecycle URLs, as Graph does before it answers
201. A test makes an address unreachable through `reachable`. A second subscription of a mailbox
with the same resource and change types is refused with 409. Listings withhold `clientState`, as
Graph does. Graph documents the statuses and the messages used here; the error codes are
stand-ins, since the adapter reads only the status and whether a 400 says the URL failed
validation.

Sources:
- https://learn.microsoft.com/en-us/graph/api/subscription-post-subscriptions?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/change-notifications-delivery-webhooks
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

GRAPH = "https://graph.microsoft.com/v1.0"
Json = dict[str, Any]

PAGE = 2
"""Small, so a listing of more than two subscriptions is answered in pages."""
# Graph's message for an address that did not answer its validation request, with something
# private that must never be kept.
UNVALIDATED = (
    "Subscription validation request failed. Notification endpoint must respond with 200 OK to "
    "validation request. private-marker"
)


@dataclass
class StoredSubscription:
    id: str
    mailbox: str
    resource: str
    change_type: str
    notification_url: str
    lifecycle_url: str | None
    client_state: str | None
    expires: str

    def answer(self, *, with_state: bool) -> Json:
        return {
            "id": self.id,
            "resource": self.resource,
            "changeType": self.change_type,
            "notificationUrl": self.notification_url,
            "lifecycleNotificationUrl": self.lifecycle_url,
            "expirationDateTime": self.expires,
            "clientState": self.client_state if with_state else None,
        }


class FakeGraphSubscriptions:
    """`/subscriptions` for every mailbox of a FakeMicrosoftGraph."""

    def __init__(self) -> None:
        self.stored: dict[str, StoredSubscription] = {}
        self.reachable: Callable[[str], bool] = lambda _address: True
        self._next = 1

    def seed(
        self,
        mailbox: str,
        notification_url: str,
        *,
        resource: str = "me/events",
        change_type: str = "created,updated,deleted",
        expires: str = "2026-09-02T10:00:00Z",
    ) -> str:
        """A subscription made earlier, by another registration or another application."""
        subscription = StoredSubscription(
            self._new_id(),
            mailbox,
            resource,
            change_type,
            notification_url,
            notification_url,
            "someone-elses-state",
            expires,
        )
        self.stored[subscription.id] = subscription
        return subscription.id

    def serve(self, request: httpx.Request, mailbox: str, path: str) -> httpx.Response:
        rest = path.removeprefix("/subscriptions").strip("/")
        if not rest:
            if request.method == "POST":
                return self._create(mailbox, _json(request))
            return self._list(mailbox, int(request.url.params.get("page", "0")))
        found = self.stored.get(rest)
        if found is None or found.mailbox != mailbox:
            return _error(404, "ResourceNotFound", "private-marker not found")
        if request.method == "PATCH":
            found.expires = str(_json(request)["expirationDateTime"])
            return httpx.Response(200, json=found.answer(with_state=False))
        if request.method == "DELETE":
            del self.stored[rest]
            return httpx.Response(204)
        return httpx.Response(200, json=found.answer(with_state=False))

    def _create(self, mailbox: str, body: Json) -> httpx.Response:
        url = str(body.get("notificationUrl", ""))
        lifecycle = body.get("lifecycleNotificationUrl")
        addresses = [url, *([lifecycle] if isinstance(lifecycle, str) else [])]
        if not all(self.reachable(address) for address in addresses):
            return _error(400, "ValidationError", UNVALIDATED)
        resource, change_type = str(body["resource"]), str(body["changeType"])
        for existing in self.stored.values():
            if (
                existing.mailbox == mailbox
                and existing.resource.lower() == resource.lower()
                and existing.change_type == change_type
            ):
                return _error(
                    409,
                    "Conflict",
                    f"Subscription Id {existing.id} already exists for the requested combination",
                )
        subscription = StoredSubscription(
            self._new_id(),
            mailbox,
            resource,
            change_type,
            url,
            lifecycle if isinstance(lifecycle, str) else None,
            str(body.get("clientState")),
            str(body["expirationDateTime"]),
        )
        self.stored[subscription.id] = subscription
        return httpx.Response(201, json=subscription.answer(with_state=True))

    def _list(self, mailbox: str, page: int) -> httpx.Response:
        mine = [s for s in self.stored.values() if s.mailbox == mailbox]
        body: Json = {
            "value": [s.answer(with_state=False) for s in mine[page * PAGE : (page + 1) * PAGE]]
        }
        if (page + 1) * PAGE < len(mine):
            body["@odata.nextLink"] = f"{GRAPH}/subscriptions?page={page + 1}"
        return httpx.Response(200, json=body)

    def _new_id(self) -> str:
        identifier = f"subscription-{self._next}"
        self._next += 1
        return identifier


def _json(request: httpx.Request) -> Json:
    body = json.loads(request.content or b"{}")
    assert isinstance(body, dict)
    return body


def _error(status: int, code: str, message: str) -> httpx.Response:
    return httpx.Response(status, json={"error": {"code": code, "message": message}})
