"""Upkeep of one User's Calendar Watches, so their providers report changes (ADR 0036).

Upkeep makes the registrations providers hold match what the User's enabled rules need. A
registration is persisted before its provider is asked for it, and no provider call happens
inside a write transaction, so a crash or a lost answer leaves a row upkeep recognizes, never
one it does not know. Each state change is a conditional write, so a late writer changes nothing.

Every provider call spends the cycle's budget by what it measured, so a scope its adapter knows
without asking costs nothing, and a listing that pages costs each page. Progress is persisted as
it is made, so a cycle the budget ends early resumes where it stopped.
"""

from __future__ import annotations

import random
import secrets
from collections.abc import Callable, Iterable, Sequence
from contextlib import suppress
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Protocol
from uuid import uuid4

from calendar_sync.application.shared.ports import Clock
from calendar_sync.application.sync.errors import ProviderFailure
from calendar_sync.application.sync.ports import ProviderCallStats, ProviderCallTally
from calendar_sync.application.sync.resource_use import (
    CallCountingUnitOfWork,
    record_provider_calls,
)
from calendar_sync.application.sync.watch_ports import (
    CalendarWatcher,
    CalendarWatchRepository,
    DeliveryEvidenceLog,
    Receipt,
    WatcherFor,
    WatchFailure,
    WatchFailureKind,
    notice_address,
)
from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.model import CalendarEndpoint, CalendarId, ConnectedAccountId, SyncRule
from calendar_sync.domain.watches import (
    CONFIRMATION_DEADLINE,
    LONGEST_REGISTRATION,
    MAX_BACKOFF,
    CalendarWatch,
    CalendarWatchId,
    RegistrationState,
    WatchRegistration,
    WatchRegistrationId,
    WatchScope,
    backoff,
    renewal_time,
    token_hash,
)

STOP_DEADLINE = timedelta(seconds=10)
"""How long User Deletion and account disconnection wait on stopping registrations."""
UNWATCHABLE_RECHECK = timedelta(days=1)
"""How long a Source Calendar its provider cannot watch goes without being asked again."""


class RuleListing(Protocol):
    def list(self) -> Sequence[SyncRule]: ...


class WatchUnitOfWork(CallCountingUnitOfWork, Protocol):
    """The part of one User's unit of work upkeep uses: their watches, their rules to read, and
    their provider call counts."""

    @property
    def watches(self) -> CalendarWatchRepository: ...

    @property
    def rules(self) -> RuleListing: ...


class WatchUnitOfWorkFactory(Protocol):
    """Opens units of work for the one User whose watches upkeep keeps (ADR 0029)."""

    def __call__(self) -> WatchUnitOfWork: ...


class AccountLapses(Protocol):
    """Records Lapsed Authorization, as `LapsedAuthorizations` does (ADR 0027)."""

    def lapsed(
        self, account_id: ConnectedAccountId, failure: ProviderFailure, *, attempted_at: datetime
    ) -> bool: ...


@dataclass(slots=True)
class CallBudget:
    """How many provider calls an upkeep cycle may still make, across every User it keeps."""

    remaining: int

    def spend(self, calls: int) -> None:
        """Take the calls one provider method made; the last one may take it below zero."""
        self.remaining -= calls

    @property
    def exhausted(self) -> bool:
        return self.remaining <= 0


@dataclass(slots=True)
class AccountBackoff:
    """When upkeep may ask a provider again what it can watch: an account after failures, and a
    calendar it cannot watch after a day.

    Kept in the process only: after a restart, everything is asked again at once. Each account
    belongs to one User, whose upkeep runs one at a time, so no two threads change one entry.
    """

    waits: dict[ConnectedAccountId, tuple[datetime, int]] = field(default_factory=dict, init=False)
    unwatchable: dict[CalendarEndpoint, datetime] = field(default_factory=dict, init=False)
    """Until when each calendar found unwatchable goes without being asked again."""

    def waiting(self, account: ConnectedAccountId, now: datetime) -> bool:
        wait = self.waits.get(account)
        return wait is not None and wait[0] > now

    def failed(
        self, account: ConnectedAccountId, at: datetime, retry_after: timedelta | None
    ) -> None:
        failures = self.waits.get(account, (at, 0))[1] + 1
        self.waits[account] = (at + backoff(failures, retry_after), failures)

    def succeeded(self, account: ConnectedAccountId) -> None:
        self.waits.pop(account, None)

    def known_unwatchable(self, calendar: CalendarEndpoint, now: datetime) -> bool:
        until = self.unwatchable.get(calendar)
        return until is not None and until > now

    def cannot_watch(self, calendar: CalendarEndpoint, at: datetime) -> None:
        self.unwatchable[calendar] = at + UNWATCHABLE_RECHECK


@dataclass(frozen=True, slots=True)
class WatchProviders:
    """How upkeep reaches the provider of each Connected Account."""

    watcher_for: WatcherFor
    provider_of: Callable[[ConnectedAccountId], ProviderKind | None]
    slug_of: Callable[[ProviderKind], str]
    """The provider's slug in notice addresses, from its descriptor."""
    backoff: AccountBackoff = field(default_factory=AccountBackoff)
    """Shared by every User's upkeep, so bootstrap passes one instance to all of them."""


def _new_token() -> str:
    return secrets.token_urlsafe(32)


def _new_id() -> str:
    return uuid4().hex


@dataclass(frozen=True, slots=True)
class FreshValues:
    """Where upkeep takes new secrets, identifiers, and renewal jitter."""

    new_token: Callable[[], str] = _new_token
    """A registration's secret token: 32 random bytes."""
    new_id: Callable[[], str] = _new_id
    """A watch's or registration's identifier: 32 lowercase hex characters."""
    jitter: Callable[[], float] = random.random
    """Where in its window a registration is renewed, in [0, 1); not a secret."""


@dataclass(slots=True)
class UpkeepWatches:
    """Keeps one User's Calendar Watches and their registrations as their enabled rules need."""

    unit_of_work: WatchUnitOfWorkFactory
    providers: WatchProviders
    evidence: DeliveryEvidenceLog
    clock: Clock
    call_stats: ProviderCallStats
    """Measures the provider calls upkeep makes, which spend the budget and count for the User."""
    lapses: AccountLapses | None = None
    fresh: FreshValues = field(default_factory=FreshValues)

    def execute(self, *, allowed: bool, address: str | None, budget: CallBudget) -> None:
        """Reconcile the User's watches with what their enabled rules need.

        Nothing is desired unless Instant Sync is `allowed` for the User and the installation has
        a public `address`. No provider call starts once the budget is exhausted; what it could
        not pay for waits for the next cycle, and an account whose sources were not all scoped
        keeps every watch it has.
        """
        with self.call_stats.measure() as calls:
            try:
                cycle = _Cycle(self, address, _Meter(budget, calls), self.clock.now())
                cycle.run(allowed)
            finally:
                record_provider_calls(self.unit_of_work, self.clock, calls)

    def stop_all(
        self, account: ConnectedAccountId | None = None, deadline: timedelta = STOP_DEADLINE
    ) -> None:
        """Stop the registrations of every watch, or of one account's, then remove the watches.

        Best effort, for User Deletion and account disconnection: no stop starts after
        `deadline`, and a registration left running, or whose stop failed, expires with its
        provider, its notices then finding no registration.
        """
        with self.call_stats.measure() as calls:
            try:
                self._stop_all(account, self.clock.now() + deadline)
            finally:
                record_provider_calls(self.unit_of_work, self.clock, calls)

    def _stop_all(self, account: ConnectedAccountId | None, until: datetime) -> None:
        now = self.clock.now()
        with self.unit_of_work() as uow:
            watches = tuple(
                watch for watch in uow.watches.list() if account is None or watch.account == account
            )
            registrations = tuple(uow.watches.registrations())
        running = [
            (watch, registration)
            for watch in watches
            for registration in registrations
            if registration.watch_id == watch.id
            and registration.handle is not None
            and not registration.gone(now)
        ]
        for watch, registration in running:
            if self.clock.now() >= until:
                break
            watcher = self.providers.watcher_for(watch.account)
            if watcher is not None:
                with suppress(WatchFailure):
                    watcher.stop(watch.account, registration)
        with self.unit_of_work() as uow:
            for watch in watches:
                uow.watches.remove(watch.id)
            uow.commit()


def _sources(rules: Sequence[SyncRule]) -> tuple[CalendarEndpoint, ...]:
    """The Source Calendars of enabled rules, each once: only sources are watched."""
    return tuple(dict.fromkeys(rule.source for rule in rules if rule.synchronizes))


def _retry_after(failure: WatchFailure) -> timedelta | None:
    seconds = failure.retry_after_seconds
    return None if seconds is None else timedelta(seconds=seconds)


def _lapse(
    lapses: AccountLapses | None,
    account: ConnectedAccountId,
    failure: WatchFailure,
    attempted_at: datetime,
) -> bool:
    """Lapse the account for a refusal of its credentials; whether the failure was one.

    The call's start decides, so a refusal of credentials since replaced lapses nothing.
    """
    if failure.kind is not WatchFailureKind.UNAUTHORIZED:
        return False
    if lapses is None or failure.failure is None:
        return False
    lapses.lapsed(account, failure.failure, attempted_at=attempted_at)
    return True


@dataclass(slots=True)
class _Meter:
    """The cycle's budget, spent by the provider calls each watcher method measured."""

    budget: CallBudget
    tally: ProviderCallTally

    @property
    def exhausted(self) -> bool:
        return self.budget.exhausted

    def paid[T](self, call: Callable[[], T]) -> T:
        before = self.tally.calls
        try:
            return call()
        finally:
            self.budget.spend(self.tally.calls - before)


@dataclass(frozen=True, slots=True)
class _Target:
    """A watch to keep, with its provider's watcher and the installation's public address."""

    watch: CalendarWatch
    watcher: CalendarWatcher
    provider: ProviderKind
    slug: str
    address: str

    def notice_address(self, registration_id: WatchRegistrationId) -> str:
        return notice_address(self.address, self.slug, registration_id)

    def current(
        self, registrations: Sequence[WatchRegistration], now: datetime
    ) -> WatchRegistration | None:
        """The live registration that points at the installation's address now."""
        return next(
            (each for each in registrations if each.usable(now, self.notice_address(each.id))),
            None,
        )


@dataclass(slots=True)
class _Cycle:
    """One upkeep run for one User: its time, public address, and metered call budget."""

    upkeep: UpkeepWatches
    address: str | None
    meter: _Meter
    now: datetime

    def run(self, allowed: bool) -> None:
        with self.upkeep.unit_of_work() as uow:
            rules = tuple(uow.rules.list())
            _tidy_registrations(uow.watches, self.now)
            watches = tuple(uow.watches.list())
            uow.commit()
        sources = _sources(rules) if allowed and self.address is not None else ()
        unsure = self._discover(sources, watches)
        with self.upkeep.unit_of_work() as uow:
            _narrow_coverage(uow.watches, sources, unsure)
            watches = tuple(uow.watches.list())
            registrations = tuple(uow.watches.registrations())
            uow.commit()
        for watch in watches:
            owned = tuple(each for each in registrations if each.watch_id == watch.id)
            if watch.coverage:
                self._keep(watch, owned)
            elif watch.account not in unsure:
                self._retire(watch, owned)

    def _discover(
        self, sources: Sequence[CalendarEndpoint], watches: Iterable[CalendarWatch]
    ) -> frozenset[ConnectedAccountId]:
        """Scope each source no watch covers yet, keeping each one as it is found; the accounts
        whose sources were not all scoped.

        A covered source keeps its watch's scope without asking its provider again.
        """
        known = {(watch.account, watch.scope): watch for watch in watches}
        unsure: set[ConnectedAccountId] = set()
        for source in sources:
            account = source.connected_account_id
            if account in unsure or any(watch.covers(source) for watch in known.values()):
                continue
            scoped, scope = self._scope(source)
            if not scoped:
                unsure.add(account)
            elif scope is not None:
                self._cover(known, account, scope, source.calendar_id)
        return frozenset(unsure)

    def _scope(self, source: CalendarEndpoint) -> tuple[bool, WatchScope | None]:
        """Whether the source's provider said what watches it, and what does: None when nothing
        can, such as for a calendar shared from another mailbox."""
        account = source.connected_account_id
        providers = self.upkeep.providers
        watcher = providers.watcher_for(account)
        if watcher is None or providers.backoff.known_unwatchable(source, self.now):
            return True, None
        if self.meter.exhausted or providers.backoff.waiting(account, self.now):
            return False, None
        attempted_at = self.upkeep.clock.now()
        try:
            scope = self.meter.paid(lambda: watcher.scope(source))
        except WatchFailure as failure:
            if not _lapse(self.upkeep.lapses, account, failure, attempted_at):
                providers.backoff.failed(account, self.upkeep.clock.now(), _retry_after(failure))
            return False, None
        providers.backoff.succeeded(account)
        if scope is None:
            # Asked again only after a day, so such calendars never spend every cycle's budget.
            providers.backoff.cannot_watch(source, self.now)
        return True, scope

    def _cover(
        self,
        known: dict[tuple[ConnectedAccountId, WatchScope], CalendarWatch],
        account: ConnectedAccountId,
        scope: WatchScope,
        calendar: CalendarId,
    ) -> None:
        """Keep a calendar in the coverage of its watch at once, adding the watch if needed."""
        found = known.get((account, scope))
        with self.upkeep.unit_of_work() as uow:
            if found is None:
                watch_id = CalendarWatchId(self.upkeep.fresh.new_id())
                found = CalendarWatch(watch_id, account, scope, frozenset({calendar}))
                uow.watches.add(found)
            else:
                found = replace(found, coverage=found.coverage | {calendar})
                uow.watches.set_coverage(found.id, found.coverage)
            uow.commit()
        known[(account, scope)] = found

    def _keep(self, watch: CalendarWatch, owned: Sequence[WatchRegistration]) -> None:
        target = self._target(watch)
        if target is None:
            return
        current = target.current(owned, self.now)
        for registration in owned:
            if registration.state is RegistrationState.RETIRING or (
                registration.state is RegistrationState.LIVE and registration != current
            ):
                # Replaced, removed, or pointing at an address no longer the installation's.
                self._stop(target.watcher, watch, registration)
        if current is None:
            self._ensure(target, owned)
            return
        self._check_confirmation(target, current)
        if current.renewal_due(self.now) and not watch.waiting(self.now):
            self._renew(target, current)

    def _target(self, watch: CalendarWatch) -> _Target | None:
        providers = self.upkeep.providers
        watcher = providers.watcher_for(watch.account)
        provider = providers.provider_of(watch.account)
        if watcher is None or provider is None or self.address is None:
            return None
        return _Target(watch, watcher, provider, providers.slug_of(provider), self.address)

    def _ensure(self, target: _Target, owned: Sequence[WatchRegistration]) -> None:
        """Create a registration, unless one is being created or the watch waits out a backoff."""
        creating = any(each.state is RegistrationState.CREATING for each in owned)
        if not creating and not target.watch.waiting(self.now):
            self._create(target)

    def _create(self, target: _Target, replacing: WatchRegistration | None = None) -> None:
        if self.meter.exhausted:
            return
        token = self.upkeep.fresh.new_token()
        registration = self._persist(target, token)
        attempted_at = self.upkeep.clock.now()
        try:
            receipt: Receipt | None = self.meter.paid(
                lambda: target.watcher.register(
                    target.watch.account,
                    target.watch.scope,
                    registration.id,
                    token,
                    registration.address,
                    registration.requested_until,
                )
            )
        except WatchFailure as failure:
            receipt = self._refused(target, registration, failure, attempted_at)
        if receipt is not None:
            self._record(target, registration, receipt, replacing)

    def _persist(self, target: _Target, token: str) -> WatchRegistration:
        """Keep a new registration as being created, before its provider is asked for it."""
        created_at = self.upkeep.clock.now()
        registration_id = WatchRegistrationId(self.upkeep.fresh.new_id())
        registration = WatchRegistration(
            id=registration_id,
            watch_id=target.watch.id,
            state=RegistrationState.CREATING,
            address=target.notice_address(registration_id),
            token_hash=token_hash(token),
            created_at=created_at,
            requested_until=created_at + LONGEST_REGISTRATION,
        )
        with self.upkeep.unit_of_work() as uow:
            uow.watches.add_registration(registration)
            uow.commit()
        return registration

    def _refused(
        self,
        target: _Target,
        registration: WatchRegistration,
        failure: WatchFailure,
        attempted_at: datetime,
    ) -> Receipt | None:
        if failure.kind is WatchFailureKind.DUPLICATE:
            return self._adopt(target, registration)
        self._forget(registration, failure)
        self._failed(target, failure, attempted_at)
        return None

    def _adopt(self, target: _Target, registration: WatchRegistration) -> Receipt | None:
        """After a duplicate, take over the provider's registration only if it names this one's
        id, as one whose answer a retry lost does."""
        if self.meter.exhausted:
            return None
        attempted_at = self.upkeep.clock.now()
        try:
            receipt = self.meter.paid(
                lambda: target.watcher.adopt(
                    target.watch.account, target.watch.scope, registration.id, registration.address
                )
            )
        except WatchFailure as failure:
            self._forget(registration, failure)
            self._failed(target, failure, attempted_at)
            return None
        if receipt is None:
            # Another registration holds the scope, such as another User's of the same mailbox.
            # It is never touched; the scope is left to Scheduled Sync for a day.
            with self.upkeep.unit_of_work() as uow:
                uow.watches.delete_registration(registration.id)
                retry_at = self.upkeep.clock.now() + MAX_BACKOFF
                uow.watches.set_retry(target.watch.id, retry_at, target.watch.failures + 1)
                uow.commit()
        return receipt

    def _forget(self, registration: WatchRegistration, failure: WatchFailure) -> None:
        """Drop a registration its provider refused; keep one it may have made recognized."""
        with self.upkeep.unit_of_work() as uow:
            if failure.kind is WatchFailureKind.TEMPORARY:
                uow.watches.abandon(registration.id)
            else:
                uow.watches.delete_registration(registration.id)
            uow.commit()

    def _record(
        self,
        target: _Target,
        registration: WatchRegistration,
        receipt: Receipt,
        replacing: WatchRegistration | None,
    ) -> None:
        at = self.upkeep.clock.now()
        renew_at = renewal_time(registration.created_at, receipt.expires_at, self._jitter())
        with self.upkeep.unit_of_work() as uow:
            recorded = uow.watches.record_receipt(registration.id, receipt, renew_at, at)
            if recorded and replacing is not None:
                # Both count until the replaced one is stopped, in this cycle or a later one.
                uow.watches.retire(replacing.id)
            if recorded:
                _clear_backoff(uow.watches, target.watch)
            uow.commit()
        if receipt.confirmed:
            self.upkeep.evidence.succeeded(target.provider, target.address, at)
        if recorded and replacing is not None:
            self._stop(target.watcher, target.watch, replacing)

    def _renew(self, target: _Target, current: WatchRegistration) -> None:
        if self.meter.exhausted:
            return
        seen = current.renew_requested_at
        attempted_at = self.upkeep.clock.now()
        until = attempted_at + LONGEST_REGISTRATION
        try:
            expires_at = self.meter.paid(
                lambda: target.watcher.extend(target.watch.account, current, until)
            )
        except WatchFailure as failure:
            self._failed(target, failure, attempted_at)
            return
        if expires_at is None:
            # Its provider renews only by replacement: a new registration, recorded first.
            self._create(target, replacing=current)
            return
        renew_at = renewal_time(attempted_at, expires_at, self._jitter())
        with self.upkeep.unit_of_work() as uow:
            if uow.watches.record_extension(current.id, expires_at, renew_at, seen):
                _clear_backoff(uow.watches, target.watch)
            uow.commit()

    def _check_confirmation(self, target: _Target, current: WatchRegistration) -> None:
        if current.confirmation_overdue(self.now):
            # Recorded at the deadline, not now, so every later cycle records the same failure.
            at = current.created_at + CONFIRMATION_DEADLINE
            self.upkeep.evidence.failed(target.provider, target.address, at)

    def _retire(self, watch: CalendarWatch, owned: Sequence[WatchRegistration]) -> None:
        """Stop a watch no rule needs; it goes once no registration of it is left."""
        watcher = self.upkeep.providers.watcher_for(watch.account)
        for registration in owned:
            if registration.state in {RegistrationState.LIVE, RegistrationState.RETIRING}:
                self._stop(watcher, watch, registration)
        with self.upkeep.unit_of_work() as uow:
            if not any(each.watch_id == watch.id for each in uow.watches.registrations()):
                uow.watches.remove(watch.id)
            uow.commit()

    def _stop(
        self, watcher: CalendarWatcher | None, watch: CalendarWatch, registration: WatchRegistration
    ) -> None:
        """Stop a registration, best effort, then delete it.

        One whose stop fails is abandoned until it would expire, and one the budget cannot pay
        to stop yet keeps its state, so the next cycle stops it.
        """
        if watcher is not None:
            if self.meter.exhausted:
                return
            try:
                self.meter.paid(lambda: watcher.stop(watch.account, registration))
            except WatchFailure:
                with self.upkeep.unit_of_work() as uow:
                    uow.watches.abandon(registration.id)
                    uow.commit()
                return
        with self.upkeep.unit_of_work() as uow:
            uow.watches.delete_registration(registration.id)
            uow.commit()

    def _failed(self, target: _Target, failure: WatchFailure, attempted_at: datetime) -> None:
        """Lapse the account for a refusal of its credentials; back off for any other failure."""
        if _lapse(self.upkeep.lapses, target.watch.account, failure, attempted_at):
            return
        at = self.upkeep.clock.now()
        if failure.kind is WatchFailureKind.UNREACHABLE:
            self.upkeep.evidence.failed(target.provider, target.address, at)
        failures = target.watch.failures + 1
        retry_at = at + backoff(failures, _retry_after(failure))
        with self.upkeep.unit_of_work() as uow:
            uow.watches.set_retry(target.watch.id, retry_at, failures)
            uow.commit()

    def _jitter(self) -> float:
        return self.upkeep.fresh.jitter()


def _tidy_registrations(watches: CalendarWatchRepository, now: datetime) -> None:
    """Delete registrations their providers no longer keep, and abandon lost creations."""
    for registration in watches.registrations():
        if registration.gone(now):
            watches.delete_registration(registration.id)
        elif registration.creation_stale(now):
            # A crash or a lost answer: the provider may hold it, so its notices stay
            # recognized, and ignored, until it would have expired.
            watches.abandon(registration.id)


def _narrow_coverage(
    watches: CalendarWatchRepository,
    sources: Sequence[CalendarEndpoint],
    unsure: frozenset[ConnectedAccountId],
) -> None:
    """Drop from each watch the calendars no enabled rule has as its source any more.

    An account whose sources were not all scoped keeps its coverage as it is.
    """
    needed = {(source.connected_account_id, source.calendar_id) for source in sources}
    for watch in watches.list():
        if watch.account in unsure:
            continue
        coverage = frozenset(each for each in watch.coverage if (watch.account, each) in needed)
        if coverage != watch.coverage:
            # Its notices wake no rule for what it no longer covers.
            watches.set_coverage(watch.id, coverage)


def _clear_backoff(watches: CalendarWatchRepository, watch: CalendarWatch) -> None:
    if watch.failures or watch.retry_at is not None:
        watches.set_retry(watch.id, None, 0)
