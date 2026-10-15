"""Instant Sync over the Web API: the public Watch Notice route, the User's switch, and each
rule's Effective Cadence (ADR 0036)."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient

from calendar_sync.application.operations.ports import InboxBusy
from calendar_sync.application.sync.watch_ports import (
    MalformedNotice,
    NoticeKind,
    NoticeRequest,
    WatchNotice,
)
from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import build_adapters, build_container, compose
from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.model import CalendarEndpoint
from calendar_sync.domain.watches import WatchRegistrationId
from calendar_sync.infrastructure.scheduling import InstantSyncDispatcher
from calendar_sync.infrastructure.security import CredentialCipher
from calendar_sync.interfaces.api.app import create_app
from calendar_sync.interfaces.api.routes.watch_notices import (
    NOTICE_BODY_LIMIT,
    VALIDATION_TOKEN_LIMIT,
)
from tests.helpers import rule
from tests.users import first_user, sign_in, sqlite_units

ADDRESS = "https://ghost.example.test"
REGISTRATION = "0123456789abcdef0123456789abcdef"
TOKEN = "synthetic-watch-token"
NOTICE_PATH = f"/api/v1/watch-notices/google/{REGISTRATION}"


class Reader:
    """A provider's notice reader: a validationToken query asks for an echo, and the body
    b"garbled" is no notice."""

    def __init__(self) -> None:
        self.reads = 0

    def validation_token(self, request: NoticeRequest) -> str | None:
        return request.query.get("validationToken")

    def read(
        self, registration_id: WatchRegistrationId, request: NoticeRequest
    ) -> tuple[WatchNotice, ...]:
        self.reads += 1
        if request.body == b"garbled":
            raise MalformedNotice("synthetic unreadable notice")
        token = request.headers.get("x-watch-token", "")
        return (WatchNotice(registration_id, token, None, NoticeKind.CHANGED),)


class Inbox:
    """The Watch Notice inbox: how many rules each request asks for, or busy storage."""

    def __init__(self, requested: int = 1, *, busy: bool = False) -> None:
        self.requested, self.busy = requested, busy
        self.recorded: list[tuple[tuple[WatchNotice, ...], ProviderKind, str]] = []

    def record(
        self,
        notices: Sequence[WatchNotice],
        provider: ProviderKind,
        address_base: str,
        at: datetime,
    ) -> int:
        if self.busy:
            raise InboxBusy("synthetic lock wait")
        self.recorded.append((tuple(notices), provider, address_base))
        return self.requested


class Dispatcher:
    def __init__(self) -> None:
        self.woken = 0

    def wake(self) -> None:
        self.woken += 1

    async def run_forever(self) -> None:
        return None


def _client(
    tmp_path: Path,
    inbox: Inbox,
    *,
    dispatcher: Dispatcher | None = None,
    reader: Reader | None = None,
    address: str | None = ADDRESS,
) -> TestClient:
    container = replace(
        build_container(Settings(tmp_path / "test.db")),
        watch_inbox=inbox,
        notice_readers={"google": (ProviderKind.GOOGLE, reader or Reader())},
        instant_dispatcher=cast(InstantSyncDispatcher, dispatcher or Dispatcher()),
        instant_sync_address=address,
    )
    return TestClient(create_app(container))


def _chunks(size: int, count: int) -> Iterator[bytes]:
    """A body sent in chunks, without a Content-Length."""
    for _ in range(count):
        yield b"x" * size


def test_an_unknown_provider_is_answered_as_any_unknown_api_path(tmp_path: Path) -> None:
    inbox = Inbox()
    with _client(tmp_path, inbox) as client:
        unknown = client.post(f"/api/v1/watch-notices/nobody/{REGISTRATION}", content=b"{}")
        elsewhere = client.post("/api/v1/nothing-here", content=b"{}")

    assert unknown.status_code == elsewhere.status_code == 404
    assert unknown.json() == elsewhere.json()
    assert inbox.recorded == []


def test_without_a_public_https_address_no_notice_is_heard(tmp_path: Path) -> None:
    inbox = Inbox()
    with _client(tmp_path, inbox, address=None) as client:
        answer = client.post(NOTICE_PATH, content=b"{}")

    assert (answer.status_code, answer.json()["code"]) == (404, "not_found")
    assert inbox.recorded == []


def test_a_body_above_the_cap_is_refused_before_it_is_held_whole(tmp_path: Path) -> None:
    inbox = Inbox()
    with _client(tmp_path, inbox) as client:
        declared = client.post(NOTICE_PATH, content=b"x" * (NOTICE_BODY_LIMIT + 1))
        streamed = client.post(NOTICE_PATH, content=_chunks(NOTICE_BODY_LIMIT // 2 + 1, 2))
        one_chunk = client.post(NOTICE_PATH, content=_chunks(NOTICE_BODY_LIMIT + 1, 1))
        at_the_cap = client.post(NOTICE_PATH, content=b"x" * NOTICE_BODY_LIMIT)

    assert (declared.status_code, declared.json()["code"]) == (413, "notice_too_large")
    assert (streamed.status_code, streamed.json()["code"]) == (413, "notice_too_large")
    assert (one_chunk.status_code, one_chunk.json()["code"]) == (413, "notice_too_large")
    assert at_the_cap.status_code == 202
    assert len(inbox.recorded) == 1


def test_a_validation_request_is_echoed_before_its_body_is_read(tmp_path: Path) -> None:
    inbox, dispatcher, reader = Inbox(), Dispatcher(), Reader()
    with _client(tmp_path, inbox, dispatcher=dispatcher, reader=reader) as client:
        echoed = client.post(
            NOTICE_PATH,
            params={"validationToken": "synthetic-validation"},
            content=b"x" * (NOTICE_BODY_LIMIT + 1),
            headers={"Content-Type": "text/plain"},
        )
        long = client.post(
            NOTICE_PATH, params={"validationToken": "v" * (VALIDATION_TOKEN_LIMIT + 50)}
        )

    assert echoed.status_code == 200
    assert echoed.headers["content-type"].startswith("text/plain")
    # A browser must never read the echoed text as anything but plain text.
    assert echoed.headers["x-content-type-options"] == "nosniff"
    assert echoed.text == "synthetic-validation"
    assert long.text == "v" * VALIDATION_TOKEN_LIMIT
    assert (reader.reads, inbox.recorded, dispatcher.woken) == (0, [], 0)


def test_a_request_that_is_no_notice_is_refused(tmp_path: Path) -> None:
    inbox = Inbox()
    with _client(tmp_path, inbox) as client:
        answer = client.post(NOTICE_PATH, content=b"garbled")

    assert (answer.status_code, answer.json()["code"]) == (400, "malformed_notice")
    assert inbox.recorded == []


def test_busy_storage_asks_the_provider_to_retry(tmp_path: Path) -> None:
    with _client(tmp_path, Inbox(busy=True)) as client:
        answer = client.post(NOTICE_PATH, content=b"{}")

    assert (answer.status_code, answer.json()["code"]) == (503, "inbox_busy")


def test_known_unknown_and_refused_notices_are_answered_alike(tmp_path: Path) -> None:
    requesting, ignoring = Inbox(requested=2), Inbox(requested=0)
    woke, slept = Dispatcher(), Dispatcher()
    headers = {"X-Watch-Token": TOKEN}
    with _client(tmp_path, requesting, dispatcher=woke) as client:
        known = client.post(NOTICE_PATH, content=b"{}", headers=headers)
    with _client(tmp_path, ignoring, dispatcher=slept) as client:
        unknown = client.post(NOTICE_PATH, content=b"{}", headers=headers)
        blank = client.post("/api/v1/watch-notices/google/%20", content=b"{}", headers=headers)

    assert (known.status_code, known.content) == (202, b"")
    assert (unknown.status_code, unknown.content) == (202, b"")
    assert (blank.status_code, blank.content) == (202, b"")
    # Only a notice that requested a run wakes the dispatcher.
    assert (woke.woken, slept.woken) == (1, 0)
    assert requesting.recorded == [
        (
            (WatchNotice(WatchRegistrationId(REGISTRATION), TOKEN, None, NoticeKind.CHANGED),),
            ProviderKind.GOOGLE,
            ADDRESS,
        )
    ]
    assert len(ignoring.recorded) == 1


class Occupying(Dispatcher):
    """A loop beside the scheduler that holds every default worker thread of the event loop,
    which `asyncio.to_thread` takes, as busy sync runs could."""

    def __init__(self) -> None:
        super().__init__()
        self.release, self.holding = threading.Event(), threading.Event()

    async def run_forever(self) -> None:
        loop = asyncio.get_running_loop()
        loop.set_default_executor(ThreadPoolExecutor(1))
        await loop.run_in_executor(None, self._hold)

    def _hold(self) -> None:
        self.holding.set()
        self.release.wait(10)
        self.holding.clear()


def test_a_notice_is_recorded_while_busy_loops_hold_the_default_worker_threads(
    tmp_path: Path,
) -> None:
    # Graph waits only 3 seconds for an answer.
    inbox, dispatcher = Inbox(), Occupying()
    with _client(tmp_path, inbox, dispatcher=dispatcher) as client:
        assert dispatcher.holding.wait(5)
        answer = client.post(NOTICE_PATH, content=b"{}", headers={"X-Watch-Token": TOKEN})
        answered_while_held = dispatcher.holding.is_set()
        dispatcher.release.set()

    assert answer.status_code == 202
    assert answered_while_held
    assert len(inbox.recorded) == 1


def test_no_log_line_names_a_notices_registration_token_or_body(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG), _client(tmp_path, Inbox()) as client:
        for body in (b'{"value": "synthetic body"}', b"garbled"):
            client.post(NOTICE_PATH, content=body, headers={"X-Watch-Token": TOKEN})
    with caplog.at_level(logging.DEBUG), _client(tmp_path, Inbox(busy=True)) as client:
        client.post(NOTICE_PATH, content=b"{}", headers={"X-Watch-Token": TOKEN})

    ours = "\n".join(
        record.getMessage()
        for record in caplog.records
        if record.name.startswith(("calendar_sync", "uvicorn", "fastapi"))
    )
    for secret in (REGISTRATION, TOKEN, "synthetic body"):
        assert secret not in ours


def _signed_in_app(
    tmp_path: Path, public_url: str, *, unwatchable: tuple[CalendarEndpoint, ...] = ()
) -> TestClient:
    settings = Settings(
        tmp_path / "test.db", master_key=CredentialCipher.generate_key(), public_url=public_url
    )
    adapters = build_adapters(settings)
    for calendar in unwatchable:
        # As upkeep records a calendar its provider cannot watch.
        adapters.watch_backoff.cannot_watch(calendar, datetime.now(UTC))
    container = replace(
        compose(settings, adapters), scheduler=None, instant_dispatcher=None, watch_keeper=None
    )
    return TestClient(create_app(container))


def test_a_user_turns_instant_sync_off_and_on(tmp_path: Path) -> None:
    with _signed_in_app(tmp_path, ADDRESS) as client:
        sign_in(client)
        before = client.get("/api/v1/session").json()["user"]
        off = client.put("/api/v1/account/instant-sync", json={"instant_sync": False}).json()
        after = client.get("/api/v1/session").json()["user"]
        on = client.put("/api/v1/account/instant-sync", json={"instant_sync": True}).json()

    def switch(user: dict[str, object]) -> tuple[object, object, object]:
        return (
            user["instant_sync"],
            user["instant_sync_availability"],
            user["instant_sync_help"],
        )

    assert switch(before) == (True, "on", None)
    assert switch(off) == (False, "off_by_user", None)
    assert switch(after) == (False, "off_by_user", None)
    assert switch(on) == (True, "on", None)


def test_without_a_public_https_address_the_switch_says_why_and_links_the_fix(
    tmp_path: Path,
) -> None:
    with _signed_in_app(tmp_path, "http://ghost.example.test") as client:
        sign_in(client)
        user = client.get("/api/v1/session").json()["user"]

    assert (user["instant_sync_availability"], user["instant_sync_help"]) == (
        "no_public_address",
        "no-public-https-address",
    )


@pytest.mark.parametrize(
    ("public_url", "unwatchable", "cadence"),
    [
        (ADDRESS, (), "waiting_for_provider"),
        (ADDRESS, (rule().source,), "not_watchable"),
        ("", (), "no_public_address"),
    ],
    ids=["https, nothing watched yet", "https, found unwatchable", "no public address"],
)
def test_each_rule_says_how_often_it_syncs(
    tmp_path: Path, public_url: str, unwatchable: tuple[CalendarEndpoint, ...], cadence: str
) -> None:
    database = tmp_path / "test.db"
    client = _signed_in_app(tmp_path, public_url, unwatchable=unwatchable)
    owner = first_user(database)
    with sqlite_units(database, user=owner)() as uow:
        uow.rules.add(rule())
        uow.commit()

    with client:
        sign_in(client)
        listed = client.get("/api/v1/rules").json()
        detail = client.get(f"/api/v1/rules/{rule().id.value}").json()

    assert [(item["effective_cadence"], item["poll_every_minutes"]) for item in listed] == [
        (cadence, 5)
    ]
    assert (detail["effective_cadence"], detail["poll_every_minutes"]) == (cadence, 5)
