"""Plan limits hold when requests race on one SQLite database (ADR 0038).

Each limit check reads the User's Allowance once its own write holds SQLite's writer lock, so two
requests cannot both take the last place, and a lower limit cannot commit between a check and
its write. `HeldAllowances` holds a check at its read, so a test can show what another request
does meanwhile.
"""

from __future__ import annotations

import time
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from threading import Barrier, Event, Thread

import pytest

from calendar_sync.application.identity.integration_tokens import IssueIntegrationToken
from calendar_sync.application.identity.plans import ChangePlan
from calendar_sync.application.identity.ports import IntegrationTokenScope, IssuedIntegrationToken
from calendar_sync.application.sync.locking import RuleLocks
from calendar_sync.application.sync.ports import Allowances, UnitOfWorkFactory
from calendar_sync.application.sync.rules import EnableSyncRule
from calendar_sync.domain.access import UserId
from calendar_sync.domain.model import SyncRule, SyncRuleId, SyncRuleState
from calendar_sync.domain.plans import (
    Allowance,
    LimitedResource,
    Plan,
    PlanKey,
    PlanLimitReached,
    PlanLimits,
    SyncInterval,
)
from calendar_sync.infrastructure.clock import SystemClock
from calendar_sync.infrastructure.identifiers import UuidIdGenerator
from calendar_sync.infrastructure.integration_tokens import SqliteIntegrationTokens
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.persistence.migrations import initialize_database
from calendar_sync.infrastructure.persistence.plans import SqlitePlans
from calendar_sync.infrastructure.persistence.users import SqliteUserDirectory
from tests.helpers import NOW, endpoint, rule
from tests.plans import FAMILY, plans_on
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


@dataclass
class SlowAllowanceReads:
    """Reads the Allowance, then holds the Start a moment longer, writer lock and all, so the
    other Start reaches its own save meanwhile."""

    inner: Allowances

    def of(self, user: UserId) -> Allowance:
        allowance = self.inner.of(user)
        time.sleep(0.2)
        return allowance

    def of_users(self, users: Collection[UserId]) -> Mapping[UserId, Allowance]:
        return self.inner.of_users(users)


@dataclass
class GatedAllowanceReads:
    """Reads the Allowance, says so, then holds the Start, writer lock and all, until released."""

    inner: Allowances
    read: Event = field(default_factory=Event)
    release: Event = field(default_factory=Event)

    def of(self, user: UserId) -> Allowance:
        allowance = self.inner.of(user)
        self.read.set()
        assert self.release.wait(5)
        return allowance

    def of_users(self, users: Collection[UserId]) -> Mapping[UserId, Allowance]:
        return self.inner.of_users(users)


def test_two_starts_for_the_last_place_admit_exactly_one(tmp_path: Path) -> None:
    plans, units = _member_with_rules(
        tmp_path / "calendar-sync.db",
        rule(),
        _previewed_rule(NEXT_RULE),
        _previewed_rule(LATER_RULE),
    )
    enable = EnableSyncRule(units, RuleLocks(), SlowAllowanceReads(plans), USER)
    start = Barrier(2)
    started: list[SyncRuleId] = []
    refused: list[SyncRuleId] = []

    def start_rule(rule_id: SyncRuleId) -> None:
        start.wait()
        try:
            enable.execute(rule_id)
        except PlanLimitReached:
            refused.append(rule_id)
        else:
            started.append(rule_id)

    threads = [Thread(target=start_rule, args=(rule_id,)) for rule_id in (NEXT_RULE, LATER_RULE)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)

    assert len(started) == 1
    assert len(refused) == 1
    assert _rule_state(units, started[0]) is SyncRuleState.ENABLED
    assert _rule_state(units, refused[0]) is SyncRuleState.PREVIEWED


def test_a_plan_lowered_during_a_start_waits_for_the_start_to_commit(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    plans, units = _member_with_rules(
        database, rule(), _previewed_rule(NEXT_RULE), _previewed_rule(LATER_RULE)
    )
    actor = add_user(database, UserId("admin-1"))
    lowered = replace(TWO_RULES, limits=replace(TWO_RULES.limits, rules=1))
    gate = GatedAllowanceReads(plans)
    start = Thread(target=EnableSyncRule(units, RuleLocks(), gate, USER).execute, args=(NEXT_RULE,))
    lowering = Thread(
        target=ChangePlan(SqliteUserDirectory(database), plans, SystemClock()).execute,
        args=(actor, lowered),
    )

    start.start()
    assert gate.read.wait(5)
    lowering.start()
    lowering.join(0.3)
    lowered_during_the_start = not lowering.is_alive()
    gate.release.set()
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
    plans.change_settings(False, TWO_RULES.key)

    waited, outcome = _start_behind(
        database,
        plans,
        units,
        "UPDATE installation_settings SET plans_enabled = 1 WHERE singleton = 1",
    )

    assert waited
    assert outcome == ["refused"]
    assert _rule_state(units, NEXT_RULE) is SyncRuleState.PREVIEWED
