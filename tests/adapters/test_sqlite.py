import sqlite3
from dataclasses import replace
from datetime import UTC, date, datetime
from importlib.resources import files
from pathlib import Path
from threading import Thread

import pytest

from calendar_sync.application.errors import (
    ConnectedAccountRequired,
    DuplicateDirectionalRelationship,
)
from calendar_sync.application.ports import (
    AuditAction,
    AuditEntry,
    AuditOutcome,
    CalendarAccess,
    ConnectedAccountState,
    DiscoveredCalendar,
    RulePreviewSummary,
    RuleRunOutcome,
    RunKind,
)
from calendar_sync.application.providers import ProviderKind
from calendar_sync.application.rules import CreateSyncRule
from calendar_sync.domain.model import (
    CalendarEndpoint,
    CalendarId,
    ConnectedAccountId,
    EventId,
    EventMapping,
    EventMappingId,
    EventRef,
    OccurrenceMapping,
    OccurrenceMappingId,
    OccurrenceState,
    ProjectionContent,
    ProjectionFingerprint,
    SyncReason,
    SyncRule,
    SyncRuleId,
    SyncRuleState,
    TentativeEventPolicy,
    TransformationPolicy,
    UnansweredInvitationPolicy,
)
from calendar_sync.infrastructure.persistence.accounts import SqliteConnectedAccountStore
from calendar_sync.infrastructure.persistence.memory import InMemoryUnitOfWorkFactory
from calendar_sync.infrastructure.persistence.sqlite import (
    SqliteUnitOfWorkFactory,
    initialize_database,
)
from calendar_sync.infrastructure.security import CredentialCipher
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


def test_sqlite_rule_repository_keeps_the_invitation_response_policies(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    factory = SqliteUnitOfWorkFactory(database)
    waiting = replace(
        rule(),
        transformation=TransformationPolicy(
            tentative=TentativeEventPolicy.SKIP, unanswered=UnansweredInvitationPolicy.WAIT
        ),
    )

    with factory() as uow:
        uow.rules.add(waiting)
        uow.commit()
    with factory() as uow:
        uow.rules.save(replace(waiting, transformation=TransformationPolicy()))
        uow.commit()
    with factory() as uow:
        restored = uow.rules.get(rule().id)

    assert restored == replace(waiting, transformation=TransformationPolicy())


def test_migration_15_gives_existing_rules_the_defaults_and_reprojects_them(
    tmp_path: Path,
) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    with SqliteUnitOfWorkFactory(database)() as uow:
        uow.rules.add(rule())
        uow.commit()
    with sqlite3.connect(database) as connection:
        connection.execute("ALTER TABLE sync_rules DROP COLUMN tentative_policy")
        connection.execute("ALTER TABLE sync_rules DROP COLUMN unanswered_policy")
        connection.execute("DELETE FROM schema_migrations WHERE version = 15")

    initialize_database(database)
    initialize_database(database)

    with SqliteUnitOfWorkFactory(database)() as uow:
        restored = uow.rules.get(rule().id)
    assert restored == replace(rule(), reprojection_required=True)


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
        titles = connection.execute("SELECT DISTINCT event_title FROM audit_entries").fetchall()
    assert versions == list(range(1, 18))
    assert rows == [
        ("conflict", "blocked", "recurring_unsupported", None),
        ("create", "completed", "source_created", None),
        ("ignore", "completed", None, None),
    ]
    # Earlier entries are not backfilled with event names (ADR 0014).
    assert titles == [(None,)]


def test_audit_entries_persist_reason_and_run(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)

    with SqliteUnitOfWorkFactory(database)() as uow:
        uow.audit.append(
            AuditEntry(
                occurred_at=NOW,
                rule_id=rule().id,
                action=AuditAction.IGNORE,
                outcome=AuditOutcome.SKIPPED,
                source_event_id="weekly",
                reason=SyncReason.RECURRING_UNSUPPORTED,
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
    assert sync is not None
    assert sync.last_succeeded_at == datetime(2026, 9, 1, tzinfo=UTC)
    # A failure-only history stays empty rather than inventing a success.
    assert reconciliation is not None
    assert reconciliation.last_succeeded_at is None


def test_reprojection_flag_round_trips(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    factory = SqliteUnitOfWorkFactory(database)
    changed = rule().change_policy(TransformationPolicy(content=ProjectionContent.DETAILS))
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
        assert latest is not None
        assert latest.last_succeeded_at is None
        uow.run_outcomes.record(succeeded)
        uow.commit()
    with factory() as uow:
        latest = uow.run_outcomes.latest(rule().id, RunKind.SYNC)
        assert latest is not None
        assert latest.last_succeeded_at == succeeded.completed_at


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
            AuditEntry(
                datetime(2026, 9, 1, tzinfo=UTC),
                rule().id,
                AuditAction.CREATE,
                AuditOutcome.COMPLETED,
            )
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
        assert connection.execute("SELECT state, resolution FROM incidents").fetchone() == (
            "resolved",
            "rule_removed",
        )
        assert connection.execute("SELECT COUNT(*) FROM audit_entries").fetchone()[0] == 1


def test_rule_purge_deletes_its_audit_entries_and_incidents_but_no_other_rules(
    tmp_path: Path,
) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    factory = SqliteUnitOfWorkFactory(database)
    other = replace(rule(), id=SyncRuleId("rule-2"), source=endpoint("other", "calendar"))
    with factory() as uow:
        for kept_or_purged in (rule(), other):
            uow.rules.add(kept_or_purged)
            uow.audit.append(
                AuditEntry(
                    datetime(2026, 9, 1, tzinfo=UTC),
                    kept_or_purged.id,
                    AuditAction.CREATE,
                    AuditOutcome.COMPLETED,
                )
            )
        uow.mappings.save(_mapping())
        uow.commit()
    with sqlite3.connect(database) as connection:
        connection.executemany(
            """
            INSERT INTO incidents (id, deduplication_key, rule_id, category, state,
                summary, opened_at, updated_at)
            VALUES (?, ?, ?, 'temporary', 'open', 's', 't', 't')
            """,
            [("i-1", "provider:rule-1", "rule-1"), ("i-2", "provider:rule-2", "rule-2")],
        )

    with factory() as uow:
        uow.rules.purge(rule().id)
        uow.commit()

    with factory() as uow:
        assert [kept.id for kept in uow.rules.list()] == [other.id]
        assert uow.mappings.count_for_rule(rule().id) == 0
    with sqlite3.connect(database) as connection:
        for table in ("audit_entries", "incidents"):
            assert connection.execute(f"SELECT rule_id FROM {table}").fetchall() == [("rule-2",)]


def test_account_deletion_holds_the_write_lock_so_reauthorization_waits_for_it(
    tmp_path: Path,
) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    store = SqliteConnectedAccountStore(database, CredentialCipher(CredentialCipher.generate_key()))
    disconnected = store.save("Personal", "person@example.test", "{}", provider=ProviderKind.GOOGLE)
    store.disconnect(disconnected.id)
    connected = store.save("Work", "work@example.test", "{}", provider=ProviderKind.GOOGLE)
    factory = SqliteUnitOfWorkFactory(database)
    reauthorize = Thread(
        target=store.save,
        args=("Personal", "person@example.test", "{}"),
        kwargs={"provider": ProviderKind.GOOGLE},
    )

    with factory() as uow:
        assert uow.accounts.delete_disconnected(connected.id) is False
        assert uow.accounts.delete_disconnected(disconnected.id) is True
        reauthorize.start()
        reauthorize.join(0.2)
        waited_for_deletion = reauthorize.is_alive()
        uow.commit()
    reauthorize.join(2)

    assert waited_for_deletion
    # Reauthorizing after the deletion connects the identity afresh.
    assert {account.email: account.id for account in store.list()}["work@example.test"] == (
        connected.id
    )
    assert store.get(disconnected.id) is None


def test_a_rule_creation_waiting_behind_account_deletion_is_refused_afterwards(
    tmp_path: Path,
) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    store = SqliteConnectedAccountStore(database, CredentialCipher(CredentialCipher.generate_key()))
    deleted = store.save("Personal", "person@example.test", "{}", provider=ProviderKind.GOOGLE)
    store.disconnect(deleted.id)
    kept = store.save("Work", "work@example.test", "{}", provider=ProviderKind.GOOGLE)
    factory = SqliteUnitOfWorkFactory(database)
    late_rule = SyncRule(
        SyncRuleId("late"),
        endpoint(deleted.id.value, "personal-calendar"),
        endpoint(kept.id.value, "work-calendar"),
    )
    refused: list[Exception] = []

    def create() -> None:
        try:
            CreateSyncRule(factory).execute(late_rule)
        except ConnectedAccountRequired as error:
            refused.append(error)

    creating = Thread(target=create)
    with factory() as uow:
        assert uow.accounts.delete_disconnected(deleted.id)
        creating.start()
        creating.join(0.2)
        waited_for_deletion = creating.is_alive()
        uow.commit()
    creating.join(2)

    assert waited_for_deletion
    assert len(refused) == 1
    with factory() as uow:
        assert uow.rules.list() == ()


def test_account_records_report_state_inside_the_unit_of_work(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    store = SqliteConnectedAccountStore(database, CredentialCipher(CredentialCipher.generate_key()))
    account = store.save("Work", "work@example.test", "{}", provider=ProviderKind.GOOGLE)

    with SqliteUnitOfWorkFactory(database)() as uow:
        assert uow.accounts.state(account.id) is ConnectedAccountState.CONNECTED
        assert uow.accounts.state(ConnectedAccountId("missing")) is None


class _MovableClock:
    def __init__(self, now: datetime) -> None:
        self.moment = now

    def now(self) -> datetime:
        return self.moment


def _calendar(calendar_id: str, name: str) -> DiscoveredCalendar:
    return DiscoveredCalendar(calendar_id, name, access=CalendarAccess.OWNER, primary=False)


def test_calendar_names_record_only_changes_and_go_with_their_account(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    store = SqliteConnectedAccountStore(database, CredentialCipher(CredentialCipher.generate_key()))
    account = store.save("Personal", "person@example.test", "{}", provider=ProviderKind.GOOGLE)
    clock = _MovableClock(datetime(2026, 9, 1, tzinfo=UTC))
    factory = SqliteUnitOfWorkFactory(database, clock)
    family = CalendarEndpoint(account.id, CalendarId("family"))
    work = CalendarEndpoint(account.id, CalendarId("work"))
    with factory() as uow:
        uow.calendar_names.remember(
            account.id, [_calendar("family", "Family"), _calendar("work", "Work")]
        )
        uow.calendar_names.remember(ConnectedAccountId("missing"), [_calendar("other", "Other")])
        uow.commit()
    clock.moment = datetime(2026, 9, 2, tzinfo=UTC)
    # Work is no longer listed, and Family's name is unchanged, so only Family's rename writes.
    with factory() as uow:
        uow.calendar_names.remember(account.id, [_calendar("family", "Household")])
        uow.commit()
    clock.moment = datetime(2026, 9, 3, tzinfo=UTC)
    with factory() as uow:
        uow.calendar_names.remember(account.id, [_calendar("family", "Household")])
        uow.commit()

    with factory() as uow:
        assert uow.calendar_names.names([family, work]) == {family: "Household", work: "Work"}
        assert uow.calendar_names.names([family]) == {family: "Household"}
        assert uow.calendar_names.names([]) == {}
    with sqlite3.connect(database) as connection:
        updated = dict(
            connection.execute("SELECT calendar_id, updated_at FROM calendar_names").fetchall()
        )
        assert updated == {
            "family": "2026-09-02T00:00:00+00:00",
            "work": "2026-09-01T00:00:00+00:00",
        }
    store.disconnect(account.id)
    with factory() as uow:
        assert uow.accounts.delete_disconnected(account.id)
        uow.commit()
    with factory() as uow:
        assert uow.calendar_names.names([family, work]) == {}


def test_memory_adapter_keeps_calendar_names_of_existing_accounts() -> None:
    factory = InMemoryUnitOfWorkFactory()
    account = ConnectedAccountId("account-1")
    factory.state.accounts[account] = ConnectedAccountState.DISCONNECTED
    family = CalendarEndpoint(account, CalendarId("family"))
    with factory() as uow:
        uow.calendar_names.remember(account, [_calendar("family", "Family")])
        uow.calendar_names.remember(ConnectedAccountId("missing"), [_calendar("other", "Other")])
        uow.commit()
    with factory() as uow:
        assert uow.calendar_names.names([family]) == {family: "Family"}
        assert uow.accounts.delete_disconnected(account)
        uow.commit()
    assert factory.state.calendar_names == {}


def test_memory_adapter_purges_a_rule_with_its_audit_entries() -> None:
    factory = InMemoryUnitOfWorkFactory()
    # Another direction, since SQLite refuses a second rule for one source and destination.
    other = replace(
        rule(), id=SyncRuleId("rule-2"), destination=endpoint("work-account", "other-calendar")
    )
    with factory() as uow:
        for kept_or_purged in (rule(), other):
            uow.rules.add(kept_or_purged)
            uow.audit.append(
                AuditEntry(
                    datetime(2026, 9, 1, tzinfo=UTC),
                    kept_or_purged.id,
                    AuditAction.CREATE,
                    AuditOutcome.COMPLETED,
                )
            )
        uow.mappings.save(_mapping())
        uow.commit()

    with factory() as uow:
        uow.rules.purge(rule().id)
        uow.commit()

    assert list(factory.state.rules) == [other.id]
    assert factory.state.mappings == {}
    assert [entry.rule_id for entry in factory.state.audit] == [other.id]


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


def test_migration_7_indexes_audit_entries_by_run(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    with sqlite3.connect(database) as connection:
        connection.execute("DROP INDEX audit_entries_run_id")
        connection.execute("DELETE FROM schema_migrations WHERE version = 7")

    initialize_database(database)
    initialize_database(database)

    with sqlite3.connect(database) as connection:
        versions = [row[0] for row in connection.execute("SELECT version FROM schema_migrations")]
        plan = " ".join(
            str(row[3])
            for row in connection.execute(
                "EXPLAIN QUERY PLAN SELECT id FROM audit_entries WHERE run_id = ? ORDER BY id DESC",
                ("run-1",),
            )
        )
    assert versions.count(7) == 1
    assert "audit_entries_run_id" in plan


def test_migration_12_keeps_earlier_resolutions_unknown(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    with sqlite3.connect(database) as connection:
        connection.execute("ALTER TABLE incidents DROP COLUMN resolution")
        connection.execute("DELETE FROM schema_migrations WHERE version = 12")
        connection.execute(
            """
            INSERT INTO incidents (id, deduplication_key, rule_id, category, state,
                summary, opened_at, updated_at, resolved_at)
            VALUES ('i-1', 'provider:rule-1', 'rule-1', 'temporary', 'resolved', 's', 't', 't', 't')
            """
        )

    initialize_database(database)
    initialize_database(database)

    with sqlite3.connect(database) as connection:
        versions = [row[0] for row in connection.execute("SELECT version FROM schema_migrations")]
        resolution = connection.execute("SELECT resolution FROM incidents").fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE incidents SET resolution = 'fixed'")
    # The reason an earlier release resolved an Incident was never recorded.
    assert versions.count(12) == 1
    assert resolution is None


def test_migration_13_keeps_earlier_incident_accounts_unknown(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    with sqlite3.connect(database) as connection:
        connection.execute("ALTER TABLE incidents DROP COLUMN account_id")
        connection.execute("DELETE FROM schema_migrations WHERE version = 13")
        connection.execute(
            """
            INSERT INTO incidents (id, deduplication_key, rule_id, category, state,
                summary, opened_at, updated_at)
            VALUES ('i-1', 'provider:rule-1', 'rule-1', 'authentication', 'open', 's', 't', 't')
            """
        )

    initialize_database(database)
    initialize_database(database)

    with sqlite3.connect(database) as connection:
        versions = [row[0] for row in connection.execute("SELECT version FROM schema_migrations")]
        account = connection.execute("SELECT account_id FROM incidents").fetchone()[0]
    # Which account an earlier release's failure came from was never recorded.
    assert versions.count(13) == 1
    assert account is None


def test_migration_8_backfills_the_last_full_run(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    completed = datetime(2026, 9, 1, tzinfo=UTC)
    with SqliteUnitOfWorkFactory(database)() as uow:
        uow.rules.add(rule())
        uow.run_outcomes.record(RuleRunOutcome(rule().id, RunKind.SYNC, completed, True, True))
        uow.commit()
    with sqlite3.connect(database) as connection:
        connection.execute("ALTER TABLE rule_run_outcomes DROP COLUMN last_full_succeeded_at")
        connection.execute("DELETE FROM schema_migrations WHERE version = 8")

    initialize_database(database)
    initialize_database(database)

    with SqliteUnitOfWorkFactory(database)() as uow:
        latest = uow.run_outcomes.latest(rule().id, RunKind.SYNC)
    assert latest is not None
    assert latest.last_full_succeeded_at == completed
