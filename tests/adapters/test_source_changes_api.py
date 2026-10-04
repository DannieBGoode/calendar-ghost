"""Activity lists which fields a source change touched and shows their values on request."""

from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from calendar_sync.application.ports import AuditAction, AuditEntry, AuditOutcome, RecordedEvent
from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import build_container
from calendar_sync.domain.changes import SourceChange, SourceObservation
from calendar_sync.domain.model import TimedInterval
from calendar_sync.infrastructure.persistence.sqlite import (
    SqliteUnitOfWorkFactory,
    initialize_database,
)
from calendar_sync.infrastructure.security import CredentialCipher, HistoryCipher
from calendar_sync.interfaces.api.app import create_app
from tests.helpers import NOW, event, rule

PASSWORD = "correct horse battery staple"
KEY = CredentialCipher.generate_key()


def _change() -> SourceChange:
    before = SourceObservation.of(
        replace(
            event(),
            guests=("ana@example.com", "ben@example.com"),
            conferencing=("https://meet.example.com/old",),
        )
    )
    assert before is not None
    after = replace(
        before,
        revision="revision-2",
        title="Renamed",
        time=TimedInterval(NOW + timedelta(hours=1), NOW + timedelta(hours=2)),
        description="Dial in: 1234#",
        guests=("ana@example.com", "cleo@example.com"),
        conferencing=("https://meet.example.com/new",),
    )
    change = SourceChange.between(before, after)
    assert change is not None
    return change


def _record(database: Path, key: str, change: SourceChange | None) -> None:
    initialize_database(database)
    factory = SqliteUnitOfWorkFactory(database, history=HistoryCipher(key))
    with factory() as uow:
        if uow.rules.get(rule().id) is None:
            uow.rules.add(rule())
        uow.audit.append(
            AuditEntry(
                occurred_at=NOW,
                rule_id=rule().id,
                action=AuditAction.UPDATE,
                outcome=AuditOutcome.COMPLETED,
                source_event_id=event().reference.event_id.value,
                reason=None,
                run_id="run-1",
                event=RecordedEvent(title="Renamed"),
                change=change,
            )
        )
        uow.commit()


def _client(database: Path, key: str = KEY) -> TestClient:
    return TestClient(create_app(build_container(Settings(database, master_key=key))))


def test_entries_list_the_fields_their_source_change_touched(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    _record(database, KEY, _change())
    _record(database, KEY, None)

    with _client(database) as client:
        client.post("/api/v1/setup/admin", json={"password": PASSWORD})
        listed = client.get("/api/v1/audit-entries").json()

    assert [entry["changed_fields"] for entry in listed] == [
        None,
        ["title", "time", "description", "guests", "conferencing"],
    ]


def test_an_entry_shows_its_values_before_and_after(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    _record(database, KEY, _change())

    with _client(database) as client:
        client.post("/api/v1/setup/admin", json={"password": PASSWORD})
        entry_id = client.get("/api/v1/audit-entries").json()[0]["id"]
        response = client.get(f"/api/v1/audit-entries/{entry_id}/changes")

    assert response.status_code == 200
    body = response.json()
    changes = {change["field"]: change for change in body["changes"]}
    assert body["values_available"] is True
    assert changes["title"]["before"] == "Private appointment"
    assert changes["title"]["after"] == "Renamed"
    assert changes["description"]["before"] == "Sensitive description"
    assert changes["description"]["after"] == "Dial in: 1234#"
    assert changes["time"]["after_time"]["starts"] == (NOW + timedelta(hours=1)).isoformat()
    assert changes["guests"]["added"] == ["cleo@example.com"]
    assert changes["guests"]["removed"] == ["ben@example.com"]
    assert changes["conferencing"]["added"] == ["https://meet.example.com/new"]
    assert changes["conferencing"]["removed"] == ["https://meet.example.com/old"]


def test_values_sealed_under_another_master_key_are_unavailable(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    _record(database, CredentialCipher.generate_key(), _change())

    with _client(database) as client:
        client.post("/api/v1/setup/admin", json={"password": PASSWORD})
        entry_id = client.get("/api/v1/audit-entries").json()[0]["id"]
        body = client.get(f"/api/v1/audit-entries/{entry_id}/changes").json()

    assert body["values_available"] is False
    assert [change["field"] for change in body["changes"]] == ["title"]
    assert body["fields"] == ["title", "time", "description", "guests", "conferencing"]


def test_an_entry_without_a_source_change_has_none(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    _record(database, KEY, None)

    with _client(database) as client:
        client.post("/api/v1/setup/admin", json={"password": PASSWORD})
        entry_id = client.get("/api/v1/audit-entries").json()[0]["id"]
        response = client.get(f"/api/v1/audit-entries/{entry_id}/changes")

    assert response.status_code == 404
    assert response.json()["code"] == "source_change_not_found"


def test_source_change_values_require_an_administrator(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    _record(database, KEY, _change())

    with _client(database) as client:
        response = client.get("/api/v1/audit-entries/1/changes")

    assert response.status_code == 401
