"""Instant Sync across Users (ADR 0036): watch upkeep, the dispatch of Instant Sync Requests,
and what the Web UI reads about both.

Upkeep and dispatch run beside the scheduler and, like it, read every User through the
installation-wide unit of work (ADR 0029). Each User's own work still runs with that User's
units: their watch upkeep, each rule's run through the scheduled pass, and each acknowledgement.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from calendar_sync.application.identity.ports import UserDirectory
from calendar_sync.application.operations.ports import (
    InstallationUnitOfWorkFactory,
    InstantSyncOwner,
    PendingInstantRun,
)
from calendar_sync.application.operations.scheduled_pass import (
    ScheduledPass,
    ScheduledRun,
    fairly_ordered,
)
from calendar_sync.application.shared.ports import Clock
from calendar_sync.application.sync.instant_sync import CallBudget, UpkeepWatches
from calendar_sync.application.sync.ports import UnitOfWorkFactory
from calendar_sync.application.sync.watch_ports import (
    DeliveryEvidenceLog,
    PendingRequest,
    SyncCadencePolicy,
    cadences_of,
)
from calendar_sync.domain.access import UserId
from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.cadence import DEFAULT_CADENCE, SyncCadence
from calendar_sync.domain.model import (
    CalendarEndpoint,
    ConnectedAccountId,
    SyncRuleId,
    SyncRuleState,
)
from calendar_sync.domain.watches import (
    Availability,
    CadenceReason,
    CalendarWatch,
    DeliveryState,
    WatchRegistration,
    effective_cadence,
    instant_sync_availability,
)

logger = logging.getLogger(__name__)

QUIET = timedelta(seconds=10)
"""How long a rule's notices must stay quiet before its instant run, so a burst runs it once."""
MAX_WAIT = timedelta(seconds=30)
"""The longest that notices which keep coming hold a rule's instant run back."""
MIN_GAP = timedelta(seconds=30)
"""The shortest time between two instant runs of one rule."""
UPKEEP_BUDGET = 200
"""Provider calls one upkeep cycle may make across every User; the rest waits a cycle."""


@dataclass(slots=True)
class WatchUpkeep:
    """Keeps every User's Calendar Watches as their rules, preference, and Plan want them.

    Each cycle visits Users with nothing planned yet first, then the others in order of their
    earliest due work, so what waited longest goes first. Disabled Users are visited too: nothing
    is wanted for them, so their watches stop. A User whose Sync Cadence cannot be read counts
    as instant, so a Plans fault never retires their watches (ADR 0038).
    """

    installation: InstallationUnitOfWorkFactory
    upkeep_for: Callable[[UserId], UpkeepWatches | None]
    """A User's own upkeep; None where no provider can watch, as without the master key."""
    cadence: SyncCadencePolicy
    address: str | None
    """The installation's public https address; None when it has none."""
    clock: Clock
    _carried: tuple[UserId, ...] = ()
    """The Users the last cycle never reached, then the User it stopped on; they go first."""

    def run(self, budget: int = UPKEEP_BUDGET) -> None:
        calls = CallBudget(budget)
        with self.installation() as installation:
            owners = self._in_turn(installation.instant_sync_owners())
        # One read of every listed User's cadence per cycle, outside any unit of work.
        cadences = cadences_of(self.cadence, [owner.user for owner in owners])
        self._carried = ()
        for position, owner in enumerate(owners):
            self._keep(owner, cadences.get(owner.user), calls)
            if calls.exhausted:
                # The Users it never reached go first next cycle, then this one, whose upkeep
                # the budget may have cut short. So a User with a large backlog never stays
                # first forever, and two such Users take turns.
                unreached = owners[position + 1 :]
                self._carried = (*(each.user for each in unreached), owner.user)
                logger.info("Watch upkeep spent its provider call budget; the rest waits a cycle")
                return

    def _in_turn(self, owners: Sequence[InstantSyncOwner]) -> list[InstantSyncOwner]:
        """The Users the last cycle never reached, then the User it stopped on, then those with
        nothing planned yet, whose coverage is missing, then the rest by earliest due work."""
        now = self.clock.now()
        carried = {user: turn for turn, user in enumerate(self._carried)}

        def turn(owner: InstantSyncOwner) -> tuple[int, int, datetime, str]:
            if owner.user in carried:
                return 0, carried[owner.user], now, owner.user.value
            if owner.next_due is None:
                return 1, 0, now, owner.user.value
            return 2, 0, owner.next_due, owner.user.value

        return sorted(owners, key=turn)

    def _keep(
        self, owner: InstantSyncOwner, cadence: SyncCadence | None, calls: CallBudget
    ) -> None:
        """One User's upkeep; a failure waits for the next cycle and holds up nobody else."""
        try:
            upkeep = self.upkeep_for(owner.user)
            if upkeep is not None:
                upkeep.execute(
                    allowed=self._allowed(owner, cadence), address=self.address, budget=calls
                )
        except Exception as error:
            # Only the class: a provider's text, which the error may carry along, can quote a
            # token or a registration address.
            logger.error(
                "Upkeep of a User's watches failed; trying again next cycle (%s)",
                error.__class__.__name__,
            )

    def _allowed(self, owner: InstantSyncOwner, cadence: SyncCadence | None) -> bool:
        """Whether the User may have watches: the installation can be reached, the User is
        active and wants Instant Sync, and their Plan includes it, or could not be read."""
        return (
            self.address is not None
            and not owner.disabled
            and owner.wanted
            and _may_sync_instantly(cadence)
        )


@dataclass(frozen=True, slots=True)
class InstantRun:
    """A rule's run for its Instant Sync Request, and the request's sequence it answers."""

    scheduled: ScheduledRun
    seq: int
    """The request's `requested_seq` when the run was chosen; notices after it stay pending."""


def due_at(request: PendingRequest) -> datetime:
    """When a pending request may run: once its notices were quiet for QUIET, or MAX_WAIT after
    the first, and never within MIN_GAP of the rule's last instant run."""
    settled = min(request.last_requested_at + QUIET, request.first_requested_at + MAX_WAIT)
    if request.last_run_at is None:
        return settled
    return max(settled, request.last_run_at + MIN_GAP)


@dataclass(slots=True)
class InstantDispatch:
    """Chooses which rules run now for their Instant Sync Requests, and runs them.

    A request whose rule may no longer run instantly is acknowledged and dropped: its owner turned
    Instant Sync off, their Plan no longer includes it, or the rule's last run failed, which
    Scheduled Sync retries with its own backoff. Requests of a paused rule or a disabled User are
    not listed, so they wait, and run or are dropped once the rule or User is active again.
    Delivery Evidence never holds a run back: an authenticated notice proves delivery works. A
    User whose Sync Cadence cannot be read counts as instant, so a Plans fault drops nothing.
    """

    installation: InstallationUnitOfWorkFactory
    scheduled_pass: ScheduledPass
    requests_for: Callable[[UserId], UnitOfWorkFactory]
    """Each User's units, which acknowledge that User's requests."""
    cadence: SyncCadencePolicy
    clock: Clock
    _held_until: dict[SyncRuleId, datetime] = field(default_factory=dict, init=False)
    """Rules whose acknowledgement failed, and until when they wait, as if it had succeeded.
    Kept in the process only: after a restart, the request runs again at once. Runs write it
    and looks read it from different threads, each access one dictionary operation."""

    def due(self, reserved: Collection[str]) -> tuple[tuple[InstantRun, ...], datetime | None]:
        """The runs to start now, taking turns between Users, and when the next pending request
        becomes due. Rules in `reserved` are queued or running already and are left alone."""
        now = self.clock.now()
        with self.installation() as installation:
            instant = self._instant_users(installation.instant_sync_owners())
            pending = installation.pending_instant_runs()
        ready: list[PendingInstantRun] = []
        later: list[datetime] = []
        for item in pending:
            if item.scheduled.rule.id.value in reserved:
                continue
            if not _eligible(item, instant):
                self._drop(item, now)
            elif (at := self._due_at(item)) <= now:
                ready.append(item)
            else:
                later.append(at)
        return _fair_runs(ready), min(later, default=None)

    def run(self, item: InstantRun) -> None:
        """Run the rule as the scheduler does, then acknowledge the request whether the run
        succeeded or failed. A notice that came during the run raised the request past the
        captured sequence, so another run follows; a crash before acknowledging runs it again.

        A run may wait in the dispatcher's queue, so the request is read again first. One no
        longer listed waits, as `due` leaves it: its rule was paused or its owner disabled. One
        whose rule may no longer run instantly is dropped without running."""
        scheduled = item.scheduled.scheduled
        current, instant = self._recheck(item)
        if current is None:
            return
        if not _eligible(current, instant):
            self._drop(current, self.clock.now())
            return
        try:
            self.scheduled_pass.run(item.scheduled)
        finally:
            ran_at = self.clock.now()
            try:
                self._acknowledge(scheduled.owner, scheduled.rule.id, item.seq, ran_at)
            except Exception as error:
                # Its request still looks unanswered, so the rule waits the gap here instead:
                # storage that keeps refusing must not run it back to back.
                self._held_until[scheduled.rule.id] = ran_at + MIN_GAP
                logger.error(
                    "Could not acknowledge the instant run of rule %s; it runs again (%s)",
                    scheduled.rule.id.value,
                    error.__class__.__name__,
                )
            else:
                self._held_until.pop(scheduled.rule.id, None)

    def _due_at(self, item: PendingInstantRun) -> datetime:
        """When a pending request may run, and not before the gap after a run whose
        acknowledgement failed."""
        at = due_at(item.request)
        held = self._held_until.get(item.scheduled.rule.id)
        return at if held is None else max(at, held)

    def _recheck(self, item: InstantRun) -> tuple[PendingInstantRun | None, frozenset[UserId]]:
        """The run's request as it is pending now, if it still is, and who may run instantly."""
        owner, rule_id = item.scheduled.scheduled.owner, item.scheduled.scheduled.rule.id
        with self.installation() as installation:
            instant = self._instant_users(installation.instant_sync_owners())
            pending = installation.pending_instant_runs()
        current = next(
            (
                each
                for each in pending
                if each.scheduled.owner == owner and each.scheduled.rule.id == rule_id
            ),
            None,
        )
        return current, instant

    def _instant_users(self, owners: Sequence[InstantSyncOwner]) -> frozenset[UserId]:
        """The Users whose rules may run instantly now, their cadences read in one batch."""
        wanting = [owner.user for owner in owners if owner.wanted and not owner.disabled]
        cadences = cadences_of(self.cadence, wanting)
        return frozenset(user for user in wanting if _may_sync_instantly(cadences.get(user)))

    def _drop(self, item: PendingInstantRun, now: datetime) -> None:
        """Acknowledge a request no instant run will answer; Scheduled Sync runs the rule."""
        scheduled = item.scheduled
        try:
            self._acknowledge(scheduled.owner, scheduled.rule.id, item.request.requested_seq, now)
        except Exception as error:
            logger.error(
                "Could not drop an Instant Sync Request; trying again next look (%s)",
                error.__class__.__name__,
            )

    def _acknowledge(self, owner: UserId, rule_id: SyncRuleId, seq: int, at: datetime) -> None:
        with self.requests_for(owner)() as uow:
            uow.instant_requests.acknowledge(rule_id, seq, at)
            uow.commit()


def _may_sync_instantly(cadence: SyncCadence | None) -> bool:
    """Whether a User's cadence allows Instant Sync; one that could not be read does, so a Plans
    fault never drops a request or retires a watch (ADR 0038)."""
    return cadence is None or cadence.instant


def _eligible(item: PendingInstantRun, instant: frozenset[UserId]) -> bool:
    return (
        item.scheduled.owner in instant
        and item.scheduled.rule.state is SyncRuleState.ENABLED
        and not item.last_run_failed
    )


def _fair_runs(ready: Sequence[PendingInstantRun]) -> tuple[InstantRun, ...]:
    """Due runs taking turns between Users, as a scheduled pass orders its rules."""
    seqs = {
        (item.scheduled.owner, item.scheduled.rule.id): item.request.requested_seq for item in ready
    }
    return tuple(
        InstantRun(ScheduledRun(scheduled, full=False), seqs[scheduled.owner, scheduled.rule.id])
        for scheduled in fairly_ordered([item.scheduled for item in ready])
    )


@dataclass(frozen=True, slots=True)
class WatchedSources:
    """What watch upkeep knows of each Source Calendar's provider."""

    provider_of: Callable[[ConnectedAccountId], ProviderKind | None]
    known_unwatchable: Callable[[CalendarEndpoint, datetime], bool]
    """Whether upkeep found lately that the calendar's provider cannot watch it."""


@dataclass(slots=True)
class InstantSyncStatus:
    """Whether Instant Sync is on for a User, and why each of their rules syncs as it does.

    The account switch and the rule pages read it. It reads the User's own records, their
    preference, their Plan's cadence, and the Delivery Evidence of the installation's address.
    """

    users: UserDirectory
    unit_of_work: Callable[[UserId], UnitOfWorkFactory]
    cadence: SyncCadencePolicy
    evidence: DeliveryEvidenceLog
    sources: WatchedSources
    address: str | None
    """The installation's public https address; None when it cannot offer Instant Sync."""
    clock: Clock

    def availability(self, user: UserId) -> Availability:
        with self.unit_of_work(user)() as uow:
            watches = tuple(uow.watches.list())
        return self._availability(user, watches)

    def cadences(self, user: UserId) -> Mapping[SyncRuleId, CadenceReason]:
        """Each rule's Effective Cadence: instant, or why Scheduled Sync runs it instead."""
        with self.unit_of_work(user)() as uow:
            rules = tuple(uow.rules.list())
            watches = tuple(uow.watches.list())
            registrations = tuple(uow.watches.registrations())
        availability = self._availability(user, watches)
        now = self.clock.now()
        # A registration made for an earlier public address delivers nowhere this one hears.
        current = tuple(
            registration
            for registration in registrations
            if self.address is not None and registration.address.startswith(f"{self.address}/")
        )
        return {
            rule.id: _cadence_of(
                rule.source,
                availability,
                watches,
                current,
                now,
                unwatchable=self.sources.known_unwatchable(rule.source, now),
            )
            for rule in rules
        }

    def poll_every(self, user: UserId) -> timedelta:
        """How often Scheduled Sync runs the User's rules, as their Plan says."""
        return self._cadence(user).poll_every

    def _availability(self, user: UserId, watches: Sequence[CalendarWatch]) -> Availability:
        found = self.users.get(user)
        return instant_sync_availability(
            address_is_https=self.address is not None,
            cadence=self._cadence(user),
            wanted=found is not None and found.instant_sync,
            delivery=self._delivery(watches),
        )

    def _cadence(self, user: UserId) -> SyncCadence:
        """The User's cadence, or the default one when it cannot be read, so a Plans fault never
        breaks sign-in or the rules API (ADR 0038)."""
        try:
            return self.cadence.cadence(user)
        except Exception as error:
            # Only the class: the error's text could quote the database's own words.
            logger.warning(
                "Could not read a User's Sync Cadence; showing the default one (%s)",
                error.__class__.__name__,
            )
            return DEFAULT_CADENCE

    def _delivery(self, watches: Sequence[CalendarWatch]) -> tuple[DeliveryState, ...]:
        """The Delivery State of each provider the User's watched sources use, at this
        installation's address; evidence for another address says nothing about this one."""
        if self.address is None or not watches:
            return ()
        evidence = self.evidence.evidence(self.address)
        providers = {self.sources.provider_of(watch.account) for watch in watches}
        return tuple(
            evidence[provider].state if provider in evidence else DeliveryState.UNKNOWN
            for provider in providers
            if provider is not None
        )


def _cadence_of(
    source: CalendarEndpoint,
    availability: Availability,
    watches: Sequence[CalendarWatch],
    registrations: Sequence[WatchRegistration],
    now: datetime,
    *,
    unwatchable: bool,
) -> CadenceReason:
    """One rule's Effective Cadence, from the watch covering its Source Calendar, if any."""
    watch = next((each for each in watches if each.covers(source)), None)
    own = tuple(
        registration
        for registration in registrations
        if watch is not None and registration.watch_id == watch.id
    )
    return effective_cadence(availability, watch, own, now, unwatchable=unwatchable)
