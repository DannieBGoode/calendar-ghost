import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import calendar_sync.interfaces.api.app as api_module
from calendar_sync.application.ports import AuditEntry
from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import build_container
from calendar_sync.domain.model import SyncRuleId
from calendar_sync.interfaces.api.app import create_app

PASSWORD = "correct horse battery staple"


def test_audit_entries_return_empty_list_before_any_synchronization(tmp_path: Path) -> None:
    app = create_app(build_container(Settings(tmp_path / "test.db")))

    with TestClient(app) as client:
        client.post("/api/v1/setup/admin", json={"password": PASSWORD})
        response = client.get("/api/v1/audit-entries")

    assert response.status_code == 200
    assert response.json() == []


def test_legacy_activity_route_returns_not_found_instead_of_the_web_page(tmp_path: Path) -> None:
    container = build_container(Settings(tmp_path / "test.db"))
    with container.unit_of_work() as uow:
        uow.audit.append(
            AuditEntry(
                occurred_at=datetime(2026, 9, 28, tzinfo=UTC),
                rule_id=SyncRuleId("rule-1"),
                action="create",
                outcome="completed",
                detail="legacy route probe",
            )
        )
        uow.commit()
    app = create_app(container)

    with TestClient(app) as client:
        anonymous = client.get("/api/v1/activity")
        client.post("/api/v1/setup/admin", json={"password": PASSWORD})
        authenticated = client.get("/api/v1/activity")
        current = client.get("/api/v1/audit-entries")

    for response in (anonymous, authenticated):
        assert response.status_code == 404
        assert response.json() == {"detail": "Not Found"}
    assert current.json()[0]["detail"] == "legacy route probe"


@pytest.mark.parametrize("path", ["/api", "/api/", "/api/v1/unknown", "/api/v2/audit-entries"])
def test_unknown_api_paths_return_not_found_instead_of_the_web_page(
    tmp_path: Path, path: str
) -> None:
    app = create_app(build_container(Settings(tmp_path / "test.db")))

    with TestClient(app) as client:
        response = client.get(path)

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


def test_shipped_frontend_bundle_requests_audit_entries_path() -> None:
    assets = Path(api_module.__file__).with_name("static") / "assets"
    bundles = [path.read_text(encoding="utf-8") for path in assets.glob("*.js")]

    assert bundles, "the committed frontend build is missing"
    combined = "\n".join(bundles)
    assert "/api/v1/audit-entries" in combined
    assert re.search(r"/api/v1/activity\b", combined) is None
