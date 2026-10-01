from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import build_adapters, compose
from calendar_sync.infrastructure.log_files import RotatingLogFiles
from calendar_sync.interfaces.api.app import create_app

PASSWORD = "correct horse battery staple"


def _client(tmp_path: Path, *, file_logging: bool = True) -> TestClient:
    settings = Settings(tmp_path / "test.db")
    logs = tmp_path / "logs"
    if file_logging:
        logs.mkdir()
        (logs / "calendar-sync.log").write_text("2026-10-01T18:04:12Z INFO calendar_sync.x ok\n")
    adapters = replace(
        build_adapters(settings), log_files=RotatingLogFiles(logs) if file_logging else None
    )
    container = replace(compose(settings, adapters), scheduler=None)
    client = TestClient(create_app(container))
    assert client.post("/api/v1/setup/admin", json={"password": PASSWORD}).status_code == 200
    return client


def test_storage_reports_database_and_logs(tmp_path: Path) -> None:
    body = _client(tmp_path).get("/api/v1/storage").json()

    assert body["database"]["bytes"] > 0
    assert body["database"]["activity_entries"] == 0
    assert body["database"]["oldest_activity_at"] is None
    assert body["logs"]["files"] == 1
    assert body["logs"]["newest_at"] == "2026-10-01T18:04:12+00:00"
    assert body["activity_ages"] == [30, 90, 180, 365]


def test_storage_without_file_logging_reports_no_logs(tmp_path: Path) -> None:
    client = _client(tmp_path, file_logging=False)

    assert client.get("/api/v1/storage").json()["logs"] is None
    assert client.get("/api/v1/storage/logs").status_code == 404
    assert client.delete("/api/v1/storage/logs").status_code == 404


def test_clearable_activity_is_counted_for_an_offered_age_only(tmp_path: Path) -> None:
    client = _client(tmp_path)

    assert client.get("/api/v1/storage/activity", params={"older_than_days": 90}).json() == {
        "older_than_days": 90,
        "entries": 0,
    }
    assert client.get("/api/v1/storage/activity", params={"older_than_days": 7}).status_code == 422


def test_clearing_activity_answers_what_was_removed(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post("/api/v1/storage/activity/clear", json={"older_than_days": 30})

    assert response.status_code == 200
    assert response.json()["removed"] == 0
    assert (
        client.post("/api/v1/storage/activity/clear", json={"older_than_days": 1}).status_code
        == 422
    )


def test_clearing_while_a_rule_runs_is_a_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from calendar_sync.application.errors import StorageBusy
    from calendar_sync.application.storage import StorageAdministration

    def busy(self: StorageAdministration, older_than_days: int) -> object:
        raise StorageBusy("Old Activity was cleared, but its space could not be reclaimed")

    monkeypatch.setattr(StorageAdministration, "clear_activity", busy)

    response = _client(tmp_path).post(
        "/api/v1/storage/activity/clear", json={"older_than_days": 30}
    )

    assert response.status_code == 409
    assert response.json()["detail"].startswith("Old Activity was cleared")


def test_logs_download_as_one_dated_text_file(tmp_path: Path) -> None:
    response = _client(tmp_path).get("/api/v1/storage/logs")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.headers["content-disposition"].startswith(
        'attachment; filename="calendar-sync-logs-'
    )
    assert response.text.endswith("INFO calendar_sync.x ok\n")


def test_purging_logs_empties_them(tmp_path: Path) -> None:
    client = _client(tmp_path)

    assert client.delete("/api/v1/storage/logs").status_code == 204
    assert "calendar_sync.x ok" not in client.get("/api/v1/storage/logs").text
