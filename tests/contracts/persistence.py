"""What every unit of work must honor, asked only through the persistence ports.

SQLite is what installations run; the in-memory unit of work stands in for it in application
tests. Both pass this suite, so the storage behavior it states holds for a use case tested in
memory; behavior it does not state may still differ. A subclass supplies a harness that records
Connected Accounts, which happens outside any unit of work.
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Protocol

import pytest

from calendar_sync.application.identity.credentials import CredentialChanges
from calendar_sync.application.identity.errors import EmailTaken, UserDisabled
from calendar_sync.application.identity.password_reset import SelfServicePasswordResets
from calendar_sync.application.identity.ports import PasswordResetLinks, Sessions, UserDirectory
from calendar_sync.application.operations.ports import (
    AccountStanding,
    CauseSighting,
    InstallationUnitOfWorkFactory,
    InstantSyncOwner,
    PendingInstantRun,
    ProviderCallUse,
    RecordedRule,
)
from calendar_sync.application.sync.errors import (
    DuplicateDirectionalRelationship,
    IdentityCollision,
    MissingReference,
    RecordRefused,
)
from calendar_sync.application.sync.ports import (
    CalendarAccess,
    DiscoveredCalendar,
    IncidentRepository,
    ProviderCallCounts,
    RulePreviewSummary,
    ScheduledRule,
    UnitOfWork,
    UnitOfWorkFactory,
)
from calendar_sync.application.sync.watch_ports import PendingRequest, Receipt
from calendar_sync.domain.access import Role, UserId, UserState
from calendar_sync.domain.accounts import ConnectedAccountState, ProviderKind
from calendar_sync.domain.audit import (
    AuditAction,
    AuditEntry,
    AuditOutcome,
    FoundBy,
    RecordedDecision,
    RecordedEvent,
    RunReason,
)
from calendar_sync.domain.causes import Cause
from calendar_sync.domain.changes import ComparisonKind, SourceObservation
from calendar_sync.domain.incidents import (
    AccountAuthorization,
    IncidentCategory,
    IncidentReport,
    IncidentResolution,
)
from calendar_sync.domain.model import (
    AllDayRange,
    CalendarEndpoint,
    CalendarId,
    ConnectedAccountId,
    EventId,
    EventMapping,
    EventMappingId,
    EventRef,
    OccurrenceMapping,
    OccurrenceMappingId,
    OccurrenceStart,
    OccurrenceState,
    ProjectionFingerprint,
    SyncReason,
    SyncRule,
    SyncRuleId,
    SyncRuleState,
    TimedInterval,
)
from calendar_sync.domain.plan_hold import PlanGrace, RulePlace
from calendar_sync.domain.plans import PlanUse
from calendar_sync.domain.providers import ProviderFailureKind
from calendar_sync.domain.runs import RuleRunOutcome, RunKind
from calendar_sync.domain.watches import (
    CREATION_DEADLINE,
    CalendarWatch,
    CalendarWatchId,
    RegistrationState,
    WatchRegistration,
    WatchRegistrationId,
    WatchScope,
    token_hash,
)
from tests.helpers import NOW, endpoint, rule, week_start
from tests.users import OTHER_USER, USER

RULE = rule()
OTHER_RULE = replace(
    rule(), id=SyncRuleId("rule-0"), destination=endpoint("work-account", "other-calendar")
)
"""Sorts before RULE, so listing order is by identifier rather than by insertion."""
ACCOUNT = ConnectedAccountId("personal-account")
THEIR_ACCOUNT = ConnectedAccountId("their-account")
THEIR_SOURCE = endpoint("their-personal-account", "personal-calendar")
THEIR_DESTINATION = endpoint("their-work-account", "work-calendar")
"""Another User's calendars, with the same calendar identifiers as RULE's."""
DAY = timedelta(days=1)
HOUR = timedelta(hours=1)
MINUTE = timedelta(minutes=1)
WATCH = CalendarWatch(
    CalendarWatchId("watch-1"),
    ACCOUNT,
    WatchScope.calendar(RULE.source.calendar_id),
    frozenset({RULE.source.calendar_id}),
)
THEIR_WATCH = CalendarWatch(
    CalendarWatchId("their-watch"),
    THEIR_SOURCE.connected_account_id,
    WatchScope.calendar(THEIR_SOURCE.calendar_id),
    frozenset({THEIR_SOURCE.calendar_id}),
)
"""Another User's watch of a calendar with the same identifier as WATCH's."""
RECEIPT = Receipt("handle-1", NOW + 7 * DAY)


@dataclass(frozen=True, slots=True)
class PersistenceHarness:
    units: Callable[[UserId], UnitOfWorkFactory]
    """Each User's units of work over one store."""
    connect: Callable[[ConnectedAccountId, UserId], object]
    """Record a User's Connected Account, as authorizing it would outside any unit of work."""
    disconnect: Callable[[ConnectedAccountId, UserId], object]
    disable: Callable[[UserId], object]
    """Disable a User, as an Installation Administrator would outside any unit of work."""
    installation: InstallationUnitOfWorkFactory
    """Units of work across every User, as the scheduler and the Operator Overview read them."""
    incidents: Callable[[UserId], IncidentRepository]
    """Each User's Incidents, which open and resolve outside any unit of work."""
    request_run: Callable[[UserId, SyncRuleId, datetime], object]
    """Raise a rule's Instant Sync Request, as an authentic Watch Notice would outside any unit
    of work."""
    prefer: Callable[[UserId, bool], object]
    """Record whether a User wants Instant Sync, as their account settings would outside any unit
    of work."""
    issue_token: Callable[[UserId, bool], object]
    """Record an Integration Token of a User, revoked or not, as issuing one would outside any
    unit of work."""

    @property
    def unit_of_work(self) -> UnitOfWorkFactory:
        return self.units(USER)

    def connect_account(self, account_id: ConnectedAccountId, user: UserId = USER) -> None:
        self.connect(account_id, user)

    def disconnect_account(self, account_id: ConnectedAccountId, user: UserId = USER) -> None:
        self.disconnect(account_id, user)


def _mapping(name: str, rule_id: SyncRuleId = RULE.id, destination: str = "") -> EventMapping:
    return EventMapping(
        EventMappingId(name),
        rule_id,
        EventRef(RULE.source, EventId(f"source-{name}")),
        EventRef(RULE.destination, EventId(destination or f"destination-{name}")),
        "revision-1",
        ProjectionFingerprint("fingerprint"),
    )


def _occurrence(series: EventMapping, start: OccurrenceStart, name: str) -> OccurrenceMapping:
    return OccurrenceMapping(
        OccurrenceMappingId(name),
        series.id,
        start,
        EventRef(RULE.source, EventId(f"{series.source.event_id.value}_{name}")),
        EventRef(RULE.destination, EventId(f"{series.destination.event_id.value}_{name}")),
        OccurrenceState.CANCELLED,
        "revision-1",
    )


def _observation(ends_at: datetime = NOW, recurrence: tuple[str, ...] = ()) -> SourceObservation:
    return SourceObservation(
        revision="revision-1",
        title="Planning",
        time=TimedInterval(ends_at - timedelta(hours=1), ends_at),
        recurrence=recurrence,
    )


def _account_incident(account_id: ConnectedAccountId) -> IncidentReport:
    """The Incident an account's Lapsed Authorization opens."""
    return IncidentReport(
        f"authorization:{account_id.value}",
        None,
        IncidentCategory.AUTHENTICATION,
        "Authorization for Google Calendar expired",
        account_id=account_id,
    )


def _rule_incident(
    rule_id: SyncRuleId, cause: Cause | None = Cause.CALENDAR_FORBIDDEN, key: str = ""
) -> IncidentReport:
    """The Incident a rule's provider failure opens."""
    return IncidentReport(
        key or f"provider:{rule_id.value}",
        rule_id,
        IncidentCategory.PERMANENT,
        "Google Calendar rejected synchronization",
        account_id=RULE.destination.connected_account_id,
        cause=cause,
    )


def _block(
    rule_id: SyncRuleId, event_id: str | None, reason: SyncReason | None = None
) -> AuditEntry:
    return AuditEntry(
        NOW, rule_id, AuditAction.CONFLICT, AuditOutcome.BLOCKED, event_id, reason=reason
    )


def _skip(
    source_event_id: str,
    reason: SyncReason,
    time: TimedInterval | AllDayRange | None = None,
) -> AuditEntry:
    return AuditEntry(
        occurred_at=NOW,
        rule_id=RULE.id,
        action=AuditAction.IGNORE,
        outcome=AuditOutcome.SKIPPED,
        source_event_id=source_event_id,
        reason=reason,
        event=RecordedEvent(
            title="Seminar",
            time=time or TimedInterval(NOW, NOW + timedelta(hours=1)),
            recurring=True,
        ),
        run_reason=RunReason.CHANGES,
        found_by=FoundBy.SOURCE_FEED,
        source_comparison=ComparisonKind.UNTRACKED,
    )


def _lapse(harness: PersistenceHarness, account_id: ConnectedAccountId, user: UserId) -> None:
    """Lapse the account and open its Incident, as a refused request does."""
    with harness.units(user)() as uow:
        assert uow.accounts.lapse(account_id, attempted_at=NOW)
        uow.commit()
    assert harness.incidents(user).open(_account_incident(account_id), NOW)


def _calendar(calendar_id: str, name: str) -> DiscoveredCalendar:
    return DiscoveredCalendar(calendar_id, name, CalendarAccess.OWNER, primary=False)


def _add_then_fail(unit_of_work: UnitOfWorkFactory) -> None:
    with unit_of_work() as uow:
        uow.rules.add(RULE)
        raise RuntimeError("stop")


def _commit_then_fail(unit_of_work: UnitOfWorkFactory) -> None:
    with unit_of_work() as uow:
        uow.rules.add(RULE)
        uow.commit()
        uow.rules.add(OTHER_RULE)
        raise RuntimeError("stop")


def _commit_as(
    harness: PersistenceHarness, user: UserId, write: Callable[[UnitOfWork], object]
) -> None:
    with harness.units(user)() as uow:
        write(uow)
        uow.commit()


def _registration(
    name: str = "registration-1", watch: CalendarWatchId = WATCH.id
) -> WatchRegistration:
    """A registration upkeep recorded before asking the provider for it."""
    return WatchRegistration(
        WatchRegistrationId(name),
        watch,
        RegistrationState.CREATING,
        f"https://calendar.example.test/api/v1/watch-notices/test/{name}",
        token_hash(f"token-{name}"),
        NOW,
        NOW + 7 * DAY,
    )


def _live(name: str = "registration-1", watch: CalendarWatchId = WATCH.id) -> WatchRegistration:
    return replace(
        _registration(name, watch),
        state=RegistrationState.LIVE,
        handle=f"handle-{name}",
        expires_at=NOW + 7 * DAY,
        renew_at=NOW + 5 * DAY,
    )


def _watching(harness: PersistenceHarness, *registrations: WatchRegistration) -> None:
    """USER's watch of RULE's Source Calendar, with `registrations`."""
    with harness.unit_of_work() as uow:
        uow.watches.add(WATCH)
        for registration in registrations:
            uow.watches.add_registration(registration)
        uow.commit()


class PersistenceContract:
    @pytest.fixture
    def harness(self) -> PersistenceHarness:
        raise NotImplementedError

    def test_standings_rank_and_keep_survives_late_rule_save(
        self, harness: PersistenceHarness
    ) -> None:
        reserved = replace(OTHER_RULE, state=SyncRuleState.DRAFT, keeps_place=True)
        held = replace(
            RULE.hold(),
            id=SyncRuleId("held"),
            destination=endpoint("work-account", "held-calendar"),
        )
        excluded = replace(
            RULE.pause(),
            id=SyncRuleId("paused"),
            destination=endpoint("work-account", "paused-calendar"),
        )
        with harness.unit_of_work() as uow:
            for each in (RULE, reserved, held, excluded):
                uow.rules.add(each)
            uow.rules.keep([held.id, reserved.id])
            uow.rules.save(held)
            uow.commit()
        with harness.unit_of_work() as uow:
            standings = uow.rules.standings()
            assert [(item.rule_id, item.place, item.kept) for item in standings] == [
                (reserved.id, RulePlace.RESERVED, True),
                (held.id, RulePlace.HELD, True),
                (RULE.id, RulePlace.COUNTED, False),
            ]
            assert [each.id for each in uow.rules.list()] == sorted(
                (RULE.id, reserved.id, held.id, excluded.id), key=lambda each: each.value
            )
            uow.rules.keep([])
            uow.commit()
        with harness.unit_of_work() as uow:
            assert [item.rule_id for item in uow.rules.standings()] == [
                RULE.id,
                reserved.id,
                held.id,
            ]
            assert not any(item.kept for item in uow.rules.standings())
            # Equal creation order and keep rank use the identifier as the final tie-breaker.
            uow.rules.inherit_place(reserved.id, of=RULE.id)
            assert [item.rule_id for item in uow.rules.standings()] == [
                reserved.id,
                RULE.id,
                held.id,
            ]
            uow.rules.keep([RULE.id])
        with harness.unit_of_work() as uow:
            assert not any(item.kept for item in uow.rules.standings())

    @pytest.mark.parametrize("previous", [RULE, RULE.hold(), RULE.pause(), RULE.degrade()])
    def test_replacement_inherits_order_and_keep_only_with_a_place(
        self, harness: PersistenceHarness, previous: SyncRule
    ) -> None:
        successor = replace(OTHER_RULE, state=SyncRuleState.DRAFT).take_place_of(previous)
        with harness.unit_of_work() as uow:
            uow.rules.add(previous)
            uow.rules.keep([previous.id])
            before = uow.rules.standings()
            uow.rules.add(successor)
            if successor.keeps_place:
                uow.rules.inherit_place(successor.id, of=previous.id)
            uow.rules.remove(previous.id)
            uow.commit()
        with harness.unit_of_work() as uow:
            stored = uow.rules.get(successor.id)
            assert stored == successor
            assert uow.plan_grace.admissions() == 0
            if previous.counts_toward_plan:
                standing = uow.rules.standings()[0]
                assert standing.order == before[0].order
                assert standing.kept
            else:
                # Starting the new draft reveals its own new order and no inherited mark.
                uow.rules.save(successor.mark_previewed().enable())
                standing = uow.rules.standings()[0]
                assert standing.order > (before[0].order if before else 0)
                assert not standing.kept

    def test_plan_grace_and_admissions_commit_or_discard(self, harness: PersistenceHarness) -> None:
        grace = PlanGrace(NOW + 7 * DAY, 2, 4)
        with harness.unit_of_work() as uow:
            uow.plan_grace.acquire()
            assert uow.plan_grace.get() is None
            assert uow.plan_grace.admissions() == 0
            uow.plan_grace.save(grace)
            uow.plan_grace.admit()
            uow.plan_grace.admit(3)
            uow.commit()
            uow.plan_grace.save(None)
            uow.plan_grace.admit(8)
        with harness.unit_of_work() as uow:
            assert uow.plan_grace.get() == grace
            assert uow.plan_grace.admissions() == 4

        def fail() -> None:
            with harness.unit_of_work() as uow:
                uow.plan_grace.acquire()
                uow.plan_grace.save(None)
                uow.plan_grace.admit()
                raise RuntimeError("discard")

        with pytest.raises(RuntimeError):
            fail()
        with harness.unit_of_work() as uow:
            assert uow.plan_grace.get() == grace
            assert uow.plan_grace.admissions() == 4
            uow.plan_grace.save(None)
            uow.commit()
        with harness.unit_of_work() as uow:
            assert uow.plan_grace.get() is None
            assert uow.plan_grace.admissions() == 4

    def test_plan_records_are_user_scoped(self, harness: PersistenceHarness) -> None:
        for endpoint_ in (THEIR_SOURCE, THEIR_DESTINATION):
            harness.connect_account(endpoint_.connected_account_id, OTHER_USER)
        theirs = replace(
            RULE, id=SyncRuleId("their-rule"), source=THEIR_SOURCE, destination=THEIR_DESTINATION
        )
        grace = PlanGrace(NOW + DAY, 1, 9)
        with harness.units(OTHER_USER)() as uow:
            uow.rules.add(theirs)
            uow.rules.keep([theirs.id])
            uow.plan_grace.acquire()
            uow.plan_grace.save(grace)
            uow.plan_grace.admit(9)
            uow.commit()
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.rules.keep([theirs.id])
            uow.rules.inherit_place(RULE.id, of=theirs.id)
            uow.rules.inherit_place(theirs.id, of=RULE.id)
            uow.plan_grace.acquire()
            assert uow.plan_grace.get() is None
            assert uow.plan_grace.admissions() == 0
            uow.plan_grace.admit()
            uow.commit()
        with harness.units(OTHER_USER)() as uow:
            assert [item.rule_id for item in uow.rules.standings()] == [theirs.id]
            assert uow.rules.standings()[0].kept
            assert uow.plan_grace.get() == grace
            assert uow.plan_grace.admissions() == 9
        with harness.unit_of_work() as uow:
            assert [item.rule_id for item in uow.rules.standings()] == [RULE.id]
            assert not uow.rules.standings()[0].kept
            assert uow.plan_grace.admissions() == 1

    # Units of work

    def test_writes_without_a_commit_are_discarded(self, harness: PersistenceHarness) -> None:
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)

        with harness.unit_of_work() as uow:
            assert uow.rules.get(RULE.id) is None

    def test_a_unit_that_raises_discards_its_writes(self, harness: PersistenceHarness) -> None:
        with pytest.raises(RuntimeError):
            _add_then_fail(harness.unit_of_work)

        with harness.unit_of_work() as uow:
            assert uow.rules.get(RULE.id) is None

    def test_writes_after_a_commit_need_another_commit(self, harness: PersistenceHarness) -> None:
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.commit()
            uow.rules.add(OTHER_RULE)

        with harness.unit_of_work() as uow:
            assert uow.rules.list() == (RULE,)

    def test_a_unit_that_raises_after_a_commit_keeps_what_it_committed(
        self, harness: PersistenceHarness
    ) -> None:
        with pytest.raises(RuntimeError):
            _commit_then_fail(harness.unit_of_work)

        with harness.unit_of_work() as uow:
            assert uow.rules.list() == (RULE,)

    def test_a_unit_reads_its_own_writes(self, harness: PersistenceHarness) -> None:
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            assert uow.rules.get(RULE.id) == RULE

    def test_a_unit_sees_its_user_disabled_even_while_it_is_open(
        self, harness: PersistenceHarness
    ) -> None:
        with harness.unit_of_work() as uow:
            active = uow.user_active()
            harness.disable(USER)
            disabled_meanwhile = uow.user_active()
        with harness.units(OTHER_USER)() as theirs:
            assert theirs.user_active()

        assert (active, disabled_meanwhile) == (True, False)

    # Directional Sync Rules

    def test_rules_round_trip_and_list_by_identifier(self, harness: PersistenceHarness) -> None:
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.rules.add(OTHER_RULE)
            uow.commit()
        stopped = RULE.degrade(awaiting_reauthorization=True)
        with harness.unit_of_work() as uow:
            uow.rules.save(stopped)
            uow.commit()

        with harness.unit_of_work() as uow:
            assert uow.rules.list() == (OTHER_RULE, stopped)
            assert uow.rules.get(RULE.id) == stopped

    def test_a_draft_keeps_its_place_through_its_preview_until_it_starts(
        self, harness: PersistenceHarness
    ) -> None:
        draft = replace(RULE, state=SyncRuleState.DRAFT, keeps_place=True)
        with harness.unit_of_work() as uow:
            uow.rules.add(draft)
            uow.commit()
        with harness.unit_of_work() as uow:
            added = uow.rules.get(RULE.id)
            uow.rules.save(draft.mark_previewed())
            uow.commit()
        with harness.unit_of_work() as uow:
            previewed = uow.rules.list()
            uow.rules.save(draft.mark_previewed().enable())
            uow.commit()
        with harness.unit_of_work() as uow:
            started = uow.rules.get(RULE.id)

        assert added == draft
        assert previewed == (replace(draft, state=SyncRuleState.PREVIEWED),)
        assert previewed[0].keeps_place
        assert started is not None
        assert not started.keeps_place
        assert started == RULE

    def test_a_second_rule_for_one_direction_is_refused(self, harness: PersistenceHarness) -> None:
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            with pytest.raises(DuplicateDirectionalRelationship):
                uow.rules.add(replace(RULE, id=SyncRuleId("rule-2")))

    def test_moving_a_rule_onto_another_rules_direction_is_refused(
        self, harness: PersistenceHarness
    ) -> None:
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.rules.add(OTHER_RULE)
            with pytest.raises(DuplicateDirectionalRelationship):
                uow.rules.save(replace(OTHER_RULE, destination=RULE.destination))

    def test_a_second_rule_with_one_identifier_is_refused(
        self, harness: PersistenceHarness
    ) -> None:
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            with pytest.raises(IdentityCollision):
                uow.rules.add(replace(OTHER_RULE, id=RULE.id))

    def test_every_refusal_is_a_record_refused(self, harness: PersistenceHarness) -> None:
        """A use case can handle any refusal of any store as one error."""
        assert issubclass(DuplicateDirectionalRelationship, RecordRefused)
        assert issubclass(IdentityCollision, RecordRefused)
        assert issubclass(MissingReference, RecordRefused)
        with harness.unit_of_work() as uow, pytest.raises(RecordRefused):
            uow.cursors.save(RULE.id, "cursor")

    def test_a_rule_needs_accounts_its_user_has_when_the_unit_commits(
        self, harness: PersistenceHarness
    ) -> None:
        harness.connect_account(THEIR_ACCOUNT, OTHER_USER)
        unknown = replace(RULE, id=SyncRuleId("unknown"), source=endpoint("unknown", "calendar"))
        theirs = replace(
            RULE, id=SyncRuleId("theirs"), destination=endpoint(THEIR_ACCOUNT.value, "calendar")
        )

        for refused in (unknown, theirs):
            with harness.unit_of_work() as uow:
                # Accounts are checked at commit, so an account and its rules go in either order.
                uow.rules.add(refused)
                with pytest.raises(MissingReference):
                    uow.commit()
        with harness.unit_of_work() as uow:
            assert uow.rules.list() == ()

    def test_an_account_a_rule_still_names_is_deleted_only_with_the_rule(
        self, harness: PersistenceHarness
    ) -> None:
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.commit()
        harness.disconnect_account(ACCOUNT)

        with harness.unit_of_work() as uow:
            assert uow.accounts.delete_disconnected(ACCOUNT)
            with pytest.raises(MissingReference):
                uow.commit()
        with harness.unit_of_work() as uow:
            kept = uow.accounts.state(ACCOUNT)
            assert uow.accounts.delete_disconnected(ACCOUNT)
            uow.rules.purge(RULE.id)
            uow.commit()

        with harness.unit_of_work() as uow:
            assert (kept, uow.accounts.state(ACCOUNT)) == (ConnectedAccountState.DISCONNECTED, None)
            assert uow.rules.list() == ()

    def test_saving_an_unknown_rule_fails(self, harness: PersistenceHarness) -> None:
        with harness.unit_of_work() as uow, pytest.raises(KeyError):
            uow.rules.save(RULE)

    def test_a_relationship_has_a_direction(self, harness: PersistenceHarness) -> None:
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            assert uow.rules.relationship_exists(RULE.source, RULE.destination)
            assert not uow.rules.relationship_exists(RULE.destination, RULE.source)

    def test_removing_a_rule_takes_its_records_and_keeps_others(
        self, harness: PersistenceHarness
    ) -> None:
        series, other = _mapping("series"), _mapping("other", OTHER_RULE.id)
        source = EventRef(RULE.source, EventId("observed"))
        with harness.unit_of_work() as uow:
            for each, mapping in ((RULE, series), (OTHER_RULE, other)):
                uow.rules.add(each)
                uow.mappings.save(mapping)
                uow.replays.add(mapping.id)
                uow.cursors.save(each.id, "source-cursor")
                uow.destination_cursors.save(each.id, "destination-cursor")
                uow.run_outcomes.record(RuleRunOutcome(each.id, RunKind.SYNC, NOW, True))
                uow.previews.record(RulePreviewSummary(each.id, NOW, 1, 0))
                uow.observations.save(each.id, source, _observation(), NOW)
            uow.occurrences.save(_occurrence(series, week_start(1), "1"))
            uow.commit()

        with harness.unit_of_work() as uow:
            uow.rules.remove(RULE.id)
            uow.commit()

        with harness.unit_of_work() as uow:
            assert uow.rules.get(RULE.id) is None
            assert uow.mappings.for_rule(RULE.id) == ()
            assert uow.occurrences.for_series(series.id) == ()
            assert uow.replays.pending(RULE.id) == ()
            assert uow.cursors.get(RULE.id) is None
            assert uow.destination_cursors.get(RULE.id) is None
            assert uow.run_outcomes.latest(RULE.id, RunKind.SYNC) is None
            assert uow.previews.latest(RULE.id) is None
            assert uow.observations.get(RULE.id, source) is None
            assert uow.mappings.for_rule(OTHER_RULE.id) == (other,)
            assert uow.replays.pending(OTHER_RULE.id) == (other,)
            assert uow.cursors.get(OTHER_RULE.id) == "source-cursor"
            assert uow.previews.latest(OTHER_RULE.id) is not None
            assert uow.observations.get(OTHER_RULE.id, source) is not None

    def test_purging_a_rule_removes_it_with_its_mappings(self, harness: PersistenceHarness) -> None:
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.mappings.save(_mapping("series"))
            uow.commit()
        with harness.unit_of_work() as uow:
            uow.rules.purge(RULE.id)
            uow.commit()

        with harness.unit_of_work() as uow:
            assert uow.rules.get(RULE.id) is None
            assert uow.mappings.count_for_rule(RULE.id) == 0

    def test_removing_a_rule_resolves_its_open_incidents_when_the_unit_commits(
        self, harness: PersistenceHarness
    ) -> None:
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.rules.add(OTHER_RULE)
            uow.commit()
        incidents = harness.incidents(USER)
        for each in (RULE, OTHER_RULE):
            assert incidents.open(_rule_incident(each.id), NOW)

        with harness.unit_of_work() as uow:
            uow.rules.remove(RULE.id)
        with harness.installation() as installation:
            uncommitted = installation.status_records([USER])[USER].incidents
        with harness.unit_of_work() as uow:
            uow.rules.remove(RULE.id)
            uow.commit()
        with harness.installation() as installation:
            records = installation.status_records([USER])[USER]
            seen = installation.failure_causes(NOW - HOUR)

        assert {incident.rule_id for incident in uncommitted} == {
            RULE.id.value,
            OTHER_RULE.id.value,
        }
        assert [incident.rule_id for incident in records.incidents] == [OTHER_RULE.id.value]
        assert records.overview.open_incidents == 1
        # Resolved, not deleted: the removed rule's Incident is still a recent failure.
        assert sorted(sighting.open for sighting in seen) == [False, True]

    def test_a_unit_entered_again_forgets_the_incident_changes_it_did_not_commit(
        self, harness: PersistenceHarness
    ) -> None:
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.commit()
        assert harness.incidents(USER).open(_rule_incident(RULE.id), NOW)
        unit = harness.unit_of_work()

        with unit as uow:
            uow.rules.purge(RULE.id)
        with unit as uow:
            uow.commit()
        with harness.installation() as installation:
            records = installation.status_records([USER])[USER]

        assert [incident.rule_id for incident in records.incidents] == [RULE.id.value]

    def test_purging_a_rule_deletes_its_incidents_when_the_unit_commits(
        self, harness: PersistenceHarness
    ) -> None:
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.rules.add(OTHER_RULE)
            uow.commit()
        incidents = harness.incidents(USER)
        assert incidents.open(_rule_incident(RULE.id, key="provider:resolved"), NOW - HOUR)
        incidents.resolve("provider:resolved", NOW, IncidentResolution.SYNC_SUCCEEDED)
        for each in (RULE, OTHER_RULE):
            assert incidents.open(_rule_incident(each.id), NOW)

        with harness.unit_of_work() as uow:
            uow.rules.purge(RULE.id)
        with harness.installation() as installation:
            uncommitted = installation.failure_causes(NOW - DAY)
        with harness.unit_of_work() as uow:
            uow.rules.purge(RULE.id)
            uow.commit()
        with harness.installation() as installation:
            seen = installation.failure_causes(NOW - DAY)

        assert len(uncommitted) == 3
        assert seen == [CauseSighting(USER, Cause.CALENDAR_FORBIDDEN, NOW, True)]

    # Event Mappings

    def test_mappings_are_found_by_source_destination_and_rule(
        self, harness: PersistenceHarness
    ) -> None:
        first, second, other = _mapping("b"), _mapping("a"), _mapping("c", OTHER_RULE.id)
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.rules.add(OTHER_RULE)
            for mapping in (first, second, other):
                uow.mappings.save(mapping)
            uow.commit()

        with harness.unit_of_work() as uow:
            assert uow.mappings.for_source(RULE.id, first.source) == first
            assert uow.mappings.for_destination(RULE.id, first.destination) == first
            assert uow.mappings.for_destination(OTHER_RULE.id, first.destination) is None
            assert uow.mappings.for_rule(RULE.id) == (second, first)
            assert uow.mappings.count_for_rule(RULE.id) == 2

    def test_saving_a_mapping_again_updates_it(self, harness: PersistenceHarness) -> None:
        mapping = _mapping("series")
        updated = replace(
            mapping,
            source_revision="revision-2",
            projection_fingerprint=ProjectionFingerprint("new"),
        )
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.mappings.save(mapping)
            uow.mappings.save(updated)
            uow.commit()

        with harness.unit_of_work() as uow:
            assert uow.mappings.for_rule(RULE.id) == (updated,)

    def test_a_projection_mapped_to_another_source_is_refused(
        self, harness: PersistenceHarness
    ) -> None:
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.mappings.save(_mapping("first", destination="projection"))
            with pytest.raises(IdentityCollision):
                uow.mappings.save(_mapping("second", destination="projection"))

    def test_deleting_a_mapping_takes_its_occurrences_and_replay(
        self, harness: PersistenceHarness
    ) -> None:
        series = _mapping("series")
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.mappings.save(series)
            uow.occurrences.save(_occurrence(series, week_start(1), "1"))
            uow.replays.add(series.id)
            uow.commit()
        with harness.unit_of_work() as uow:
            uow.mappings.delete(series)
            uow.commit()

        with harness.unit_of_work() as uow:
            assert uow.occurrences.for_series(series.id) == ()
            assert uow.replays.pending(RULE.id) == ()

    # Occurrence Mappings and exception replays

    def test_occurrences_round_trip_in_start_order(self, harness: PersistenceHarness) -> None:
        timed, all_day = _mapping("timed"), _mapping("all-day")
        later = _occurrence(timed, week_start(2), "2")
        earlier = _occurrence(timed, week_start(1), "1")
        day = _occurrence(all_day, date(2026, 9, 1), "day")
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.mappings.save(timed)
            uow.mappings.save(all_day)
            for occurrence in (later, earlier, day):
                uow.occurrences.save(occurrence)
            uow.commit()

        with harness.unit_of_work() as uow:
            assert uow.occurrences.for_series(timed.id) == (earlier, later)
            assert uow.occurrences.get(all_day.id, date(2026, 9, 1)) == day
            assert uow.occurrences.get(all_day.id, date(2026, 9, 8)) is None

    def test_an_occurrence_needs_its_series_mapping(self, harness: PersistenceHarness) -> None:
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            with pytest.raises(MissingReference):
                uow.occurrences.save(_occurrence(_mapping("missing"), week_start(1), "1"))

    def test_pending_replays_follow_their_series_mapping(self, harness: PersistenceHarness) -> None:
        kept, deleted = _mapping("kept"), _mapping("deleted")
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.mappings.save(kept)
            uow.mappings.save(deleted)
            uow.replays.add(kept.id)
            uow.replays.add(kept.id)
            uow.replays.add(deleted.id)
            uow.commit()

        with harness.unit_of_work() as uow:
            assert [mapping.id for mapping in uow.replays.pending(RULE.id)] == [
                deleted.id,
                kept.id,
            ]
            uow.mappings.delete(deleted)
            uow.commit()
        with harness.unit_of_work() as uow:
            assert uow.replays.pending(RULE.id) == (kept,)
            uow.replays.remove(kept.id)
            uow.commit()
        with harness.unit_of_work() as uow:
            assert uow.replays.pending(RULE.id) == ()

    def test_a_replay_needs_its_series_mapping(self, harness: PersistenceHarness) -> None:
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            with pytest.raises(MissingReference):
                uow.replays.add(EventMappingId("missing"))

    # Cursors, outcomes, previews

    def test_source_and_destination_cursors_are_kept_apart(
        self, harness: PersistenceHarness
    ) -> None:
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.cursors.save(RULE.id, "source-1")
            uow.destination_cursors.save(RULE.id, "destination-1")
            uow.cursors.save(RULE.id, "source-2")
            uow.commit()

        with harness.unit_of_work() as uow:
            assert uow.cursors.get(RULE.id) == "source-2"
            assert uow.destination_cursors.get(RULE.id) == "destination-1"

    def test_run_outcomes_keep_the_last_successes_across_later_runs(
        self, harness: PersistenceHarness
    ) -> None:
        full = RuleRunOutcome(RULE.id, RunKind.SYNC, NOW, True, full_run=True)
        incremental = replace(full, completed_at=NOW + timedelta(days=1), full_run=False)
        failed = replace(full, completed_at=NOW + timedelta(days=2), succeeded=False)
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.run_outcomes.record(full)
            uow.run_outcomes.record(incremental)
            # A failed full run leaves the daily pass due, so it must not count as completed.
            uow.run_outcomes.record(failed)
            uow.commit()

        with harness.unit_of_work() as uow:
            latest = uow.run_outcomes.latest(RULE.id, RunKind.SYNC)
            assert uow.run_outcomes.latest(RULE.id, RunKind.RECONCILIATION) is None
        assert latest is not None
        assert latest.completed_at == failed.completed_at
        assert not latest.succeeded
        assert latest.last_succeeded_at == incremental.completed_at
        assert latest.last_full_succeeded_at == full.completed_at

    def test_a_failed_run_keeps_its_cause_and_a_success_has_none(
        self, harness: PersistenceHarness
    ) -> None:
        failed = RuleRunOutcome(
            RULE.id,
            RunKind.SYNC,
            NOW,
            False,
            failure_kind=ProviderFailureKind.AUTHORIZATION,
            failure_cause=Cause.API_DISABLED,
        )
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.run_outcomes.record(failed)
            uow.commit()
        with harness.unit_of_work() as uow:
            kept = uow.run_outcomes.latest(RULE.id, RunKind.SYNC)
            uow.run_outcomes.record(
                replace(
                    failed,
                    completed_at=NOW + DAY,
                    succeeded=True,
                    failure_kind=None,
                    failure_cause=None,
                )
            )
            uow.commit()
        with harness.unit_of_work() as uow:
            succeeded = uow.run_outcomes.latest(RULE.id, RunKind.SYNC)

        assert kept is not None
        assert kept.failure_cause is Cause.API_DISABLED
        assert succeeded is not None
        assert succeeded.failure_cause is None

    def test_a_failed_run_recorded_without_a_cause_has_none_and_suggests_nothing(
        self, harness: PersistenceHarness
    ) -> None:
        # Such as a failure the adapter raised itself, which no provider answer explains.
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.run_outcomes.record(
                RuleRunOutcome(
                    RULE.id, RunKind.SYNC, NOW, False, failure_kind=ProviderFailureKind.TEMPORARY
                )
            )
            uow.commit()
        with harness.unit_of_work() as uow:
            latest = uow.run_outcomes.latest(RULE.id, RunKind.SYNC)
        with harness.installation() as installation:
            seen = installation.failure_causes(NOW - timedelta(hours=1))

        assert latest is not None
        assert latest.failure_kind is ProviderFailureKind.TEMPORARY
        assert latest.failure_cause is None
        assert list(seen) == []

    def test_failure_causes_name_each_users_failed_runs_since_a_time(
        self, harness: PersistenceHarness
    ) -> None:
        failed = RuleRunOutcome(
            RULE.id,
            RunKind.SYNC,
            NOW,
            False,
            failure_kind=ProviderFailureKind.AUTHORIZATION,
            failure_cause=Cause.API_DISABLED,
            failure_provider=ProviderKind.GOOGLE,
        )
        older = replace(failed, rule_id=OTHER_RULE.id, completed_at=NOW - DAY)
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.rules.add(OTHER_RULE)
            uow.run_outcomes.record(failed)
            uow.run_outcomes.record(older)
            uow.commit()
        theirs = replace(
            RULE, id=SyncRuleId("their-rule"), source=THEIR_SOURCE, destination=THEIR_DESTINATION
        )
        for account in (THEIR_SOURCE, THEIR_DESTINATION):
            harness.connect_account(account.connected_account_id, OTHER_USER)
        with harness.units(OTHER_USER)() as uow:
            uow.rules.add(theirs)
            uow.run_outcomes.record(RuleRunOutcome(theirs.id, RunKind.SYNC, NOW, True))
            uow.commit()

        with harness.installation() as installation:
            seen = installation.failure_causes(NOW - timedelta(hours=1))

        # Only who, why, and which provider said so: never which rule, calendar, or account.
        assert list(seen) == [
            CauseSighting(USER, Cause.API_DISABLED, NOW, False, provider=ProviderKind.GOOGLE)
        ]

    def test_users_with_unfinished_lapses_have_a_rule_a_lapse_alone_stopped(
        self, harness: PersistenceHarness
    ) -> None:
        theirs = replace(
            RULE, id=SyncRuleId("their-rule"), source=THEIR_SOURCE, destination=THEIR_DESTINATION
        )
        for account in (THEIR_SOURCE, THEIR_DESTINATION):
            harness.connect_account(account.connected_account_id, OTHER_USER)
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE.degrade(awaiting_reauthorization=True))
            uow.rules.add(OTHER_RULE)
            uow.commit()
        with harness.units(OTHER_USER)() as uow:
            # Stopped for another reason, so recovering needs a preview, not an account.
            uow.rules.add(theirs.degrade())
            uow.commit()

        with harness.installation() as installation:
            unfinished = list(installation.users_with_unfinished_lapses())
        harness.disable(USER)
        with harness.installation() as installation:
            while_disabled = list(installation.users_with_unfinished_lapses())

        assert (unfinished, while_disabled) == ([USER], [])

    def test_users_with_unfinished_lapses_have_an_authorized_account_with_its_incident_open(
        self, harness: PersistenceHarness
    ) -> None:
        harness.connect_account(ACCOUNT)
        harness.connect_account(THEIR_ACCOUNT, OTHER_USER)
        _lapse(harness, ACCOUNT, USER)
        # Still lapsed, so its open Incident is no unfinished restoration.
        _lapse(harness, THEIR_ACCOUNT, OTHER_USER)
        with harness.unit_of_work() as uow:
            assert uow.accounts.clear_lapse(ACCOUNT, requested_before=NOW)
            uow.commit()

        with harness.installation() as installation:
            unfinished = list(installation.users_with_unfinished_lapses())
        harness.incidents(USER).resolve(
            _account_incident(ACCOUNT).key,
            NOW,
            IncidentResolution.ACCESS_RESTORED,
            while_authorized=ACCOUNT,
        )
        with harness.installation() as installation:
            once_resolved = list(installation.users_with_unfinished_lapses())

        assert (unfinished, once_resolved) == ([USER], [])

    def test_a_local_failure_has_no_cause_and_suggests_nothing(
        self, harness: PersistenceHarness
    ) -> None:
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.run_outcomes.record(
                RuleRunOutcome(
                    RULE.id,
                    RunKind.SYNC,
                    NOW,
                    False,
                    failure_kind=ProviderFailureKind.INFRASTRUCTURE,
                )
            )
            uow.commit()
        with harness.unit_of_work() as uow:
            latest = uow.run_outcomes.latest(RULE.id, RunKind.SYNC)
        with harness.installation() as installation:
            seen = installation.failure_causes(NOW - timedelta(hours=1))

        assert latest is not None
        assert latest.failure_cause is None
        assert list(seen) == []

    def test_the_latest_preview_replaces_the_previous(self, harness: PersistenceHarness) -> None:
        later = RulePreviewSummary(RULE.id, NOW + timedelta(hours=1), 5, 2, 1, 3)
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.previews.record(RulePreviewSummary(RULE.id, NOW, 1, 0))
            uow.previews.record(later)
            uow.commit()

        with harness.unit_of_work() as uow:
            assert uow.previews.latest(RULE.id) == later

    # Source Observations

    def test_stale_observations_are_forgotten_and_series_kept(
        self, harness: PersistenceHarness
    ) -> None:
        current = EventRef(RULE.source, EventId("current"))
        ended = EventRef(RULE.source, EventId("ended"))
        series = EventRef(RULE.source, EventId("series"))
        elsewhere = EventRef(endpoint("personal-account", "old-calendar"), EventId("elsewhere"))
        past = NOW - timedelta(days=100)
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.observations.save(RULE.id, current, _observation(), NOW)
            uow.observations.save(RULE.id, ended, _observation(past), NOW)
            uow.observations.save(RULE.id, series, _observation(past, ("RRULE:FREQ=WEEKLY",)), NOW)
            uow.observations.save(RULE.id, elsewhere, _observation(), NOW)
            uow.commit()
        with harness.unit_of_work() as uow:
            uow.observations.forget_stale(RULE.id, RULE.source, NOW - timedelta(days=90))
            uow.commit()

        with harness.unit_of_work() as uow:
            assert uow.observations.get(RULE.id, current) == _observation()
            assert uow.observations.get(RULE.id, ended) is None
            assert uow.observations.get(RULE.id, series) is not None
            assert uow.observations.get(RULE.id, elsewhere) is None

    # Connected Accounts and calendar names

    def test_only_a_disconnected_account_is_deleted(self, harness: PersistenceHarness) -> None:
        harness.connect_account(ACCOUNT)
        with harness.unit_of_work() as uow:
            assert uow.accounts.state(ACCOUNT) is ConnectedAccountState.CONNECTED
            assert not uow.accounts.delete_disconnected(ACCOUNT)
        harness.disconnect_account(ACCOUNT)
        with harness.unit_of_work() as uow:
            assert uow.accounts.state(ACCOUNT) is ConnectedAccountState.DISCONNECTED
            assert uow.accounts.delete_disconnected(ACCOUNT)
            uow.commit()

        with harness.unit_of_work() as uow:
            assert uow.accounts.state(ACCOUNT) is None
            assert not uow.accounts.delete_disconnected(ACCOUNT)

    def test_deleting_an_account_deletes_its_own_incidents_when_the_unit_commits(
        self, harness: PersistenceHarness
    ) -> None:
        work = RULE.destination.connected_account_id
        for account in (ACCOUNT, work):
            harness.connect_account(account)
            _lapse(harness, account, USER)
        incidents = harness.incidents(USER)
        # A rule's Incident naming the account is the rule's, so it stays.
        assert incidents.open(_rule_incident(OTHER_RULE.id), NOW)
        harness.disconnect_account(ACCOUNT)

        with harness.unit_of_work() as uow:
            assert uow.accounts.delete_disconnected(ACCOUNT)
        uncommitted = incidents.accounts_with_open_incidents()
        with harness.unit_of_work() as uow:
            assert uow.accounts.delete_disconnected(ACCOUNT)
            uow.commit()
        with harness.installation() as installation:
            kept = installation.status_records([USER])[USER].incidents

        assert uncommitted == {ACCOUNT, work}
        assert incidents.accounts_with_open_incidents() == {work}
        assert sorted((incident.rule_id or "", incident.account_id) for incident in kept) == [
            ("", work.value),
            (OTHER_RULE.id.value, work.value),
        ]

    def test_a_connected_account_stays_lapsed_until_its_lapse_clears(
        self, harness: PersistenceHarness
    ) -> None:
        harness.connect_account(ACCOUNT)
        with harness.unit_of_work() as uow:
            assert uow.accounts.authorized(ACCOUNT)
            assert uow.accounts.lapse(ACCOUNT, attempted_at=NOW)
            assert uow.accounts.lapse(ACCOUNT, attempted_at=NOW)
            uow.commit()

        with harness.unit_of_work() as uow:
            assert not uow.accounts.authorized(ACCOUNT)
            # A lapse recorded after the provider accepted the account stands.
            assert not uow.accounts.clear_lapse(
                ACCOUNT, requested_before=NOW - timedelta(seconds=1)
            )
            assert uow.accounts.clear_lapse(ACCOUNT, requested_before=NOW)
            assert not uow.accounts.clear_lapse(ACCOUNT, requested_before=NOW)
            uow.commit()
        with harness.unit_of_work() as uow:
            assert uow.accounts.authorized(ACCOUNT)

    def test_a_request_made_before_the_last_authorization_lapses_nothing(
        self, harness: PersistenceHarness
    ) -> None:
        # The account was authorized at NOW; this request used the credentials it replaced.
        harness.connect_account(ACCOUNT)
        with harness.unit_of_work() as uow:
            assert not uow.accounts.lapse(ACCOUNT, attempted_at=NOW - timedelta(minutes=1))
            uow.commit()
        with harness.unit_of_work() as uow:
            assert uow.accounts.authorized(ACCOUNT)

    def test_only_a_connected_account_lapses(self, harness: PersistenceHarness) -> None:
        missing = ConnectedAccountId("missing")
        harness.connect_account(ACCOUNT)
        harness.disconnect_account(ACCOUNT)
        with harness.unit_of_work() as uow:
            assert not uow.accounts.lapse(ACCOUNT, attempted_at=NOW)
            assert not uow.accounts.lapse(missing, attempted_at=NOW)
            assert not uow.accounts.authorized(ACCOUNT)
            assert not uow.accounts.authorized(missing)

    def test_users_with_unfinished_lapses_have_a_lapsed_account_with_a_rule_still_enabled(
        self, harness: PersistenceHarness
    ) -> None:
        for account in RULE.source, RULE.destination:
            harness.connect_account(account.connected_account_id)
        harness.connect_account(THEIR_ACCOUNT, OTHER_USER)
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.commit()
        _lapse(harness, ACCOUNT, USER)
        # Lapsed with its Incident open and no rule enabled: nothing is left to finish.
        _lapse(harness, THEIR_ACCOUNT, OTHER_USER)

        with harness.installation() as installation:
            unfinished = list(installation.users_with_unfinished_lapses())
        with harness.unit_of_work() as uow:
            uow.rules.save(RULE.pause())
            uow.commit()
        with harness.installation() as installation:
            once_paused = list(installation.users_with_unfinished_lapses())

        assert (unfinished, once_paused) == ([USER], [])

    def test_users_with_unfinished_lapses_have_a_lapsed_account_without_its_incident(
        self, harness: PersistenceHarness
    ) -> None:
        harness.connect_account(ACCOUNT)
        with harness.unit_of_work() as uow:
            assert uow.accounts.lapse(ACCOUNT, attempted_at=NOW)
            uow.commit()

        with harness.installation() as installation:
            unfinished = list(installation.users_with_unfinished_lapses())
        assert harness.incidents(USER).open(_account_incident(ACCOUNT), NOW, refresh=False)
        with harness.installation() as installation:
            once_opened = list(installation.users_with_unfinished_lapses())

        assert (unfinished, once_opened) == ([USER], [])

    def test_an_open_incident_opened_without_refreshing_is_not_opened_again(
        self, harness: PersistenceHarness
    ) -> None:
        harness.connect_account(ACCOUNT)
        _lapse(harness, ACCOUNT, USER)
        incidents = harness.incidents(USER)

        assert not incidents.open(_account_incident(ACCOUNT), NOW, refresh=False)
        assert incidents.accounts_with_open_incidents() == {ACCOUNT}

    def test_lapsed_accounts_are_the_connected_ones_whose_authorization_lapsed(
        self, harness: PersistenceHarness
    ) -> None:
        disconnected = ConnectedAccountId("work-account")
        for account in ACCOUNT, disconnected:
            harness.connect_account(account)
        with harness.unit_of_work() as uow:
            assert uow.accounts.lapsed() == {}
            for account in ACCOUNT, disconnected:
                assert uow.accounts.lapse(account, attempted_at=NOW)
            uow.commit()
        harness.disconnect_account(disconnected)

        with harness.unit_of_work() as uow:
            assert uow.accounts.lapsed() == {ACCOUNT: ProviderKind.GOOGLE}
        with harness.units(OTHER_USER)() as uow:
            assert uow.accounts.lapsed() == {}

    def test_an_accounts_incident_opens_only_while_the_account_is_lapsed(
        self, harness: PersistenceHarness
    ) -> None:
        harness.connect_account(ACCOUNT)
        incidents = harness.incidents(USER)
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.commit()

        assert not incidents.open(_account_incident(ACCOUNT), NOW)
        # A rule's Incident is not its account's, even when it names the account.
        rules = IncidentReport(
            "provider:rule-1", RULE.id, IncidentCategory.TEMPORARY, "x", account_id=ACCOUNT
        )
        assert incidents.open(rules, NOW)
        assert incidents.accounts_with_open_incidents() == frozenset()
        _lapse(harness, ACCOUNT, USER)

        assert not incidents.open(_account_incident(ACCOUNT), NOW)
        assert incidents.accounts_with_open_incidents() == {ACCOUNT}
        assert harness.incidents(OTHER_USER).accounts_with_open_incidents() == frozenset()

    def test_an_accounts_incident_resolves_only_while_the_account_is_authorized(
        self, harness: PersistenceHarness
    ) -> None:
        harness.connect_account(ACCOUNT)
        incidents = harness.incidents(USER)
        key = _account_incident(ACCOUNT).key
        _lapse(harness, ACCOUNT, USER)

        incidents.resolve(key, NOW, IncidentResolution.ACCESS_RESTORED, while_authorized=ACCOUNT)
        while_lapsed = incidents.accounts_with_open_incidents()
        with harness.unit_of_work() as uow:
            assert uow.accounts.clear_lapse(ACCOUNT, requested_before=NOW)
            uow.commit()
        incidents.resolve(key, NOW, IncidentResolution.ACCESS_RESTORED, while_authorized=ACCOUNT)

        assert (while_lapsed, incidents.accounts_with_open_incidents()) == (
            frozenset({ACCOUNT}),
            frozenset(),
        )
        # A new lapse opens it again, as a new episode.
        _lapse(harness, ACCOUNT, USER)

    def test_calendar_names_belong_to_an_existing_account_and_go_with_it(
        self, harness: PersistenceHarness
    ) -> None:
        family = CalendarEndpoint(ACCOUNT, CalendarId("family"))
        work = CalendarEndpoint(ACCOUNT, CalendarId("work"))
        missing = ConnectedAccountId("missing")
        harness.connect_account(ACCOUNT)
        with harness.unit_of_work() as uow:
            uow.calendar_names.remember(ACCOUNT, [_calendar("family", "Family")])
            uow.calendar_names.remember(missing, [_calendar("other", "Other")])
            uow.calendar_names.remember(ACCOUNT, [_calendar("family", "Household")])
            uow.commit()

        with harness.unit_of_work() as uow:
            assert uow.calendar_names.names([family, work]) == {family: "Household"}
            assert uow.calendar_names.names([CalendarEndpoint(missing, CalendarId("other"))]) == {}
            assert uow.calendar_names.names([]) == {}
        harness.disconnect_account(ACCOUNT)
        with harness.unit_of_work() as uow:
            assert uow.accounts.delete_disconnected(ACCOUNT)
            uow.commit()
        with harness.unit_of_work() as uow:
            assert uow.calendar_names.names([family]) == {}

    def test_a_calendar_its_provider_gave_no_name_is_remembered_without_one(
        self, harness: PersistenceHarness
    ) -> None:
        family = CalendarEndpoint(ACCOUNT, CalendarId("family"))
        harness.connect_account(ACCOUNT)
        unnamed = replace(_calendar("family", "family"), named=False)
        with harness.unit_of_work() as uow:
            uow.calendar_names.remember(ACCOUNT, [_calendar("family", "Family")])
            uow.calendar_names.remember(ACCOUNT, [unnamed])
            uow.commit()

        # Its label, such as its identifier, is no name, so a rule never shows it as one.
        with harness.unit_of_work() as uow:
            assert uow.calendar_names.names([family]) == {family: ""}

    # Records need their rule, and identities stay unique

    def test_records_of_a_rule_that_does_not_exist_are_refused(
        self, harness: PersistenceHarness
    ) -> None:
        source = EventRef(RULE.source, EventId("observed"))
        writes: tuple[Callable[[UnitOfWork], object], ...] = (
            lambda uow: uow.mappings.save(_mapping("series")),
            lambda uow: uow.cursors.save(RULE.id, "cursor"),
            lambda uow: uow.destination_cursors.save(RULE.id, "cursor"),
            lambda uow: uow.run_outcomes.record(RuleRunOutcome(RULE.id, RunKind.SYNC, NOW, True)),
            lambda uow: uow.previews.record(RulePreviewSummary(RULE.id, NOW, 1, 0)),
            lambda uow: uow.observations.save(RULE.id, source, _observation(), NOW),
        )
        for write in writes:
            with harness.unit_of_work() as uow, pytest.raises(MissingReference):
                write(uow)

    def test_a_second_mapping_for_one_source_is_refused(self, harness: PersistenceHarness) -> None:
        first = _mapping("first")
        again = replace(_mapping("second"), source=first.source)
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.mappings.save(first)
            with pytest.raises(IdentityCollision):
                uow.mappings.save(again)

    def test_saving_a_mapping_again_keeps_its_rule_and_source(
        self, harness: PersistenceHarness
    ) -> None:
        mapping = _mapping("series")
        moved = replace(
            mapping,
            source=EventRef(RULE.source, EventId("elsewhere")),
            destination=EventRef(RULE.destination, EventId("new-projection")),
            source_revision="revision-2",
        )
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.mappings.save(mapping)
            uow.mappings.save(moved)
            uow.commit()

        with harness.unit_of_work() as uow:
            # A mapping's rule and source never change; its projection and revision do.
            assert uow.mappings.for_rule(RULE.id) == (replace(moved, source=mapping.source),)
            assert uow.mappings.for_source(RULE.id, moved.source) is None

    def test_saving_an_occurrence_again_keeps_its_identifier(
        self, harness: PersistenceHarness
    ) -> None:
        series = _mapping("series")
        first = _occurrence(series, week_start(1), "1")
        renamed = replace(first, id=OccurrenceMappingId("other"), source_revision="revision-2")
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.mappings.save(series)
            uow.occurrences.save(first)
            uow.occurrences.save(renamed)
            uow.commit()

        with harness.unit_of_work() as uow:
            assert uow.occurrences.for_series(series.id) == (replace(renamed, id=first.id),)

    def test_one_occurrence_identifier_names_one_occurrence(
        self, harness: PersistenceHarness
    ) -> None:
        series = _mapping("series")
        first = _occurrence(series, week_start(1), "1")
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.mappings.save(series)
            uow.occurrences.save(first)
            with pytest.raises(IdentityCollision):
                uow.occurrences.save(replace(first, original_start=week_start(2)))

    # Users (ADR 0029): another User can neither read, change, nor delete these records. The two
    # Users' rules name identical calendar and event identifiers, so only the User tells them apart.

    def _seed_first_user(self, harness: PersistenceHarness) -> tuple[EventMapping, EventRef]:
        """User A's rule with one record of every kind; returns its series mapping and source."""
        series = _mapping("series")
        source = EventRef(RULE.source, EventId("observed"))
        harness.connect_account(ACCOUNT)
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.mappings.save(series)
            uow.occurrences.save(_occurrence(series, week_start(1), "1"))
            uow.replays.add(series.id)
            uow.cursors.save(RULE.id, "source-cursor")
            uow.destination_cursors.save(RULE.id, "destination-cursor")
            uow.run_outcomes.record(RuleRunOutcome(RULE.id, RunKind.SYNC, NOW, True))
            uow.previews.record(RulePreviewSummary(RULE.id, NOW, 1, 0))
            uow.observations.save(RULE.id, source, _observation(), NOW)
            uow.calendar_names.remember(ACCOUNT, [_calendar("personal-calendar", "Family")])
            uow.accounts.lapse(ACCOUNT, attempted_at=NOW)
            uow.commit()
        for account in (THEIR_SOURCE, THEIR_DESTINATION):
            harness.connect_account(account.connected_account_id, OTHER_USER)
        return series, source

    def _assert_first_user_unchanged(
        self, harness: PersistenceHarness, series: EventMapping, source: EventRef
    ) -> None:
        with harness.unit_of_work() as uow:
            assert uow.rules.list() == (RULE,)
            assert uow.mappings.for_rule(RULE.id) == (series,)
            assert len(uow.occurrences.for_series(series.id)) == 1
            assert uow.replays.pending(RULE.id) == (series,)
            assert uow.cursors.get(RULE.id) == "source-cursor"
            assert uow.destination_cursors.get(RULE.id) == "destination-cursor"
            assert uow.run_outcomes.latest(RULE.id, RunKind.SYNC) is not None
            assert uow.previews.latest(RULE.id) == RulePreviewSummary(RULE.id, NOW, 1, 0)
            assert uow.observations.get(RULE.id, source) == _observation()
            assert uow.calendar_names.names([RULE.source]) == {RULE.source: "Family"}
            assert uow.accounts.state(ACCOUNT) is ConnectedAccountState.CONNECTED
            assert not uow.accounts.authorized(ACCOUNT)

    def test_another_user_reads_none_of_a_users_records(self, harness: PersistenceHarness) -> None:
        series, source = self._seed_first_user(harness)
        mapped_destination = series.destination

        with harness.units(OTHER_USER)() as uow:
            assert uow.rules.get(RULE.id) is None
            assert uow.rules.list() == ()
            assert not uow.rules.relationship_exists(RULE.source, RULE.destination)
            assert uow.mappings.for_source(RULE.id, series.source) is None
            assert uow.mappings.for_destination(RULE.id, mapped_destination) is None
            assert uow.mappings.for_rule(RULE.id) == ()
            assert uow.mappings.count_for_rule(RULE.id) == 0
            assert uow.occurrences.for_series(series.id) == ()
            assert uow.occurrences.get(series.id, week_start(1)) is None
            assert uow.replays.pending(RULE.id) == ()
            assert uow.cursors.get(RULE.id) is None
            assert uow.destination_cursors.get(RULE.id) is None
            assert uow.run_outcomes.latest(RULE.id, RunKind.SYNC) is None
            assert uow.previews.latest(RULE.id) is None
            assert uow.observations.get(RULE.id, source) is None
            assert uow.calendar_names.names([RULE.source]) == {}
            assert uow.accounts.state(ACCOUNT) is None
            assert not uow.accounts.authorized(ACCOUNT)

    def test_another_user_reads_only_their_own_records_with_the_same_identifiers(
        self, harness: PersistenceHarness
    ) -> None:
        self._seed_first_user(harness)
        theirs = replace(RULE, id=SyncRuleId("their-rule"), source=THEIR_SOURCE)
        their_theirs = replace(theirs, destination=THEIR_DESTINATION)

        with harness.units(OTHER_USER)() as uow:
            uow.rules.add(their_theirs)
            uow.calendar_names.remember(
                THEIR_SOURCE.connected_account_id, [_calendar("personal-calendar", "Theirs")]
            )
            uow.commit()

        with harness.units(OTHER_USER)() as uow:
            assert uow.rules.list() == (their_theirs,)
            assert uow.calendar_names.names([THEIR_SOURCE, RULE.source]) == {THEIR_SOURCE: "Theirs"}
        with harness.unit_of_work() as uow:
            assert uow.rules.list() == (RULE,)

    def test_another_user_changes_none_of_a_users_records(
        self, harness: PersistenceHarness
    ) -> None:
        series, source = self._seed_first_user(harness)
        # Another User's rule and series are missing to this User; their identifiers are taken.
        writes: tuple[tuple[type[Exception], Callable[[UnitOfWork], object]], ...] = (
            (KeyError, lambda uow: uow.rules.save(RULE.pause())),
            (
                IdentityCollision,
                lambda uow: uow.mappings.save(replace(series, source_revision="theirs")),
            ),
            (
                MissingReference,
                lambda uow: uow.mappings.save(replace(_mapping("theirs"), rule_id=RULE.id)),
            ),
            (
                MissingReference,
                lambda uow: uow.occurrences.save(_occurrence(series, week_start(2), "theirs")),
            ),
            (MissingReference, lambda uow: uow.replays.add(series.id)),
            (MissingReference, lambda uow: uow.cursors.save(RULE.id, "their-cursor")),
            (MissingReference, lambda uow: uow.destination_cursors.save(RULE.id, "their-cursor")),
            (
                MissingReference,
                lambda uow: uow.run_outcomes.record(
                    RuleRunOutcome(RULE.id, RunKind.SYNC, NOW, False)
                ),
            ),
            (
                MissingReference,
                lambda uow: uow.previews.record(RulePreviewSummary(RULE.id, NOW, 9, 9)),
            ),
            (
                MissingReference,
                lambda uow: uow.observations.save(RULE.id, source, _observation(NOW + DAY), NOW),
            ),
        )
        for refusal, write in writes:
            with pytest.raises(refusal):
                _commit_as(harness, OTHER_USER, write)
        with harness.units(OTHER_USER)() as uow:
            uow.calendar_names.remember(ACCOUNT, [_calendar("personal-calendar", "Renamed")])
            assert not uow.accounts.lapse(ACCOUNT, attempted_at=NOW + DAY)
            assert not uow.accounts.clear_lapse(ACCOUNT, requested_before=NOW + DAY)
            uow.commit()

        self._assert_first_user_unchanged(harness, series, source)

    def test_another_user_deletes_none_of_a_users_records(
        self, harness: PersistenceHarness
    ) -> None:
        series, source = self._seed_first_user(harness)
        harness.disconnect_account(ACCOUNT)

        with harness.units(OTHER_USER)() as uow:
            uow.rules.remove(RULE.id)
            uow.rules.purge(RULE.id)
            uow.mappings.delete(series)
            uow.occurrences.delete(_occurrence(series, week_start(1), "1"))
            uow.replays.remove(series.id)
            uow.observations.forget_stale(RULE.id, THEIR_SOURCE, NOW + DAY * 365)
            assert not uow.accounts.delete_disconnected(ACCOUNT)
            uow.commit()

        with harness.unit_of_work() as uow:
            assert uow.accounts.state(ACCOUNT) is ConnectedAccountState.DISCONNECTED
        harness.connect_account(ACCOUNT)
        with harness.unit_of_work() as uow:
            uow.accounts.lapse(ACCOUNT, attempted_at=NOW + DAY)
            uow.commit()
        self._assert_first_user_unchanged(harness, series, source)

    def test_a_rule_taking_another_users_identifier_or_account_is_refused(
        self, harness: PersistenceHarness
    ) -> None:
        self._seed_first_user(harness)
        same_identifier = replace(RULE, source=THEIR_SOURCE, destination=THEIR_DESTINATION)
        their_account = replace(RULE, id=SyncRuleId("their-rule"), destination=THEIR_DESTINATION)

        # The identifier is refused when the rule is added; the account when the unit commits.
        for refusal, refused in (
            (IdentityCollision, same_identifier),
            (MissingReference, their_account),
        ):

            def add(uow: UnitOfWork, rule_: SyncRule = refused) -> None:
                uow.rules.add(rule_)

            with pytest.raises(refusal):
                _commit_as(harness, OTHER_USER, add)

        with harness.units(OTHER_USER)() as uow:
            assert uow.rules.list() == ()

    # What the Operator Overview reads across Users

    def test_status_records_hold_each_users_rules_in_the_order_they_were_created(
        self, harness: PersistenceHarness
    ) -> None:
        theirs = replace(
            RULE, id=SyncRuleId("rule-00"), source=THEIR_SOURCE, destination=THEIR_DESTINATION
        )
        for account in (THEIR_SOURCE, THEIR_DESTINATION):
            harness.connect_account(account.connected_account_id, OTHER_USER)
        outcome = RuleRunOutcome(OTHER_RULE.id, RunKind.SYNC, NOW, True)
        preview = RulePreviewSummary(RULE.id, NOW, 3, 1)
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.rules.add(OTHER_RULE)
            uow.run_outcomes.record(outcome)
            uow.previews.record(preview)
            uow.commit()
        _commit_as(harness, OTHER_USER, lambda uow: uow.rules.add(theirs))
        with harness.unit_of_work() as uow:
            # Saving a rule again keeps its place.
            uow.rules.save(RULE.pause())
            uow.commit()

        with harness.installation() as installation:
            records = installation.status_records([USER, OTHER_USER])

        assert records[USER].rules == (
            RecordedRule(RULE.pause(), None, preview),
            RecordedRule(OTHER_RULE, replace(outcome, last_succeeded_at=NOW), None),
        )
        assert records[OTHER_USER].rules == (RecordedRule(theirs, None, None),)

    def test_a_replacement_ranks_where_the_rule_it_replaced_ranked(
        self, harness: PersistenceHarness
    ) -> None:
        successor = replace(
            RULE,
            id=SyncRuleId("rule-9"),
            destination=endpoint("work-account", "replacement-calendar"),
            state=SyncRuleState.DRAFT,
        )
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.rules.add(OTHER_RULE)
            uow.commit()
        with harness.unit_of_work() as uow:
            # As a Rule Replacement moves a place: in the step that begins the old rule's removal.
            uow.rules.save(RULE.begin_removal())
            uow.rules.add(successor.take_place_of(RULE))
            uow.rules.inherit_place(successor.id, of=RULE.id)
            uow.commit()
        with harness.unit_of_work() as uow:
            uow.rules.remove(RULE.id)
            uow.commit()

        with harness.installation() as installation:
            records = installation.status_records([USER])[USER]
        with harness.unit_of_work() as uow:
            listed = uow.rules.list()

        # Created after OTHER_RULE and sorting after it by identifier, it ranks first all the same.
        assert [recorded.rule.id for recorded in records.rules] == [successor.id, OTHER_RULE.id]
        assert records.rules[0].rule.keeps_place
        # Listing keeps its order by identifier, so the Rules page does not change.
        assert [each.id for each in listed] == [OTHER_RULE.id, successor.id]

    def test_a_place_passes_only_between_rules_of_one_user(
        self, harness: PersistenceHarness
    ) -> None:
        for account in (THEIR_SOURCE, THEIR_DESTINATION):
            harness.connect_account(account.connected_account_id, OTHER_USER)
        their_first = replace(
            RULE, id=SyncRuleId("their-b"), source=THEIR_SOURCE, destination=THEIR_DESTINATION
        )
        their_second = replace(
            their_first,
            id=SyncRuleId("their-a"),
            destination=endpoint(THEIR_DESTINATION.connected_account_id.value, "other-calendar"),
        )
        # Created in turns, so the two Users' rules interleave, and each User's identifiers sort
        # against the order they were created in.
        _commit_as(harness, OTHER_USER, lambda uow: uow.rules.add(their_first))
        _commit_as(harness, USER, lambda uow: uow.rules.add(RULE))
        _commit_as(harness, OTHER_USER, lambda uow: uow.rules.add(their_second))
        _commit_as(harness, USER, lambda uow: uow.rules.add(OTHER_RULE))

        with harness.unit_of_work() as uow:
            uow.rules.inherit_place(OTHER_RULE.id, of=their_first.id)
            uow.rules.inherit_place(their_first.id, of=OTHER_RULE.id)
            uow.commit()
        with harness.installation() as installation:
            records = installation.status_records([USER, OTHER_USER])

        assert [recorded.rule.id for recorded in records[USER].rules] == [RULE.id, OTHER_RULE.id]
        assert [recorded.rule.id for recorded in records[OTHER_USER].rules] == [
            their_first.id,
            their_second.id,
        ]

    def test_status_records_hold_each_users_accounts_and_last_sync(
        self, harness: PersistenceHarness
    ) -> None:
        for account in (RULE.source, RULE.destination):
            harness.connect_account(account.connected_account_id)
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.run_outcomes.record(RuleRunOutcome(RULE.id, RunKind.SYNC, NOW, True))
            uow.accounts.lapse(ACCOUNT, attempted_at=NOW + DAY)
            uow.commit()
        harness.disconnect_account(RULE.destination.connected_account_id)
        harness.connect_account(THEIR_SOURCE.connected_account_id, OTHER_USER)

        with harness.installation() as installation:
            records = installation.status_records([USER, OTHER_USER])

        mine, theirs = records[USER].overview, records[OTHER_USER].overview
        assert mine.accounts == (
            AccountStanding(
                "personal-account",
                ConnectedAccountState.CONNECTED,
                ProviderKind.GOOGLE,
                lapsed=True,
            ),
            AccountStanding(
                "work-account", ConnectedAccountState.DISCONNECTED, ProviderKind.GOOGLE
            ),
        )
        assert (mine.connected_accounts, mine.disconnected_accounts) == (1, 1)
        assert mine.last_synced_at == NOW
        assert theirs.accounts == (
            AccountStanding(
                "their-personal-account", ConnectedAccountState.CONNECTED, ProviderKind.GOOGLE
            ),
        )
        assert theirs.last_synced_at is None
        assert records[OTHER_USER].rules == ()

    def test_status_records_hold_each_users_open_incidents_most_recently_updated_first(
        self, harness: PersistenceHarness
    ) -> None:
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.commit()
        harness.disconnect_account(RULE.destination.connected_account_id)
        incidents = harness.incidents(USER)
        assert incidents.open(_rule_incident(RULE.id), NOW)
        assert incidents.open(_rule_incident(OTHER_RULE.id), NOW + HOUR)
        # Refreshing keeps when it opened; a resolved one is no longer read.
        assert not incidents.open(_rule_incident(RULE.id, Cause.API_DISABLED), NOW + 2 * HOUR)
        assert incidents.open(_rule_incident(RULE.id, key="provider:resolved"), NOW)
        incidents.resolve("provider:resolved", NOW, IncidentResolution.SYNC_SUCCEEDED)
        assert harness.incidents(OTHER_USER).open(_rule_incident(SyncRuleId("theirs")), NOW)

        with harness.installation() as installation:
            records = installation.status_records([USER, OTHER_USER])

        mine = records[USER]
        assert mine.overview.open_incidents == 2
        assert [
            (each.rule_id, each.state, each.opened_at, each.updated_at, each.cause)
            for each in mine.incidents
        ] == [
            (RULE.id.value, "open", NOW, NOW + 2 * HOUR, Cause.API_DISABLED),
            (OTHER_RULE.id.value, "open", NOW + HOUR, NOW + HOUR, Cause.CALENDAR_FORBIDDEN),
        ]
        refreshed, of_no_rule = mine.incidents
        assert (refreshed.category, refreshed.summary, refreshed.account_id) == (
            IncidentCategory.PERMANENT,
            "Google Calendar rejected synchronization",
            RULE.destination.connected_account_id.value,
        )
        # Its rule and the rule's accounts as they are now, which its next step weighs.
        assert refreshed.rule_exists
        assert refreshed.rule_accounts == (
            AccountAuthorization(RULE.source.connected_account_id, True, NOW),
            AccountAuthorization(RULE.destination.connected_account_id, False, None),
        )
        assert (of_no_rule.rule_exists, of_no_rule.rule_accounts) == (False, ())
        assert [each.rule_id for each in records[OTHER_USER].incidents] == ["theirs"]

    def test_the_latest_entry_for_an_event_is_its_previous_decision(
        self, harness: PersistenceHarness
    ) -> None:
        first = _skip("seminar", SyncReason.SERIES_NOT_SYNCHRONIZED)
        latest = _skip("seminar", SyncReason.SERIES_WITHOUT_OCCURRENCES)
        other_event = _skip("other", SyncReason.DECLINED)
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.rules.add(OTHER_RULE)
            for entry in (first, latest, other_event):
                uow.audit.append(entry)
            uow.commit()

        with harness.unit_of_work() as uow:
            assert uow.audit.latest_for(RULE.id, "seminar") == RecordedDecision.of(latest)
            assert uow.audit.latest_for(RULE.id, "missing") is None
            assert uow.audit.latest_for(OTHER_RULE.id, "seminar") is None

    def test_the_previous_decision_keeps_an_all_day_event_and_a_missing_one(
        self, harness: PersistenceHarness
    ) -> None:
        holiday = _skip(
            "holiday",
            SyncReason.DECLINED,
            AllDayRange(date(2026, 10, 15), date(2026, 10, 17)),
        )
        unseen = replace(_skip("unseen", SyncReason.DECLINED), event=None)
        untimed = replace(
            _skip("untimed", SyncReason.DECLINED),
            event=RecordedEvent(title="Gone", cancelled=True),
        )
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            for entry in (holiday, unseen, untimed):
                uow.audit.append(entry)
            uow.commit()

        with harness.unit_of_work() as uow:
            for entry in (holiday, unseen, untimed):
                assert uow.audit.latest_for(RULE.id, entry.source_event_id or "") == (
                    RecordedDecision.of(entry)
                )

    def test_status_records_hold_each_users_open_blocks_newest_first(
        self, harness: PersistenceHarness
    ) -> None:
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.rules.add(OTHER_RULE)
            for entry in (
                _block(RULE.id, "cleared"),
                _block(RULE.id, "blocked"),
                AuditEntry(NOW, RULE.id, AuditAction.CREATE, AuditOutcome.COMPLETED, "cleared"),
                # Recurring exclusions were recorded as conflicts before reason codes; they skip.
                _block(OTHER_RULE.id, "skipped", SyncReason.RECURRING_UNSUPPORTED),
                _block(OTHER_RULE.id, "blocked"),
                _block(RULE.id, None),
            ):
                uow.audit.append(entry)
            uow.commit()
        # Another User's later decision about the same rule and event identifiers is theirs.
        _commit_as(
            harness,
            OTHER_USER,
            lambda uow: uow.audit.append(
                AuditEntry(NOW, RULE.id, AuditAction.CREATE, AuditOutcome.COMPLETED, "blocked")
            ),
        )

        with harness.installation() as installation:
            records = installation.status_records([USER, OTHER_USER])
        with harness.unit_of_work() as uow:
            uow.rules.remove(OTHER_RULE.id)
            uow.commit()
        with harness.installation() as installation:
            once_removed = installation.status_records([USER])[USER]

        blocks = records[USER].overview.open_blocks
        assert [block.rule_id for block in blocks] == [OTHER_RULE.id.value, RULE.id.value]
        assert blocks[0].entry_id > blocks[1].entry_id
        assert records[OTHER_USER].overview.open_blocks == ()
        # A removed rule's blocks are no longer open.
        assert once_removed.overview.open_blocks == (blocks[1],)

    def test_failure_causes_name_each_users_provider_incidents_open_or_updated_since_a_time(
        self, harness: PersistenceHarness
    ) -> None:
        harness.connect_account(ACCOUNT)
        harness.connect_account(THEIR_ACCOUNT, OTHER_USER)
        incidents = harness.incidents(USER)
        for key, opened, cause, resolved in (
            ("provider:long-resolved", NOW - 2 * DAY, Cause.QUOTA_EXCEEDED, NOW - DAY),
            ("provider:just-resolved", NOW - 2 * DAY, Cause.CALENDAR_FORBIDDEN, NOW),
            ("provider:open", NOW + HOUR, Cause.API_DISABLED, None),
            ("provider:no-cause", NOW, None, None),
        ):
            assert incidents.open(_rule_incident(RULE.id, cause, key), opened)
            if resolved is not None:
                incidents.resolve(key, resolved, IncidentResolution.SYNC_SUCCEEDED)
        # Events still blocked have no Cause, even when one was recorded.
        blocked = replace(_rule_incident(RULE.id, key="blocks"), category=IncidentCategory.CONFLICT)
        assert incidents.open(blocked, NOW)
        # A lapsed account's own Incident tells how long after its authorization it opened.
        with harness.unit_of_work() as uow:
            assert uow.accounts.lapse(ACCOUNT, attempted_at=NOW)
            uow.commit()
        revoked = replace(_account_incident(ACCOUNT), cause=Cause.ACCESS_REVOKED)
        assert incidents.open(revoked, NOW + 2 * HOUR)

        with harness.installation() as installation:
            seen = installation.failure_causes(NOW - HOUR)

        assert seen == [
            CauseSighting(USER, Cause.CALENDAR_FORBIDDEN, NOW, False),
            CauseSighting(USER, Cause.API_DISABLED, NOW + HOUR, True),
            CauseSighting(USER, Cause.ACCESS_REVOKED, NOW + 2 * HOUR, True, 2 * HOUR),
        ]

    def test_status_records_of_a_user_without_records_are_empty(
        self, harness: PersistenceHarness
    ) -> None:
        with harness.installation() as installation:
            records = installation.status_records([OTHER_USER])

        assert records[OTHER_USER].rules == ()
        assert records[OTHER_USER].incidents == ()
        assert records[OTHER_USER].overview.accounts == ()
        assert records[OTHER_USER].overview.open_blocks == ()

    # Resource use

    def test_provider_calls_add_up_per_user_provider_and_day(
        self, harness: PersistenceHarness
    ) -> None:
        day, google = NOW.date(), ProviderKind.GOOGLE
        with harness.unit_of_work() as uow:
            uow.provider_calls.add(day, google, ProviderCallCounts(5, 1, 2))
            uow.provider_calls.add(day, google, ProviderCallCounts(3, 0, 1))
            uow.provider_calls.add(day - DAY, google, ProviderCallCounts(7, 0, 0))
            uow.commit()
        _commit_as(
            harness,
            OTHER_USER,
            lambda uow: uow.provider_calls.add(day, google, ProviderCallCounts(100)),
        )

        with harness.installation() as installation:
            today = installation.resource_use([USER, OTHER_USER], since=day)
            two_days = installation.resource_use([USER], since=day - DAY)

        assert today[USER].provider_calls == (ProviderCallUse(google, 8, 1, 3),)
        assert two_days[USER].provider_calls == (ProviderCallUse(google, 15, 1, 3),)
        assert today[OTHER_USER].provider_calls == (ProviderCallUse(google, 100, 0, 0),)

    def test_forgetting_provider_calls_keeps_the_later_days(
        self, harness: PersistenceHarness
    ) -> None:
        day, google = NOW.date(), ProviderKind.GOOGLE
        with harness.unit_of_work() as uow:
            uow.provider_calls.add(day - 2 * DAY, google, ProviderCallCounts(4))
            uow.provider_calls.add(day - DAY, google, ProviderCallCounts(2))
            uow.provider_calls.add(day, google, ProviderCallCounts(1))
            uow.commit()

        with harness.installation() as installation:
            installation.forget_provider_calls(before=day - DAY)
            installation.commit()
        with harness.installation() as installation:
            kept = installation.resource_use([USER], since=day - 10 * DAY)

        assert kept[USER].provider_calls == (ProviderCallUse(google, 3, 0, 0),)

    def test_resource_use_counts_each_users_rules_accounts_and_activity(
        self, harness: PersistenceHarness
    ) -> None:
        for account in (RULE.source, RULE.destination, OTHER_RULE.destination):
            harness.connect_account(account.connected_account_id)
        harness.connect_account(THEIR_SOURCE.connected_account_id, OTHER_USER)
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.rules.add(OTHER_RULE)
            for number in range(3):
                uow.audit.append(
                    AuditEntry(
                        NOW, RULE.id, AuditAction.CREATE, AuditOutcome.COMPLETED, f"e{number}"
                    )
                )
            uow.commit()

        with harness.installation() as installation:
            use = installation.resource_use([USER, OTHER_USER], since=NOW.date())

        assert (use[USER].rules, use[USER].connected_accounts, use[USER].activity_entries) == (
            2,
            2,
            3,
        )
        assert use[USER].provider_calls == ()
        assert (use[OTHER_USER].rules, use[OTHER_USER].connected_accounts) == (0, 1)
        assert use[OTHER_USER].activity_entries == 0

    def test_plan_use_counts_rules_that_count_every_account_and_unrevoked_tokens(
        self, harness: PersistenceHarness
    ) -> None:
        def to(
            calendar: str, state: SyncRuleState, *, lapsed: bool = False, keeps: bool = False
        ) -> SyncRule:
            return replace(
                RULE,
                id=SyncRuleId(f"rule-{calendar}"),
                destination=endpoint("work-account", calendar),
                state=state,
                awaiting_reauthorization=lapsed,
                keeps_place=keeps,
            )

        counting = [
            to("enabled", SyncRuleState.ENABLED),
            to("lapsed", SyncRuleState.DEGRADED, lapsed=True),
            to("previewed-keeping", SyncRuleState.PREVIEWED, keeps=True),
            to("draft-keeping", SyncRuleState.DRAFT, keeps=True),
        ]
        not_counting = [
            to("stopped", SyncRuleState.DEGRADED),
            to("paused", SyncRuleState.PAUSED),
            to("draft", SyncRuleState.DRAFT),
            to("previewed", SyncRuleState.PREVIEWED),
            to("removing", SyncRuleState.REMOVING),
        ]
        with harness.unit_of_work() as uow:
            for each in (*counting, *not_counting):
                uow.rules.add(each)
            uow.commit()
        old_account = ConnectedAccountId("old-account")
        harness.connect_account(old_account)
        harness.disconnect_account(old_account)
        for revoked in (False, False, True):
            harness.issue_token(USER, revoked)
        harness.connect_account(THEIR_SOURCE.connected_account_id, OTHER_USER)
        harness.issue_token(OTHER_USER, False)
        nobody = UserId("user-3")

        with harness.installation() as installation:
            use = installation.plan_use([USER, OTHER_USER, nobody])

        # USER's two accounts the rules use and a disconnected one.
        assert use[USER] == PlanUse(rules=4, connected_accounts=3, integration_tokens=2)
        assert use[OTHER_USER] == PlanUse(rules=0, connected_accounts=1, integration_tokens=1)
        assert use[nobody] == PlanUse(rules=0, connected_accounts=0, integration_tokens=0)

    # Calendar Watches and Instant Sync Requests

    def test_watches_round_trip_with_their_coverage_and_registrations(
        self, harness: PersistenceHarness
    ) -> None:
        live = _live("registration-2")
        _watching(harness, _registration(), live)
        family = CalendarId("family")
        with harness.unit_of_work() as uow:
            uow.watches.set_coverage(WATCH.id, frozenset({RULE.source.calendar_id, family}))
            uow.watches.set_retry(WATCH.id, NOW + HOUR, 2)
            uow.commit()

        with harness.unit_of_work() as uow:
            watches, registrations = uow.watches.list(), uow.watches.registrations()

        assert watches == (
            replace(
                WATCH,
                coverage=frozenset({RULE.source.calendar_id, family}),
                retry_at=NOW + HOUR,
                failures=2,
            ),
        )
        assert registrations == (_registration(), live)

    def test_a_receipt_makes_only_a_registration_still_being_created_live(
        self, harness: PersistenceHarness
    ) -> None:
        created, abandoned = (
            WatchRegistrationId("registration-1"),
            WatchRegistrationId("registration-2"),
        )
        _watching(harness, _registration(), _registration("registration-2"))
        with harness.unit_of_work() as uow:
            # Creation itself proved delivery, as a provider that validates the address does.
            assert uow.watches.record_receipt(
                created, Receipt("handle-1", NOW + 7 * DAY, confirmed=True), NOW + 5 * DAY, NOW
            )
            assert uow.watches.abandon(abandoned)
            uow.commit()

        with harness.unit_of_work() as uow:
            # Late receipts: the registration was abandoned, made live, or deleted meanwhile.
            late = (
                uow.watches.record_receipt(abandoned, RECEIPT, NOW + 5 * DAY, NOW + MINUTE),
                uow.watches.record_receipt(
                    created, Receipt("handle-other", NOW + DAY), NOW, NOW + HOUR
                ),
                uow.watches.record_receipt(
                    WatchRegistrationId("missing"), RECEIPT, NOW, NOW + HOUR
                ),
            )
            uow.commit()
        with harness.unit_of_work() as uow:
            registrations = uow.watches.registrations()

        assert late == (False, False, False)
        assert registrations == (
            replace(
                _registration(),
                state=RegistrationState.LIVE,
                handle="handle-1",
                expires_at=NOW + 7 * DAY,
                renew_at=NOW + 5 * DAY,
                confirmed_at=NOW,
            ),
            replace(_registration("registration-2"), state=RegistrationState.ABANDONED),
        )

    def test_a_receipt_after_a_removal_abandoned_its_registration_changes_nothing(
        self, harness: PersistenceHarness
    ) -> None:
        creating = _registration()
        _watching(harness, creating)
        # The inbox abandons a registration being created when its provider removes it.
        with harness.unit_of_work() as uow:
            removed = uow.watches.abandon(creating.id)
            uow.commit()
        with harness.unit_of_work() as uow:
            late = uow.watches.record_receipt(
                creating.id, Receipt("handle-1", NOW + 7 * DAY, confirmed=True), NOW, NOW
            )
            uow.commit()
        with harness.unit_of_work() as uow:
            registrations = uow.watches.registrations()

        assert (removed, late) == (True, False)
        assert registrations == (replace(creating, state=RegistrationState.ABANDONED),)

    def test_an_extension_keeps_a_renewal_request_newer_than_the_one_it_answered(
        self, harness: PersistenceHarness
    ) -> None:
        asked = replace(_live(), renew_requested_at=NOW + HOUR)
        _watching(harness, asked)
        with harness.unit_of_work() as uow:
            # Upkeep read a request of NOW; the provider asked again at NOW + HOUR meanwhile.
            assert uow.watches.record_extension(
                asked.id, NOW + 8 * DAY, NOW + 6 * DAY, seen_request=NOW
            )
            uow.commit()
        with harness.unit_of_work() as uow:
            kept = uow.watches.registrations()[0]
            assert uow.watches.record_extension(
                asked.id, NOW + 9 * DAY, NOW + 7 * DAY, seen_request=NOW + HOUR
            )
            uow.commit()
        with harness.unit_of_work() as uow:
            cleared = uow.watches.registrations()[0]

        assert (kept.expires_at, kept.renew_at, kept.renew_requested_at) == (
            NOW + 8 * DAY,
            NOW + 6 * DAY,
            NOW + HOUR,
        )
        assert (cleared.expires_at, cleared.renew_at, cleared.renew_requested_at) == (
            NOW + 9 * DAY,
            NOW + 7 * DAY,
            None,
        )

    def test_only_a_live_registration_extends_or_retires_and_any_is_abandoned(
        self, harness: PersistenceHarness
    ) -> None:
        creating = WatchRegistrationId("registration-1")
        live = WatchRegistrationId("registration-2")
        _watching(harness, _registration(), _live("registration-2"))
        with harness.unit_of_work() as uow:
            refused = (
                uow.watches.record_extension(creating, NOW + DAY, NOW, seen_request=None),
                uow.watches.retire(creating),
            )
            retired = (uow.watches.retire(live), uow.watches.retire(live))
            extended_retiring = uow.watches.record_extension(
                live, NOW + DAY, NOW, seen_request=None
            )
            abandoned = (
                uow.watches.abandon(creating),
                uow.watches.abandon(live),
                uow.watches.abandon(live),
                uow.watches.abandon(WatchRegistrationId("missing")),
            )
            uow.commit()
        with harness.unit_of_work() as uow:
            states = [registration.state for registration in uow.watches.registrations()]
            uow.watches.delete_registration(creating)
            uow.commit()
        with harness.unit_of_work() as uow:
            left = [registration.id for registration in uow.watches.registrations()]

        assert refused == (False, False)
        assert retired == (True, False)
        assert not extended_retiring
        # Abandoning works from any state, again too; only a missing registration refuses it.
        assert abandoned == (True, True, True, False)
        assert states == [RegistrationState.ABANDONED, RegistrationState.ABANDONED]
        assert left == [live]

    def test_a_watch_needs_its_users_account_one_scope_and_a_token_of_its_own(
        self, harness: PersistenceHarness
    ) -> None:
        harness.connect_account(THEIR_ACCOUNT, OTHER_USER)
        with harness.unit_of_work() as uow:
            uow.watches.add(WATCH)
            uow.watches.add_registration(_registration())
            with pytest.raises(IdentityCollision):
                uow.watches.add(replace(WATCH, id=CalendarWatchId("watch-2")))
            with pytest.raises(MissingReference):
                uow.watches.add(
                    replace(WATCH, id=CalendarWatchId("watch-3"), account=THEIR_ACCOUNT)
                )
            with pytest.raises(MissingReference):
                uow.watches.add_registration(
                    _registration("registration-2", CalendarWatchId("missing"))
                )
            with pytest.raises(IdentityCollision):
                uow.watches.add_registration(
                    replace(_registration("registration-3"), token_hash=_registration().token_hash)
                )
            uow.commit()

        with harness.unit_of_work() as uow:
            assert uow.watches.list() == (WATCH,)
            assert uow.watches.registrations() == (_registration(),)

    def test_another_user_can_neither_read_nor_change_a_users_watches_or_requests(
        self, harness: PersistenceHarness
    ) -> None:
        asked = replace(_live(), renew_requested_at=NOW)
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.commit()
        _watching(harness, asked, _registration("registration-2"))
        harness.request_run(USER, RULE.id, NOW)
        harness.connect_account(THEIR_SOURCE.connected_account_id, OTHER_USER)
        with harness.unit_of_work() as uow:
            watches, registrations = uow.watches.list(), uow.watches.registrations()

        with harness.units(OTHER_USER)() as theirs:
            seen = (
                theirs.watches.list(),
                theirs.watches.registrations(),
                theirs.instant_requests.pending(),
            )
            changed = (
                theirs.watches.record_receipt(
                    WatchRegistrationId("registration-2"), RECEIPT, NOW, NOW
                ),
                theirs.watches.record_extension(asked.id, NOW + 9 * DAY, NOW, seen_request=NOW),
                theirs.watches.retire(asked.id),
                theirs.watches.abandon(asked.id),
            )
            theirs.watches.set_coverage(WATCH.id, frozenset())
            theirs.watches.set_retry(WATCH.id, NOW + DAY, 5)
            theirs.watches.delete_registration(asked.id)
            theirs.watches.remove(WATCH.id)
            theirs.instant_requests.acknowledge(RULE.id, 1, NOW)
            # The identifier is taken; the account and the watch are another User's.
            with pytest.raises(IdentityCollision):
                theirs.watches.add(replace(THEIR_WATCH, id=WATCH.id))
            with pytest.raises(MissingReference):
                theirs.watches.add(replace(THEIR_WATCH, account=ACCOUNT))
            with pytest.raises(MissingReference):
                theirs.watches.add_registration(_registration("theirs"))
            theirs.commit()

        with harness.unit_of_work() as uow:
            assert (uow.watches.list(), uow.watches.registrations()) == (watches, registrations)
            assert uow.instant_requests.pending() == (
                PendingRequest(RULE.id, 1, 0, NOW, NOW, None),
            )
        assert seen == ((), (), ())
        assert changed == (False, False, False, False)

    def test_acknowledging_a_request_never_lowers_what_was_handled(
        self, harness: PersistenceHarness
    ) -> None:
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.commit()
        for minutes in (0, 1, 2):
            harness.request_run(USER, RULE.id, NOW + minutes * MINUTE)
        with harness.unit_of_work() as uow:
            waiting = uow.instant_requests.pending()
            uow.instant_requests.acknowledge(RULE.id, 3, NOW + 3 * MINUTE)
            # A run that captured an earlier request finishes later.
            uow.instant_requests.acknowledge(RULE.id, 1, NOW + 4 * MINUTE)
            uow.commit()
        with harness.unit_of_work() as uow:
            handled = uow.instant_requests.pending()
        harness.request_run(USER, RULE.id, NOW + 5 * MINUTE)
        with harness.unit_of_work() as uow:
            again = uow.instant_requests.pending()

        assert waiting == (PendingRequest(RULE.id, 3, 0, NOW, NOW + 2 * MINUTE, None),)
        assert handled == ()
        # Waiting starts again from the notice that came after the runs.
        assert again == (
            PendingRequest(RULE.id, 4, 3, NOW + 5 * MINUTE, NOW + 5 * MINUTE, NOW + 4 * MINUTE),
        )

    def test_removing_a_rule_removes_its_request_and_deleting_an_account_its_watches(
        self, harness: PersistenceHarness
    ) -> None:
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.rules.add(OTHER_RULE)
            uow.commit()
        for each in (RULE, OTHER_RULE):
            harness.request_run(USER, each.id, NOW)
        _watching(harness, _live())

        with harness.unit_of_work() as uow:
            uow.rules.remove(RULE.id)
            uow.commit()
        with harness.unit_of_work() as uow:
            kept = [request.rule_id for request in uow.instant_requests.pending()]
            uow.rules.purge(OTHER_RULE.id)
            uow.commit()
        harness.disconnect_account(ACCOUNT)
        with harness.unit_of_work() as uow:
            assert uow.accounts.delete_disconnected(ACCOUNT)
            uow.commit()
        with harness.unit_of_work() as uow:
            left = (
                uow.watches.list(),
                uow.watches.registrations(),
                uow.instant_requests.pending(),
            )

        assert kept == [OTHER_RULE.id]
        assert left == ((), (), ())

    # What Instant Sync reads across Users

    def test_instant_sync_owners_have_an_enabled_rule_or_a_watch_disabled_ones_included(
        self, harness: PersistenceHarness
    ) -> None:
        theirs = replace(
            RULE, id=SyncRuleId("their-rule"), source=THEIR_SOURCE, destination=THEIR_DESTINATION
        )
        for account in (THEIR_SOURCE, THEIR_DESTINATION):
            harness.connect_account(account.connected_account_id, OTHER_USER)
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.commit()
        _commit_as(harness, OTHER_USER, lambda uow: uow.rules.add(theirs.pause()))
        with harness.installation() as installation:
            without_watches = installation.instant_sync_owners()

        _watching(harness, replace(_live(), confirmed_at=NOW))
        with harness.unit_of_work() as uow:
            uow.watches.set_retry(WATCH.id, NOW + HOUR, 1)
            uow.commit()

        def watch_theirs(uow: UnitOfWork) -> None:
            uow.watches.add(THEIR_WATCH)
            uow.watches.add_registration(_registration("their-registration", THEIR_WATCH.id))

        _commit_as(harness, OTHER_USER, watch_theirs)
        harness.disable(OTHER_USER)
        harness.prefer(OTHER_USER, False)
        with harness.installation() as installation:
            owners = installation.instant_sync_owners()

        # A paused rule alone needs no watch, and a User without a watch has nothing planned.
        assert without_watches == (InstantSyncOwner(USER, True, False, None),)
        assert owners == (
            # The retry comes before the planned renewal.
            InstantSyncOwner(USER, wanted=True, disabled=False, next_due=NOW + HOUR),
            # A disabled User is listed, so upkeep stops their watches.
            InstantSyncOwner(
                OTHER_USER, wanted=False, disabled=True, next_due=NOW + CREATION_DEADLINE
            ),
        )

    def test_pending_instant_runs_are_unhandled_requests_of_enabled_rules_of_active_users(
        self, harness: PersistenceHarness
    ) -> None:
        handled = replace(
            OTHER_RULE, id=SyncRuleId("rule-2"), destination=endpoint("work-account", "third")
        )
        theirs = replace(
            RULE, id=SyncRuleId("their-rule"), source=THEIR_SOURCE, destination=THEIR_DESTINATION
        )
        for account in (THEIR_SOURCE, THEIR_DESTINATION):
            harness.connect_account(account.connected_account_id, OTHER_USER)
        failed = RuleRunOutcome(
            RULE.id, RunKind.SYNC, NOW, False, failure_kind=ProviderFailureKind.TEMPORARY
        )
        with harness.unit_of_work() as uow:
            for each in (RULE, OTHER_RULE, handled):
                uow.rules.add(each)
            uow.run_outcomes.record(failed)
            uow.commit()
        _commit_as(harness, OTHER_USER, lambda uow: uow.rules.add(theirs))
        requested = ((USER, RULE), (USER, OTHER_RULE), (USER, handled), (OTHER_USER, theirs))
        for owner, each in requested:
            harness.request_run(owner, each.id, NOW)
        with harness.unit_of_work() as uow:
            uow.rules.save(OTHER_RULE.pause())
            uow.instant_requests.acknowledge(handled.id, 1, NOW + MINUTE)
            uow.commit()
        harness.disable(OTHER_USER)

        with harness.installation() as installation:
            failing = installation.pending_instant_runs()
        with harness.unit_of_work() as uow:
            uow.run_outcomes.record(
                replace(failed, completed_at=NOW + HOUR, succeeded=True, failure_kind=None)
            )
            uow.commit()
        with harness.installation() as installation:
            recovered = installation.pending_instant_runs()

        request = PendingRequest(RULE.id, 1, 0, NOW, NOW, None)
        assert failing == (
            PendingInstantRun(
                ScheduledRule(USER, RULE, None, last_run_at=NOW, failing=True),
                request,
                last_run_failed=True,
            ),
        )
        assert recovered == (
            PendingInstantRun(
                ScheduledRule(USER, RULE, None, last_run_at=NOW + HOUR),
                request,
                last_run_failed=False,
            ),
        )

    # What the scheduler reads across Users

    def test_scheduled_rules_say_when_each_last_ran_failed_and_was_previewed(
        self, harness: PersistenceHarness
    ) -> None:
        never_ran, ran = OTHER_RULE, RULE
        failed = replace(RULE, id=SyncRuleId("rule-2"), destination=endpoint("work-account", "b"))
        previewed = replace(
            RULE, id=SyncRuleId("rule-3"), destination=endpoint("work-account", "c")
        )
        reprojecting = replace(
            RULE,
            id=SyncRuleId("rule-4"),
            destination=endpoint("work-account", "d"),
            reprojection_required=True,
        )
        ran_as_previewed = replace(
            RULE, id=SyncRuleId("rule-5"), destination=endpoint("work-account", "e")
        )
        with harness.unit_of_work() as uow:
            for each in (never_ran, ran, failed, previewed, reprojecting, ran_as_previewed):
                uow.rules.add(each)
                uow.previews.record(RulePreviewSummary(each.id, NOW, 1, 0))
            for each in (ran, reprojecting):
                uow.run_outcomes.record(RuleRunOutcome(each.id, RunKind.SYNC, NOW + MINUTE, True))
            uow.run_outcomes.record(RuleRunOutcome(ran_as_previewed.id, RunKind.SYNC, NOW, True))
            uow.run_outcomes.record(
                RuleRunOutcome(
                    failed.id,
                    RunKind.SYNC,
                    NOW + MINUTE,
                    False,
                    failure_kind=ProviderFailureKind.TEMPORARY,
                )
            )
            uow.run_outcomes.record(RuleRunOutcome(previewed.id, RunKind.SYNC, NOW - HOUR, True))
            uow.commit()

        with harness.installation() as installation:
            scheduled = installation.scheduled_rules()

        assert scheduled == (
            ScheduledRule(USER, never_ran, None, previewed_at=NOW),
            ScheduledRule(USER, ran, None, last_run_at=NOW + MINUTE, previewed_at=NOW),
            ScheduledRule(
                USER, failed, None, last_run_at=NOW + MINUTE, failing=True, previewed_at=NOW
            ),
            ScheduledRule(USER, previewed, None, last_run_at=NOW - HOUR, previewed_at=NOW),
            ScheduledRule(USER, reprojecting, None, last_run_at=NOW + MINUTE, previewed_at=NOW),
            ScheduledRule(USER, ran_as_previewed, None, last_run_at=NOW, previewed_at=NOW),
        )
        # Only a rule that ran without failing since its preview waits for its interval, and a
        # run that completed at the instant of its preview counts as since.
        assert [each.always_due for each in scheduled] == [True, False, True, True, True, False]

    def test_plan_standings_include_grace_only_and_disabled_held_owners(
        self, harness: PersistenceHarness
    ) -> None:
        grace = PlanGrace(NOW + DAY, 1, 0)
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE.hold())
            uow.rules.add(replace(OTHER_RULE, state=SyncRuleState.PREVIEWED, keeps_place=True))
            uow.rules.keep({RULE.id})
            uow.plan_grace.admit(2)
            uow.commit()
        with harness.units(OTHER_USER)() as uow:
            uow.plan_grace.save(grace)
            uow.commit()
        harness.disable(USER)
        with harness.installation() as installation:
            standings = {each.owner: each for each in installation.plan_standings()}
        assert set(standings) == {USER, OTHER_USER}
        assert not standings[USER].active
        assert standings[USER].admissions == 2
        assert [(each.rule_id, each.place, each.kept) for each in standings[USER].standings] == [
            (RULE.id, RulePlace.HELD, True),
            (OTHER_RULE.id, RulePlace.RESERVED, False),
        ]
        assert standings[OTHER_USER].standings == ()
        assert standings[OTHER_USER].grace == grace

    def test_held_rules_have_no_scheduled_instant_or_wanted_watch_work(
        self, harness: PersistenceHarness
    ) -> None:
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE.hold())
            uow.commit()
        harness.request_run(USER, RULE.id, NOW)
        with harness.installation() as installation:
            assert installation.scheduled_rules() == ()
            assert installation.pending_instant_runs() == ()
            assert installation.users_with_unfinished_lapses() == ()
            assert installation.instant_sync_owners() == ()
        _watching(harness, replace(_live(), confirmed_at=NOW))
        with harness.installation() as installation:
            assert [each.user for each in installation.instant_sync_owners()] == [USER]

    def test_only_exact_lapse_stop_code_wants_lapse_recovery(
        self, harness: PersistenceHarness
    ) -> None:
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE.hold())
            uow.rules.add(OTHER_RULE.degrade(awaiting_reauthorization=True))
            uow.commit()
        with harness.installation() as installation:
            assert list(installation.users_with_unfinished_lapses()) == [USER]
        with harness.unit_of_work() as uow:
            uow.rules.save(OTHER_RULE.degrade())
            uow.commit()
        with harness.installation() as installation:
            assert installation.users_with_unfinished_lapses() == ()


# Identity writes use narrow ports, apart from the calendar units of work above.
@dataclass
class CredentialPersistenceHarness:
    users: "UserDirectory"
    sessions: "Sessions"
    links: "PasswordResetLinks"
    public: "SelfServicePasswordResets"
    changes: "CredentialChanges"
    clock: "MutableCredentialClock"


class MutableCredentialClock(Protocol):
    moment: datetime

    def now(self) -> datetime: ...


class CredentialPersistenceContract:
    def test_reset_lifetimes_and_resend(self, credentials: CredentialPersistenceHarness) -> None:
        h = credentials
        first, second = h.users.list()
        public = h.public.issue_for_email(second.email or "")
        sibling = h.public.issue_for_email(second.email or "")
        assert public is not None
        assert sibling is not None
        assert public.link.expires_at == h.clock.now() + HOUR
        assert h.links.owner(public.link.token, h.clock.now()) == second.id
        assert h.links.owner(sibling.link.token, h.clock.now()) == second.id
        admin = h.links.issue(second.id, first.id, h.clock.now())
        assert admin.expires_at == h.clock.now() + 7 * DAY
        assert h.links.owner(public.link.token, h.clock.now()) is None
        later = h.public.issue_for_email(second.email or "")
        assert later is not None
        assert h.links.reset(later.link.token, "reset-hash") == second.id
        for link in (public.link, sibling.link, admin, later.link):
            assert h.links.owner(link.token, h.clock.now()) is None
            assert h.links.reset(link.token, "replay") is None
        assert h.users.password_hash(second.id) == "reset-hash"

    def test_administrator_cannot_issue_for_disabled_user(
        self, credentials: CredentialPersistenceHarness
    ) -> None:
        h = credentials
        first, second = h.users.list()
        h.users.set_state(second.id, UserState.DISABLED)
        with pytest.raises(UserDisabled):
            h.links.issue(second.id, first.id, h.clock.now())
        assert h.public.issue_for_email(second.email or "") is None
        assert h.public.issue_for_email("unknown@example.test") is None

    @pytest.mark.parametrize("change", ["disabled", "deleted", "email", "password", "reenabled"])
    def test_reset_refuses_disabled_deleted_changed_and_replayed_proofs(
        self, credentials: CredentialPersistenceHarness, change: str
    ) -> None:
        h = credentials
        first, second = h.users.list()
        link = h.links.issue(second.id, first.id, h.clock.now())
        session = h.sessions.start(first.id, "old-hash")
        assert session is not None
        if change in ("disabled", "reenabled"):
            h.users.set_state(second.id, UserState.DISABLED)
            if change == "reenabled":
                h.users.set_state(second.id, UserState.ACTIVE)
        elif change == "deleted":
            h.users.delete(second.id)
        elif change == "email":
            h.users.set_email(second.id, "away@example.test")
            h.users.set_email(second.id, second.email or "")
        else:
            h.users.set_password_hash(second.id, "changed-hash")
        before = h.users.password_hash(second.id)
        assert h.links.owner(link.token, h.clock.now()) is None
        assert h.links.reset(link.token, "forbidden") is None
        assert h.users.password_hash(second.id) == before
        assert h.users.password_hash(first.id) == "old-hash"
        assert h.sessions.user_of(session.token) == first.id

    def test_reset_and_sign_in_serialize_sessions(
        self, credentials: CredentialPersistenceHarness
    ) -> None:
        h = credentials
        first, second = h.users.list()
        old = h.sessions.start(second.id, "other-hash")
        theirs = h.sessions.start(first.id, "old-hash")
        assert old is not None
        assert theirs is not None
        link = h.links.issue(second.id, first.id, h.clock.now())
        assert h.links.reset(link.token, "new-hash") == second.id
        assert h.sessions.user_of(old.token) is None
        assert h.sessions.start(second.id, "other-hash") is None
        new = h.sessions.start(second.id, "new-hash")
        assert new is not None
        assert h.sessions.user_of(new.token) == second.id
        assert h.sessions.user_of(theirs.token) == first.id

    def test_stale_own_password_and_email_changes_lose_to_reset(
        self, credentials: CredentialPersistenceHarness
    ) -> None:
        h = credentials
        first, second = h.users.list()
        expected = h.changes.current(second.id)
        assert expected is not None
        link = h.links.issue(second.id, first.id, h.clock.now())
        assert h.links.reset(link.token, "new-hash") == second.id
        assert not h.changes.change_password(expected, "stale-hash", None)
        assert not h.changes.change_email(expected, "stale@example.test")
        assert h.users.password_hash(second.id) == "new-hash"
        assert h.users.get(second.id) == second

    def test_credential_failure_keeps_proofs_password_and_sessions(
        self, credentials: CredentialPersistenceHarness
    ) -> None:
        h = credentials
        first, second = h.users.list()
        link = h.links.issue(second.id, first.id, h.clock.now())
        expected = h.changes.current(second.id)
        foreign = h.sessions.start(first.id, "old-hash")
        own = h.sessions.start(second.id, "other-hash")
        assert expected is not None
        assert foreign is not None
        assert own is not None
        assert not h.changes.change_password(expected, "forbidden", foreign.token)
        with pytest.raises(EmailTaken):
            h.changes.change_email(expected, first.email or "")
        assert h.changes.current(second.id) == expected
        assert h.links.owner(link.token, h.clock.now()) == second.id
        assert h.sessions.user_of(own.token) == second.id

    def test_own_changes_revoke_proofs_and_preserve_only_the_owned_session(
        self, credentials: CredentialPersistenceHarness
    ) -> None:
        h = credentials
        first, second = h.users.list()
        expected = h.changes.current(second.id)
        kept = h.sessions.start(second.id, "other-hash")
        old = h.sessions.start(second.id, "other-hash")
        assert expected is not None
        assert kept is not None
        assert old is not None
        link = h.links.issue(second.id, first.id, h.clock.now())
        assert h.changes.change_password(expected, "new-hash", kept.token)
        assert h.sessions.user_of(kept.token) == second.id
        assert h.sessions.user_of(old.token) is None
        assert h.links.owner(link.token, h.clock.now()) is None
        expected = h.changes.current(second.id)
        assert expected is not None
        link = h.links.issue(second.id, first.id, h.clock.now())
        assert h.changes.change_email(expected, "new@example.test")
        assert h.links.owner(link.token, h.clock.now()) is None
        assert h.sessions.user_of(kept.token) == second.id

    def test_reset_exact_expiry_changes_nothing(
        self, credentials: CredentialPersistenceHarness
    ) -> None:
        h = credentials
        _first, second = h.users.list()
        public = h.public.issue_for_email(second.email or "")
        assert public is not None
        session = h.sessions.start(second.id, "other-hash")
        assert session is not None
        h.clock.moment = public.link.expires_at
        assert h.links.reset(public.link.token, "forbidden") is None
        assert h.users.password_hash(second.id) == "other-hash"
        assert h.sessions.user_of(session.token) == second.id

    @pytest.mark.parametrize("change", ["demote", "disable"])
    def test_issuance_rechecks_administrator_permission(
        self, credentials: CredentialPersistenceHarness, change: str
    ) -> None:
        from calendar_sync.application.identity.administration import AdministratorRequired

        h = credentials
        first, second = h.users.list()
        h.users.set_role(second.id, Role.INSTALLATION_ADMINISTRATOR)
        if change == "demote":
            h.users.set_role(first.id, Role.USER)
        else:
            h.users.set_state(first.id, UserState.DISABLED)
        with pytest.raises(AdministratorRequired):
            h.links.issue(second.id, first.id, h.clock.now())
        assert h.users.password_hash(second.id) == "other-hash"

    def test_noncredential_changes_preserve_proofs(
        self, credentials: CredentialPersistenceHarness
    ) -> None:
        h = credentials
        first, second = h.users.list()
        link = h.links.issue(second.id, first.id, h.clock.now())
        h.users.set_role(second.id, Role.INSTALLATION_ADMINISTRATOR)
        h.users.set_notification_email(second.id, False)
        assert h.links.owner(link.token, h.clock.now()) == second.id
        assert h.links.reset(link.token, "reset-hash") == second.id

    def test_reset_only_invalidates_its_owners_proofs(
        self, credentials: CredentialPersistenceHarness
    ) -> None:
        h = credentials
        first, second = h.users.list()
        theirs = h.public.issue_for_email(first.email or "")
        own = h.public.issue_for_email(second.email or "")
        assert theirs is not None
        assert own is not None
        assert h.links.reset(own.link.token, "reset-hash") == second.id
        assert h.links.owner(theirs.link.token, h.clock.now()) == first.id
        assert h.users.password_hash(first.id) == "old-hash"

    def test_own_changes_refuse_disabled_credentials(
        self, credentials: CredentialPersistenceHarness
    ) -> None:
        h = credentials
        _first, second = h.users.list()
        expected = h.changes.current(second.id)
        assert expected is not None
        h.users.set_state(second.id, UserState.DISABLED)
        assert h.changes.current(second.id) is None
        assert not h.changes.change_password(expected, "forbidden", None)
        assert not h.changes.change_email(expected, "forbidden@example.test")
        assert h.users.password_hash(second.id) == "other-hash"
        assert h.users.get(second.id) == replace(second, state=UserState.DISABLED)
