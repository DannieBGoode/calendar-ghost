"""Watch Notices as the inbox records them for every User, in SQLite and in memory alike."""

from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path

import pytest

from calendar_sync.application.operations.ports import InboxBusy, WatchNoticeInbox
from calendar_sync.application.sync.ports import UnitOfWorkFactory
from calendar_sync.application.sync.watch_ports import (
    DeliveryEvidenceLog,
    NoticeKind,
    PendingRequest,
    Receipt,
    WatchNotice,
    notice_address,
)
from calendar_sync.domain.access import UserId
from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.model import ConnectedAccountId, SyncRule, SyncRuleId, SyncRuleState
from calendar_sync.domain.watches import (
    CalendarWatch,
    CalendarWatchId,
    DeliveryEvidence,
    RegistrationState,
    WatchRegistration,
    WatchRegistrationId,
    WatchScope,
    token_hash,
)
from calendar_sync.infrastructure.persistence.connections import open_connection
from calendar_sync.infrastructure.persistence.memory import (
    InMemoryUnitOfWorkFactory,
    MemoryDatabase,
)
from calendar_sync.infrastructure.persistence.memory_installation import (
    InMemoryDeliveryEvidenceLog,
    InMemoryWatchNoticeInbox,
)
from calendar_sync.infrastructure.persistence.migrations import initialize_database
from calendar_sync.infrastructure.persistence.sqlite import SqliteUnitOfWorkFactory
from calendar_sync.infrastructure.persistence.watch_inbox import (
    SqliteDeliveryEvidenceLog,
    SqliteWatchNoticeInbox,
)
from tests.helpers import NOW, endpoint, rule
from tests.users import OTHER_USER, RULE_ACCOUNTS, USER, add_account, memory_units

GOOGLE, OUTLOOK = ProviderKind.GOOGLE, ProviderKind.OUTLOOK
BASE = "https://calendar.example.test"
SECOND, MINUTE, HOUR, DAY = (
    timedelta(seconds=1),
    timedelta(minutes=1),
    timedelta(hours=1),
    timedelta(days=1),
)
THEIR_ACCOUNTS = ("their-personal-account", "their-work-account")
RULE = rule()
UNCOVERED = replace(
    RULE, id=SyncRuleId("rule-uncovered"), source=endpoint("personal-account", "family")
)
PAUSED = replace(
    RULE,
    id=SyncRuleId("rule-paused"),
    destination=endpoint("work-account", "other-calendar"),
    state=SyncRuleState.PAUSED,
)
THEIRS = replace(
    RULE,
    id=SyncRuleId("their-rule"),
    source=endpoint("their-personal-account", "personal-calendar"),
    destination=endpoint("their-work-account", "work-calendar"),
)
"""Another User's rule, whose Source Calendar has the same identifier as RULE's."""
WATCH = CalendarWatch(
    CalendarWatchId("watch-1"),
    RULE.source.connected_account_id,
    WatchScope.calendar(RULE.source.calendar_id),
    frozenset({RULE.source.calendar_id}),
)
THEIR_WATCH = CalendarWatch(
    CalendarWatchId("their-watch"),
    THEIRS.source.connected_account_id,
    WatchScope.calendar(THEIRS.source.calendar_id),
    frozenset({THEIRS.source.calendar_id}),
)
RECEIPT = Receipt("handle-registration-1", NOW + 7 * DAY)


@dataclass(frozen=True, slots=True)
class Store:
    units: Callable[[UserId], UnitOfWorkFactory]
    inbox: WatchNoticeInbox
    evidence: DeliveryEvidenceLog


@pytest.fixture(params=["sqlite", "memory"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> Store:
    """Both stores, with each User's accounts connected as their provider's."""
    owners = ((USER, RULE_ACCOUNTS), (OTHER_USER, THEIR_ACCOUNTS))
    if request.param == "sqlite":
        database = tmp_path / "calendar-sync.db"
        initialize_database(database)
        for user, accounts in owners:
            for account in accounts:
                add_account(database, account, user)
        return Store(
            SqliteUnitOfWorkFactory(database).for_user,
            SqliteWatchNoticeInbox(database),
            SqliteDeliveryEvidenceLog(database),
        )
    factory = InMemoryUnitOfWorkFactory()
    for user, accounts in owners:
        units = memory_units(factory, user=user, accounts=accounts)
        for account in accounts:
            units.state.providers[ConnectedAccountId(account)] = GOOGLE
    return Store(
        factory.for_user,
        InMemoryWatchNoticeInbox(factory.database),
        InMemoryDeliveryEvidenceLog(factory.database),
    )


def _registration(
    state: RegistrationState = RegistrationState.LIVE,
    *,
    name: str = "registration-1",
    watch: CalendarWatch = WATCH,
    base: str = BASE,
) -> WatchRegistration:
    registration_id = WatchRegistrationId(name)
    answered = state is not RegistrationState.CREATING
    return WatchRegistration(
        registration_id,
        watch.id,
        state,
        notice_address(base, "google", registration_id),
        token_hash(f"token-{name}"),
        NOW - HOUR,
        NOW + 7 * DAY,
        handle=f"handle-{name}" if answered else None,
        expires_at=NOW + 7 * DAY if answered else None,
    )


def _seed(
    store: Store,
    registration: WatchRegistration,
    *,
    user: UserId = USER,
    watch: CalendarWatch = WATCH,
    rules: tuple[SyncRule, ...] = (RULE,),
) -> None:
    with store.units(user)() as uow:
        for each in rules:
            uow.rules.add(each)
        uow.watches.add(watch)
        uow.watches.add_registration(registration)
        uow.commit()


def _notice(
    kind: NoticeKind = NoticeKind.CHANGED,
    *,
    name: str = "registration-1",
    token: str | None = None,
    handle: str | None = None,
) -> WatchNotice:
    return WatchNotice(WatchRegistrationId(name), token or f"token-{name}", handle, kind)


def _record(
    store: Store,
    *notices: WatchNotice,
    after: timedelta = timedelta(0),
    provider: ProviderKind = GOOGLE,
) -> int:
    return store.inbox.record(notices, provider, BASE, NOW + after)


def _pending(store: Store, user: UserId = USER) -> tuple[PendingRequest, ...]:
    with store.units(user)() as uow:
        return tuple(uow.instant_requests.pending())


def _registrations(store: Store, user: UserId = USER) -> tuple[WatchRegistration, ...]:
    with store.units(user)() as uow:
        return tuple(uow.watches.registrations())


def test_an_unknown_registration_changes_nothing_and_proves_nothing(store: Store) -> None:
    _seed(store, _registration())

    assert _record(store, _notice(name="missing")) == 0

    assert _pending(store) == ()
    assert store.evidence.evidence(BASE) == {}


def test_a_wrong_token_changes_nothing(store: Store) -> None:
    _seed(store, _registration())

    assert _record(store, _notice(token="token-guessed")) == 0
    assert _record(store, _notice(NoticeKind.REAUTHORIZE, token="token-guessed")) == 0

    assert _pending(store) == ()
    assert _registrations(store) == (_registration(),)
    assert store.evidence.evidence(BASE) == {}


def test_an_abandoned_registration_is_recognized_and_ignored(store: Store) -> None:
    _seed(store, _registration(RegistrationState.ABANDONED))

    assert _record(store, _notice(), _notice(NoticeKind.STARTED)) == 0

    assert _pending(store) == ()
    assert _registrations(store) == (_registration(RegistrationState.ABANDONED),)
    assert store.evidence.evidence(BASE) == {}


def test_a_handle_that_differs_is_refused_and_a_missing_one_is_not_checked(store: Store) -> None:
    _seed(store, _registration())

    refused = _record(store, _notice(handle="handle-other"))
    accepted = _record(store, _notice(handle="handle-registration-1"), after=MINUTE)
    unchecked = _record(store, _notice(), after=2 * MINUTE)

    assert (refused, accepted, unchecked) == (0, 1, 1)
    assert [request.requested_seq for request in _pending(store)] == [2]


@pytest.mark.parametrize(
    ("token", "handle"),
    [("token-\ud800", None), ("token-registration-1", "handle-\udfff")],
    ids=["token", "handle"],
)
def test_a_lone_surrogate_is_refused_as_any_wrong_token_is(
    store: Store, token: str, handle: str | None
) -> None:
    # JSON may escape a lone surrogate, which no encoding accepts: a known registration must
    # answer as an unknown one does, not fail.
    _seed(store, _registration())

    assert _record(store, _notice(token=token, handle=handle)) == 0

    assert _pending(store) == ()
    assert _registrations(store) == (_registration(),)


def test_a_notice_at_another_providers_address_is_refused(store: Store) -> None:
    _seed(store, _registration())

    assert _record(store, _notice(), provider=OUTLOOK) == 0

    assert _pending(store) == ()


def test_a_start_notice_confirms_a_registration_even_before_its_receipt(store: Store) -> None:
    # The provider confirmed the channel before it answered the request that created it.
    creating = _registration(RegistrationState.CREATING)
    _seed(store, creating)

    assert _record(store, _notice(NoticeKind.STARTED)) == 0
    assert _record(store, _notice(NoticeKind.STARTED), after=MINUTE) == 0
    with store.units(USER)() as uow:
        made_live = uow.watches.record_receipt(
            creating.id, RECEIPT, NOW + 5 * DAY, NOW + 2 * MINUTE
        )
        uow.commit()

    assert made_live
    assert _registrations(store) == (
        replace(
            creating,
            state=RegistrationState.LIVE,
            handle=RECEIPT.handle,
            expires_at=RECEIPT.expires_at,
            renew_at=NOW + 5 * DAY,
            confirmed_at=NOW,
        ),
    )


@pytest.mark.parametrize("kind", list(NoticeKind), ids=[kind.value for kind in NoticeKind])
def test_every_authentic_notice_confirms_its_registration_once(
    store: Store, kind: NoticeKind
) -> None:
    # Google's start notice may be lost, and Graph's creation may predate a fixed proxy; any
    # notice that arrives proves that the provider reaches the installation through it.
    _seed(store, _registration())

    _record(store, _notice(kind), after=MINUTE)
    _record(store, _notice(kind), after=2 * MINUTE)

    assert _registrations(store)[0].confirmed_at == NOW + MINUTE


def test_a_refused_notice_confirms_nothing(store: Store) -> None:
    _seed(store, _registration())

    _record(store, _notice(token="token-guessed"))

    assert _registrations(store)[0].confirmed_at is None


def test_a_change_requests_only_the_covered_enabled_rules_of_the_owner(store: Store) -> None:
    _seed(store, _registration(), rules=(RULE, UNCOVERED, PAUSED))
    _seed(
        store,
        _registration(name="their-registration", watch=THEIR_WATCH),
        user=OTHER_USER,
        watch=THEIR_WATCH,
        rules=(THEIRS,),
    )

    first = _record(store, _notice())
    missed = _record(store, _notice(NoticeKind.MISSED), after=MINUTE)
    waiting = _pending(store)
    with store.units(USER)() as uow:
        uow.instant_requests.acknowledge(RULE.id, 2, NOW + 2 * MINUTE)
        uow.commit()
    again = _record(store, _notice(), after=3 * MINUTE)

    assert (first, missed, again) == (1, 1, 1)
    assert waiting == (PendingRequest(RULE.id, 2, 0, NOW, NOW + MINUTE, None),)
    # Waiting starts again from the first notice after the run.
    assert _pending(store) == (
        PendingRequest(RULE.id, 3, 2, NOW + 3 * MINUTE, NOW + 3 * MINUTE, NOW + 2 * MINUTE),
    )
    # Another User's rule of a calendar with the same identifier is not this notice's to wake.
    assert _pending(store, OTHER_USER) == ()


def test_one_notice_repeated_in_a_batch_counts_once(store: Store) -> None:
    _seed(store, _registration())

    assert _record(store, _notice(), _notice()) == 1

    assert [request.requested_seq for request in _pending(store)] == [1]


def test_a_reauthorization_notice_asks_for_renewal_at_its_latest_time(store: Store) -> None:
    _seed(store, _registration())

    assert _record(store, _notice(NoticeKind.REAUTHORIZE), after=MINUTE) == 0
    assert _record(store, _notice(NoticeKind.REAUTHORIZE), after=2 * MINUTE) == 0

    assert _registrations(store)[0].renew_requested_at == NOW + 2 * MINUTE
    assert _pending(store) == ()


def test_an_extension_clears_the_renewal_request_it_read_and_keeps_a_later_one(
    store: Store,
) -> None:
    # Upkeep compares the request it read with the stored one, so both must be in one format.
    _seed(store, _registration())
    _record(store, _notice(NoticeKind.REAUTHORIZE), after=MINUTE)
    read = _registrations(store)[0].renew_requested_at
    _record(store, _notice(NoticeKind.REAUTHORIZE), after=2 * MINUTE)

    with store.units(USER)() as uow:
        kept_later = uow.watches.record_extension(
            WatchRegistrationId("registration-1"), NOW + 8 * DAY, NOW + 6 * DAY, read
        )
        uow.commit()

    assert kept_later
    assert _registrations(store)[0].renew_requested_at == NOW + 2 * MINUTE

    with store.units(USER)() as uow:
        uow.watches.record_extension(
            WatchRegistrationId("registration-1"),
            NOW + 8 * DAY,
            NOW + 6 * DAY,
            NOW + 2 * MINUTE,
        )
        uow.commit()

    assert _registrations(store)[0].renew_requested_at is None


def test_a_removal_notice_retires_the_registration_and_asks_for_a_catch_up_run(
    store: Store,
) -> None:
    _seed(store, _registration())

    assert _record(store, _notice(NoticeKind.REMOVED)) == 1

    assert _registrations(store)[0].state is RegistrationState.RETIRING
    assert [request.rule_id for request in _pending(store)] == [RULE.id]


def test_a_removal_before_the_receipt_abandons_the_registration_for_good(store: Store) -> None:
    # The provider removed the subscription before upkeep recorded its answer.
    creating = _registration(RegistrationState.CREATING)
    _seed(store, creating)

    assert _record(store, _notice(NoticeKind.REMOVED)) == 1
    with store.units(USER)() as uow:
        late = uow.watches.record_receipt(creating.id, RECEIPT, NOW + 5 * DAY, NOW + MINUTE)
        uow.commit()

    assert not late
    assert _registrations(store) == (
        replace(creating, state=RegistrationState.ABANDONED, confirmed_at=NOW),
    )
    # Its later notices are recognized and ignored.
    assert _record(store, _notice(), after=2 * MINUTE) == 0


def test_notices_committed_out_of_order_never_move_a_requests_times_back(store: Store) -> None:
    _seed(store, _registration())

    # Two requests' notices: the later one commits first.
    _record(store, _notice(), after=MINUTE)
    _record(store, _notice())

    assert _pending(store) == (PendingRequest(RULE.id, 2, 0, NOW, NOW + MINUTE, None),)


def test_success_evidence_is_refreshed_at_most_once_a_minute(store: Store) -> None:
    _seed(store, _registration())

    _record(store, _notice())
    _record(store, _notice(), after=30 * SECOND)
    throttled = store.evidence.evidence(BASE)
    _record(store, _notice(), after=61 * SECOND)
    refreshed = store.evidence.evidence(BASE)
    # A failure since the last success is answered by the next notice, however soon.
    store.evidence.failed(GOOGLE, BASE, NOW + 70 * SECOND)
    _record(store, _notice(), after=80 * SECOND)

    assert throttled == {GOOGLE: DeliveryEvidence(GOOGLE, BASE, last_success_at=NOW)}
    assert refreshed[GOOGLE].last_success_at == NOW + 61 * SECOND
    assert store.evidence.evidence(BASE) == {
        GOOGLE: DeliveryEvidence(
            GOOGLE,
            BASE,
            last_success_at=NOW + 80 * SECOND,
            last_failure_at=NOW + 70 * SECOND,
        )
    }


def test_a_notice_sent_to_an_earlier_address_proves_nothing_about_the_current_one(
    store: Store,
) -> None:
    _seed(store, _registration(base="https://old.example.test"))

    assert _record(store, _notice()) == 1

    assert store.evidence.evidence(BASE) == {}


def test_delivery_evidence_keeps_the_latest_success_and_failure_per_provider_and_address(
    store: Store,
) -> None:
    other = "https://other.example.test"
    store.evidence.succeeded(GOOGLE, BASE, NOW)
    store.evidence.failed(GOOGLE, BASE, NOW + HOUR)
    # An earlier time recorded later moves nothing back.
    store.evidence.succeeded(GOOGLE, BASE, NOW - HOUR)
    store.evidence.failed(GOOGLE, BASE, NOW)
    store.evidence.failed(OUTLOOK, other, NOW)

    assert store.evidence.evidence(BASE) == {
        GOOGLE: DeliveryEvidence(GOOGLE, BASE, last_success_at=NOW, last_failure_at=NOW + HOUR)
    }
    assert store.evidence.evidence(other) == {
        OUTLOOK: DeliveryEvidence(OUTLOOK, other, last_failure_at=NOW)
    }


def test_a_locked_store_answers_busy_and_records_nothing(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    for account in RULE_ACCOUNTS:
        add_account(database, account, USER)
    units = SqliteUnitOfWorkFactory(database).for_user(USER)
    with units() as uow:
        uow.rules.add(RULE)
        uow.watches.add(WATCH)
        uow.watches.add_registration(_registration())
        uow.commit()
    inbox = SqliteWatchNoticeInbox(database, lock_wait=0.05)

    with closing(open_connection(database)) as blocker:
        # Another writer holds the lock past the inbox's wait.
        blocker.execute("BEGIN IMMEDIATE")
        with pytest.raises(InboxBusy):
            inbox.record([_notice()], GOOGLE, BASE, NOW)
        blocker.rollback()

    with units() as uow:
        assert uow.instant_requests.pending() == ()


def test_the_in_memory_inbox_stands_for_a_locked_store_when_busy() -> None:
    inbox = InMemoryWatchNoticeInbox(MemoryDatabase(), busy=True)

    with pytest.raises(InboxBusy):
        inbox.record([_notice()], GOOGLE, BASE, NOW)
