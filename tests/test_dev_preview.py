import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from calendar_sync.application.errors import ProviderFailure
from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import build_adapters
from calendar_sync.interfaces.api.app import create_app
from scripts.dev_preview import (
    PREVIEW_PASSWORD,
    NotAPreviewDatabase,
    build_preview_container,
    reset_preview_database,
)
from tests.helpers import rule

REPOSITORY = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 28, 18, 0, tzinfo=UTC)


def test_preview_refuses_a_database_it_did_not_create(tmp_path: Path) -> None:
    real = tmp_path / "calendar-sync.db"
    adapters = build_adapters(Settings(real))
    with adapters.unit_of_work() as uow:
        uow.rules.add(rule())
        uow.commit()

    with pytest.raises(NotAPreviewDatabase):
        build_preview_container(real, NOW)

    with adapters.unit_of_work() as uow:
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

    assert container.scheduler is None
    assert container.execute_sync_rule is None
    assert container.inspect_activity_event.provider is not None
    with pytest.raises(ProviderFailure):
        cast(Any, container.inspect_activity_event.provider).create_projection()
    with TestClient(create_app(container)) as client:
        assert (
            client.post("/api/v1/session", json={"password": PREVIEW_PASSWORD}).status_code == 200
        )
        entries = client.get("/api/v1/audit-entries", params={"category": "changed"}).json()
    events = {(item["source_event_id"], item["reason"]): item["event"] for item in entries}
    assert events["flight", "source_changed"]["renamed_from"] == "Flight"
    assert events["flight", "destination_drift_repaired"]["renamed_from"] is None
    assert events["dinner", "source_cancelled"]["title"] == "Dinner at Marta's"
    with closing(sqlite3.connect(database)) as connection:
        rules = connection.execute("SELECT COUNT(*) FROM sync_rules").fetchone()[0]
    assert rules == 2


def test_preview_is_not_shipped_in_the_package_or_image() -> None:
    dockerfile = (REPOSITORY / "Dockerfile").read_text(encoding="utf-8")
    dockerignore = (REPOSITORY / ".dockerignore").read_text(encoding="utf-8").splitlines()
    pyproject = (REPOSITORY / "pyproject.toml").read_text(encoding="utf-8")

    assert "scripts" in dockerignore
    assert "COPY scripts" not in dockerfile
    assert "COPY . " not in dockerfile
    assert 'packages = ["src/calendar_sync"]' in pyproject
