"""The rule limit through the Web API: the rule page, and Start with Plans off (ADR 0038)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import build_adapters, compose
from calendar_sync.domain.model import SyncRule, SyncRuleId, SyncRuleState
from calendar_sync.interfaces.api.app import create_app
from calendar_sync.interfaces.api.dependencies import SESSION_COOKIE
from tests.helpers import endpoint, rule
from tests.plans import plans_on
from tests.users import OTHER_USER, administrator, limited_user, session_for, sqlite_units

NEXT = SyncRule(
    SyncRuleId("next"),
    endpoint("personal-account", "next-calendar"),
    rule().destination,
    state=SyncRuleState.PREVIEWED,
)


def _client(tmp_path: Path, *, plans: bool) -> TestClient:
    """A member with one enabled rule and one previewed, signed in; with `plans`, Plans are on
    and the Default Plan, Free, lets one rule sync."""
    database = tmp_path / "test.db"
    settings = Settings(database)
    adapters = build_adapters(settings)
    administrator(adapters)
    member = limited_user(database, OTHER_USER)
    if plans:
        plans_on(adapters.plan_catalog)
    with sqlite_units(database, user=member)() as uow:
        uow.rules.add(rule())
        uow.rules.add(NEXT)
        uow.commit()
    client = TestClient(create_app(replace(compose(settings, adapters), scheduler=None)))
    client.cookies.set(SESSION_COOKIE, session_for(database, member))
    return client


def test_rule_details_say_whether_start_would_pass_and_name_the_limit(tmp_path: Path) -> None:
    with _client(tmp_path, plans=True) as client:
        over = client.get("/api/v1/rules/next").json()
        enabled = client.get("/api/v1/rules/rule-1").json()

    assert (over["can_start"], over["rule_limit"]) == (False, 1)
    assert (enabled["can_start"], enabled["rule_limit"]) == (True, 1)


def test_with_plans_off_details_name_no_limit_and_start_passes(tmp_path: Path) -> None:
    with _client(tmp_path, plans=False) as client:
        details = client.get("/api/v1/rules/next").json()
        started = client.post("/api/v1/rules/next/enable")

    assert (details["can_start"], details["rule_limit"]) == (True, None)
    assert started.status_code == 200
    assert started.json()["state"] == "enabled"
