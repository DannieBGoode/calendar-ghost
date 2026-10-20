"""The manual-run limit through the Web API: Sync now, Reconcile now, and Preview share twelve runs
an hour for a User a Plan limits, and the thirteenth says when to try again (ADR 0038)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import Adapters, build_adapters, compose
from calendar_sync.domain.access import UserId
from calendar_sync.infrastructure.security import CredentialCipher
from calendar_sync.interfaces.api.app import create_app
from calendar_sync.interfaces.api.dependencies import SESSION_COOKIE
from tests.plans import plans_on
from tests.users import administrator, limited_user, session_for

RUNS = ("sync", "reconcile", "preview")


def _installation(database: Path, *, plans: bool = True) -> tuple[Settings, Adapters]:
    """An installation whose rules can run, with its administrator; with `plans`, Plans are on
    and the Default Plan limits everyone else."""
    database.parent.mkdir(exist_ok=True)
    settings = Settings(database, master_key=CredentialCipher.generate_key())
    adapters = build_adapters(settings)
    administrator(adapters)
    if plans:
        plans_on(adapters.plan_catalog)
    return settings, adapters


def _client(settings: Settings, adapters: Adapters, user: UserId) -> TestClient:
    client = TestClient(create_app(replace(compose(settings, adapters), scheduler=None)))
    client.cookies.set(SESSION_COOKIE, session_for(settings.database_path, user))
    return client


def _route(number: int) -> str:
    """The route of the `number`th manual run, taking turns among the three. The rule does not
    exist, so once admitted the run answers 404 and calls no provider."""
    return f"/api/v1/rules/missing/{RUNS[number % len(RUNS)]}"


def test_twelve_manual_runs_are_shared_by_sync_reconcile_and_preview_and_the_thirteenth_waits(
    tmp_path: Path,
) -> None:
    settings, adapters = _installation(tmp_path / "test.db")
    member = limited_user(settings.database_path)

    with _client(settings, adapters, member) as client:
        admitted = [client.post(_route(number)).status_code for number in range(12)]
        # A refused run is not recorded, so each of the three is refused in turn.
        refused = {_route(number): client.post(_route(number)) for number in range(12, 15)}

    assert admitted == [404] * 12
    for route, answer in refused.items():
        retry_after = int(answer.headers["Retry-After"])
        assert (answer.status_code, answer.json()["code"]) == (429, "manual_runs_throttled"), route
        # The first run leaves the hour first, and the runs took seconds: one hour, in minutes.
        assert answer.json()["params"] == {"retry_after": retry_after, "count": 60}
        assert 3540 < retry_after <= 3600


def test_an_administrator_and_plans_off_are_never_limited(tmp_path: Path) -> None:
    settings, adapters = _installation(tmp_path / "plans-on" / "test.db")
    off_settings, off_adapters = _installation(tmp_path / "plans-off" / "test.db", plans=False)
    member = limited_user(off_settings.database_path)

    with _client(settings, adapters, administrator(adapters)) as client:
        as_administrator = {client.post(_route(number)).status_code for number in range(20)}
    with _client(off_settings, off_adapters, member) as client:
        with_plans_off = {client.post(_route(number)).status_code for number in range(20)}

    assert as_administrator == with_plans_off == {404}


def test_turning_plans_on_with_no_default_limits_no_manual_run(tmp_path: Path) -> None:
    """The No limits Plan it makes the default limits nothing, so turning Plans on changes
    nothing."""
    settings, adapters = _installation(tmp_path / "test.db", plans=False)
    admin, member = administrator(adapters), limited_user(settings.database_path)

    with _client(settings, adapters, admin) as client:
        client.put(
            "/api/v1/plan-settings", json={"enabled": True, "default_plan": None}
        ).raise_for_status()
    with _client(settings, adapters, member) as client:
        basis = client.get("/api/v1/account/plan").json()["basis"]
        runs = {client.post(_route(number)).status_code for number in range(20)}

    assert (basis, runs) == ("plan", {404})


def test_an_unavailable_run_uses_no_budget(tmp_path: Path) -> None:
    """A 503 is answered before the run is admitted, so it counts against nothing."""
    settings, adapters = _installation(tmp_path / "test.db")
    member = limited_user(settings.database_path)
    # No calendar provider, and the same throttle.
    unavailable = replace(adapters, calendar_provider=None)

    with _client(settings, unavailable, member) as client:
        unanswered = {client.post(_route(number)).status_code for number in range(20)}
    with _client(settings, adapters, member) as client:
        runs = [client.post(_route(number)).status_code for number in range(13)]

    assert unanswered == {503}
    assert runs == [404] * 12 + [429]
