"""Upkeep keeps one User's Calendar Watches as their enabled rules need (ADR 0036).

The fakes keep committed records apart from each unit's own writes, as a store does, and the
watcher fails a test that calls it while a unit of work is open: no provider call may happen
inside a write transaction. Each watcher method adds its cost to the measured tally, as an
adapter adds each HTTP call, and the budget is spent by what the tally grew.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from itertools import count
from types import TracebackType
from typing import Self

import pytest

from calendar_sync.application.sync.errors import ProviderFailure
from calendar_sync.application.sync.instant_sync import (
    CallBudget,
    FreshValues,
    UpkeepWatches,
    WatchProviders,
)
from calendar_sync.application.sync.ports import ProviderCallCounts, ProviderCallTally
from calendar_sync.application.sync.watch_ports import (
    Receipt,
    WatchFailure,
    WatchFailureKind,
    notice_address,
)
from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.model import (
    CalendarEndpoint,
    CalendarId,
    ConnectedAccountId,
    SyncRule,
    SyncRuleId,
    SyncRuleState,
)
from calendar_sync.domain.providers import ProviderFailureKind
from calendar_sync.domain.watches import (
    CONFIRMATION_DEADLINE,
    CREATION_DEADLINE,
    LONGEST_REGISTRATION,
    MAX_BACKOFF,
    CalendarWatch,
    CalendarWatchId,
    DeliveryEvidence,
    RegistrationState,
    WatchRegistration,
    WatchRegistrationId,
    WatchScope,
    renewal_time,
    token_hash,
)
from tests.helpers import NOW, endpoint

ADDRESS = "https://ghost.example.test"
MOVED = "https://moved.example.test"
PERSONAL = ConnectedAccountId("personal-account")
OTHER = ConnectedAccountId("other-account")
THIRD = ConnectedAccountId("third-account")
SOURCE = endpoint("personal-account", "personal-calendar")
SCOPE = WatchScope.calendar(CalendarId("personal-calendar"))
LIFETIME = timedelta(days=6)
JITTER = 0.5
EXPIRED = ProviderFailure(ProviderFailureKind.AUTHENTICATION, "expired", account_id=PERSONAL)


def source_rule(
    source: CalendarEndpoint = SOURCE,
    rule_id: str = "rule-1",
    state: SyncRuleState = SyncRuleState.ENABLED,
) -> SyncRule:
    return SyncRule(
        id=SyncRuleId(rule_id),
        source=source,
        destination=endpoint("work-account", "work-calendar"),
        state=state,
    )


@dataclass
class Records:
    watches: dict[CalendarWatchId, CalendarWatch] = field(default_factory=dict)
    registrations: dict[WatchRegistrationId, WatchRegistration] = field(default_factory=dict)

    def copy(self) -> Records:
        return Records(dict(self.watches), dict(self.registrations))


class Watches:
    """A CalendarWatchRepository over one unit's records, with the store's conditional writes."""

    def __init__(self, records: Records) -> None:
        self.records = records

    def list(self) -> Sequence[CalendarWatch]:
        return tuple(self.records.watches.values())

    def registrations(self) -> Sequence[WatchRegistration]:
        return tuple(self.records.registrations.values())

    def add(self, watch: CalendarWatch) -> None:
        self.records.watches[watch.id] = watch

    def set_coverage(self, watch_id: CalendarWatchId, coverage: frozenset[CalendarId]) -> None:
        watch = self.records.watches[watch_id]
        self.records.watches[watch_id] = replace(watch, coverage=coverage)

    def set_retry(
        self, watch_id: CalendarWatchId, retry_at: datetime | None, failures: int
    ) -> None:
        watch = self.records.watches[watch_id]
        self.records.watches[watch_id] = replace(watch, retry_at=retry_at, failures=failures)

    def remove(self, watch_id: CalendarWatchId) -> None:
        del self.records.watches[watch_id]
        for registration in self.registrations():
            if registration.watch_id == watch_id:
                del self.records.registrations[registration.id]

    def add_registration(self, registration: WatchRegistration) -> None:
        self.records.registrations[registration.id] = registration

    def record_receipt(
        self,
        registration_id: WatchRegistrationId,
        receipt: Receipt,
        renew_at: datetime,
        at: datetime,
    ) -> bool:
        current = self.records.registrations.get(registration_id)
        if current is None or current.state is not RegistrationState.CREATING:
            return False
        confirmed_at = current.confirmed_at or (at if receipt.confirmed else None)
        self.records.registrations[registration_id] = replace(
            current,
            state=RegistrationState.LIVE,
            handle=receipt.handle,
            expires_at=receipt.expires_at,
            confirmed_at=confirmed_at,
            renew_at=renew_at,
        )
        return True

    def record_extension(
        self,
        registration_id: WatchRegistrationId,
        expires_at: datetime,
        renew_at: datetime,
        seen_request: datetime | None,
    ) -> bool:
        current = self.records.registrations.get(registration_id)
        if current is None or current.state is not RegistrationState.LIVE:
            return False
        request = None if current.renew_requested_at == seen_request else current.renew_requested_at
        self.records.registrations[registration_id] = replace(
            current, expires_at=expires_at, renew_at=renew_at, renew_requested_at=request
        )
        return True

    def retire(self, registration_id: WatchRegistrationId) -> bool:
        return self._move(registration_id, RegistrationState.LIVE, RegistrationState.RETIRING)

    def abandon(self, registration_id: WatchRegistrationId) -> bool:
        return self._move(registration_id, None, RegistrationState.ABANDONED)

    def delete_registration(self, registration_id: WatchRegistrationId) -> None:
        self.records.registrations.pop(registration_id, None)

    def _move(
        self,
        registration_id: WatchRegistrationId,
        source: RegistrationState | None,
        target: RegistrationState,
    ) -> bool:
        current = self.records.registrations.get(registration_id)
        if current is None or source not in (None, current.state):
            return False
        self.records.registrations[registration_id] = replace(current, state=target)
        return True


@dataclass
class Rules:
    rules: list[SyncRule]

    def list(self) -> Sequence[SyncRule]:
        return tuple(self.rules)


@dataclass
class ProviderCalls:
    counted: list[tuple[date, ProviderKind, int]] = field(default_factory=list)

    def add(self, day: date, provider: ProviderKind, counts: ProviderCallCounts) -> None:
        self.counted.append((day, provider, counts.calls))


@dataclass
class Units:
    """One User's units of work: each works on a copy of the committed records."""

    rules: list[SyncRule] = field(default_factory=lambda: [source_rule()])
    committed: Records = field(default_factory=Records)
    provider_calls: ProviderCalls = field(default_factory=ProviderCalls)
    open: int = 0

    def __call__(self) -> Unit:
        return Unit(self)


class Unit:
    def __init__(self, units: Units) -> None:
        self._units = units
        self._records = units.committed.copy()
        self.watches = Watches(self._records)
        self.rules = Rules(units.rules)
        self.provider_calls = units.provider_calls

    def __enter__(self) -> Self:
        self._units.open += 1
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._units.open -= 1

    def commit(self) -> None:
        self._units.committed = self._records.copy()


@dataclass
class MovingClock:
    at: datetime = NOW

    def now(self) -> datetime:
        return self.at


Hook = Callable[[Records], None]


@dataclass
class FakeWatcher:
    """A provider that watches calendars; `during` hooks act while a call is in flight.

    Scoping is local, as Google's is, unless a test gives it a cost; every other call costs one.
    """

    units: Units
    clock: MovingClock
    costs: dict[str, int] = field(default_factory=lambda: {"scope": 0})
    tally: ProviderCallTally = field(default_factory=ProviderCallTally)
    scopes: dict[CalendarEndpoint, WatchScope | None] = field(default_factory=dict)
    refusals: dict[str, WatchFailure] = field(default_factory=dict)
    during: dict[str, Hook] = field(default_factory=dict)
    confirms: bool = False
    extends: bool = True
    """False for a provider that renews only by replacement."""
    adoptable: Receipt | None = None
    calls: list[tuple[str, str]] = field(default_factory=list)

    def scope(self, calendar: CalendarEndpoint) -> WatchScope | None:
        self._call("scope", calendar.calendar_id.value)
        return self.scopes.get(calendar, WatchScope.calendar(calendar.calendar_id))

    def register(
        self,
        account: ConnectedAccountId,
        scope: WatchScope,
        registration_id: WatchRegistrationId,
        token: str,
        address: str,
        until: datetime,
    ) -> Receipt:
        # Persisted and committed before the provider is asked, so no answer can be lost.
        persisted = self.units.committed.registrations[registration_id]
        assert persisted.state is RegistrationState.CREATING
        assert (persisted.token_hash, persisted.address) == (token_hash(token), address)
        assert until == persisted.requested_until
        self._call("register", registration_id.value)
        expires_at = self.clock.now() + LIFETIME
        return Receipt(f"handle-{registration_id.value}", expires_at, self.confirms)

    def extend(
        self, account: ConnectedAccountId, registration: WatchRegistration, until: datetime
    ) -> datetime | None:
        self._call("extend", registration.id.value)
        return self.clock.now() + LIFETIME if self.extends else None

    def adopt(
        self,
        account: ConnectedAccountId,
        scope: WatchScope,
        registration_id: WatchRegistrationId,
        address: str,
    ) -> Receipt | None:
        self._call("adopt", registration_id.value)
        return self.adoptable

    def stop(self, account: ConnectedAccountId, registration: WatchRegistration) -> None:
        self._call("stop", registration.id.value)

    def _call(self, operation: str, subject: str) -> None:
        assert self.units.open == 0, "a provider call inside a unit of work"
        self.calls.append((operation, subject))
        cost = self.costs.get(operation, 1)
        self.tally.calls += cost
        self.tally.providers.setdefault(ProviderKind.GOOGLE, ProviderCallCounts()).calls += cost
        if operation in self.during:
            self.during[operation](self.units.committed)
        if operation in self.refusals:
            raise self.refusals[operation]

    def operations(self) -> list[str]:
        return [operation for operation, _ in self.calls]


@dataclass
class CallStats:
    """Gives each run a fresh tally, which the watcher adds its calls to."""

    watcher: FakeWatcher | None = None

    def measure(self) -> AbstractContextManager[ProviderCallTally]:
        assert self.watcher is not None
        self.watcher.tally = ProviderCallTally()
        return nullcontext(self.watcher.tally)


@dataclass
class Evidence:
    successes: list[tuple[ProviderKind, str, datetime]] = field(default_factory=list)
    failures: list[tuple[ProviderKind, str, datetime]] = field(default_factory=list)

    def succeeded(self, provider: ProviderKind, address: str, at: datetime) -> None:
        self.successes.append((provider, address, at))

    def failed(self, provider: ProviderKind, address: str, at: datetime) -> None:
        self.failures.append((provider, address, at))

    def evidence(self, address: str) -> Mapping[ProviderKind, DeliveryEvidence]:
        return {}


@dataclass
class Lapses:
    recorded: list[tuple[ConnectedAccountId, ProviderFailure, datetime]] = field(
        default_factory=list
    )

    def lapsed(
        self, account_id: ConnectedAccountId, failure: ProviderFailure, *, attempted_at: datetime
    ) -> bool:
        self.recorded.append((account_id, failure, attempted_at))
        return True


@dataclass
class World:
    clock: MovingClock
    units: Units
    watcher: FakeWatcher
    evidence: Evidence
    lapses: Lapses
    upkeep: UpkeepWatches

    def run(
        self, *, allowed: bool = True, address: str | None = ADDRESS, budget: int = 100
    ) -> CallBudget:
        calls = CallBudget(budget)
        self.upkeep.execute(allowed=allowed, address=address, budget=calls)
        return calls

    def watches(self) -> list[CalendarWatch]:
        return list(self.units.committed.watches.values())

    def registrations(self) -> list[WatchRegistration]:
        return list(self.units.committed.registrations.values())

    def registration(self) -> WatchRegistration:
        (registration,) = self.registrations()
        return registration


def world(*rules: SyncRule) -> World:
    clock = MovingClock()
    units = Units(rules=list(rules or (source_rule(),)))
    watcher = FakeWatcher(units, clock)
    evidence, lapses = Evidence(), Lapses()
    call_stats = CallStats(watcher)
    ids = count(1)
    upkeep = UpkeepWatches(
        units,
        WatchProviders(
            watcher_for=lambda _account: watcher,
            provider_of=lambda _account: ProviderKind.GOOGLE,
            slug_of=lambda _provider: "example",
        ),
        evidence,
        clock,
        call_stats,
        lapses,
        FreshValues(
            new_token=lambda: f"token-{next(ids)}",
            new_id=lambda: f"{next(ids):032x}",
            jitter=lambda: JITTER,
        ),
    )
    return World(clock, units, watcher, evidence, lapses, upkeep)


def seeded(registration_state: RegistrationState, *, created_at: datetime = NOW) -> World:
    """A world whose watch already holds one registration in `registration_state`."""
    scenario = world()
    watch = CalendarWatch(
        CalendarWatchId("watch-1"), PERSONAL, SCOPE, frozenset({CalendarId("personal-calendar")})
    )
    registration_id = WatchRegistrationId("0" * 31 + "a")
    live = registration_state is not RegistrationState.CREATING
    registration = WatchRegistration(
        id=registration_id,
        watch_id=watch.id,
        state=registration_state,
        address=notice_address(ADDRESS, "example", registration_id),
        token_hash=token_hash("seeded-token"),
        created_at=created_at,
        requested_until=created_at + LONGEST_REGISTRATION,
        handle="seeded-handle" if live else None,
        expires_at=created_at + LIFETIME if live else None,
        confirmed_at=created_at if live else None,
        renew_at=renewal_time(created_at, created_at + LIFETIME, JITTER) if live else None,
    )
    scenario.units.committed = Records({watch.id: watch}, {registration.id: registration})
    return scenario


def refusal(kind: WatchFailureKind, retry_after_seconds: int | None = None) -> WatchFailure:
    return WatchFailure(kind, "refused", retry_after_seconds=retry_after_seconds)


def test_upkeep_registers_a_watch_for_an_enabled_rules_source_after_persisting_it() -> None:
    scenario = world()

    scenario.run()

    (watch,) = scenario.watches()
    assert (watch.account, watch.scope, watch.coverage) == (
        PERSONAL,
        SCOPE,
        frozenset({CalendarId("personal-calendar")}),
    )
    registration = scenario.registration()
    assert registration.state is RegistrationState.LIVE
    assert registration.address == notice_address(ADDRESS, "example", registration.id)
    assert registration.handle == f"handle-{registration.id.value}"
    assert registration.expires_at == NOW + LIFETIME
    assert registration.renew_at == renewal_time(NOW, NOW + LIFETIME, JITTER)
    assert registration.confirmed_at is None
    # Only the Source Calendar is watched.
    assert scenario.watcher.calls == [
        ("scope", "personal-calendar"),
        ("register", registration.id.value),
    ]


def test_a_second_run_with_everything_in_place_registers_nothing() -> None:
    scenario = world()
    scenario.run()

    scenario.run()

    # The covered source keeps its watch's scope, so the provider is not asked again.
    assert scenario.watcher.operations() == ["scope", "register"]


def test_one_account_scope_covers_every_watchable_calendar_and_skips_a_shared_one() -> None:
    other = endpoint("personal-account", "other-calendar")
    shared = endpoint("personal-account", "shared-calendar")
    scenario = world(source_rule(), source_rule(other, "rule-2"), source_rule(shared, "rule-3"))
    scenario.watcher.scopes = {
        SOURCE: WatchScope.account(),
        other: WatchScope.account(),
        shared: None,
    }

    scenario.run()

    (watch,) = scenario.watches()
    assert watch.scope == WatchScope.account()
    assert watch.coverage == {CalendarId("personal-calendar"), CalendarId("other-calendar")}
    assert scenario.watcher.operations().count("register") == 1


@pytest.mark.parametrize(
    ("allowed", "address", "state"),
    [
        (False, ADDRESS, SyncRuleState.ENABLED),
        (True, None, SyncRuleState.ENABLED),
        (True, ADDRESS, SyncRuleState.PAUSED),
    ],
)
def test_a_watch_no_rule_needs_is_stopped_and_removed(
    allowed: bool, address: str | None, state: SyncRuleState
) -> None:
    scenario = world()
    scenario.run()
    registration = scenario.registration()
    scenario.units.rules = [source_rule(state=state)]

    scenario.run(allowed=allowed, address=address)

    assert scenario.watcher.calls[-1] == ("stop", registration.id.value)
    assert scenario.watches() == []
    assert scenario.registrations() == []


def test_a_registration_whose_stop_fails_is_abandoned_until_it_expires() -> None:
    scenario = world()
    scenario.run()
    scenario.watcher.refusals["stop"] = refusal(WatchFailureKind.TEMPORARY)

    scenario.run(allowed=False)

    assert scenario.registration().state is RegistrationState.ABANDONED
    (watch,) = scenario.watches()
    assert watch.coverage == frozenset()
    scenario.clock.at = NOW + LIFETIME
    scenario.run(allowed=False)
    assert scenario.registrations() == []
    assert scenario.watches() == []


def test_a_changed_public_address_replaces_the_registration() -> None:
    scenario = world()
    scenario.run()
    old = scenario.registration()

    scenario.run(address=MOVED)

    new = scenario.registration()
    assert new.address == notice_address(MOVED, "example", new.id)
    assert ("stop", old.id.value) in scenario.watcher.calls


def test_a_lost_creation_is_abandoned_and_a_new_registration_made() -> None:
    scenario = seeded(RegistrationState.CREATING, created_at=NOW - CREATION_DEADLINE)

    scenario.run()

    states = sorted(registration.state for registration in scenario.registrations())
    assert states == [RegistrationState.ABANDONED, RegistrationState.LIVE]


def test_a_creation_still_in_progress_is_left_alone() -> None:
    scenario = seeded(RegistrationState.CREATING, created_at=NOW - timedelta(minutes=1))

    scenario.run()

    assert scenario.registration().state is RegistrationState.CREATING
    assert "register" not in scenario.watcher.operations()


def test_a_late_receipt_for_a_registration_abandoned_meanwhile_changes_nothing() -> None:
    def abandon_creations(records: Records) -> None:
        for registration in list(records.registrations.values()):
            abandoned = replace(registration, state=RegistrationState.ABANDONED)
            records.registrations[registration.id] = abandoned

    scenario = world()
    scenario.watcher.during["register"] = abandon_creations

    scenario.run()

    registration = scenario.registration()
    assert (registration.state, registration.handle) == (RegistrationState.ABANDONED, None)


def test_a_late_receipt_for_a_registration_deleted_meanwhile_brings_nothing_back() -> None:
    scenario = world()
    scenario.watcher.during["register"] = lambda records: records.registrations.clear()

    scenario.run()

    assert scenario.registrations() == []


def test_a_start_notice_that_arrives_before_register_returns_is_kept() -> None:
    def confirm(records: Records) -> None:
        for registration in list(records.registrations.values()):
            records.registrations[registration.id] = replace(registration, confirmed_at=NOW)

    scenario = world()
    scenario.watcher.during["register"] = confirm

    scenario.run()

    assert scenario.registration().confirmed_at == NOW


def test_a_receipt_that_proves_delivery_confirms_and_records_success() -> None:
    scenario = world()
    scenario.watcher.confirms = True

    scenario.run()

    assert scenario.registration().confirmed_at == NOW
    assert scenario.evidence.successes == [(ProviderKind.GOOGLE, ADDRESS, NOW)]


def test_an_unconfirmed_registration_records_the_same_failure_at_its_deadline() -> None:
    scenario = world()
    scenario.run()

    scenario.clock.at = NOW + CONFIRMATION_DEADLINE
    scenario.run()
    scenario.clock.at = NOW + timedelta(minutes=7)
    scenario.run()

    deadline = (ProviderKind.GOOGLE, ADDRESS, NOW + CONFIRMATION_DEADLINE)
    assert scenario.evidence.failures == [deadline, deadline]


def test_a_duplicate_adopts_the_providers_registration_that_names_this_id() -> None:
    scenario = world()
    scenario.watcher.refusals["register"] = refusal(WatchFailureKind.DUPLICATE)
    scenario.watcher.adoptable = Receipt("adopted-handle", NOW + LIFETIME, confirmed=True)

    scenario.run()

    registration = scenario.registration()
    assert (registration.state, registration.handle) == (RegistrationState.LIVE, "adopted-handle")
    assert ("adopt", registration.id.value) in scenario.watcher.calls


def test_a_duplicate_held_by_another_registration_is_never_touched_and_waits_a_day() -> None:
    scenario = world()
    scenario.watcher.refusals["register"] = refusal(WatchFailureKind.DUPLICATE)

    scenario.run()

    assert scenario.registrations() == []
    (watch,) = scenario.watches()
    assert (watch.retry_at, watch.failures) == (NOW + MAX_BACKOFF, 1)
    assert scenario.watcher.operations() == ["scope", "register", "adopt"]
    scenario.clock.at = NOW + timedelta(hours=1)
    scenario.run()
    assert "stop" not in scenario.watcher.operations()
    assert scenario.watcher.operations().count("register") == 1


def test_a_registration_due_for_renewal_is_extended_in_place() -> None:
    scenario = seeded(RegistrationState.LIVE)
    due = scenario.registration().renew_at
    assert due is not None
    scenario.clock.at = due

    scenario.run()

    registration = scenario.registration()
    assert registration.expires_at == due + LIFETIME
    assert registration.renew_at == renewal_time(due, due + LIFETIME, JITTER)
    assert scenario.watcher.operations() == ["extend"]


def test_an_early_renewal_request_is_cleared_once_honored() -> None:
    scenario = seeded(RegistrationState.LIVE)
    registration = scenario.registration()
    scenario.units.committed.registrations[registration.id] = replace(
        registration, renew_requested_at=NOW
    )

    scenario.run()

    assert scenario.registration().renew_requested_at is None


def test_an_early_renewal_request_that_arrives_during_renewal_is_not_lost() -> None:
    later = NOW + timedelta(seconds=30)

    def request_again(records: Records) -> None:
        for registration in list(records.registrations.values()):
            records.registrations[registration.id] = replace(registration, renew_requested_at=later)

    scenario = seeded(RegistrationState.LIVE)
    registration = scenario.registration()
    scenario.units.committed.registrations[registration.id] = replace(
        registration, renew_requested_at=NOW
    )
    scenario.watcher.during["extend"] = request_again

    scenario.run()

    assert scenario.registration().renew_requested_at == later


def test_a_replacement_is_recorded_before_the_registration_it_replaces_is_stopped() -> None:
    scenario = seeded(RegistrationState.LIVE)
    old = scenario.registration()
    assert old.renew_at is not None
    scenario.clock.at = old.renew_at
    scenario.watcher.extends = False
    seen: dict[str, RegistrationState] = {}

    def at_register(records: Records) -> None:
        seen["register"] = records.registrations[old.id].state

    def at_stop(records: Records) -> None:
        seen["stop"] = records.registrations[old.id].state

    scenario.watcher.during = {"register": at_register, "stop": at_stop}

    scenario.run()

    # Notices on both count until the old one is stopped.
    assert seen == {"register": RegistrationState.LIVE, "stop": RegistrationState.RETIRING}
    new = scenario.registration()
    assert new.id != old.id
    assert new.state is RegistrationState.LIVE
    assert scenario.watcher.operations() == ["extend", "register", "stop"]


def test_a_replaced_registration_whose_stop_fails_is_abandoned() -> None:
    scenario = seeded(RegistrationState.LIVE)
    old = scenario.registration()
    assert old.renew_at is not None
    scenario.clock.at = old.renew_at
    scenario.watcher.extends = False
    scenario.watcher.refusals["stop"] = refusal(WatchFailureKind.TEMPORARY)

    scenario.run()

    states = {registration.id: registration.state for registration in scenario.registrations()}
    assert states.pop(old.id) is RegistrationState.ABANDONED
    assert list(states.values()) == [RegistrationState.LIVE]


def test_a_refusal_of_credentials_lapses_the_account_as_of_the_calls_start() -> None:
    scenario = world()
    scenario.watcher.refusals["register"] = WatchFailure(
        WatchFailureKind.UNAUTHORIZED, "refused", failure=EXPIRED
    )

    def slow(records: Records) -> None:
        scenario.clock.at = NOW + timedelta(seconds=5)

    scenario.watcher.during["register"] = slow

    scenario.run()

    assert scenario.lapses.recorded == [(PERSONAL, EXPIRED, NOW)]
    assert scenario.registrations() == []
    (watch,) = scenario.watches()
    assert (watch.retry_at, watch.failures) == (None, 0)


def test_a_provider_that_cannot_watch_a_calendar_backs_off_and_never_lapses_the_account() -> None:
    scenario = world()
    scenario.watcher.refusals["register"] = refusal(WatchFailureKind.UNSUPPORTED)

    scenario.run()
    (watch,) = scenario.watches()
    assert (watch.retry_at, watch.failures) == (NOW + timedelta(minutes=1), 1)
    scenario.run()
    assert scenario.watcher.operations().count("register") == 1
    scenario.clock.at = NOW + timedelta(minutes=1)
    scenario.run()

    (watch,) = scenario.watches()
    assert (watch.retry_at, watch.failures) == (NOW + timedelta(minutes=3), 2)
    assert scenario.lapses.recorded == []
    assert scenario.registrations() == []


def test_a_rate_limit_waits_at_least_as_long_as_the_provider_asks() -> None:
    scenario = world()
    scenario.watcher.refusals["register"] = refusal(WatchFailureKind.RATE_LIMITED, 600)

    scenario.run()

    (watch,) = scenario.watches()
    assert watch.retry_at == NOW + timedelta(minutes=10)


def test_an_unreachable_address_records_failing_delivery() -> None:
    scenario = world()
    scenario.watcher.refusals["register"] = refusal(WatchFailureKind.UNREACHABLE)

    scenario.run()

    assert scenario.evidence.failures == [(ProviderKind.GOOGLE, ADDRESS, NOW)]
    (watch,) = scenario.watches()
    assert watch.failures == 1


def test_a_temporary_failure_keeps_a_registration_the_provider_may_have_made() -> None:
    scenario = world()
    scenario.watcher.refusals["register"] = refusal(WatchFailureKind.TEMPORARY)

    scenario.run()

    assert scenario.registration().state is RegistrationState.ABANDONED


def test_a_success_after_failures_clears_the_backoff() -> None:
    scenario = world()
    scenario.watcher.refusals["register"] = refusal(WatchFailureKind.UNSUPPORTED)
    scenario.run()
    del scenario.watcher.refusals["register"]
    scenario.clock.at = NOW + timedelta(minutes=1)

    scenario.run()

    (watch,) = scenario.watches()
    assert (watch.retry_at, watch.failures) == (None, 0)
    assert scenario.registration().state is RegistrationState.LIVE


def test_an_account_whose_scope_is_refused_keeps_its_watches_and_lapses() -> None:
    scenario = seeded(RegistrationState.LIVE)
    # The seeded watch's rule is gone; the new rule's source has no watch yet.
    scenario.units.rules = [source_rule(endpoint("personal-account", "other-calendar"))]
    scenario.watcher.refusals["scope"] = WatchFailure(
        WatchFailureKind.UNAUTHORIZED, "refused", failure=EXPIRED
    )

    scenario.run()

    assert scenario.lapses.recorded == [(PERSONAL, EXPIRED, NOW)]
    assert scenario.registration().state is RegistrationState.LIVE
    (watch,) = scenario.watches()
    assert watch.coverage == {CalendarId("personal-calendar")}
    assert scenario.watcher.operations() == ["scope"]


def test_an_account_whose_sources_are_not_all_scoped_keeps_its_watches() -> None:
    scenario = seeded(RegistrationState.LIVE)
    scenario.units.rules = [source_rule(endpoint("personal-account", "other-calendar"))]
    scenario.watcher.costs["scope"] = 1
    before = scenario.units.committed.copy()

    scenario.run(budget=0)

    assert scenario.watcher.calls == []
    assert scenario.units.committed == before
    scenario.run(budget=10)
    (watch,) = scenario.watches()
    assert watch.coverage == {CalendarId("other-calendar")}
    assert scenario.watcher.operations() == ["scope", "stop", "register"]


def test_a_large_user_makes_progress_across_cycles_when_scoping_is_free() -> None:
    sources = [endpoint("personal-account", f"calendar-{n}") for n in range(250)]
    scenario = world(*(source_rule(source, f"rule-{n}") for n, source in enumerate(sources)))

    first = scenario.run(budget=200)

    assert len(scenario.watches()) == 250
    assert len(scenario.registrations()) == 200
    assert first.exhausted
    scenario.run(budget=200)
    assert len(scenario.registrations()) == 250
    assert all(each.state is RegistrationState.LIVE for each in scenario.registrations())
    assert scenario.watcher.operations().count("scope") == 250


def test_scoping_that_costs_calls_is_kept_as_found_and_never_asked_again() -> None:
    sources = [endpoint("personal-account", f"calendar-{n}") for n in range(250)]
    scenario = world(*(source_rule(source, f"rule-{n}") for n, source in enumerate(sources)))
    scenario.watcher.costs["scope"] = 1

    scenario.run(budget=200)
    assert (len(scenario.watches()), len(scenario.registrations())) == (200, 0)
    scenario.run(budget=200)
    assert (len(scenario.watches()), len(scenario.registrations())) == (250, 150)
    scenario.run(budget=200)

    assert len(scenario.registrations()) == 250
    assert scenario.watcher.operations().count("scope") == 250


def test_a_calendar_that_cannot_be_watched_is_not_asked_again_for_a_day() -> None:
    shared = [endpoint("personal-account", f"shared-{n}") for n in range(250)]
    rules = [source_rule(source, f"rule-{n}") for n, source in enumerate(shared)]
    scenario = world(*rules, source_rule(SOURCE, "watchable"))
    scenario.watcher.costs["scope"] = 1
    scenario.watcher.scopes = dict.fromkeys(shared)

    scenario.run(budget=200)
    scenario.run(budget=200)

    assert scenario.registration().state is RegistrationState.LIVE
    asked = [subject for operation, subject in scenario.watcher.calls if operation == "scope"]
    assert len(asked) == len(set(asked)) == 251
    scenario.clock.at = NOW + timedelta(hours=23)
    scenario.run(budget=200)
    assert scenario.watcher.operations().count("scope") == 251
    scenario.clock.at = NOW + timedelta(days=1)
    scenario.run(budget=500)
    assert scenario.watcher.operations().count("scope") == 501


def test_upkeep_counts_its_measured_calls_for_the_user() -> None:
    scenario = world()

    budget = scenario.run(budget=5)

    assert budget.remaining == 4
    assert scenario.units.provider_calls.counted == [(NOW.date(), ProviderKind.GOOGLE, 1)]


def test_a_creation_the_budget_cannot_pay_for_persists_nothing() -> None:
    scenario = world()

    scenario.run(budget=0)

    assert scenario.watches() == []
    assert scenario.registrations() == []
    scenario.run(budget=1)
    assert scenario.registration().state is RegistrationState.LIVE


def test_a_spent_budget_may_go_below_zero_and_stays_exhausted() -> None:
    budget = CallBudget(2)

    budget.spend(1)
    assert not budget.exhausted
    budget.spend(3)

    assert (budget.remaining, budget.exhausted) == (-2, True)


def test_a_replaced_registration_the_budget_could_not_stop_is_stopped_next_cycle() -> None:
    scenario = seeded(RegistrationState.LIVE)
    old = scenario.registration()
    assert old.renew_at is not None
    scenario.clock.at = old.renew_at
    scenario.watcher.extends = False

    scenario.run(budget=2)

    states = {registration.id: registration.state for registration in scenario.registrations()}
    assert states.pop(old.id) is RegistrationState.RETIRING
    assert list(states.values()) == [RegistrationState.LIVE]
    scenario.run(budget=10)
    assert scenario.registration().id != old.id
    assert scenario.watcher.calls[-1] == ("stop", old.id.value)


def test_a_refused_scope_backs_off_as_long_as_the_provider_asks() -> None:
    scenario = world()
    scenario.watcher.refusals["scope"] = refusal(WatchFailureKind.RATE_LIMITED, 600)

    scenario.run()
    scenario.clock.at = NOW + timedelta(minutes=5)
    scenario.run()
    assert scenario.watcher.operations() == ["scope"]
    del scenario.watcher.refusals["scope"]
    scenario.clock.at = NOW + timedelta(minutes=10)
    scenario.run()

    assert scenario.watcher.operations() == ["scope", "scope", "register"]
    assert scenario.lapses.recorded == []


def test_a_scope_the_provider_cannot_give_backs_off_from_a_minute() -> None:
    scenario = world()
    scenario.watcher.refusals["scope"] = refusal(WatchFailureKind.UNSUPPORTED)

    scenario.run()
    scenario.clock.at = NOW + timedelta(seconds=59)
    scenario.run()
    scenario.clock.at = NOW + timedelta(minutes=1)
    scenario.run()

    assert scenario.watcher.operations() == ["scope", "scope"]


def test_stopping_one_accounts_watches_leaves_the_others() -> None:
    scenario = world(source_rule(), source_rule(endpoint("other-account", "other-calendar"), "r2"))
    scenario.run()
    scenario.watcher.refusals["stop"] = refusal(WatchFailureKind.TEMPORARY)

    scenario.upkeep.stop_all(PERSONAL)

    (watch,) = scenario.watches()
    assert watch.account == OTHER
    assert scenario.watcher.operations().count("stop") == 1
    scenario.upkeep.stop_all()
    assert scenario.watches() == []
    assert scenario.registrations() == []


def test_stopping_everything_gives_up_on_stops_at_the_deadline_and_removes_every_row() -> None:
    accounts = ("personal-account", "other-account", "third-account")
    scenario = world(*(source_rule(endpoint(account, "calendar"), account) for account in accounts))
    scenario.run()

    def slow(records: Records) -> None:
        scenario.clock.at += timedelta(seconds=6)

    scenario.watcher.during["stop"] = slow

    scenario.upkeep.stop_all(deadline=timedelta(seconds=10))

    assert scenario.watcher.operations().count("stop") == 2
    assert scenario.watches() == []
    assert scenario.registrations() == []
