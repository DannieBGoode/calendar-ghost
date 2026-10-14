"""Outlook watches through Graph subscriptions: one per mailbox, only for calendars it owns,
renewed in place, adopted only by their exact address, never deleted unidentified, and refused
without Graph's words (ADR 0036)."""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx
import pytest

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
from calendar_sync.domain.model import ConnectedAccountId
from calendar_sync.domain.watches import (
    CalendarWatchId,
    RegistrationState,
    WatchRegistration,
    WatchRegistrationId,
    WatchScope,
)
from calendar_sync.infrastructure.microsoft.graph import GraphHttp
from calendar_sync.infrastructure.microsoft.watches import (
    OutlookCalendarWatcher,
    OutlookNoticeReader,
)
from calendar_sync.infrastructure.provider_calls import ContextProviderCallStats
from tests.adapters.microsoft.test_calendar_provider_contract import MAILBOXES, IssuedTokens
from tests.fake_microsoft_graph_api import FakeCalendar, FakeMicrosoftGraph, Refusal, graph_error
from tests.helpers import NOW, endpoint

ACCOUNT = ConnectedAccountId("personal-account")
MAILBOX = MAILBOXES["personal-account"][0]
OWN = endpoint("personal-account", "personal-calendar")
SHARED = endpoint("personal-account", "shared-calendar")
OURS = WatchRegistrationId("0123456789abcdef0123456789abcdef")
THEIRS = WatchRegistrationId("fedcba9876543210fedcba9876543210")
PUBLIC = "https://ghost.example.test"
ADDRESS = notice_address(PUBLIC, "microsoft", OURS)
OTHER_ADDRESS = notice_address(PUBLIC, "microsoft", THEIRS)
TOKEN = "synthetic-client-state"
UNTIL = NOW + timedelta(days=3)


@dataclass
class MovingClock:
    moment: datetime = NOW

    def now(self) -> datetime:
        return self.moment


def outlook(
    clock: MovingClock | None = None,
) -> tuple[OutlookCalendarWatcher, FakeMicrosoftGraph]:
    graph = FakeMicrosoftGraph()
    tokens = {}
    for account, (address, calendar) in MAILBOXES.items():
        graph.mailbox(
            address,
            calendars=[
                FakeCalendar(calendar, calendar.title(), default=True),
                FakeCalendar(
                    "shared-calendar", "Colleague", can_edit=False, owner="colleague@example.test"
                ),
            ],
        )
        tokens[account] = graph.issue(address)["access_token"]
    watcher = OutlookCalendarWatcher(
        IssuedTokens(tokens), GraphHttp(graph.client()), clock or MovingClock()
    )
    return watcher, graph


def register(
    watcher: OutlookCalendarWatcher,
    registration_id: WatchRegistrationId = OURS,
    address: str = ADDRESS,
    until: datetime = UNTIL,
) -> Receipt:
    return watcher.register(ACCOUNT, WatchScope.account(), registration_id, TOKEN, address, until)


def registration(
    handle: str | None, registration_id: WatchRegistrationId = OURS, address: str = ADDRESS
) -> WatchRegistration:
    return WatchRegistration(
        id=registration_id,
        watch_id=CalendarWatchId("watch-1"),
        state=RegistrationState.LIVE,
        address=address,
        token_hash="synthetic-hash",
        created_at=NOW,
        requested_until=UNTIL,
        handle=handle,
    )


def sent(graph: FakeMicrosoftGraph, method: str, path: str) -> list[httpx.Request]:
    return [r for r in graph.requests if r.method == method and r.url.path == f"/v1.0{path}"]


# Scope ------------------------------------------------------------------------------------


def test_a_calendar_the_mailbox_owns_is_watched_with_the_whole_mailbox() -> None:
    watcher, _ = outlook()

    assert watcher.scope(OWN) == WatchScope.account()


def test_a_calendar_another_mailbox_shares_cannot_be_watched() -> None:
    watcher, _ = outlook()

    assert watcher.scope(SHARED) is None


def test_a_calendar_that_is_gone_cannot_be_watched() -> None:
    watcher, _ = outlook()

    assert watcher.scope(endpoint("personal-account", "deleted-calendar")) is None


def test_who_owns_a_calendar_is_read_once_per_upkeep_cycle() -> None:
    clock = MovingClock()
    watcher, graph = outlook(clock)

    watcher.scope(OWN)
    watcher.scope(OWN)

    assert len(sent(graph, "GET", "/me/calendar")) == 1
    assert len(sent(graph, "GET", "/me/calendars/personal-calendar")) == 1
    clock.moment += timedelta(minutes=5)
    watcher.scope(OWN)
    assert len(sent(graph, "GET", "/me/calendars/personal-calendar")) == 2


def test_a_cold_scope_is_measured_as_two_provider_calls_and_a_warm_one_as_none() -> None:
    watcher, _ = outlook()

    with ContextProviderCallStats().measure() as cold:
        watcher.scope(OWN)
    with ContextProviderCallStats().measure() as warm:
        watcher.scope(OWN)

    assert cold.calls == 2
    assert cold.providers[ProviderKind.OUTLOOK].calls == 2
    assert warm.calls == 0


# Subscriptions ----------------------------------------------------------------------------


def test_a_subscription_covers_the_mailbox_and_proves_delivery() -> None:
    watcher, graph = outlook()

    receipt = register(watcher)

    (created,) = graph.subscriptions.stored.values()
    # Graph validated the address before it answered, so delivery is proven.
    assert receipt == Receipt(created.id, UNTIL, confirmed=True)
    assert json.loads(sent(graph, "POST", "/subscriptions")[0].content) == {
        "changeType": "created,updated,deleted",
        "notificationUrl": ADDRESS,
        "lifecycleNotificationUrl": ADDRESS,
        "resource": "me/events",
        "expirationDateTime": "2026-09-02T10:00:00Z",
        "clientState": TOKEN,
    }


def test_a_subscription_asks_for_no_longer_than_graph_allows() -> None:
    watcher, graph = outlook()

    receipt = register(watcher, until=NOW + timedelta(days=30))

    assert receipt.expires_at == NOW + timedelta(minutes=10_075)
    body = json.loads(sent(graph, "POST", "/subscriptions")[0].content)
    assert body["expirationDateTime"] == "2026-09-06T09:55:00Z"


def test_only_the_whole_mailbox_at_an_address_naming_the_registration_is_subscribed() -> None:
    watcher, graph = outlook()

    for scope, address in (
        (WatchScope.calendar(OWN.calendar_id), ADDRESS),
        (WatchScope.account(), OTHER_ADDRESS),
    ):
        with pytest.raises(WatchFailure) as raised:
            watcher.register(ACCOUNT, scope, OURS, TOKEN, address, UNTIL)
        assert raised.value.kind is WatchFailureKind.UNSUPPORTED
    assert sent(graph, "POST", "/subscriptions") == []


def test_an_address_graph_cannot_reach_is_unreachable_and_keeps_none_of_graphs_words() -> None:
    watcher, graph = outlook()
    graph.subscriptions.reachable = lambda _address: False

    with pytest.raises(WatchFailure) as raised:
        register(watcher)

    assert raised.value.kind is WatchFailureKind.UNREACHABLE
    assert "private-marker" not in raised.value.detail
    assert "validation request" not in raised.value.detail
    assert graph.subscriptions.stored == {}


def test_a_second_subscription_is_a_duplicate_adopted_only_by_its_exact_address() -> None:
    watcher, graph = outlook()
    first = register(watcher)

    with pytest.raises(WatchFailure) as raised:
        register(watcher, THEIRS, OTHER_ADDRESS)

    assert raised.value.kind is WatchFailureKind.DUPLICATE
    assert first.handle not in raised.value.detail
    # The subscription holding the mailbox belongs to another registration: never adopted.
    assert watcher.adopt(ACCOUNT, WatchScope.account(), THEIRS, OTHER_ADDRESS) is None
    assert watcher.adopt(ACCOUNT, WatchScope.account(), OURS, ADDRESS) == first
    assert not any(request.method == "DELETE" for request in graph.requests)
    assert list(graph.subscriptions.stored) == [first.handle]


def test_adoption_never_matches_by_resource_or_address_alone() -> None:
    watcher, graph = outlook()
    graph.subscriptions.seed(MAILBOX, OTHER_ADDRESS)
    graph.subscriptions.seed(MAILBOX, ADDRESS, resource="me/mailFolders('Inbox')/messages")

    assert watcher.adopt(ACCOUNT, WatchScope.account(), OURS, ADDRESS) is None
    # An address that does not name the registration is never looked for.
    assert watcher.adopt(ACCOUNT, WatchScope.account(), OURS, OTHER_ADDRESS) is None


def test_adoption_reads_every_page_of_the_mailboxs_subscriptions() -> None:
    watcher, graph = outlook()
    for number in range(3):
        other = WatchRegistrationId(f"{number:032x}")
        graph.subscriptions.seed(MAILBOX, notice_address(PUBLIC, "microsoft", other))
    ours = graph.subscriptions.seed(MAILBOX, ADDRESS)

    with ContextProviderCallStats().measure() as tally:
        adopted = watcher.adopt(ACCOUNT, WatchScope.account(), OURS, ADDRESS)

    assert adopted == Receipt(ours, UNTIL, confirmed=True)
    assert len(sent(graph, "GET", "/subscriptions")) == 2
    # Upkeep spends what it measured, so every page counts.
    assert tally.calls == 2


def test_a_subscription_is_renewed_in_place() -> None:
    watcher, graph = outlook()
    receipt = register(watcher)

    renewed = watcher.extend(ACCOUNT, registration(receipt.handle), NOW + timedelta(days=6))

    assert renewed == NOW + timedelta(days=6)
    assert graph.subscriptions.stored[receipt.handle].expires == "2026-09-05T10:00:00Z"


def test_a_subscription_graph_removed_is_replaced_rather_than_renewed() -> None:
    watcher, graph = outlook()

    assert watcher.extend(ACCOUNT, registration("removed-subscription"), UNTIL) is None
    assert watcher.extend(ACCOUNT, registration(None), UNTIL) is None
    assert sent(graph, "POST", "/subscriptions") == []


def test_stopping_deletes_the_subscription_and_one_already_gone_is_stopped() -> None:
    watcher, graph = outlook()
    receipt = register(watcher)

    watcher.stop(ACCOUNT, registration(receipt.handle))
    watcher.stop(ACCOUNT, registration(receipt.handle))

    assert graph.subscriptions.stored == {}


def test_a_subscription_whose_answer_was_lost_is_stopped_by_its_exact_address() -> None:
    watcher, graph = outlook()
    register(watcher)

    watcher.stop(ACCOUNT, registration(None))

    assert graph.subscriptions.stored == {}


def test_stopping_never_deletes_a_subscription_another_registration_holds() -> None:
    watcher, graph = outlook()
    theirs = register(watcher, THEIRS, OTHER_ADDRESS)

    watcher.stop(ACCOUNT, registration(None))

    assert list(graph.subscriptions.stored) == [theirs.handle]
    assert not any(request.method == "DELETE" for request in graph.requests)


# Refusals ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("refusal", "kind"),
    [
        (graph_error(401, "InvalidAuthenticationToken"), WatchFailureKind.UNAUTHORIZED),
        (graph_error(403, "Authorization_RequestDenied"), WatchFailureKind.UNAUTHORIZED),
        # A refusal of this request alone never lapses the account.
        (graph_error(403, "ErrorAccessDenied"), WatchFailureKind.UNSUPPORTED),
        (graph_error(400, "BadRequest"), WatchFailureKind.UNSUPPORTED),
        (
            graph_error(429, "TooManyRequests", **{"Retry-After": "30"}),
            WatchFailureKind.RATE_LIMITED,
        ),
        (graph_error(503, "ServiceNotAvailable"), WatchFailureKind.TEMPORARY),
    ],
)
def test_refusals_are_classed_for_upkeep_without_graphs_words(
    refusal: Refusal, kind: WatchFailureKind
) -> None:
    watcher, graph = outlook()
    graph.refuse(refusal, lambda request: request.url.path.endswith("/subscriptions"))

    with pytest.raises(WatchFailure) as raised:
        register(watcher)

    failure = raised.value
    assert failure.kind is kind
    assert "private-marker" not in failure.detail
    assert failure.failure is None or "private-marker" not in failure.failure.detail


def test_a_rate_limit_carries_graphs_retry_after() -> None:
    watcher, graph = outlook()
    graph.refuse(graph_error(429, "TooManyRequests", **{"Retry-After": "30"}))

    with pytest.raises(WatchFailure) as raised:
        register(watcher)

    assert raised.value.retry_after_seconds == 30


def test_an_account_graph_refuses_lapses_from_when_its_token_was_read() -> None:
    watcher, graph = outlook()
    graph.revoke(MAILBOX)

    with pytest.raises(WatchFailure) as raised:
        register(watcher)

    assert raised.value.kind is WatchFailureKind.UNAUTHORIZED
    lapse = raised.value.failure
    assert lapse is not None
    assert lapse.account_id == ACCOUNT
    assert lapse.attempted_at == NOW


@dataclass
class UnavailableTokens:
    """A credential store whose account was removed, or waits for reauthorization."""

    error: Exception

    def access_token(self, account_id: ConnectedAccountId) -> str:
        raise self.error


@pytest.mark.parametrize(
    "gone",
    [
        ConnectedAccountNotFound("connected account personal-account does not exist"),
        ConnectedAccountDisconnected("connected account personal-account needs reauthorization"),
    ],
)
def test_an_account_without_credentials_is_unsupported_in_every_call(gone: Exception) -> None:
    graph = FakeMicrosoftGraph()
    watcher = OutlookCalendarWatcher(
        UnavailableTokens(gone), GraphHttp(graph.client()), MovingClock()
    )
    calls = (
        lambda: watcher.scope(OWN),
        lambda: register(watcher),
        lambda: watcher.extend(ACCOUNT, registration("subscription-1"), UNTIL),
        lambda: watcher.adopt(ACCOUNT, WatchScope.account(), OURS, ADDRESS),
        lambda: watcher.stop(ACCOUNT, registration("subscription-1")),
    )

    for call in calls:
        with pytest.raises(WatchFailure) as raised:
            call()
        assert raised.value.kind is WatchFailureKind.UNSUPPORTED
        assert "personal-account" not in raised.value.detail
    assert graph.requests == []


def test_a_scope_graph_refuses_is_a_watch_failure() -> None:
    watcher, graph = outlook()
    graph.refuse(graph_error(503, "ServiceNotAvailable"))

    with pytest.raises(WatchFailure) as raised:
        watcher.scope(OWN)

    assert raised.value.kind is WatchFailureKind.TEMPORARY


# Notices ----------------------------------------------------------------------------------


def item(**fields: object) -> dict[str, object]:
    return {
        "subscriptionId": "subscription-1",
        "clientState": TOKEN,
        "tenantId": "synthetic-tenant",
        "subscriptionExpirationDateTime": "2026-09-02T10:00:00Z",
        **fields,
    }


def batch(*items: object) -> NoticeRequest:
    body = json.dumps({"value": list(items)}).encode()
    return NoticeRequest({"content-type": "application/json"}, {}, body)


def test_graph_asks_the_address_to_echo_its_validation_token() -> None:
    reader = OutlookNoticeReader()

    request = NoticeRequest({}, {"validationToken": "opaque token"}, b"")
    assert reader.validation_token(request) == "opaque token"
    assert reader.validation_token(batch(item())) is None


def test_a_batch_reads_changes_and_lifecycle_events() -> None:
    notices = OutlookNoticeReader().read(
        OURS,
        batch(
            item(changeType="updated", resource="Users/synthetic/Events/synthetic"),
            item(lifecycleEvent="missed"),
            item(lifecycleEvent="reauthorizationRequired"),
            item(lifecycleEvent="subscriptionRemoved"),
            # One this release does not know asks for a catch-up run.
            item(lifecycleEvent="somethingNew"),
        ),
    )

    assert [notice.kind for notice in notices] == [
        NoticeKind.CHANGED,
        NoticeKind.MISSED,
        NoticeKind.REAUTHORIZE,
        NoticeKind.REMOVED,
        NoticeKind.MISSED,
    ]
    assert notices[0] == WatchNotice(OURS, TOKEN, "subscription-1", NoticeKind.CHANGED)


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"\xff\xfe",
        b"{}",
        b"[]",
        json.dumps({"value": []}).encode(),
        json.dumps({"value": [item()] * 101}).encode(),
        json.dumps({"value": [item(clientState=None)]}).encode(),
        json.dumps({"value": [item(subscriptionId=7)]}).encode(),
        json.dumps({"value": ["text"]}).encode(),
    ],
)
def test_a_body_outlook_would_not_send_is_malformed(body: bytes) -> None:
    with pytest.raises(MalformedNotice):
        OutlookNoticeReader().read(OURS, NoticeRequest({}, {}, body))
