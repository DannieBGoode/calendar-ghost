"""What the Web UI reads about Instant Sync: whether it is on for a User, and why each of their
rules syncs as it does (ADR 0036)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from calendar_sync.application.operations.instant_sync import InstantSyncStatus
from calendar_sync.application.sync.watch_ports import (
    EveryUserInstant,
    Receipt,
    SyncCadencePolicy,
    notice_address,
)
from calendar_sync.domain.access import Role, User, UserId, UserState
from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.cadence import SCHEDULED_EVERY, SyncCadence
from calendar_sync.domain.model import SyncRuleId
from calendar_sync.domain.watches import (
    Availability,
    CadenceReason,
    CalendarWatch,
    CalendarWatchId,
    DeliveryEvidence,
    RegistrationState,
    WatchRegistration,
    WatchRegistrationId,
    WatchScope,
    token_hash,
)
from calendar_sync.infrastructure.persistence.memory import (
    InMemoryUnitOfWorkFactory,
    InMemoryUserUnitOfWorkFactory,
)
from tests.fake_calendar import FixedClock
from tests.helpers import NOW, rule
from tests.identity_fakes import MemoryUsers
from tests.users import OTHER_USER, USER, memory_units

ADDRESS = "https://ghost.example.test"
WATCH = CalendarWatch(
    CalendarWatchId("watch-1"),
    rule().source.connected_account_id,
    WatchScope.calendar(rule().source.calendar_id),
)
REGISTRATION = WatchRegistrationId("0123456789abcdef0123456789abcdef")
FAILING = DeliveryEvidence(
    ProviderKind.GOOGLE,
    ADDRESS,
    last_success_at=NOW - timedelta(hours=2),
    last_failure_at=NOW - timedelta(hours=1),
)


class Evidence:
    """Delivery Evidence per provider and address; the status only reads it."""

    def __init__(self, *recorded: DeliveryEvidence) -> None:
        self.recorded = recorded

    def succeeded(self, provider: ProviderKind, address: str, at: datetime) -> None:
        raise AssertionError("the status records nothing")

    def failed(self, provider: ProviderKind, address: str, at: datetime) -> None:
        raise AssertionError("the status records nothing")

    def evidence(self, address: str) -> Mapping[ProviderKind, DeliveryEvidence]:
        return {item.provider: item for item in self.recorded if item.address == address}


class Plan:
    def __init__(self, *, instant: bool = True, poll_every: timedelta = SCHEDULED_EVERY) -> None:
        self.allowed = SyncCadence(instant=instant, poll_every=poll_every)

    def cadence(self, user: UserId) -> SyncCadence:
        return self.allowed


def _user(user_id: UserId = USER, *, wanted: bool = True) -> User:
    return User(
        user_id,
        f"{user_id.value}@example.test",
        Role.USER,
        UserState.ACTIVE,
        NOW,
        instant_sync=wanted,
    )


def _status(
    database: InMemoryUnitOfWorkFactory,
    *,
    users: tuple[User, ...] = (_user(),),
    address: str | None = ADDRESS,
    evidence: Evidence | None = None,
    plan: SyncCadencePolicy | None = None,
) -> InstantSyncStatus:
    directory = MemoryUsers()
    for user in users:
        directory.add(user, "hashed:synthetic")
    return InstantSyncStatus(
        users=directory,
        unit_of_work=database.for_user,
        cadence=plan or EveryUserInstant(),
        evidence=evidence or Evidence(),
        provider_of=lambda _account: ProviderKind.GOOGLE,
        address=address,
        clock=FixedClock(),
    )


def _with_rule(
    database: InMemoryUnitOfWorkFactory, user: UserId = USER, *, rule_id: str | None = None
) -> InMemoryUserUnitOfWorkFactory:
    """`user`'s units holding the sample rule; a rule's id is unique across Users, so a second
    User's copy takes `rule_id`."""
    units = memory_units(database, user=user)
    with units() as uow:
        uow.rules.add(rule() if rule_id is None else replace(rule(), id=SyncRuleId(rule_id)))
        uow.commit()
    return units


def _watched(units: InMemoryUserUnitOfWorkFactory, *, confirmed: bool) -> None:
    """The rule's source covered by a watch whose registration its provider created."""
    created = NOW - timedelta(minutes=5)
    with units() as uow:
        uow.watches.add(WATCH)
        uow.watches.set_coverage(WATCH.id, frozenset({rule().source.calendar_id}))
        uow.watches.add_registration(
            WatchRegistration(
                REGISTRATION,
                WATCH.id,
                RegistrationState.CREATING,
                notice_address(ADDRESS, "google", REGISTRATION),
                token_hash("synthetic-watch-token"),
                created,
                NOW + timedelta(days=7),
            )
        )
        uow.watches.record_receipt(
            REGISTRATION,
            Receipt("synthetic-handle", NOW + timedelta(days=7), confirmed=confirmed),
            NOW + timedelta(days=5),
            created,
        )
        uow.commit()


def test_instant_sync_is_on_for_a_user_who_wants_it_on_an_https_installation() -> None:
    database = InMemoryUnitOfWorkFactory()
    _watched(_with_rule(database), confirmed=True)

    status = _status(database)

    assert status.availability(USER) is Availability.ON
    assert status.cadences(USER) == {rule().id: CadenceReason.INSTANT}


OFF: dict[str, tuple[Callable[[InMemoryUnitOfWorkFactory], InstantSyncStatus], Availability]] = {
    "no public address": (
        lambda database: _status(database, address=None),
        Availability.NO_PUBLIC_ADDRESS,
    ),
    "not in plan": (
        lambda database: _status(database, plan=Plan(instant=False)),
        Availability.NOT_IN_PLAN,
    ),
    "turned off": (
        lambda database: _status(database, users=(_user(wanted=False),)),
        Availability.OFF_BY_USER,
    ),
    "deleted meanwhile": (lambda database: _status(database, users=()), Availability.OFF_BY_USER),
    "providers cannot reach it": (
        lambda database: _status(database, evidence=Evidence(FAILING)),
        Availability.NOT_REACHING,
    ),
}


@pytest.mark.parametrize(("make", "expected"), list(OFF.values()), ids=list(OFF))
def test_instant_sync_says_why_it_is_off_and_every_rule_says_the_same(
    make: Callable[[InMemoryUnitOfWorkFactory], InstantSyncStatus], expected: Availability
) -> None:
    database = InMemoryUnitOfWorkFactory()
    _watched(_with_rule(database), confirmed=True)

    status = make(database)

    assert status.availability(USER) is expected
    assert status.cadences(USER) == {rule().id: CadenceReason(expected.value)}


def test_failing_evidence_matters_only_for_providers_the_users_watches_use() -> None:
    database = InMemoryUnitOfWorkFactory()
    _with_rule(database)

    status = _status(database, evidence=Evidence(FAILING))

    assert status.availability(USER) is Availability.ON
    assert status.cadences(USER) == {rule().id: CadenceReason.NOT_WATCHABLE}


def test_evidence_for_another_address_is_not_this_installations() -> None:
    database = InMemoryUnitOfWorkFactory()
    _watched(_with_rule(database), confirmed=True)
    elsewhere = DeliveryEvidence(
        ProviderKind.GOOGLE,
        "https://old.example.test",
        last_success_at=None,
        last_failure_at=NOW,
    )

    assert _status(database, evidence=Evidence(elsewhere)).availability(USER) is Availability.ON


def test_a_registration_its_provider_has_not_confirmed_waits_for_the_provider() -> None:
    database = InMemoryUnitOfWorkFactory()
    _watched(_with_rule(database), confirmed=False)

    assert _status(database).cadences(USER) == {rule().id: CadenceReason.WAITING_FOR_PROVIDER}


def test_a_registration_for_an_earlier_address_never_makes_a_rule_instant() -> None:
    database = InMemoryUnitOfWorkFactory()
    _watched(_with_rule(database), confirmed=True)

    moved = _status(database, address="https://new.example.test")

    assert moved.availability(USER) is Availability.ON
    assert moved.cadences(USER) == {rule().id: CadenceReason.WAITING_FOR_PROVIDER}


def test_another_users_watch_never_makes_a_rule_instant() -> None:
    database = InMemoryUnitOfWorkFactory()
    _with_rule(database)
    _watched(_with_rule(database, OTHER_USER, rule_id="rule-2"), confirmed=True)

    status = _status(database, users=(_user(), _user(OTHER_USER)))

    assert status.cadences(USER) == {rule().id: CadenceReason.NOT_WATCHABLE}
    assert status.cadences(OTHER_USER) == {SyncRuleId("rule-2"): CadenceReason.INSTANT}


def test_rules_are_polled_as_often_as_the_plan_says() -> None:
    status = _status(InMemoryUnitOfWorkFactory(), plan=Plan(poll_every=timedelta(minutes=15)))

    assert status.poll_every(USER) == timedelta(minutes=15)
