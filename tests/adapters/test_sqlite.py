import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from calendar_sync.application.errors import DuplicateDirectionalRelationship
from calendar_sync.application.ports import AuditEntry, RuleRunOutcome, RunKind
from calendar_sync.domain.model import (
    EventId,
    EventMapping,
    EventMappingId,
    EventRef,
    PrivacyPolicy,
    ProjectionFingerprint,
    SyncRuleId,
    SyncRuleState,
    TransformationPolicy,
)
from calendar_sync.infrastructure.persistence.memory import InMemoryUnitOfWorkFactory
from calendar_sync.infrastructure.persistence.sqlite import (
    SqliteUnitOfWorkFactory,
    initialize_database,
)
from tests.helpers import endpoint, event, rule


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


def _mapping(event_id: str = "source-event") -> EventMapping:
    return EventMapping(
        EventMappingId(f"mapping-{event_id}"),
        rule().id,
        EventRef(rule().source, EventId(event_id)),
        EventRef(rule().destination, EventId(f"destination-{event_id}")),
        "revision-1",
        ProjectionFingerprint("fingerprint"),
    )


def test_migration_3_upgrades_a_version_2_installation_with_rules(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    with SqliteUnitOfWorkFactory(database)() as uow:
        uow.rules.add(rule())
        uow.commit()
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TABLE rule_run_outcomes")
        connection.execute("ALTER TABLE sync_rules DROP COLUMN reprojection_required")
        connection.execute("DELETE FROM schema_migrations WHERE version = 3")

    initialize_database(database)
    initialize_database(database)

    with SqliteUnitOfWorkFactory(database)() as uow:
        restored = uow.rules.get(rule().id)
    with sqlite3.connect(database) as connection:
        versions = [row[0] for row in connection.execute("SELECT version FROM schema_migrations")]
    assert restored is not None
    assert restored.reprojection_required is False
    assert versions.count(3) == 1


def test_reprojection_flag_round_trips(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    factory = SqliteUnitOfWorkFactory(database)
    changed = rule().change_policy(TransformationPolicy(privacy=PrivacyPolicy.COPY_DETAILS))
    with factory() as uow:
        uow.rules.add(rule())
        uow.rules.save(changed)
        uow.commit()

    with factory() as uow:
        assert uow.rules.get(rule().id) == changed


def test_run_outcomes_keep_the_latest_per_kind(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    factory = SqliteUnitOfWorkFactory(database)
    first = RuleRunOutcome(
        rule().id, RunKind.SYNC, datetime(2026, 9, 1, tzinfo=UTC), True, created=2
    )
    second = replace(
        first,
        completed_at=datetime(2026, 9, 2, tzinfo=UTC),
        succeeded=False,
        created=0,
        failure_kind="rate_limit",
    )
    with factory() as uow:
        uow.rules.add(rule())
        uow.run_outcomes.record(first)
        uow.run_outcomes.record(second)
        uow.commit()

    with factory() as uow:
        assert uow.run_outcomes.latest(rule().id, RunKind.SYNC) == second
        assert uow.run_outcomes.latest(rule().id, RunKind.RECONCILIATION) is None


def test_rule_removal_cascades_resolves_incidents_and_keeps_audit(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    factory = SqliteUnitOfWorkFactory(database)
    with factory() as uow:
        uow.rules.add(rule())
        uow.mappings.save(_mapping())
        uow.cursors.save(rule().id, "cursor")
        uow.run_outcomes.record(
            RuleRunOutcome(rule().id, RunKind.SYNC, datetime(2026, 9, 1, tzinfo=UTC), True)
        )
        uow.audit.append(
            AuditEntry(datetime(2026, 9, 1, tzinfo=UTC), rule().id, "create", "completed")
        )
        uow.commit()
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO incidents (id, deduplication_key, rule_id, category, state,
                summary, opened_at, updated_at)
            VALUES ('i-1', 'provider:rule-1', 'rule-1', 'temporary', 'open', 's', 't', 't')
            """
        )

    with factory() as uow:
        assert uow.mappings.count_for_rule(rule().id) == 1
        uow.rules.remove(rule().id)
        uow.commit()

    with factory() as uow:
        assert uow.rules.get(rule().id) is None
        assert uow.mappings.count_for_rule(rule().id) == 0
        assert uow.cursors.get(rule().id) is None
        assert uow.run_outcomes.latest(rule().id, RunKind.SYNC) is None
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT state FROM incidents").fetchone()[0] == "resolved"
        assert connection.execute("SELECT COUNT(*) FROM audit_entries").fetchone()[0] == 1


def test_memory_adapter_supports_removal_counts_and_outcomes() -> None:
    factory = InMemoryUnitOfWorkFactory()
    with factory() as uow:
        uow.rules.add(rule(state=SyncRuleState.PAUSED))
        uow.mappings.save(_mapping())
        uow.run_outcomes.record(
            RuleRunOutcome(rule().id, RunKind.SYNC, datetime(2026, 9, 1, tzinfo=UTC), True)
        )
        uow.commit()
    with factory() as uow:
        assert uow.mappings.count_for_rule(rule().id) == 1
        assert uow.run_outcomes.latest(rule().id, RunKind.SYNC) is not None
        uow.rules.remove(rule().id)
        uow.commit()
    assert factory.state.rules == {}
    assert factory.state.mappings == {}
    assert factory.state.outcomes == {}
