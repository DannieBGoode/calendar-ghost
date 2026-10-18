"""Integration Tokens: their format and names, and issuing one within the User's Plan.

There is no in-memory Integration Token store, so issuing runs on SQLite: its Users, Plans, and
tokens share one database, as they do in the installation.
"""

from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from calendar_sync.application.identity.administration import AdministratorRequired
from calendar_sync.application.identity.errors import InvalidIntegrationTokenName
from calendar_sync.application.identity.integration_tokens import (
    IssueIntegrationToken,
    is_well_formed,
    token_name,
)
from calendar_sync.application.identity.ports import IntegrationTokenScope
from calendar_sync.application.sync.ports import Allowances
from calendar_sync.domain.access import Role, UserId
from calendar_sync.domain.plans import LimitedResource, Plan, PlanLimitReached
from calendar_sync.infrastructure.clock import SystemClock
from calendar_sync.infrastructure.identifiers import UuidIdGenerator
from calendar_sync.infrastructure.integration_tokens import SqliteIntegrationTokens
from calendar_sync.infrastructure.persistence.migrations import initialize_database
from calendar_sync.infrastructure.persistence.plans import SqlitePlans
from calendar_sync.infrastructure.persistence.users import SqliteUserDirectory
from tests.helpers import NOW
from tests.identity_fakes import BrokenAllowances
from tests.plans import FAMILY, FREE, as_new, plans_on
from tests.users import OTHER_USER, USER, add_user, limited_user

VALID = "cgs_" + "A" * 43
STATUS = frozenset({IntegrationTokenScope.STATUS_READ})
BOTH = frozenset({IntegrationTokenScope.STATUS_READ, IntegrationTokenScope.INSTALLATION_READ})


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        (VALID, True),
        ("cgs_" + "a-_9" * 10 + "abc", True),
        ("cgs_" + "A" * 42, False),
        ("cgs_" + "A" * 44, False),
        ("cgx_" + "A" * 43, False),
        ("cgs_" + "A" * 42 + "=", False),
        ("cgs_" + "A" * 42 + "\n", False),
        ("", False),
        ("x" * 10_000, False),
    ],
)
def test_only_the_exact_token_format_is_well_formed(token: str, expected: bool) -> None:
    assert is_well_formed(token) is expected


def test_names_are_trimmed() -> None:
    assert token_name("  Uptime Kuma  ") == "Uptime Kuma"


@pytest.mark.parametrize(
    "name",
    ["", "   ", "x" * 81, "Kuma\nadmin", "Kuma\x1b[31m", "Kuma\u2028admin", "Kuma\u2029admin"],
)
def test_names_must_be_short_printable_text(name: str) -> None:
    with pytest.raises(InvalidIntegrationTokenName):
        token_name(name)


# Issuing a token within the User's Plan (ADR 0038)


@dataclass
class _Installation:
    """One SQLite installation; USER is its Installation Administrator."""

    database: Path
    users: SqliteUserDirectory
    plans: SqlitePlans
    tokens: SqliteIntegrationTokens

    def issuing(self, user: UserId, allowances: Allowances | None = None) -> IssueIntegrationToken:
        """The use case one request of `user` gets, reading `allowances` or the stored Plans."""
        return IssueIntegrationToken(
            user,
            self.users,
            self.tokens.for_user(user),
            self.plans if allowances is None else allowances,
        )

    def names(self, user: UserId) -> list[str]:
        """The User's unrevoked tokens, by name."""
        return sorted(
            token.name for token in self.tokens.for_user(user).list() if token.revoked_at is None
        )


def _installation(tmp_path: Path) -> _Installation:
    database = tmp_path / "test.db"
    initialize_database(database)
    add_user(database, USER)
    return _Installation(
        database,
        SqliteUserDirectory(database),
        SqlitePlans(database),
        SqliteIntegrationTokens(database, SystemClock(), UuidIdGenerator()),
    )


def test_a_token_past_the_plans_limit_is_refused_and_nothing_is_stored(tmp_path: Path) -> None:
    installation = _installation(tmp_path)
    plans_on(installation.plans, FAMILY)
    member = limited_user(installation.database)
    for name in ("Uptime Kuma", "Homepage"):
        installation.issuing(member).execute(name, STATUS)

    with pytest.raises(PlanLimitReached) as refused:
        installation.issuing(member).execute("Claude Code", STATUS)

    assert (refused.value.resource, refused.value.limit) == (LimitedResource.INTEGRATION_TOKENS, 2)
    assert installation.names(member) == ["Homepage", "Uptime Kuma"]


def test_a_revoked_token_gives_its_place_back(tmp_path: Path) -> None:
    installation = _installation(tmp_path)
    plans_on(installation.plans, FAMILY)
    member = limited_user(installation.database)
    old = installation.issuing(member).execute("Old monitor", STATUS)
    installation.issuing(member).execute("Homepage", STATUS)
    assert installation.tokens.for_user(member).revoke(old.summary.id)

    installation.issuing(member).execute("Uptime Kuma", STATUS)

    assert installation.names(member) == ["Homepage", "Uptime Kuma"]


def test_a_plan_offering_no_tokens_refuses_the_first(tmp_path: Path) -> None:
    installation = _installation(tmp_path)
    plans_on(installation.plans, FREE)
    member = limited_user(installation.database)

    with pytest.raises(PlanLimitReached) as refused:
        installation.issuing(member).execute("Uptime Kuma", STATUS)

    assert (refused.value.resource, refused.value.limit) == (LimitedResource.INTEGRATION_TOKENS, 0)
    assert installation.names(member) == []


def test_administrators_are_never_limited(tmp_path: Path) -> None:
    installation = _installation(tmp_path)
    plans_on(installation.plans, FREE)

    for name in ("Uptime Kuma", "Homepage", "Claude Code"):
        installation.issuing(USER).execute(name, STATUS)

    assert installation.names(USER) == ["Claude Code", "Homepage", "Uptime Kuma"]


def test_with_plans_off_nobody_is_limited_even_with_a_plan_of_their_own(tmp_path: Path) -> None:
    installation = _installation(tmp_path)
    installation.plans.add(as_new(FREE), NOW)
    member = limited_user(installation.database, plan=FREE.key.value)

    for name in ("Uptime Kuma", "Homepage", "Claude Code"):
        installation.issuing(member).execute(name, STATUS)

    assert installation.names(member) == ["Claude Code", "Homepage", "Uptime Kuma"]


def test_an_allowance_that_cannot_be_read_fails_the_issue_and_stores_nothing(
    tmp_path: Path,
) -> None:
    installation = _installation(tmp_path)
    plans_on(installation.plans, FAMILY)
    member = limited_user(installation.database)

    with pytest.raises(RuntimeError, match="database is locked"):
        installation.issuing(member, BrokenAllowances()).execute("Uptime Kuma", STATUS)

    assert installation.names(member) == []


@pytest.mark.parametrize("plan", [FAMILY, FREE], ids=["room left", "no room"])
def test_installation_read_needs_an_administrator_whatever_the_plan_allows(
    tmp_path: Path, plan: Plan
) -> None:
    installation = _installation(tmp_path)
    plans_on(installation.plans, plan)
    member = limited_user(installation.database)

    with pytest.raises(AdministratorRequired):
        installation.issuing(member).execute("Uptime Kuma", BOTH)

    assert installation.names(member) == []


def test_installation_read_is_refused_before_the_plan_is_read(tmp_path: Path) -> None:
    installation = _installation(tmp_path)
    member = limited_user(installation.database)

    # Reading the Allowance would raise; the refusal comes first, so it is never read.
    with pytest.raises(AdministratorRequired):
        installation.issuing(member, BrokenAllowances()).execute("Uptime Kuma", BOTH)


def test_an_administrator_issues_an_installation_read_token(tmp_path: Path) -> None:
    installation = _installation(tmp_path)
    plans_on(installation.plans, FREE)

    issued = installation.issuing(USER).execute("Uptime Kuma", BOTH)

    assert issued.summary.scopes == BOTH


def test_existing_tokens_keep_working_after_the_limit_is_lowered(tmp_path: Path) -> None:
    installation = _installation(tmp_path)
    plans_on(installation.plans, FAMILY)
    member = limited_user(installation.database)
    issued = [
        installation.issuing(member).execute(name, STATUS) for name in ("Uptime Kuma", "Homepage")
    ]
    lowered = replace(FAMILY, limits=replace(FAMILY.limits, integration_tokens=0))
    installation.plans.change(lowered, NOW)

    with pytest.raises(PlanLimitReached) as refused:
        installation.issuing(member).execute("Claude Code", STATUS)

    assert refused.value.limit == 0
    assert [installation.tokens.authenticate(each.token) is not None for each in issued] == [
        True,
        True,
    ]


def test_an_administrator_demoted_past_the_limit_keeps_their_tokens_but_issues_no_more(
    tmp_path: Path,
) -> None:
    installation = _installation(tmp_path)
    plans_on(installation.plans, FREE)
    other = add_user(installation.database, OTHER_USER)
    kept = [
        installation.issuing(other).execute("Uptime Kuma", STATUS),
        installation.issuing(other).execute("Health monitor", BOTH),
    ]

    installation.users.set_role(other, Role.USER)
    with pytest.raises(PlanLimitReached) as refused:
        installation.issuing(other).execute("Homepage", STATUS)
    with pytest.raises(AdministratorRequired):
        installation.issuing(other).execute("Homepage", BOTH)
    working = [installation.tokens.authenticate(each.token) is not None for each in kept]
    installation.users.set_role(other, Role.INSTALLATION_ADMINISTRATOR)
    promoted = installation.issuing(other).execute("Homepage", STATUS)

    assert refused.value.limit == 0
    assert working == [True, True]
    assert promoted.summary.name == "Homepage"
    assert installation.names(other) == ["Health monitor", "Homepage", "Uptime Kuma"]
