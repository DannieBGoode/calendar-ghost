import sqlite3
from dataclasses import replace
from datetime import UTC, date, datetime
from importlib.resources import files
from pathlib import Path

import pytest

from calendar_sync.application.errors import DuplicateDirectionalRelationship
from calendar_sync.application.ports import (
    AuditEntry,
    RulePreviewSummary,
    RuleRunOutcome,
    RunKind,
)
from calendar_sync.domain.model import (
    EventId,
    EventMapping,
    EventMappingId,
    EventRef,
    OccurrenceMapping,
    OccurrenceMappingId,
    OccurrenceState,
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
from tests.helpers import NOW, endpoint, event, rule, week_start


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
    assert versions == [1, 2, 3, 4, 5, 6]
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


def _mapping(event_id: str = "source-event") -> EventMapping:
    return EventMapping(
        EventMappingId(f"mapping-{event_id}"),
        rule().id,
        EventRef(rule().source, EventId(event_id)),
        EventRef(rule().destination, EventId(f"destination-{event_id}")),
        "revision-1",
        ProjectionFingerprint("fingerprint"),
    )


def test_migration_4_upgrades_a_version_3_installation_with_rules(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    with SqliteUnitOfWorkFactory(database)() as uow:
        uow.rules.add(rule())
        uow.commit()
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TABLE rule_run_outcomes")
        connection.execute("ALTER TABLE sync_rules DROP COLUMN reprojection_required")
        connection.execute("DELETE FROM schema_migrations WHERE version = 4")

    initialize_database(database)
    initialize_database(database)

    with SqliteUnitOfWorkFactory(database)() as uow:
        restored = uow.rules.get(rule().id)
    with sqlite3.connect(database) as connection:
        versions = [row[0] for row in connection.execute("SELECT version FROM schema_migrations")]
    assert restored is not None
    assert restored.reprojection_required is False
    assert versions.count(4) == 1


def test_migration_6_backfills_the_last_successful_run(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    with SqliteUnitOfWorkFactory(database)() as uow:
        uow.rules.add(rule())
        uow.run_outcomes.record(
            RuleRunOutcome(rule().id, RunKind.SYNC, datetime(2026, 9, 1, tzinfo=UTC), True)
        )
        uow.run_outcomes.record(
            RuleRunOutcome(
                rule().id, RunKind.RECONCILIATION, datetime(2026, 9, 2, tzinfo=UTC), False
            )
        )
        uow.commit()
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TABLE rule_previews")
        connection.execute("ALTER TABLE rule_run_outcomes DROP COLUMN last_succeeded_at")
        connection.execute("DELETE FROM schema_migrations WHERE version = 6")

    initialize_database(database)

    with SqliteUnitOfWorkFactory(database)() as uow:
        sync = uow.run_outcomes.latest(rule().id, RunKind.SYNC)
        reconciliation = uow.run_outcomes.latest(rule().id, RunKind.RECONCILIATION)
    assert sync is not None and sync.last_succeeded_at == datetime(2026, 9, 1, tzinfo=UTC)
    # A failure-only history stays empty rather than inventing a success.
    assert reconciliation is not None and reconciliation.last_succeeded_at is None


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
        latest = uow.run_outcomes.latest(rule().id, RunKind.SYNC)
        assert latest == replace(second, last_succeeded_at=first.completed_at)
        assert uow.run_outcomes.latest(rule().id, RunKind.RECONCILIATION) is None


def test_a_later_success_replaces_the_last_successful_run(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    factory = SqliteUnitOfWorkFactory(database)
    failed = RuleRunOutcome(rule().id, RunKind.SYNC, datetime(2026, 9, 1, tzinfo=UTC), False)
    succeeded = replace(failed, completed_at=datetime(2026, 9, 2, tzinfo=UTC), succeeded=True)
    with factory() as uow:
        uow.rules.add(rule())
        uow.run_outcomes.record(failed)
        uow.commit()
    with factory() as uow:
        # A rule that has only ever failed has no successful run to report.
        latest = uow.run_outcomes.latest(rule().id, RunKind.SYNC)
        assert latest is not None and latest.last_succeeded_at is None
        uow.run_outcomes.record(succeeded)
        uow.commit()
    with factory() as uow:
        latest = uow.run_outcomes.latest(rule().id, RunKind.SYNC)
        assert latest is not None and latest.last_succeeded_at == succeeded.completed_at


def test_rule_previews_keep_the_latest_counts_and_cascade_with_the_rule(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    factory = SqliteUnitOfWorkFactory(database)
    first = RulePreviewSummary(rule().id, datetime(2026, 9, 1, tzinfo=UTC), 3, 1)
    second = replace(first, completed_at=datetime(2026, 9, 2, tzinfo=UTC), eligible_events=7)
    with factory() as uow:
        uow.rules.add(rule())
        uow.previews.record(first)
        uow.previews.record(second)
        uow.commit()

    with factory() as uow:
        assert uow.previews.latest(rule().id) == second
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("DELETE FROM sync_rules WHERE id = ?", (rule().id.value,))
        assert connection.execute("SELECT COUNT(*) FROM rule_previews").fetchone()[0] == 0


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


def _series_mapping() -> EventMapping:
    return EventMapping(
        EventMappingId("series-mapping"),
        rule().id,
        EventRef(rule().source, EventId("source-series")),
        EventRef(rule().destination, EventId("projection-1")),
        "r-1",
        ProjectionFingerprint("f"),
    )


def _occurrence(
    start: datetime | date, state: OccurrenceState = OccurrenceState.MODIFIED
) -> OccurrenceMapping:
    return OccurrenceMapping(
        OccurrenceMappingId(f"o-{start}"),
        EventMappingId("series-mapping"),
        start,
        EventRef(rule().source, EventId(f"source-series_{start}")),
        EventRef(rule().destination, EventId(f"projection-1_{start}")),
        state,
        "r-1",
        ProjectionFingerprint("f") if state is OccurrenceState.MODIFIED else None,
    )


def test_occurrence_mappings_round_trip_timed_and_all_day_starts(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    factory = SqliteUnitOfWorkFactory(database)
    timed = _occurrence(week_start(1))
    all_day = _occurrence(date(2026, 9, 15), OccurrenceState.CANCELLED)
    with factory() as uow:
        uow.rules.add(rule())
        uow.mappings.save(_series_mapping())
        uow.occurrences.save(timed)
        uow.occurrences.save(all_day)
        uow.occurrences.save(
            replace(timed, state=OccurrenceState.CANCELLED, projection_fingerprint=None)
        )
        uow.commit()

    with factory() as uow:
        stored = uow.occurrences.get(EventMappingId("series-mapping"), week_start(1))
        assert stored == replace(
            timed, state=OccurrenceState.CANCELLED, projection_fingerprint=None
        )
        assert uow.occurrences.get(EventMappingId("series-mapping"), date(2026, 9, 15)) == all_day
        assert len(uow.occurrences.for_series(EventMappingId("series-mapping"))) == 2


def test_occurrence_mappings_cascade_with_their_series_mapping_and_rule(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    factory = SqliteUnitOfWorkFactory(database)
    with factory() as uow:
        uow.rules.add(rule())
        uow.mappings.save(_series_mapping())
        uow.occurrences.save(_occurrence(week_start(1)))
        uow.commit()
    with factory() as uow:
        uow.mappings.delete(_series_mapping())
        uow.commit()
    with factory() as uow:
        assert uow.occurrences.for_series(EventMappingId("series-mapping")) == ()
        uow.mappings.save(_series_mapping())
        uow.occurrences.save(_occurrence(week_start(1)))
        uow.commit()
    with factory() as uow:
        uow.rules.remove(rule().id)
        uow.commit()
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM occurrence_mappings").fetchone()[0] == 0


def test_migration_5_upgrades_a_version_4_installation_and_resets_cursors(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    factory = SqliteUnitOfWorkFactory(database)
    with factory() as uow:
        uow.rules.add(rule())
        uow.mappings.save(_series_mapping())
        uow.cursors.save(rule().id, "source-cursor")
        uow.destination_cursors.save(rule().id, "destination-cursor")
        uow.commit()
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TABLE occurrence_mappings")
        connection.execute("DELETE FROM schema_migrations WHERE version = 5")

    initialize_database(database)
    initialize_database(database)

    with factory() as uow:
        assert uow.cursors.get(rule().id) is None
        assert uow.destination_cursors.get(rule().id) is None
        assert uow.mappings.count_for_rule(rule().id) == 1
        assert uow.occurrences.for_series(EventMappingId("series-mapping")) == ()
    with sqlite3.connect(database) as connection:
        versions = [row[0] for row in connection.execute("SELECT version FROM schema_migrations")]
    assert versions.count(5) == 1
