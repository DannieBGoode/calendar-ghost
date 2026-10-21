"""Plan limits hold when requests race on one SQLite database (ADR 0038).

Each limit check reads the User's Allowance once its own write holds SQLite's writer lock, so two
requests cannot both take the last place, and a lower limit cannot commit between a check and
its write. `HeldAllowances` holds a check at its read, so a test can show what another request
does meanwhile.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Collection, Iterator, Mapping
from dataclasses import dataclass, field, replace
from datetime import timedelta
from pathlib import Path
from threading import Event, Lock, Thread
from typing import ClassVar

import pytest

from calendar_sync.application.identity.integration_tokens import IssueIntegrationToken
from calendar_sync.application.identity.plans import ChangePlan
from calendar_sync.application.identity.ports import IntegrationTokenScope, IssuedIntegrationToken
from calendar_sync.application.sync.errors import ProviderFailure
from calendar_sync.application.sync.lapsed_authorization import LapsedAuthorizations
from calendar_sync.application.sync.locking import RuleLocks
from calendar_sync.application.sync.plan_holds import (
    ChooseKeptRules,
    PlanHolds,
    PlanSettlementBusy,
    SettleLocks,
)
from calendar_sync.application.sync.plan_ports import Allowances
from calendar_sync.application.sync.ports import UnitOfWorkFactory
from calendar_sync.application.sync.rules import EnableSyncRule
from calendar_sync.domain.access import UserId
from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.model import SyncRule, SyncRuleId, SyncRuleState
from calendar_sync.domain.plan_hold import GRACE, PlanGrace, PlanNotice, PlanNoticeKind
from calendar_sync.domain.plans import (
    Allowance,
    LimitedResource,
    NewPlan,
    Plan,
    PlanKey,
    PlanLimitReached,
    PlanLimits,
    PlanNameTaken,
    SyncInterval,
)
from calendar_sync.domain.providers import ProviderFailureKind
from calendar_sync.infrastructure.clock import SystemClock
from calendar_sync.infrastructure.identifiers import UuidIdGenerator
from calendar_sync.infrastructure.integration_tokens import SqliteIntegrationTokens
from calendar_sync.infrastructure.persistence import plans as plans_store
from calendar_sync.infrastructure.persistence.accounts import SqliteConnectedAccountStore
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.persistence.migrations import initialize_database
from calendar_sync.infrastructure.persistence.plans import SqlitePlans
from calendar_sync.infrastructure.persistence.sqlite.unit_of_work import SqliteUnitOfWork
from calendar_sync.infrastructure.persistence.users import SqliteUserDirectory
from calendar_sync.infrastructure.security import CredentialCipher
from tests.application.test_health import Incidents
from tests.fake_calendar import FixedClock
from tests.helpers import NOW, endpoint, rule
from tests.plans import FAMILY, FREE, plans_on
from tests.users import USER, add_user, limited_user, sqlite_units

STATUS = frozenset({IntegrationTokenScope.STATUS_READ})
WAIT = 0.5
"""How long a test gives a request that must wait to show that it does not go ahead."""


@dataclass
class HeldAllowances:
    """Allowances whose reads say when they start and answer only once released. A check that
    reads them holds its write lock meanwhile, as a slow read would."""

    inner: Allowances
    reading: Event = field(default_factory=Event)
    released: Event = field(default_factory=Event)

    def of(self, user: UserId) -> Allowance:
        self.reading.set()
        assert self.released.wait(5)
        return self.inner.of(user)

    def of_users(self, users: Collection[UserId]) -> Mapping[UserId, Allowance]:
        self.reading.set()
        assert self.released.wait(5)
        return self.inner.of_users(users)


def released(inner: Allowances) -> HeldAllowances:
    """Allowances that answer at once, and still say when they are read."""
    held = HeldAllowances(inner)
    held.released.set()
    return held


# Integration Tokens


@dataclass
class _Tokens:
    database: Path
    plans: SqlitePlans
    tokens: SqliteIntegrationTokens

    def issuing(self, user: UserId, allowances: Allowances) -> IssueIntegrationToken:
        """One request's use case, composed for it as the Web API composes each request's."""
        return IssueIntegrationToken(
            user, SqliteUserDirectory(self.database), self.tokens.for_user(user), allowances
        )

    def unrevoked(self, user: UserId) -> int:
        return sum(token.revoked_at is None for token in self.tokens.for_user(user).list())


def _tokens(tmp_path: Path) -> _Tokens:
    database = tmp_path / "test.db"
    initialize_database(database)
    add_user(database)
    return _Tokens(
        database,
        SqlitePlans(database),
        SqliteIntegrationTokens(database, SystemClock(), UuidIdGenerator()),
    )


def _issue_in_thread(issuing: IssueIntegrationToken, name: str, outcomes: list[object]) -> Thread:
    def issue() -> None:
        try:
            outcomes.append(issuing.execute(name, STATUS))
        except PlanLimitReached as refused:
            outcomes.append(refused)

    thread = Thread(target=issue)
    thread.start()
    return thread


def test_two_issues_for_the_last_token_place_store_exactly_one(tmp_path: Path) -> None:
    installation = _tokens(tmp_path)
    plans_on(installation.plans, FAMILY)
    member = limited_user(installation.database)
    installation.issuing(member, installation.plans).execute("Homepage", STATUS)
    first = HeldAllowances(installation.plans)
    second = released(installation.plans)
    outcomes: list[object] = []

    holding = _issue_in_thread(installation.issuing(member, first), "Uptime Kuma", outcomes)
    assert first.reading.wait(5)
    waiting = _issue_in_thread(installation.issuing(member, second), "Claude Code", outcomes)
    try:
        # The second issue waits for the first one's write lock, so it cannot read the limit
        # while the first holds the last place.
        assert not second.reading.wait(WAIT)
    finally:
        first.released.set()
        holding.join()
        waiting.join()

    issued = [each for each in outcomes if isinstance(each, IssuedIntegrationToken)]
    refused = [each for each in outcomes if isinstance(each, PlanLimitReached)]
    assert (len(issued), len(refused)) == (1, 1)
    assert (refused[0].resource, refused[0].limit) == (LimitedResource.INTEGRATION_TOKENS, 2)
    assert installation.unrevoked(member) == 2


def test_a_plan_lowering_waits_for_an_issue_that_holds_the_write_lock(tmp_path: Path) -> None:
    installation = _tokens(tmp_path)
    plans_on(installation.plans, FAMILY)
    member = limited_user(installation.database)
    installation.issuing(member, installation.plans).execute("Homepage", STATUS)
    held = HeldAllowances(installation.plans)
    lowered = Event()
    one_token = replace(FAMILY, limits=replace(FAMILY.limits, integration_tokens=1))
    outcomes: list[object] = []

    def lower() -> None:
        # The administrator's ChangePlan, through its own store as its own request.
        SqlitePlans(installation.database).change(one_token, NOW)
        lowered.set()

    holding = _issue_in_thread(installation.issuing(member, held), "Uptime Kuma", outcomes)
    assert held.reading.wait(5)
    lowering = Thread(target=lower)
    lowering.start()
    try:
        # The lowering waits until the issue, which reads the limit under its write lock, has
        # committed; it never lands between that read and the insert.
        assert not lowered.wait(WAIT)
    finally:
        held.released.set()
        holding.join()
        lowering.join()

    assert lowered.is_set()
    assert [type(each) for each in outcomes] == [IssuedIntegrationToken]
    with pytest.raises(PlanLimitReached) as refused:
        installation.issuing(member, installation.plans).execute("Claude Code", STATUS)
    assert refused.value.limit == 1
    assert installation.unrevoked(member) == 2


# Starts


TWO_RULES = Plan(PlanKey("two-rules"), "Two rules", PlanLimits(2, 2, 2, SyncInterval.INSTANT))
"""A Plan whose rule limit is two, so one enabled rule leaves one place."""
NEXT_RULE = SyncRuleId("next")
LATER_RULE = SyncRuleId("later")


def _previewed_rule(rule_id: SyncRuleId) -> SyncRule:
    return SyncRule(
        rule_id,
        endpoint("personal-account", f"{rule_id.value}-calendar"),
        rule().destination,
        state=SyncRuleState.PREVIEWED,
    )


def _member_with_rules(database: Path, *rules: SyncRule) -> tuple[SqlitePlans, UnitOfWorkFactory]:
    """Plans on with TWO_RULES the Default Plan, and USER, whom it limits, with `rules`."""
    initialize_database(database)
    plans = SqlitePlans(database)
    plans_on(plans, TWO_RULES)
    limited_user(database, USER)
    units = sqlite_units(database, user=USER)
    with units() as uow:
        for each in rules:
            uow.rules.add(each)
        uow.commit()
    return plans, units


def _rule_state(units: UnitOfWorkFactory, rule_id: SyncRuleId) -> SyncRuleState:
    with units() as uow:
        stored = uow.rules.get(rule_id)
    assert stored is not None
    return stored.state


def test_two_starts_for_the_last_place_admit_exactly_one(tmp_path: Path) -> None:
    plans, units = _member_with_rules(
        tmp_path / "calendar-sync.db",
        rule(),
        _previewed_rule(NEXT_RULE),
        _previewed_rule(LATER_RULE),
    )
    locks = RuleLocks()
    first = HeldAllowances(plans)
    second = released(plans)
    started: list[SyncRuleId] = []
    refused: list[SyncRuleId] = []

    def start_rule(rule_id: SyncRuleId, allowances: Allowances) -> None:
        try:
            EnableSyncRule(units, locks, allowances, USER).execute(rule_id)
        except PlanLimitReached:
            refused.append(rule_id)
        else:
            started.append(rule_id)

    holding = Thread(target=start_rule, args=(NEXT_RULE, first))
    holding.start()
    assert first.reading.wait(5)
    waiting = Thread(target=start_rule, args=(LATER_RULE, second))
    waiting.start()
    try:
        # The second Start waits for the first one's write lock, so it cannot read the limit
        # while the first holds the last place.
        assert not second.reading.wait(WAIT)
    finally:
        first.released.set()
        holding.join()
        waiting.join()

    assert (started, refused) == ([NEXT_RULE], [LATER_RULE])
    assert _rule_state(units, NEXT_RULE) is SyncRuleState.ENABLED
    assert _rule_state(units, LATER_RULE) is SyncRuleState.PREVIEWED


def test_a_plan_lowered_during_a_start_waits_for_the_start_to_commit(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    plans, units = _member_with_rules(
        database, rule(), _previewed_rule(NEXT_RULE), _previewed_rule(LATER_RULE)
    )
    actor = add_user(database, UserId("admin-1"))
    lowered = replace(TWO_RULES, limits=replace(TWO_RULES.limits, rules=1))
    gate = HeldAllowances(plans)
    start = Thread(target=EnableSyncRule(units, RuleLocks(), gate, USER).execute, args=(NEXT_RULE,))
    lowering = Thread(
        target=ChangePlan(SqliteUserDirectory(database), plans, SystemClock()).execute,
        args=(actor, lowered),
    )

    start.start()
    assert gate.reading.wait(5)
    lowering.start()
    lowering.join(0.3)
    lowered_during_the_start = not lowering.is_alive()
    gate.released.set()
    start.join(5)
    lowering.join(5)

    # The Start saw the limit of two and committed before the lowering could.
    assert not lowered_during_the_start
    assert _rule_state(units, NEXT_RULE) is SyncRuleState.ENABLED
    assert plans.get(TWO_RULES.key) == lowered
    # Nothing stopped, and the next Start meets the lowered limit.
    assert _rule_state(units, rule().id) is SyncRuleState.ENABLED
    with pytest.raises(PlanLimitReached):
        EnableSyncRule(units, RuleLocks(), plans, USER).execute(LATER_RULE)


def _start_behind(
    database: Path, plans: SqlitePlans, units: UnitOfWorkFactory, statement: str
) -> tuple[bool, list[str]]:
    """Start NEXT_RULE while another connection holds the writer lock for `statement`, as every
    SqlitePlans write does; whether the Start waited for it, and how the Start ended."""
    outcome: list[str] = []

    def start_rule() -> None:
        try:
            EnableSyncRule(units, RuleLocks(), plans, USER).execute(NEXT_RULE)
        except PlanLimitReached:
            outcome.append("refused")
        else:
            outcome.append("started")

    start = Thread(target=start_rule)
    with transaction(database) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(statement)
        start.start()
        start.join(0.3)
        waited = start.is_alive()
    start.join(5)
    return waited, outcome


def test_a_start_that_waits_for_a_lowering_reads_the_lowered_limit(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    plans, units = _member_with_rules(database, rule(), _previewed_rule(NEXT_RULE))

    waited, outcome = _start_behind(
        database, plans, units, "UPDATE plans SET rule_limit = 1 WHERE key = 'two-rules'"
    )

    # The Start's save waited for the lowering, and its limit read came after it.
    assert waited
    assert outcome == ["refused"]
    assert _rule_state(units, NEXT_RULE) is SyncRuleState.PREVIEWED


def test_a_start_that_waits_for_plans_to_turn_on_reads_the_limit(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    enabled = replace(_previewed_rule(LATER_RULE), state=SyncRuleState.ENABLED)
    plans, units = _member_with_rules(database, rule(), enabled, _previewed_rule(NEXT_RULE))
    plans.change_settings(False, TWO_RULES.key, NOW)

    waited, outcome = _start_behind(
        database,
        plans,
        units,
        "UPDATE installation_settings SET plans_enabled = 1 WHERE singleton = 1",
    )

    assert waited
    assert outcome == ["refused"]
    assert _rule_state(units, NEXT_RULE) is SyncRuleState.PREVIEWED


# Connected Accounts


def test_two_connects_for_the_last_account_place_store_exactly_one(tmp_path: Path) -> None:
    """The account limit is read inside the save's BEGIN IMMEDIATE, so a second connect waits
    for the first to commit, then counts its account (Review Focus 3)."""
    database = tmp_path / "test.db"
    initialize_database(database)
    plans = SqlitePlans(database)
    plans_on(plans, FREE)
    member = limited_user(database)
    held = HeldAllowances(plans)
    store = SqliteConnectedAccountStore(
        database, CredentialCipher(CredentialCipher.generate_key()), allowances=held
    )
    outcomes: dict[str, str] = {}

    def connect(email: str) -> None:
        try:
            store.for_user(member).save("Synthetic", email, "{}", provider=ProviderKind.GOOGLE)
        except PlanLimitReached as refused:
            outcomes[email] = f"refused at {refused.limit}"
        else:
            outcomes[email] = "connected"

    first = Thread(target=connect, args=("first@example.test",))
    first.start()
    assert held.reading.wait(5)
    second = Thread(target=connect, args=("second@example.test",))
    second.start()
    second.join(WAIT)
    # The first connect holds the writer lock while it reads the limit, so the second waits.
    assert second.is_alive()
    held.released.set()
    first.join(5)
    second.join(5)

    assert outcomes == {
        "first@example.test": "connected",
        "second@example.test": "refused at 1",
    }
    assert [account.email for account in store.for_user(member).list()] == ["first@example.test"]


def _added_while_another_adds(
    database: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> tuple[bool, list[Plan | Exception]]:
    """Add "Free", and while it holds the write lock, add a Plan named `name`: whether the
    second add waited, and what each add answered, in the order they finished."""
    initialize_database(database)
    plans = SqlitePlans(database)
    reading, release = Event(), Event()
    read_names = plans_store._names

    def held(connection: sqlite3.Connection) -> dict[str, str]:
        names = read_names(connection)
        if not reading.is_set():
            reading.set()
            assert release.wait(5)
        return names

    monkeypatch.setattr(plans_store, "_names", held)
    answers: list[Plan | Exception] = []

    def add(plan: NewPlan) -> None:
        try:
            answers.append(plans.add(plan, NOW))
        except PlanNameTaken as refused:
            answers.append(refused)

    first = Thread(target=add, args=(NewPlan("Free", FREE.limits),))
    first.start()
    assert reading.wait(5)
    second = Thread(target=add, args=(NewPlan(name, FAMILY.limits),))
    second.start()
    second.join(WAIT)
    waited = second.is_alive()
    release.set()
    first.join(5)
    second.join(5)
    return waited, answers


def test_two_plans_added_at_once_whose_names_make_one_key_get_different_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An add reads the keys once it holds the write lock, so a second add whose name makes the
    same key waits for it, then sees its key and makes another."""
    waited, answers = _added_while_another_adds(tmp_path / "test.db", monkeypatch, "Free!")

    assert waited
    assert [answer.key.value for answer in answers if isinstance(answer, Plan)] == [
        "free",
        "free-2",
    ]


def test_two_plans_added_at_once_with_one_name_are_not_both_added(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An add reads the names once it holds the write lock, so the second add with the name
    waits, then sees it taken."""
    database = tmp_path / "test.db"
    waited, answers = _added_while_another_adds(database, monkeypatch, "free")

    assert waited
    assert [type(answer) for answer in answers] == [Plan, PlanNameTaken]
    assert [listing.plan for listing in SqlitePlans(database).plans()] == [answers[0]]


# Plan Hold settlement


class _Job:
    """A bounded test worker that never hides a thread failure."""

    pending: ClassVar[list[_Job]] = []

    def __init__(self, operation: Callable[[], object]) -> None:
        self.pending.append(self)
        self.answers: list[object] = []
        self.started = Event()
        self.done = Event()

        def run() -> None:
            self.started.set()
            try:
                self.answers.append(operation())
            except BaseException as error:
                self.answers.append(error)
            finally:
                self.done.set()

        self.thread = Thread(target=run)
        self.thread.start()
        assert self.started.wait(2)

    def finish(self) -> object:
        self.thread.join(5)
        assert not self.thread.is_alive()
        assert len(self.answers) == 1
        self.pending.remove(self)
        return self.answers[0]


class _DiscoveryLocks(RuleLocks):
    """Pause settlement after discovery closes, before any rule lock is acquired."""

    def __init__(self) -> None:
        super().__init__()
        self.discovered = Event()
        self.proceed = Event()

    def for_writes(self, rule_id: SyncRuleId) -> Lock:
        if not self.discovered.is_set():
            self.discovered.set()
            assert self.proceed.wait(5)
        return super().for_writes(rule_id)


def _holds(
    units: UnitOfWorkFactory, plans: Allowances, locks: RuleLocks | None = None
) -> PlanHolds:
    return PlanHolds(units, USER, plans, locks or RuleLocks(), SettleLocks(), FixedClock())


def _save_grace(units: UnitOfWorkFactory, *, limit: int = 1, admissions: int = 0) -> None:
    with units() as uow:
        uow.plan_grace.save(PlanGrace(NOW - timedelta(days=1), limit, admissions))
        uow.commit()


def _stored_rule(units: UnitOfWorkFactory, rule_id: SyncRuleId) -> SyncRule:
    with units() as uow:
        stored = uow.rules.get(rule_id)
    assert stored is not None
    return stored


def _lower(plans: SqlitePlans, limit: int = 1) -> None:
    plans.change(replace(TWO_RULES, limits=replace(TWO_RULES.limits, rules=limit)), NOW)


def test_lowering_before_settle_is_seen_and_after_writer_waits(tmp_path: Path) -> None:
    plans, units = _member_with_rules(
        tmp_path / "test.db", rule(), _previewed_rule(NEXT_RULE).enable()
    )
    locks = _DiscoveryLocks()
    gate = HeldAllowances(plans)
    holding = _Job(_holds(units, gate, locks).settle)
    try:
        assert locks.discovered.wait(2)
        _lower(plans)
        locks.proceed.set()
        assert gate.reading.wait(2)
        raising = _Job(lambda: _lower(plans, 2))
        assert not raising.done.wait(0.1)
    finally:
        locks.proceed.set()
        gate.released.set()
    notice = holding.finish()
    assert raising.finish() is None
    assert isinstance(notice, PlanNotice)
    assert notice.kind is PlanNoticeKind.GRACE_STARTED
    assert notice.limit == 1
    with units() as uow:
        grace = uow.plan_grace.get()
        assert grace is not None
        assert grace.rule_limit == 1


@pytest.mark.parametrize("before", [True, False])
def test_lapse_before_and_after_release_is_preserved(tmp_path: Path, before: bool) -> None:
    plans, units = _member_with_rules(tmp_path / "test.db", rule().hold())
    gate = HeldAllowances(plans)
    locks = RuleLocks()
    lapses = LapsedAuthorizations(units, Incidents(), FixedClock(), locks)
    account = rule().source.connected_account_id
    failure = ProviderFailure(ProviderFailureKind.AUTHENTICATION, "synthetic", account_id=account)

    def lapse() -> bool:
        return lapses.lapsed(account, failure, attempted_at=NOW)

    if before:
        assert _Job(lapse).finish() is True
        gate.released.set()
    holding = _Job(_holds(units, gate, locks).settle)
    try:
        assert gate.reading.wait(2)
        if not before:
            lapsing = _Job(lapse)
            assert not lapsing.done.wait(0.1)
    finally:
        gate.released.set()
    assert holding.finish() is None
    if not before:
        assert lapsing.finish() is True
    current = _stored_rule(units, rule().id)
    assert current.awaiting_reauthorization
    assert not current.held_by_plan
    assert not current.synchronizes


def test_start_racing_release_cannot_exceed_limit(tmp_path: Path) -> None:
    plans, units = _member_with_rules(
        tmp_path / "test.db", rule().hold(), _previewed_rule(NEXT_RULE)
    )
    _lower(plans)
    gate = HeldAllowances(plans)
    locks = RuleLocks()
    holding = _Job(_holds(units, gate, locks).settle)
    try:
        assert gate.reading.wait(2)
        starting = _Job(lambda: EnableSyncRule(units, locks, plans, USER).execute(NEXT_RULE))
        assert not starting.done.wait(0.1)
    finally:
        gate.released.set()
    assert holding.finish() is None
    assert isinstance(starting.finish(), PlanLimitReached)
    assert _stored_rule(units, rule().id).synchronizes
    assert _stored_rule(units, NEXT_RULE).state is SyncRuleState.PREVIEWED


def test_new_start_during_discovery_stays_unchanged(tmp_path: Path) -> None:
    plans, units = _member_with_rules(tmp_path / "test.db", rule(), _previewed_rule(NEXT_RULE))
    _save_grace(units)
    locks = _DiscoveryLocks()
    holding = _Job(_holds(units, plans, locks).settle)
    try:
        assert locks.discovered.wait(2)
        EnableSyncRule(units, locks, plans, USER).execute(NEXT_RULE)
        _lower(plans)
    finally:
        locks.proceed.set()
    notice = holding.finish()
    assert isinstance(notice, PlanNotice)
    assert notice.kind is PlanNoticeKind.GRACE_STARTED
    assert _stored_rule(units, NEXT_RULE).synchronizes
    with units() as uow:
        grace = uow.plan_grace.get()
        assert grace is not None
        assert grace.admissions == 1
        assert grace.holds_at == NOW + GRACE


def test_replacement_during_settle_waits_for_next_pass(tmp_path: Path) -> None:
    old = _previewed_rule(NEXT_RULE).enable()
    plans, units = _member_with_rules(tmp_path / "test.db", rule(), old)
    _lower(plans)
    _save_grace(units)
    locks = _DiscoveryLocks()
    holding = _Job(_holds(units, plans, locks).settle)
    try:
        assert locks.discovered.wait(2)
        # The replacement's atomic place move, under the same rule write lock.
        with locks.for_writes(old.id), units() as uow:
            draft = replace(_previewed_rule(LATER_RULE), state=SyncRuleState.DRAFT).take_place_of(
                old
            )
            uow.rules.add(draft)
            uow.rules.inherit_place(draft.id, old.id)
            uow.rules.save(old.begin_removal())
            uow.commit()
    finally:
        locks.proceed.set()
    assert holding.finish() is None  # The unlocked draft was not held or counted in a held notice.
    assert _stored_rule(units, LATER_RULE).keeps_place
    with units() as uow:
        grace = uow.plan_grace.get()
        assert grace is not None
        assert grace.holds_at < NOW
    assert _holds(units, plans, locks).settle() is None
    assert not _stored_rule(units, LATER_RULE).keeps_place
    with units() as uow:
        assert uow.plan_grace.get() is None


def test_admission_survives_removal_and_restarts_grace(tmp_path: Path) -> None:
    plans, units = _member_with_rules(
        tmp_path / "test.db",
        rule(),
        _previewed_rule(NEXT_RULE).enable(),
        _previewed_rule(LATER_RULE),
    )
    _save_grace(units)
    _lower(plans, 3)
    assert isinstance(
        _Job(lambda: EnableSyncRule(units, RuleLocks(), plans, USER).execute(LATER_RULE)).finish(),
        SyncRule,
    )
    with units() as uow:
        uow.rules.remove(rule().id)
        uow.commit()
    _lower(plans)
    notice = _Job(_holds(units, plans).settle).finish()
    assert isinstance(notice, PlanNotice)
    assert notice.kind is PlanNoticeKind.GRACE_STARTED
    assert notice.holds_at == NOW + GRACE
    assert _stored_rule(units, LATER_RULE).synchronizes


def test_keep_release_during_temporary_raise_restarts_grace(tmp_path: Path) -> None:
    plans, units = _member_with_rules(
        tmp_path / "test.db",
        rule(),
        _previewed_rule(NEXT_RULE).enable(),
        _previewed_rule(LATER_RULE).enable().hold(),
    )
    _save_grace(units)
    _lower(plans, 3)
    choice = ChooseKeptRules(_holds(units, plans))
    assert _Job(lambda: choice.execute([LATER_RULE])).finish() is None
    _lower(plans)
    notice = _Job(_holds(units, plans).settle).finish()
    assert isinstance(notice, PlanNotice)
    assert notice.kind is PlanNoticeKind.GRACE_STARTED
    with units() as uow:
        assert uow.plan_grace.admissions() == 1
        grace = uow.plan_grace.get()
        assert grace is not None
        assert grace.holds_at == NOW + GRACE


def test_settle_failure_rolls_back_every_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plans, units = _member_with_rules(
        tmp_path / "test.db",
        rule(),
        _previewed_rule(NEXT_RULE).enable(),
        replace(_previewed_rule(LATER_RULE), keeps_place=True),
    )
    _lower(plans)
    _save_grace(units)

    def fail_commit(self: SqliteUnitOfWork) -> None:
        raise RuntimeError("synthetic commit failure")

    monkeypatch.setattr(SqliteUnitOfWork, "commit", fail_commit)
    answer = _Job(_holds(units, plans).settle).finish()
    assert isinstance(answer, RuntimeError)
    assert _stored_rule(units, NEXT_RULE).synchronizes
    assert _stored_rule(units, LATER_RULE).keeps_place
    with units() as uow:
        grace = uow.plan_grace.get()
        assert grace is not None
        assert grace.holds_at == NOW - timedelta(days=1)
        assert uow.plan_grace.admissions() == 0
        assert not any(each.held_by_plan for each in uow.rules.list())


def test_keep_choice_new_candidate_changes_nothing_until_retry(tmp_path: Path) -> None:
    plans, units = _member_with_rules(tmp_path / "test.db", rule(), _previewed_rule(NEXT_RULE))
    with units() as uow:
        uow.rules.keep([rule().id])
        uow.commit()
    locks = _DiscoveryLocks()
    choice = ChooseKeptRules(_holds(units, plans, locks))
    choosing = _Job(lambda: choice.execute([NEXT_RULE]))
    try:
        assert locks.discovered.wait(2)
        EnableSyncRule(units, locks, plans, USER).execute(NEXT_RULE)
    finally:
        locks.proceed.set()
    assert isinstance(choosing.finish(), PlanSettlementBusy)
    with units() as uow:
        assert {each.rule_id for each in uow.rules.standings() if each.kept} == {rule().id}
    choice.execute([NEXT_RULE])
    with units() as uow:
        assert {each.rule_id for each in uow.rules.standings() if each.kept} == {NEXT_RULE}


def test_failed_release_returns_no_notice_and_preserves_hold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plans, units = _member_with_rules(tmp_path / "test.db", rule().hold())

    def refuse(self: SqliteUnitOfWork) -> None:
        raise RuntimeError("synthetic commit failure")

    with monkeypatch.context() as patch:
        patch.setattr(SqliteUnitOfWork, "commit", refuse)
        answer = _Job(_holds(units, plans).settle).finish()
    assert isinstance(answer, RuntimeError)
    assert _stored_rule(units, rule().id).held_by_plan
    assert _holds(units, plans).settle() is None
    assert _stored_rule(units, rule().id).synchronizes


def test_held_notice_counts_only_locked_committed_holds(tmp_path: Path) -> None:
    old = _previewed_rule(NEXT_RULE).enable()
    extra = _previewed_rule(SyncRuleId("extra")).enable()
    plans, units = _member_with_rules(tmp_path / "test.db", rule(), old, extra)
    _lower(plans)
    _save_grace(units)
    locks = _DiscoveryLocks()
    holding = _Job(_holds(units, plans, locks).settle)
    try:
        assert locks.discovered.wait(2)
        with locks.for_writes(old.id), units() as uow:
            draft = _previewed_rule(LATER_RULE).take_place_of(old)
            uow.rules.add(draft)
            uow.rules.inherit_place(draft.id, old.id)
            uow.rules.save(old.begin_removal())
            uow.commit()
    finally:
        locks.proceed.set()
    notice = holding.finish()
    assert isinstance(notice, PlanNotice)
    assert notice.kind is PlanNoticeKind.RULES_HELD
    assert notice.held == 1
    assert _stored_rule(units, extra.id).held_by_plan
    assert _stored_rule(units, LATER_RULE).keeps_place
    with units() as uow:
        grace = uow.plan_grace.get()
        assert grace is not None
        assert grace.holds_at < NOW


@pytest.fixture(autouse=True)
def _join_plan_workers() -> Iterator[None]:
    """Always join workers, including when an assertion fails before finish()."""
    try:
        yield
    finally:
        for job in tuple(_Job.pending):
            job.thread.join(6)
            assert not job.thread.is_alive()
            _Job.pending.remove(job)


def test_keep_choice_counts_but_does_not_swap_fresh_unlocked_rule(tmp_path: Path) -> None:
    plans, units = _member_with_rules(
        tmp_path / "test.db", rule().hold(), _previewed_rule(NEXT_RULE)
    )
    _lower(plans)
    locks = _DiscoveryLocks()
    choice = ChooseKeptRules(_holds(units, plans, locks))
    choosing = _Job(lambda: choice.execute([rule().id]))
    try:
        assert locks.discovered.wait(2)
        EnableSyncRule(units, locks, plans, USER).execute(NEXT_RULE)
    finally:
        locks.proceed.set()
    assert choosing.finish() is None
    assert _stored_rule(units, rule().id).held_by_plan
    assert _stored_rule(units, NEXT_RULE).synchronizes
    with units() as uow:
        assert {each.rule_id for each in uow.rules.standings() if each.kept} == {rule().id}
    choice.execute([rule().id])
    assert _stored_rule(units, rule().id).synchronizes
    assert _stored_rule(units, NEXT_RULE).held_by_plan
