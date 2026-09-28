import sqlite3
from importlib.resources import files
from pathlib import Path

import pytest

from calendar_sync.application.errors import DuplicateDirectionalRelationship
from calendar_sync.application.ports import AuditEntry
from calendar_sync.domain.model import (
    EventId,
    EventMapping,
    EventMappingId,
    EventRef,
    ProjectionFingerprint,
    SyncRuleId,
)
from calendar_sync.infrastructure.persistence.sqlite import (
    SqliteUnitOfWorkFactory,
    initialize_database,
)
from tests.helpers import NOW, endpoint, event, rule


def test_sqlite_rule_repository_round_trip(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    factory = SqliteUnitOfWorkFactory(database)

    with factory() as uow:
        uow.rules.add(rule())
        uow.commit()

    with factory() as uow:
        restored = uow.rules.get(rule().id)

    assert restored == rule()


def test_database_migration_is_idempotent(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"

    initialize_database(database)
    initialize_database(database)

    with SqliteUnitOfWorkFactory(database)() as uow:
        assert uow.rules.list() == ()


def test_recreated_projection_updates_existing_mapping_and_destination_cursor(
    tmp_path: Path,
) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    factory = SqliteUnitOfWorkFactory(database)
    source = event().reference
    first_destination = EventRef(endpoint("work-account", "work-calendar"), EventId("first"))
    restored_destination = EventRef(endpoint("work-account", "work-calendar"), EventId("restored"))
    original = EventMapping(
        EventMappingId("stable-mapping"),
        rule().id,
        source,
        first_destination,
        "revision-1",
        ProjectionFingerprint("fingerprint-1"),
    )
    restored = EventMapping(
        original.id,
        original.rule_id,
        original.source,
        restored_destination,
        "revision-2",
        ProjectionFingerprint("fingerprint-2"),
    )

    with factory() as uow:
        uow.rules.add(rule())
        uow.mappings.save(original)
        uow.destination_cursors.save(rule().id, "destination-cursor")
        uow.commit()
    with factory() as uow:
        uow.mappings.save(restored)
        uow.commit()
    with factory() as uow:
        assert uow.mappings.for_source(rule().id, source) == restored
        assert uow.mappings.for_destination(rule().id, restored_destination) == restored
        assert uow.destination_cursors.get(rule().id) == "destination-cursor"


def test_sqlite_unique_relationship_is_translated_to_application_error(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    factory = SqliteUnitOfWorkFactory(database)
    duplicate = rule()
    second_id = type(duplicate)(
        id=SyncRuleId("rule-2"),
        source=duplicate.source,
        destination=duplicate.destination,
        transformation=duplicate.transformation,
        initial_lookback_days=duplicate.initial_lookback_days,
        state=duplicate.state,
    )

    with factory() as uow:
        uow.rules.add(duplicate)
        uow.commit()
    with pytest.raises(DuplicateDirectionalRelationship), factory() as uow:
        uow.rules.add(second_id)


def test_version_one_database_upgrades_audit_entries_with_reason_codes(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    initial = (
        files("calendar_sync.infrastructure.persistence").joinpath("0001_initial.sql").read_text()
    )
    with sqlite3.connect(database) as connection:
        connection.executescript(initial)
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (1, '2026-09-01')"
        )
        connection.executemany(
            """
            INSERT INTO audit_entries (occurred_at, rule_id, action, outcome, detail)
            VALUES ('2026-09-01T10:00:00+00:00', 'rule-1', ?, ?, ?)
            """,
            [
                (
                    "conflict",
                    "blocked",
                    "recurring series and occurrence exceptions are not supported yet",
                ),
                ("create", "completed", "source has no managed projection"),
                ("ignore", "completed", "excluded event has no managed projection"),
            ],
        )

    initialize_database(database)
    initialize_database(database)

    with sqlite3.connect(database) as connection:
        versions = [row[0] for row in connection.execute("SELECT version FROM schema_migrations")]
        rows = connection.execute(
            "SELECT action, outcome, reason, run_id FROM audit_entries ORDER BY id"
        ).fetchall()
    assert versions == [1, 2, 3]
    assert rows == [
        ("conflict", "blocked", "recurring_unsupported", None),
        ("create", "completed", "source_created", None),
        ("ignore", "completed", None, None),
    ]


def test_audit_entries_persist_reason_and_run(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)

    with SqliteUnitOfWorkFactory(database)() as uow:
        uow.audit.append(
            AuditEntry(
                occurred_at=NOW,
                rule_id=rule().id,
                action="ignore",
                outcome="skipped",
                source_event_id="weekly",
                reason="recurring_unsupported",
                run_id="run-1",
            )
        )
        uow.commit()

    with sqlite3.connect(database) as connection:
        stored = connection.execute(
            "SELECT reason, run_id, source_event_id, detail FROM audit_entries"
        ).fetchone()
    assert stored == ("recurring_unsupported", "run-1", "weekly", "")
