import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from calendar_sync.application.errors import ProviderFailure
from calendar_sync.infrastructure.persistence.sqlite import initialize_database
from calendar_sync.interfaces.api.app import create_app
from scripts.dev_preview import (
    PREVIEW_EMAIL,
    PREVIEW_PASSWORD,
    ROBIN_EMAIL,
    NotAPreviewDatabase,
    Scenario,
    build_preview_container,
    preview_user,
    reset_preview_database,
)
from tests.helpers import rule
from tests.users import sqlite_units

REPOSITORY = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 28, 18, 0, tzinfo=UTC)


def test_preview_refuses_a_database_it_did_not_create(tmp_path: Path) -> None:
    real = tmp_path / "calendar-sync.db"
    initialize_database(real)
    units = sqlite_units(real)
    with units() as uow:
        uow.rules.add(rule())
        uow.commit()

    with pytest.raises(NotAPreviewDatabase):
        build_preview_container(real, NOW)

    with units() as uow:
        assert [item.id.value for item in uow.rules.list()] == ["rule-1"]


def test_preview_refuses_the_configured_installation_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured = tmp_path / "installation.db"
    monkeypatch.setenv("CALENDAR_SYNC_DATABASE_PATH", str(configured))

    with pytest.raises(NotAPreviewDatabase):
        reset_preview_database(configured)


def test_preview_seeds_only_its_own_database_with_a_read_only_calendar(tmp_path: Path) -> None:
    database = tmp_path / "dev-preview.db"
    build_preview_container(database, NOW)
    # Running again replaces the preview it created.
    container = build_preview_container(database, NOW)

    services = container.for_user(preview_user(database))
    assert container.scheduler is None
    assert services.execute_sync_rule is None
    assert services.inspect_activity_event.provider is not None
    with pytest.raises(ProviderFailure):
        cast(Any, services.inspect_activity_event.provider).create_projection()
    with TestClient(create_app(container)) as client:
        assert (
            client.post(
                "/api/v1/session", json={"email": PREVIEW_EMAIL, "password": PREVIEW_PASSWORD}
            ).status_code
            == 200
        )
        entries = client.get("/api/v1/audit-entries", params={"category": "changed"}).json()
    events = {(item["source_event_id"], item["reason"]): item["event"] for item in entries}
    assert events["flight", "source_changed"]["renamed_from"] == "Flight"
    assert events["flight", "destination_drift_repaired"]["renamed_from"] is None
    assert events["dinner", "source_cancelled"]["title"] == "Dinner at Marta's"
    with closing(sqlite3.connect(database)) as connection:
        rules = connection.execute(
            "SELECT COUNT(*) FROM sync_rules WHERE user_id = ?", (preview_user(database).value,)
        ).fetchone()[0]
        # Sam's three rules; Robin keeps his own.
        assert rules == 3


def test_preview_is_not_shipped_in_the_package_or_image() -> None:
    dockerfile = (REPOSITORY / "Dockerfile").read_text(encoding="utf-8")
    dockerignore = (REPOSITORY / ".dockerignore").read_text(encoding="utf-8").splitlines()
    pyproject = (REPOSITORY / "pyproject.toml").read_text(encoding="utf-8")

    assert "scripts" in dockerignore
    assert "COPY scripts" not in dockerfile
    assert "COPY . " not in dockerfile
    assert 'packages = ["src/calendar_sync"]' in pyproject


def test_preview_shows_source_changes_with_their_values(tmp_path: Path) -> None:
    container = build_preview_container(tmp_path / "dev-preview.db", NOW)

    with TestClient(create_app(container)) as client:
        client.post("/api/v1/session", json={"email": PREVIEW_EMAIL, "password": PREVIEW_PASSWORD})
        changed = [
            entry
            for entry in client.get("/api/v1/audit-entries", params={"limit": 200}).json()
            if entry["changed_fields"]
        ]
        change = client.get(f"/api/v1/audit-entries/{changed[0]['id']}/changes").json()

    assert {entry["reason"] for entry in changed} == {"source_changed", "projection_current"}
    assert change["values_available"] is True


@pytest.mark.parametrize(
    ("scenario", "expected"),
    [
        (
            Scenario.REVIEW,
            {
                "status": "review",
                "needs_attention": True,
                "open_incidents": 1,
                "blocked_events": 2,
            },
        ),
        (
            Scenario.HEALTHY,
            {
                "status": "healthy",
                "needs_attention": False,
                "open_incidents": 0,
                "blocked_events": 0,
            },
        ),
        (
            Scenario.STOPPED,
            {"open_incidents": 1, "stopped_rules": 2, "blocked_events": 0, "lapsed_accounts": 1},
        ),
        (Scenario.WAITING, {"open_incidents": 1, "stopped_rules": 0, "enabled_rules": 3}),
        (Scenario.SEVERAL, {"open_incidents": 2, "stopped_rules": 2, "blocked_events": 2}),
        (
            Scenario.PAUSED,
            {"status": "paused", "needs_attention": False, "enabled_rules": 0, "sync_rules": 3},
        ),
        (Scenario.SETUP, {"connected_accounts": 0, "sync_rules": 0}),
    ],
)
def test_preview_scenarios_seed_each_overview_state(
    tmp_path: Path, scenario: Scenario, expected: dict[str, object]
) -> None:
    container = build_preview_container(tmp_path / "dev-preview.db", NOW, scenario=scenario)

    with TestClient(create_app(container)) as client:
        client.post("/api/v1/session", json={"email": PREVIEW_EMAIL, "password": PREVIEW_PASSWORD})
        dashboard = client.get("/api/v1/dashboard").json()

    assert {key: dashboard[key] for key in expected} == expected
    if scenario is not Scenario.SETUP:
        assert dashboard["last_synced_at"] is not None


@pytest.mark.parametrize("scenario", [Scenario.HEALTHY, Scenario.STOPPED, Scenario.WAITING])
def test_preview_people_show_each_users_own_verdict(tmp_path: Path, scenario: Scenario) -> None:
    container = build_preview_container(tmp_path / "dev-preview.db", NOW, scenario=scenario)

    with TestClient(create_app(container)) as client:
        client.post("/api/v1/session", json={"email": PREVIEW_EMAIL, "password": PREVIEW_PASSWORD})
        own = client.get("/api/v1/status").json()["status"]
        overview = client.get(
            f"/api/v1/users/{preview_user(tmp_path / 'dev-preview.db').value}/overview"
        ).json()["status"]["status"]
        health = client.get("/api/v1/installation/health").json()["users"]

    assert overview == own == scenario.value
    # Robin is here too, healthy unless the scenario breaks his rule.
    expected = {scenario.value: 1, "healthy": 1}
    expected[scenario.value] = 2 if scenario is Scenario.HEALTHY else 1
    assert health == expected


def test_preview_names_calendars_of_an_account_that_lost_access(tmp_path: Path) -> None:
    container = build_preview_container(tmp_path / "dev-preview.db", NOW, scenario=Scenario.STOPPED)

    with TestClient(create_app(container)) as client:
        client.post("/api/v1/session", json={"email": PREVIEW_EMAIL, "password": PREVIEW_PASSWORD})
        rules = client.get("/api/v1/rules").json()

    personal = next(rule for rule in rules if rule["id"] == "preview-personal-work")
    assert personal["state"] == "degraded"
    assert personal["source"]["calendar_name"] == "Personal"


def _incident_messages(path: Path, scenario: Scenario) -> dict[str, object]:
    container = build_preview_container(path, NOW, scenario=scenario)
    with TestClient(create_app(container)) as client:
        client.post("/api/v1/session", json={"email": PREVIEW_EMAIL, "password": PREVIEW_PASSWORD})
        incidents = client.get("/api/v1/incidents").json()
    return {incident["id"]: incident["message"] for incident in incidents}


def test_preview_incidents_carry_messages_and_one_keeps_only_its_summary(tmp_path: Path) -> None:
    review = _incident_messages(tmp_path / "dev-preview.db", Scenario.REVIEW)
    stopped = _incident_messages(tmp_path / "dev-preview.db", Scenario.STOPPED)

    assert review["preview-incident"] == {"code": "events_still_blocked", "params": {"count": 1}}
    assert review["preview-resolved-sync_succeeded"] == {
        "code": "provider_failure",
        "params": {"kind": "temporary", "provider": "google"},
    }
    # Kept without a message so the Web UI's fallback to the stored summary stays visible.
    assert review["preview-resolved-rule_removed"] is None
    assert stopped["authorization:preview-sam-personal"] == {
        "code": "authorization_lapsed",
        "params": {"kind": "authentication", "provider": "google"},
    }


@pytest.mark.parametrize(
    ("scenario", "cause", "hint"),
    [
        (Scenario.API_DISABLED, "api_disabled", "shared_cause"),
        (Scenario.ACCESS_REVOKED, "access_revoked", "testing_mode"),
    ],
)
def test_preview_shows_a_cause_two_people_share(
    tmp_path: Path, scenario: Scenario, cause: str, hint: str
) -> None:
    container = build_preview_container(tmp_path / "dev-preview.db", NOW, scenario=scenario)

    with TestClient(create_app(container)) as client:
        client.post("/api/v1/session", json={"email": PREVIEW_EMAIL, "password": PREVIEW_PASSWORD})
        health = client.get("/api/v1/installation/health").json()
        people = client.get("/api/v1/users").json()
        client.post("/api/v1/session", json={"email": ROBIN_EMAIL, "password": PREVIEW_PASSWORD})
        robins = client.get("/api/v1/status").json()

    assert [(each["kind"], each["cause"], each["users"]) for each in health["hints"]] == [
        (hint, cause, 2)
    ]
    assert people["total"] == 2
    assert {p["cause"] for p in robins["problems"] if p["kind"] == "stopped"} == {cause}


def test_preview_signs_in_with_a_simple_local_login(tmp_path: Path) -> None:
    container = build_preview_container(tmp_path / "dev-preview.db", NOW)

    with TestClient(create_app(container)) as client:
        signed_in = client.post(
            "/api/v1/session",
            json={"email": "preview@preview.com", "password": "previewpreview"},
        )

    # Long enough for the password policy, so the preview sets up like any installation.
    assert (PREVIEW_EMAIL, PREVIEW_PASSWORD) == ("preview@preview.com", "previewpreview")
    assert signed_in.status_code == 200


@pytest.mark.parametrize("scenario", [s for s in Scenario if s is not Scenario.SETUP])
def test_robin_signs_in_to_every_scenario_but_a_new_installation(
    tmp_path: Path, scenario: Scenario
) -> None:
    container = build_preview_container(tmp_path / "dev-preview.db", NOW, scenario=scenario)

    with TestClient(create_app(container)) as client:
        signed_in = client.post(
            "/api/v1/session", json={"email": ROBIN_EMAIL, "password": PREVIEW_PASSWORD}
        )
        robins = client.get("/api/v1/status").json()["status"]

    assert signed_in.status_code == 200
    shared = scenario in {Scenario.API_DISABLED, Scenario.ACCESS_REVOKED}
    assert robins == ("stopped" if shared else "healthy")


def test_a_new_installation_has_only_its_first_user(tmp_path: Path) -> None:
    container = build_preview_container(tmp_path / "dev-preview.db", NOW, scenario=Scenario.SETUP)

    with TestClient(create_app(container)) as client:
        refused = client.post(
            "/api/v1/session", json={"email": ROBIN_EMAIL, "password": PREVIEW_PASSWORD}
        )

    assert refused.status_code == 401
