"""The Plans routes over the Web API: an Installation Administrator defines, changes, removes,
and assigns Plans and turns them on, and every User reads their own Plan (ADR 0038)."""

from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import build_adapters, compose
from calendar_sync.domain.access import UserId
from calendar_sync.domain.model import SyncRuleId, SyncRuleState
from calendar_sync.domain.plans import NewPlan, Plan
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.persistence.plans import SqlitePlans
from calendar_sync.infrastructure.security import CredentialCipher
from calendar_sync.interfaces.api.app import create_app
from calendar_sync.interfaces.api.dependencies import SESSION_COOKIE
from tests.helpers import NOW, endpoint, rule
from tests.users import (
    ADMIN_EMAIL,
    ADMIN_PASSWORD,
    OTHER_USER,
    administrator,
    limited_user,
    session_for,
    sqlite_units,
)

MEMBER_EMAIL = "member@example.test"
# What defines tests.plans.FREE and FAMILY through the Web API.
FREE_BODY: dict[str, Any] = {
    "key": "free",
    "name": "Free",
    "limits": {
        "rules": 1,
        "connected_accounts": 1,
        "integration_tokens": 0,
        "sync_interval": "5_minutes",
    },
}
FAMILY_BODY: dict[str, Any] = {
    "key": "family",
    "name": "Family",
    "limits": {
        "rules": 5,
        "connected_accounts": 3,
        "integration_tokens": 2,
        "sync_interval": "instant",
    },
}
NO_LIMITS_BODY: dict[str, Any] = {
    "key": "no-limits",
    "name": "No limits",
    "limits": {
        "rules": None,
        "connected_accounts": None,
        "integration_tokens": None,
        "sync_interval": "instant",
    },
}
"""The Plan turning Plans on with no default makes the default."""
NO_USE: dict[str, Any] = {
    "over_people": 0,
    "use": {"rules": [], "connected_accounts": [], "integration_tokens": []},
}
"""What a Plan says when the people it limits have nothing it counts."""
NOBODY_ON_IT: dict[str, Any] = {"is_default": False, "people": 0, "limited_people": 0, **NO_USE}
"""What a Plan nobody has says about the people who have it."""
CHANGE_FREE = {"name": "Free", "limits": FREE_BODY["limits"]}
CHANGE_FAMILY = {"name": "Family", "limits": FAMILY_BODY["limits"]}
OFFERED = ["instant", "5_minutes", "10_minutes", "15_minutes", "30_minutes", "60_minutes"]
# Your plan for someone no Plan limits.
UNLIMITED = {
    "plan": None,
    "limits": None,
    "instant": True,
    "poll_every_minutes": 5,
    "may_connect_account": True,
    "may_issue_token": True,
    "over_rule_limit": False,
}


@dataclass(frozen=True, slots=True)
class Installation:
    database: Path
    client: TestClient
    admin: UserId
    member: UserId
    """Someone Plans can limit: they do not administer."""

    def as_admin(self) -> None:
        self.client.cookies.set(SESSION_COOKIE, session_for(self.database, self.admin))

    def as_member(self) -> None:
        self.client.cookies.set(SESSION_COOKIE, session_for(self.database, self.member))

    def define(self, *bodies: dict[str, Any]) -> None:
        for body in bodies:
            response = self.client.post("/api/v1/plans", json=body)
            assert response.status_code == 201, response.text

    def turn_on(self, default: str) -> None:
        response = self.client.put(
            "/api/v1/plan-settings", json={"enabled": True, "default_plan": default}
        )
        assert response.status_code == 200, response.text

    def overview_plan(self, user: UserId) -> Any:
        """The Plan the person page shows about `user`, read by the administrator."""
        response = self.client.get(f"/api/v1/users/{user.value}/overview")
        assert response.status_code == 200, response.text
        return response.json()["plan"]


@pytest.fixture
def installation(tmp_path: Path) -> Iterator[Installation]:
    database = tmp_path / "test.db"
    # A master key, so Your plan counts calendar accounts; no scheduler runs anyone's rules.
    settings = Settings(database, master_key=CredentialCipher.generate_key())
    adapters = build_adapters(settings)
    admin = administrator(adapters)
    member = limited_user(database, OTHER_USER, email=MEMBER_EMAIL)
    app = create_app(replace(compose(settings, adapters), scheduler=None))
    with TestClient(app) as client:
        installation = Installation(database, client, admin, member)
        installation.as_admin()
        yield installation


def _problem(response: Any) -> tuple[int, str, dict[str, Any]]:
    """The status, code, and params an error answer carries."""
    body = response.json()
    return response.status_code, body["code"], body["params"]


def _invalid(reason: str) -> tuple[int, str, dict[str, Any]]:
    """The answer to a Plan that is not valid; a limit's also names the largest limit."""
    params: dict[str, Any] = {"reason": reason}
    if reason == "limit":
        params["max"] = 10_000
    return 422, "invalid_plan", params


def _with_limits(body: dict[str, Any], **limits: Any) -> dict[str, Any]:
    return {**body, "limits": {**body["limits"], **limits}}


def _use(
    body: dict[str, Any], rules: int = 0, accounts: int = 0, tokens: int = 0
) -> dict[str, Any]:
    """How much of the Plan in `body` a person uses, as their page shows it."""
    limits = body["limits"]
    return {
        "rules": {"in_use": rules, "allowed": limits["rules"]},
        "connected_accounts": {"in_use": accounts, "allowed": limits["connected_accounts"]},
        "integration_tokens": {"in_use": tokens, "allowed": limits["integration_tokens"]},
        "sync_interval": limits["sync_interval"],
    }


def _member_rules(installation: Installation) -> None:
    """Two enabled rules between the member's two calendar accounts, which count, and a previewed
    rule that has not started, which does not."""
    first = rule()
    second = replace(
        first, id=SyncRuleId("rule-2"), source=first.destination, destination=first.source
    )
    previewed = replace(
        rule(state=SyncRuleState.PREVIEWED),
        id=SyncRuleId("rule-3"),
        source=endpoint("personal-account", "other-calendar"),
    )
    with sqlite_units(installation.database, user=installation.member)() as uow:
        for each in (first, second, previewed):
            uow.rules.add(each)
        uow.commit()


def test_an_administrator_defines_lists_changes_and_removes_plans(
    installation: Installation,
) -> None:
    client = installation.client
    empty = client.get("/api/v1/plans").json()
    defined = client.post("/api/v1/plans", json=FREE_BODY)
    installation.define(FAMILY_BODY)
    listed = client.get("/api/v1/plans").json()["plans"]
    changed = client.put(
        "/api/v1/plans/free",
        json={
            "name": "  Starter  ",
            "limits": {**FREE_BODY["limits"], "rules": 2, "integration_tokens": None},
        },
    )
    removed = client.delete("/api/v1/plans/family")
    after = client.get("/api/v1/plans").json()["plans"]

    assert empty == {
        "enabled": False,
        "default_plan": None,
        "sync_intervals": OFFERED,
        "followers": 2,
        "plans": [],
    }
    assert defined.status_code == 201
    assert defined.json() == {**FREE_BODY, **NOBODY_ON_IT}
    # By name: Family before Free.
    assert [plan["key"] for plan in listed] == ["family", "free"]
    # The key stays, spaces around the name go, and null is unlimited.
    assert changed.status_code == 200
    assert changed.json() == {
        "key": "free",
        "name": "Starter",
        "limits": {
            "rules": 2,
            "connected_accounts": 1,
            "integration_tokens": None,
            "sync_interval": "5_minutes",
        },
        **NOBODY_ON_IT,
    }
    assert removed.status_code == 204
    assert [plan["key"] for plan in after] == ["free"]


def test_a_new_plan_without_a_key_gets_one_made_from_its_name(
    installation: Installation,
) -> None:
    client = installation.client
    unkeyed = {key: value for key, value in FREE_BODY.items() if key != "key"}

    first = client.post("/api/v1/plans", json=unkeyed)
    second = client.post("/api/v1/plans", json={**FAMILY_BODY, "key": None, "name": "Free!"})
    unnamed = client.post("/api/v1/plans", json={**unkeyed, "name": "日本"})
    # The New plan panel's address is /people/plans/new, so no Plan has the key "new".
    new = client.post("/api/v1/plans", json={**unkeyed, "name": "New"})
    taken = client.post("/api/v1/plans", json={**FAMILY_BODY, "key": "free-2"})
    listed = client.get("/api/v1/plans").json()["plans"]

    assert first.status_code == 201
    assert first.json() == {**FREE_BODY, **NOBODY_ON_IT}
    assert (second.status_code, second.json()["key"]) == (201, "free-2")
    assert (unnamed.status_code, unnamed.json()["key"]) == (201, "plan")
    assert (new.status_code, new.json()["key"]) == (201, "new-2")
    # A key asked for is never changed to fit: another Plan has it, so it is refused.
    assert _problem(taken) == (409, "plan_key_taken", {})
    assert [(plan["key"], plan["name"]) for plan in listed] == [
        ("free", "Free"),
        ("free-2", "Free!"),
        ("new-2", "New"),
        ("plan", "日本"),
    ]


def test_a_name_another_plan_has_is_refused_on_define_and_change(
    installation: Installation,
) -> None:
    client = installation.client
    installation.define(FREE_BODY, FAMILY_BODY)

    defined = client.post("/api/v1/plans", json={**FAMILY_BODY, "key": None, "name": " free "})
    renamed = client.put("/api/v1/plans/family", json={**CHANGE_FAMILY, "name": "FREE"})
    recased = client.put("/api/v1/plans/free", json={**CHANGE_FREE, "name": "FREE"})
    listed = client.get("/api/v1/plans").json()["plans"]

    assert _problem(defined) == (409, "plan_name_taken", {"name": "Free"})
    assert _problem(renamed) == (409, "plan_name_taken", {"name": "Free"})
    # A Plan may keep its own name in another case.
    assert (recased.status_code, recased.json()["name"]) == (200, "FREE")
    assert {plan["key"]: plan["name"] for plan in listed} == {"family": "Family", "free": "FREE"}


def test_each_plan_says_how_many_people_it_limits_have_more_than_it_allows(
    installation: Installation,
) -> None:
    """The member has two rules that count and two calendar accounts, where Free allows one of
    each; nobody has Family."""
    client = installation.client
    _member_rules(installation)
    installation.define(FREE_BODY, FAMILY_BODY)

    turned_on = client.put("/api/v1/plan-settings", json={"enabled": True, "default_plan": "free"})
    listed = {plan["key"]: plan for plan in client.get("/api/v1/plans").json()["plans"]}
    raised = client.put(
        "/api/v1/plans/free", json=_with_limits(CHANGE_FREE, rules=2, connected_accounts=2)
    )
    member_page = installation.overview_plan(installation.member)

    free_use = {
        "rules": [{"in_use": 2, "people": 1}],
        "connected_accounts": [{"in_use": 2, "people": 1}],
        "integration_tokens": [],
    }
    assert turned_on.json()["plans"] == [
        {**FAMILY_BODY, **NOBODY_ON_IT},
        {
            **FREE_BODY,
            "is_default": True,
            "people": 2,
            "limited_people": 1,
            "over_people": 1,
            "use": free_use,
        },
    ]
    assert listed["free"] == turned_on.json()["plans"][1]
    # Within the raised limits, nobody has more than Free allows.
    assert (raised.json()["over_people"], raised.json()["use"]) == (0, free_use)
    assert member_page["over"] == []


def test_turning_plans_on_with_no_default_makes_a_no_limits_plan_that_limits_nobody(
    installation: Installation,
) -> None:
    client = installation.client
    installation.define(FREE_BODY)

    turned_on = client.put("/api/v1/plan-settings", json={"enabled": True, "default_plan": None})
    renamed = client.put(
        "/api/v1/plans/no-limits", json={"name": "Everyone", "limits": NO_LIMITS_BODY["limits"]}
    )
    removed = client.delete("/api/v1/plans/no-limits")
    cleared = client.put("/api/v1/plan-settings", json={"enabled": True, "default_plan": None})
    installation.as_member()
    own = client.get("/api/v1/account/plan").json()

    assert turned_on.status_code == 200
    assert turned_on.json() == {
        "enabled": True,
        "default_plan": "no-limits",
        "sync_intervals": OFFERED,
        "followers": 2,
        "plans": [
            {**FREE_BODY, **NOBODY_ON_IT},
            # Everyone has it, and it limits the member, by nothing.
            {**NO_LIMITS_BODY, "is_default": True, "people": 2, "limited_people": 1, **NO_USE},
        ],
    }
    # An ordinary Plan: it can be renamed, but not removed while it is the default.
    assert (renamed.status_code, renamed.json()["name"]) == (200, "Everyone")
    assert _problem(removed) == (409, "plan_is_default", {})
    assert _problem(cleared) == (409, "plans_need_default", {})
    assert own == {
        **UNLIMITED,
        "basis": "plan",
        "plan": {"key": "no-limits", "name": "Everyone", "on_default": True},
        "limits": NO_LIMITS_BODY["limits"],
        "rules_counted": 0,
        "connected_accounts": 0,
        "integration_tokens": 0,
    }


def test_the_default_is_never_cleared_while_plans_are_on_and_turning_them_off_keeps_every_plan(
    installation: Installation,
) -> None:
    client = installation.client
    installation.define(FREE_BODY)

    def setting(enabled: bool, default: str | None) -> Any:
        return client.put(
            "/api/v1/plan-settings", json={"enabled": enabled, "default_plan": default}
        )

    chosen = setting(False, "free")
    cleared_turning_on = setting(True, None)
    turned_on = setting(True, "free")
    cleared_while_on = setting(True, None)
    turned_off = setting(False, "free")
    cleared_while_off = setting(False, None)
    removed = client.delete("/api/v1/plans/free")

    # Turning Plans on never clears a default the administrator chose.
    assert _problem(cleared_turning_on) == (409, "plans_need_default", {})
    assert chosen.json() == {
        "enabled": False,
        "default_plan": "free",
        "sync_intervals": OFFERED,
        "followers": 2,
        # Everyone has the default; it would limit only the member, never an administrator.
        "plans": [{**FREE_BODY, "is_default": True, "people": 2, "limited_people": 1, **NO_USE}],
    }
    assert (turned_on.json()["enabled"], turned_on.json()["default_plan"]) == (True, "free")
    assert _problem(cleared_while_on) == (409, "plans_need_default", {})
    assert (turned_off.json()["enabled"], turned_off.json()["default_plan"]) == (False, "free")
    assert [plan["key"] for plan in turned_off.json()["plans"]] == ["free"]
    assert (cleared_while_off.json()["enabled"], cleared_while_off.json()["default_plan"]) == (
        False,
        None,
    )
    # No longer the default and nobody's own, so it may go.
    assert removed.status_code == 204


def test_each_refusal_answers_its_code_and_params(installation: Installation) -> None:
    client = installation.client
    installation.define(FREE_BODY, FAMILY_BODY)
    installation.turn_on("free")
    _assign(installation, "family", installation.member)

    answers = {
        "taken": client.post("/api/v1/plans", json={**FAMILY_BODY, "name": "Another"}),
        "default": client.delete("/api/v1/plans/free"),
        "in_use": client.delete("/api/v1/plans/family"),
        "needs_default": client.put(
            "/api/v1/plan-settings", json={"enabled": True, "default_plan": None}
        ),
        "unknown_default": client.put(
            "/api/v1/plan-settings", json={"enabled": True, "default_plan": "gold"}
        ),
        "unknown_change": client.put("/api/v1/plans/gold", json=CHANGE_FAMILY),
        "unknown_removal": client.delete("/api/v1/plans/gold"),
    }
    listed = client.get("/api/v1/plans").json()

    assert {name: _problem(response) for name, response in answers.items()} == {
        "taken": (409, "plan_key_taken", {}),
        "default": (409, "plan_is_default", {}),
        "in_use": (409, "plan_in_use", {"people": 1, "count": 1}),
        "needs_default": (409, "plans_need_default", {}),
        "unknown_default": (404, "plan_not_found", {}),
        "unknown_change": (404, "plan_not_found", {}),
        "unknown_removal": (404, "plan_not_found", {}),
    }
    # Nothing a refusal answered changed anything.
    assert (listed["enabled"], listed["default_plan"]) == (True, "free")
    assert [(plan["key"], plan["name"]) for plan in listed["plans"]] == [
        ("family", "Family"),
        ("free", "Free"),
    ]


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        pytest.param({**FREE_BODY, "key": "Bad"}, "key", id="upper-case-key"),
        pytest.param({**FREE_BODY, "key": "-free"}, "key", id="leading-hyphen"),
        pytest.param({**FREE_BODY, "key": "free plan"}, "key", id="space-in-key"),
        pytest.param({**FREE_BODY, "key": "a" * 33}, "key", id="33-character-key"),
        pytest.param({**FREE_BODY, "key": ""}, "key", id="empty-key"),
        pytest.param({**FREE_BODY, "key": "new"}, "key", id="reserved-key"),
        pytest.param({**FREE_BODY, "name": "   "}, "name", id="blank-name"),
        pytest.param({**FREE_BODY, "name": "Free\nplan"}, "name", id="line-break"),
        pytest.param({**FREE_BODY, "name": "x" * 61}, "name", id="61-character-name"),
        pytest.param(_with_limits(FREE_BODY, rules=0), "limit", id="no-rules"),
        pytest.param(_with_limits(FREE_BODY, connected_accounts=0), "limit", id="no-accounts"),
        pytest.param(_with_limits(FREE_BODY, integration_tokens=-1), "limit", id="minus-tokens"),
        pytest.param(_with_limits(FREE_BODY, rules=10_001), "limit", id="10001-rules"),
    ],
)
def test_a_new_plan_that_is_not_valid_is_refused_with_its_reason(
    installation: Installation, body: dict[str, Any], reason: str
) -> None:
    response = installation.client.post("/api/v1/plans", json=body)

    assert _problem(response) == _invalid(reason)
    assert installation.client.get("/api/v1/plans").json()["plans"] == []


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        pytest.param({**CHANGE_FREE, "name": ""}, "name", id="empty-name"),
        pytest.param(
            _with_limits(CHANGE_FREE, connected_accounts=10_001), "limit", id="10001-accounts"
        ),
    ],
)
def test_a_plan_change_that_is_not_valid_is_refused_with_its_reason(
    installation: Installation, change: dict[str, Any], reason: str
) -> None:
    installation.define(FREE_BODY)
    response = installation.client.put("/api/v1/plans/free", json=change)
    listed = installation.client.get("/api/v1/plans").json()["plans"]

    assert _problem(response) == _invalid(reason)
    assert listed == [{**FREE_BODY, **NOBODY_ON_IT}]


def test_an_interval_this_release_does_not_know_is_an_invalid_request(
    installation: Installation,
) -> None:
    response = installation.client.post(
        "/api/v1/plans", json=_with_limits(FREE_BODY, sync_interval="2_minutes")
    )
    body = response.json()

    assert (response.status_code, body["code"], body["params"]["field"]) == (
        422,
        "invalid_request",
        "sync_interval",
    )


def test_a_new_plan_another_administrator_removed_at_once_is_answered_as_not_found(
    installation: Installation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Plan is stored, then removed before its listing is read back: 404, never 500."""
    original_add = SqlitePlans.add

    def add_then_removed(self: SqlitePlans, plan: NewPlan, at: datetime) -> Plan:
        stored = original_add(self, plan, at)
        SqlitePlans(installation.database).remove(stored.key)
        return stored

    monkeypatch.setattr(SqlitePlans, "add", add_then_removed)
    response = installation.client.post("/api/v1/plans", json=FREE_BODY)

    assert _problem(response) == (404, "plan_not_found", {})


def _giving(plan: str) -> dict[str, Any]:
    """A request that gives the member the Plan `plan` names."""
    return {"plans": {OTHER_USER.value: plan}}


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        pytest.param("PUT", "/api/v1/plans/Bad%20Key", CHANGE_FREE, id="change-with-a-space"),
        pytest.param("PUT", f"/api/v1/plans/{'a' * 33}", CHANGE_FREE, id="change-33-characters"),
        pytest.param("DELETE", "/api/v1/plans/%20", None, id="remove-blank"),
        pytest.param("DELETE", "/api/v1/plans/UPPER", None, id="remove-upper-case"),
        pytest.param(
            "PUT",
            "/api/v1/plan-settings",
            {"enabled": True, "default_plan": "UPPER"},
            id="default-upper-case",
        ),
        pytest.param(
            "PUT",
            "/api/v1/plan-settings",
            {"enabled": False, "default_plan": "x y"},
            id="default-with-a-space",
        ),
        pytest.param("POST", "/api/v1/plan-assignments", _giving("x y"), id="assign-space"),
        pytest.param("POST", "/api/v1/plan-assignments", _giving(""), id="assign-empty"),
        pytest.param(
            "PUT",
            "/api/v1/plan-settings",
            {"enabled": False, "default_plan": "a" * 33},
            id="default-33-characters",
        ),
        pytest.param(
            "PUT",
            "/api/v1/plan-settings",
            {"enabled": False, "default_plan": "a" * 201},
            id="default-201-characters",
        ),
        pytest.param(
            "POST", "/api/v1/plan-assignments", _giving("a" * 33), id="assign-33-characters"
        ),
        pytest.param(
            "POST", "/api/v1/plan-assignments", _giving("a" * 201), id="assign-201-characters"
        ),
    ],
)
def test_a_malformed_plan_key_names_no_plan(
    installation: Installation, method: str, path: str, body: dict[str, Any] | None
) -> None:
    """Never 422 or 500: a key this release refuses, of any length, is answered as an unknown
    Plan."""
    installation.define(FREE_BODY)
    response = installation.client.request(method, path, json=body)

    assert _problem(response) == (404, "plan_not_found", {})


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        pytest.param("PUT", f"/api/v1/plans/{'a' * 5000}", CHANGE_FREE, id="path"),
        pytest.param(
            "PUT",
            "/api/v1/plan-settings",
            {"enabled": False, "default_plan": "a" * 100_000},
            id="default",
        ),
        pytest.param("POST", "/api/v1/plan-assignments", _giving("a" * 100_000), id="assign"),
    ],
)
def test_a_missing_plan_answer_never_repeats_a_malformed_key(
    installation: Installation, method: str, path: str, body: dict[str, Any] | None
) -> None:
    """However long the key sent, the answer stays short: it names no key this release refuses."""
    response = installation.client.request(method, path, json=body)

    assert _problem(response) == (404, "plan_not_found", {})
    assert "aaaa" not in response.json()["detail"]


def test_every_interval_is_offered_instant_first(installation: Installation) -> None:
    offered = installation.client.get("/api/v1/plans").json()["sync_intervals"]

    assert offered == [
        "instant",
        "5_minutes",
        "10_minutes",
        "15_minutes",
        "30_minutes",
        "60_minutes",
    ]


def test_a_plan_can_sync_every_hour(installation: Installation) -> None:
    client = installation.client
    hourly = _with_limits(FAMILY_BODY, sync_interval="60_minutes")

    defined = client.post("/api/v1/plans", json=hourly)
    listed = client.get("/api/v1/plans").json()["plans"]

    assert defined.status_code == 201
    assert defined.json() == {**hourly, **NOBODY_ON_IT}
    assert listed == [{**hourly, **NOBODY_ON_IT}]


def test_an_interval_this_release_does_not_know_reads_as_instant(
    installation: Installation,
) -> None:
    client = installation.client
    installation.define(FREE_BODY)
    installation.turn_on("free")
    with transaction(installation.database) as connection:
        connection.execute("UPDATE plans SET sync_interval = 'every_2_minutes' WHERE key = 'free'")
    listed = client.get("/api/v1/plans").json()["plans"][0]["limits"]["sync_interval"]
    installation.as_member()
    reads = [client.get(path) for path in ("/api/v1/session", "/api/v1/rules")]
    own = client.get("/api/v1/account/plan").json()

    assert listed == "instant"
    assert [response.status_code for response in reads] == [200, 200]
    assert (own["limits"]["sync_interval"], own["instant"]) == ("instant", True)


def test_a_stored_plan_key_this_release_refuses_never_breaks_sign_in_or_the_rules_api(
    installation: Installation,
) -> None:
    client = installation.client
    installation.define(FREE_BODY)
    installation.turn_on("free")
    # A key a later release might write, given to both Users.
    with transaction(installation.database) as connection:
        connection.execute(
            """
            INSERT INTO plans (
                key, name, rule_limit, account_limit, token_limit, sync_interval, created_at,
                updated_at
            ) VALUES ('Later Key', 'Later', 1, 1, 0, 'instant', ?, ?)
            """,
            (NOW.isoformat(), NOW.isoformat()),
        )
        connection.execute(
            "UPDATE users SET plan_key = 'Later Key' WHERE id IN (?, ?)",
            (installation.admin.value, installation.member.value),
        )
    client.cookies.clear()
    signed_in = client.post(
        "/api/v1/session", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    administrator_reads = [
        client.get(path)
        for path in (
            "/api/v1/session",
            "/api/v1/rules",
            "/api/v1/account/plan",
            f"/api/v1/users/{installation.member.value}/overview",
        )
    ]
    installation.as_member()
    member_reads = [
        client.get(path) for path in ("/api/v1/session", "/api/v1/rules", "/api/v1/account/plan")
    ]

    assert signed_in.status_code == 200, signed_in.text
    assert [response.status_code for response in administrator_reads + member_reads] == [200] * 7
    assert member_reads[0].json()["user"]["id"] == installation.member.value
    # The key names no Plan, so the Default Plan still limits the member.
    assert member_reads[2].json()["basis"] == "plan"


def test_an_administrator_assigns_plans_even_while_plans_are_off(
    installation: Installation,
) -> None:
    client, member = installation.client, installation.member
    installation.define(FREE_BODY, FAMILY_BODY)
    while_off = _assign(installation, "family", member)
    installation.turn_on("free")
    once_on = installation.overview_plan(member)
    returned = _assign(installation, None, member)
    to_administrator = _assign(installation, "family", installation.admin)
    listed = {plan["key"]: plan for plan in client.get("/api/v1/plans").json()["plans"]}

    family = {"key": "family", "name": "Family"}
    assert while_off["people"][0]["has"] == {**family, "on_default": False}
    # Given by the administrator, at the time it was given.
    assert datetime.fromisoformat(once_on.pop("assigned_at")).tzinfo is not None
    assert once_on == {
        "basis": "plan",
        "plan": {**family, "on_default": False},
        "assigned": family,
        "has": {**family, "on_default": False},
        "over": [],
        "assigned_by": ADMIN_EMAIL,
        "use": _use(FAMILY_BODY),
    }
    assert returned["people"][0]["has"] == {"key": "free", "name": "Free", "on_default": True}
    # An administrator's own Plan is kept, and limits them only once they stop administering.
    assert to_administrator["people"][0]["has"] == {**family, "on_default": False}
    assert (listed["family"]["people"], listed["family"]["limited_people"]) == (1, 0)
    assert (listed["free"]["people"], listed["free"]["limited_people"]) == (1, 1)


def test_everyone_without_a_plan_of_their_own_follows_a_new_default_at_once(
    installation: Installation,
) -> None:
    client, database = installation.client, installation.database
    installation.define(FREE_BODY, FAMILY_BODY)
    own_free = limited_user(database, UserId("user-3"), plan="free", email="own@example.test")
    installation.turn_on("free")
    switched = client.put("/api/v1/plan-settings", json={"enabled": True, "default_plan": "family"})
    # Someone invited after the change joins with no Plan of their own.
    client.put("/api/v1/registration", json={"policy": "invitation_only"})
    token = client.post("/api/v1/invitations").json()["token"]
    joined = client.post(
        "/api/v1/invitations/accept",
        json={"token": token, "email": "invited@example.test", "password": "a long password here"},
    )
    invited = UserId(joined.json()["user"]["id"])
    client.cookies.clear()
    installation.as_admin()
    followers = client.get("/api/v1/plans").json()["followers"]
    member_seen = installation.overview_plan(installation.member)
    invited_seen = installation.overview_plan(invited)
    own_seen = installation.overview_plan(own_free)
    old_default = client.delete("/api/v1/plans/free")
    new_default = client.delete("/api/v1/plans/family")
    cleared = client.put("/api/v1/plan-settings", json={"enabled": True, "default_plan": None})
    installation.as_member()
    member_own = client.get("/api/v1/account/plan").json()

    default_family = {"key": "family", "name": "Family", "on_default": True}
    on_family: dict[str, Any] = {
        "basis": "plan",
        "plan": default_family,
        "assigned": None,
        "has": default_family,
        "over": [],
        # Nobody gave it: they have the default.
        "assigned_by": None,
        "assigned_at": None,
        "use": _use(FAMILY_BODY),
    }
    assert switched.status_code == 200
    assert joined.status_code == 200, joined.text
    # Make default moves the administrator and the member, then the invited person too, never
    # someone with a Plan of their own.
    assert switched.json()["followers"] == 2
    assert followers == 3
    assert member_seen == on_family
    assert invited_seen == on_family
    # Someone with a Plan of their own keeps it.
    free_of_their_own = {"key": "free", "name": "Free", "on_default": False}
    # Their own, though nothing recorded who gave it.
    assert own_seen == {
        "basis": "plan",
        "plan": free_of_their_own,
        "assigned": {"key": "free", "name": "Free"},
        "has": free_of_their_own,
        "over": [],
        "assigned_by": None,
        "assigned_at": None,
        "use": _use(FREE_BODY),
    }
    assert (member_own["plan"], member_own["limits"]) == (
        {"key": "family", "name": "Family", "on_default": True},
        FAMILY_BODY["limits"],
    )
    # The old default is someone's own Plan, the new one is the default, and Plans stay on.
    assert _problem(old_default) == (409, "plan_in_use", {"people": 1, "count": 1})
    assert _problem(new_default) == (409, "plan_is_default", {})
    assert _problem(cleared) == (409, "plans_need_default", {})


THIRD_EMAIL = "third@example.test"


def _assign(installation: Installation, plan: str | None, *users: UserId, **body: Any) -> Any:
    response = installation.client.post(
        "/api/v1/plan-assignments",
        json={"plans": {user.value: plan for user in users}, **body},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_an_administrator_gives_a_plan_to_many_people_after_a_dry_run(
    installation: Installation,
) -> None:
    """The member has 2 rules that count and 2 calendar accounts, where Free allows 1 of each.
    A third person has nothing, and no Plan limits the administrator."""
    client, database = installation.client, installation.database
    member, admin = installation.member, installation.admin
    third = limited_user(database, UserId("user-3"), email=THIRD_EMAIL)
    _member_rules(installation)
    installation.define(FREE_BODY, FAMILY_BODY)
    installation.turn_on("family")
    people = (member, third, admin)

    planned = _assign(installation, "free", *people, dry_run=True)
    before = installation.overview_plan(member)
    given = _assign(installation, "free", *people)
    after = installation.overview_plan(member)
    over_free = client.get("/api/v1/users", params={"over": "true"}).json()
    returned = _assign(installation, None, member)

    family = {"key": "family", "name": "Family", "on_default": True}
    free = {"key": "free", "name": "Free", "on_default": False}
    member_over = [
        {"limit": "rules", "in_use": 2, "allowed": 1},
        {"limit": "connected_accounts", "in_use": 2, "allowed": 1},
    ]
    moves = [
        {"user_id": member.value, "email": MEMBER_EMAIL, "had": family, "has": free},
        {"user_id": third.value, "email": THIRD_EMAIL, "had": family, "has": free},
        {"user_id": admin.value, "email": ADMIN_EMAIL, "had": family, "has": free},
    ]
    overs = [member_over, [], []]
    assert planned == {
        "dry_run": True,
        "people": [{**move, "over": over} for move, over in zip(moves, overs, strict=True)],
    }
    # The dry run gave nothing.
    assert (before["has"], before["assigned_by"]) == (family, None)
    assert given == {**planned, "dry_run": False}
    assert (after["has"], after["over"], after["assigned_by"]) == (free, member_over, ADMIN_EMAIL)
    assert after["use"] == _use(FREE_BODY, rules=2, accounts=2)
    assert [row["id"] for row in over_free["users"]] == [member.value]
    assert returned["people"] == [
        {
            "user_id": member.value,
            "email": MEMBER_EMAIL,
            "had": free,
            "has": family,
            "over": [],
        }
    ]


def test_giving_people_the_default_plan_means_following_it(installation: Installation) -> None:
    """As null does, after a dry run that says so, so they move with the default."""
    member = installation.member
    installation.define(FREE_BODY, FAMILY_BODY)
    installation.turn_on("family")
    _assign(installation, "free", member)

    planned = _assign(installation, "family", member, dry_run=True)
    given = _assign(installation, "family", member)
    followers = installation.client.get("/api/v1/plans").json()["followers"]

    move = {
        "user_id": member.value,
        "email": MEMBER_EMAIL,
        "had": {"key": "free", "name": "Free", "on_default": False},
        "has": {"key": "family", "name": "Family", "on_default": True},
        "over": [],
    }
    assert planned == {"dry_run": True, "people": [move]}
    assert given == {"dry_run": False, "people": [move]}
    assert followers == 2


def test_an_undo_to_several_plans_one_of_them_removed_meanwhile_restores_nobody(
    installation: Installation,
) -> None:
    """The member had Family of their own and a third person followed Free, the default; both
    were given Starter. Undo gives each back their own Plan in one request, so once another
    administrator removes Family, it is refused and the third person stays on Starter too."""
    client, member = installation.client, installation.member
    third = limited_user(installation.database, UserId("user-3"), email=THIRD_EMAIL)
    installation.define(FREE_BODY, FAMILY_BODY, {**FREE_BODY, "key": "starter", "name": "Starter"})
    installation.turn_on("free")
    _assign(installation, "family", member)
    _assign(installation, "starter", member, third)
    # The third person, whose Plan is still there, comes first, so a split write would move them.
    undo = {third.value: None, member.value: "family"}

    planned = client.post("/api/v1/plan-assignments", json={"plans": undo, "dry_run": True})
    removed = client.delete("/api/v1/plans/family")
    refused = client.post("/api/v1/plan-assignments", json={"plans": undo})

    assert planned.status_code == 200, planned.text
    assert [(move["had"]["key"], move["has"]) for move in planned.json()["people"]] == [
        ("starter", {"key": "free", "name": "Free", "on_default": True}),
        ("starter", {"key": "family", "name": "Family", "on_default": False}),
    ]
    assert removed.status_code == 204
    assert _problem(refused) == (404, "plan_not_found", {})
    starter = {"key": "starter", "name": "Starter", "on_default": False}
    assert [installation.overview_plan(user)["has"] for user in (member, third)] == [starter] * 2


def test_a_plan_given_to_nobody_too_many_or_someone_unknown_is_refused_with_its_reason(
    installation: Installation,
) -> None:
    client, member = installation.client, installation.member.value
    installation.define(FREE_BODY)
    installation.turn_on("free")

    def assigning(*people: str, plan: str = "free", **body: Any) -> Any:
        return client.post(
            "/api/v1/plan-assignments", json={"plans": dict.fromkeys(people, plan), **body}
        )

    answers = {
        "nobody": assigning(),
        "too_many": assigning(*(f"user-{number}" for number in range(101))),
        "unknown": assigning(member, "nobody"),
        "malformed": assigning(member, " ", dry_run=True),
        "unknown_plan": assigning(member, plan="gold"),
        "malformed_plan": assigning(member, plan="Not a key", dry_run=True),
        "no_plans": client.post("/api/v1/plan-assignments", json={"dry_run": True}),
    }
    seen = installation.overview_plan(installation.member)

    assert {name: _problem(response) for name, response in answers.items()} == {
        "nobody": (422, "invalid_assignment", {"reason": "no_people"}),
        "too_many": (422, "invalid_assignment", {"reason": "too_many", "limit": 100, "count": 100}),
        "unknown": (422, "invalid_assignment", {"reason": "unknown_people"}),
        "malformed": (422, "invalid_assignment", {"reason": "unknown_people"}),
        "unknown_plan": (404, "plan_not_found", {}),
        "malformed_plan": (404, "plan_not_found", {}),
        "no_plans": (422, "invalid_request", {"field": "plans", "reason": "missing"}),
    }
    assert (seen["assigned"], seen["assigned_by"]) == (None, None)


def test_with_no_default_a_person_without_a_plan_of_their_own_has_none_to_count(
    installation: Installation,
) -> None:
    member = installation.member
    installation.define(FREE_BODY)

    planned = _assign(installation, None, member, dry_run=True)
    seen = installation.overview_plan(member)

    assert planned["people"] == [
        {"user_id": member.value, "email": MEMBER_EMAIL, "had": None, "has": None, "over": []}
    ]
    assert (seen["has"], seen["use"], seen["assigned_by"]) == (None, None, None)


def test_people_over_a_limit_of_the_plan_they_have_are_listed_whether_or_not_plans_are_on(
    installation: Installation,
) -> None:
    client, database = installation.client, installation.database
    _member_rules(installation)
    limited_user(database, UserId("user-3"), email=THIRD_EMAIL)
    installation.define(FREE_BODY, FAMILY_BODY)
    client.put("/api/v1/plan-settings", json={"enabled": False, "default_plan": "free"})

    def over(**query: str) -> tuple[list[str], int]:
        page = client.get("/api/v1/users", params={"over": "true", **query}).json()
        return [row["id"] for row in page["users"]], page["total"]

    member = installation.member.value
    while_off = over()
    installation.turn_on("free")
    while_on = over()
    on_family = over(plan="family")
    everyone = client.get("/api/v1/users", params={"over": "false"}).json()["total"]

    assert while_off == ([member], 1)
    assert while_on == ([member], 1)
    assert on_family == ([], 0)
    assert everyone == 3


def test_a_member_is_refused_every_plans_administrator_route_and_reads_their_own_plan(
    installation: Installation,
) -> None:
    client = installation.client
    installation.define(FREE_BODY)
    before = client.get("/api/v1/plans").json()
    installation.as_member()
    refused = [
        client.get("/api/v1/plans"),
        client.post("/api/v1/plans", json=FAMILY_BODY),
        client.put("/api/v1/plans/free", json=CHANGE_FREE),
        client.delete("/api/v1/plans/free"),
        client.put("/api/v1/plan-settings", json={"enabled": True, "default_plan": "free"}),
        client.post(
            "/api/v1/plan-assignments",
            json={"plans": {installation.member.value: "free"}, "dry_run": True},
        ),
    ]
    own = client.get("/api/v1/account/plan")
    installation.as_admin()
    after = client.get("/api/v1/plans").json()

    assert {(response.status_code, response.json()["code"]) for response in refused} == {
        (403, "administrator_required")
    }
    assert own.status_code == 200
    assert after == before


def test_your_plan_while_plans_are_off_for_an_administrator_and_for_a_limited_member(
    installation: Installation,
) -> None:
    client = installation.client
    _member_rules(installation)
    installation.as_member()
    while_off = client.get("/api/v1/account/plan").json()
    installation.as_admin()
    installation.define(FREE_BODY)
    installation.turn_on("free")
    administering = client.get("/api/v1/account/plan").json()
    installation.as_member()
    limited = client.get("/api/v1/account/plan").json()

    assert while_off == {
        "basis": "plans_off",
        **UNLIMITED,
        "rules_counted": 2,
        "connected_accounts": 2,
        "integration_tokens": 0,
    }
    assert administering == {
        "basis": "administrator",
        **UNLIMITED,
        "rules_counted": 0,
        "connected_accounts": 0,
        "integration_tokens": 0,
    }
    assert limited == {
        "basis": "plan",
        "plan": {"key": "free", "name": "Free", "on_default": True},
        "limits": FREE_BODY["limits"],
        "rules_counted": 2,
        "connected_accounts": 2,
        "integration_tokens": 0,
        "instant": False,
        "poll_every_minutes": 5,
        "may_connect_account": False,
        "may_issue_token": False,
        "over_rule_limit": True,
    }


def test_a_lower_default_refuses_new_starts_and_stops_nothing(installation: Installation) -> None:
    client = installation.client
    _member_rules(installation)
    installation.define(FREE_BODY)
    installation.turn_on("free")
    installation.as_member()
    refused = client.post("/api/v1/rules/rule-3/enable")
    rules = client.get("/api/v1/rules").json()

    assert _problem(refused) == (
        409,
        "plan_limit_reached",
        {"reason": "rules", "limit": 1, "count": 1},
    )
    assert [(each["id"], each["state"]) for each in rules] == [
        ("rule-1", "enabled"),
        ("rule-2", "enabled"),
        ("rule-3", "dry_run_validated"),
    ]


def test_the_rules_api_says_which_previewed_rule_keeps_a_replaced_rules_place(
    installation: Installation,
) -> None:
    """So the Rules list and the rule page can tell, as Start does, which previewed rule starts
    at the limit."""
    _member_rules(installation)
    replacement = replace(
        rule(state=SyncRuleState.PREVIEWED),
        id=SyncRuleId("rule-4"),
        source=endpoint("personal-account", "third-calendar"),
        keeps_place=True,
    )
    with sqlite_units(installation.database, user=installation.member)() as uow:
        uow.rules.add(replacement)
        uow.commit()
    installation.as_member()
    client = installation.client
    rules = client.get("/api/v1/rules").json()
    details = [client.get(f"/api/v1/rules/{each}").json() for each in ("rule-3", "rule-4")]

    assert [(each["id"], each["keeps_place"]) for each in rules] == [
        ("rule-1", False),
        ("rule-2", False),
        ("rule-3", False),
        ("rule-4", True),
    ]
    assert [(each["id"], each["keeps_place"]) for each in details] == [
        ("rule-3", False),
        ("rule-4", True),
    ]
