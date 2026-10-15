"""Plan limits hold when requests race on one SQLite database (ADR 0038).

Each limit check reads the User's Allowance once its own write holds SQLite's writer lock, so two
requests cannot both take the last place, and a lower limit cannot commit between a check and
its write. `HeldAllowances` holds a check at its read, so a test can show what another request
does meanwhile.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from threading import Event, Thread

import pytest

from calendar_sync.application.identity.integration_tokens import IssueIntegrationToken
from calendar_sync.application.identity.ports import IntegrationTokenScope, IssuedIntegrationToken
from calendar_sync.application.sync.ports import Allowances
from calendar_sync.domain.access import UserId
from calendar_sync.domain.plans import Allowance, LimitedResource, PlanLimitReached
from calendar_sync.infrastructure.clock import SystemClock
from calendar_sync.infrastructure.identifiers import UuidIdGenerator
from calendar_sync.infrastructure.integration_tokens import SqliteIntegrationTokens
from calendar_sync.infrastructure.persistence.migrations import initialize_database
from calendar_sync.infrastructure.persistence.plans import SqlitePlans
from calendar_sync.infrastructure.persistence.users import SqliteUserDirectory
from tests.helpers import NOW
from tests.plans import FAMILY, plans_on
from tests.users import add_user, limited_user

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
