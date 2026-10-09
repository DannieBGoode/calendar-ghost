import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from itertools import product
from pathlib import Path

import pytest

from calendar_sync.application.activity import (
    ActivityCategory,
    ActivityFilter,
    EntryEvents,
    activity_category,
)
from calendar_sync.application.ports import (
    AccountStanding,
    AuditAction,
    AuditEntry,
    AuditOutcome,
    OpenBlock,
    RecordedEvent,
)
from calendar_sync.domain.model import SyncAction, SyncReason, SyncRuleId, TimedInterval
from calendar_sync.infrastructure.persistence import activity_queries
from calendar_sync.infrastructure.persistence.activity_queries import (
    SqliteActivityQueries,
    SqliteOperationsQueries,
)
from calendar_sync.infrastructure.persistence.sqlite import (
    initialize_database,
)
from tests.helpers import endpoint, rule
from tests.users import RULE_ACCOUNTS, add_user, sqlite_units

RECORDED_ACTIONS = (
    *(action.value for action in SyncAction),
    "policy_changed",
    "rule_removed",
    "remove_projection",
    "detach_projection",
    "removal_conflict",
)
START = datetime(2026, 9, 28, 15, 0, tzinfo=UTC)


@pytest.fixture
def database(tmp_path: Path) -> Path:
    path = tmp_path / "test.db"
    initialize_database(path)
    add_user(path)
    return path


def _append(database: Path, *entries: AuditEntry) -> None:
    with sqlite_units(database)() as uow:
        for entry in entries:
            uow.audit.append(entry)
        uow.commit()


def _entry(
    action: str,
    reason: str | None,
    *,
    rule_id: str = "rule-1",
    run_id: str | None = "run-1",
    source_event_id: str | None = "source-event",
    title: str | None = None,
    minutes: int = 0,
) -> AuditEntry:
    return AuditEntry(
        occurred_at=START + timedelta(minutes=minutes),
        rule_id=SyncRuleId(rule_id),
        action=AuditAction(action),
        outcome={"ignore": AuditOutcome.SKIPPED, "conflict": AuditOutcome.BLOCKED}.get(
            action, AuditOutcome.COMPLETED
        ),
        source_event_id=source_event_id,
        reason=SyncReason(reason) if reason is not None else None,
        run_id=run_id,
        event=(
            RecordedEvent(title, TimedInterval(START, START + timedelta(hours=1)))
            if title is not None
            else None
        ),
    )


def test_category_sql_agrees_with_the_category_rule_for_every_recorded_decision(
    database: Path,
) -> None:
    reasons = (None, *(reason.value for reason in SyncReason))
    combinations = list(product(RECORDED_ACTIONS, reasons))
    with sqlite3.connect(database) as connection:
        connection.executemany(
            """
            INSERT INTO audit_entries (
                occurred_at, rule_id, action, outcome, detail, reason, user_id
            )
            VALUES ('2026-09-28T15:00:00+00:00', 'rule-1', ?, 'completed', '', ?,
                (SELECT id FROM users ORDER BY rowid LIMIT 1))
            """,
            combinations,
        )
        rows = connection.execute(
            f"""
            SELECT action, reason, {activity_queries._CATEGORY_SQL},
                {activity_queries._BLOCK.format(t="audit_entries")}
            FROM audit_entries
            """
        ).fetchall()

    assert len(rows) == len(combinations)
    for action, reason, category, block in rows:
        assert category == activity_category(action, reason), (action, reason)
        # A synchronization block is a blocked entry that is not a Rule Removal conflict.
        assert bool(block) == (category == "blocked" and action != "removal_conflict")


@pytest.mark.parametrize(
    ("categories", "reasons"),
    [
        ({"changed"}, ["projection_missing", "source_created"]),
        ({"unchanged"}, ["occurrence_current", "projection_current"]),
        ({"skipped"}, ["recurring_unsupported", "all_day_excluded"]),
        ({"blocked"}, ["destination_occurrence_missing"]),
        (
            {"blocked", "unchanged"},
            ["occurrence_current", "destination_occurrence_missing", "projection_current"],
        ),
    ],
)
def test_entries_filter_by_category(
    database: Path, categories: set[ActivityCategory], reasons: list[str]
) -> None:
    _append(
        database,
        _entry("create", "source_created"),
        _entry("ignore", "projection_current"),
        _entry("ignore", "all_day_excluded"),
        _entry("conflict", "recurring_unsupported"),
        _entry("conflict", "destination_occurrence_missing"),
        _entry("ignore", "occurrence_current"),
        _entry("update", "projection_missing"),
    )

    listed = SqliteActivityQueries(database, add_user(database)).entries(
        ActivityFilter(categories=frozenset(categories))
    )

    assert [entry.reason for entry in listed] == reasons
    assert {entry.category for entry in listed} == categories


def test_entries_filter_by_rule_and_title(database: Path) -> None:
    _append(
        database,
        _entry("create", "source_created", title="Reunión semanal"),
        _entry("create", "source_created", rule_id="rule-2", title="Reunion"),
        _entry("create", "source_created", run_id="run-2", title="Dentist"),
    )
    queries = SqliteActivityQueries(database, add_user(database))

    def ids(selection: ActivityFilter) -> list[int]:
        return [entry.id for entry in queries.entries(selection)]

    assert ids(ActivityFilter()) == [3, 2, 1]
    assert ids(ActivityFilter(rule_id="rule-1")) == [3, 1]
    # Search ignores case, accents, and surrounding space.
    assert ids(ActivityFilter(search="  REUNION ")) == [2, 1]
    assert ids(ActivityFilter(rule_id="rule-2", search="reunión")) == [2]
    # LIKE wildcards in a search are literal.
    assert ids(ActivityFilter(search="%")) == []
    assert ids(ActivityFilter(search="   ")) == [3, 2, 1]


def test_entries_paginate_by_entry_identifier(database: Path) -> None:
    _append(database, *(_entry("create", "source_created", minutes=n) for n in range(5)))
    queries = SqliteActivityQueries(database, add_user(database))

    def ids(limit: int, before: int | None = None) -> list[int]:
        return [entry.id for entry in queries.entries(ActivityFilter(before=before, limit=limit))]

    assert ids(limit=2) == [5, 4]
    assert ids(limit=2, before=4) == [3, 2]
    assert ids(limit=2, before=2) == [1]
    assert ids(limit=2, before=1) == []
    assert ids(limit=10, before=99) == [5, 4, 3, 2, 1]


def test_entries_name_the_event_by_its_last_observed_title(database: Path) -> None:
    _append(
        database,
        _entry("create", "source_created", title="Standup"),
        _entry("update", "source_changed", title="Daily standup"),
        _entry("remove_projection", None, run_id=None),
    )
    queries = SqliteActivityQueries(database, add_user(database))

    renamed, removed = queries.entry(2), queries.entry(3)

    assert renamed is not None
    assert renamed.event is not None
    assert (renamed.event.title, renamed.event.renamed_from) == ("Daily standup", "Standup")
    assert removed is not None
    assert removed.event is not None
    assert (removed.event.title, removed.event.renamed_from) == ("Daily standup", None)
    assert queries.entry(4) is None


def test_entry_events_name_the_rule_and_events(database: Path) -> None:
    _append(database, _entry("create", "source_created"), _entry("policy_changed", None))
    queries = SqliteActivityQueries(database, add_user(database))

    assert queries.entry_events(1) == EntryEvents("rule-1", "source-event", None)
    assert queries.entry_events(3) is None


def test_recent_changes_count_a_repair_repeated_by_later_runs_once(database: Path) -> None:
    _append(
        database,
        _entry("create", "source_created", title="Standup", run_id="run-1"),
        _entry("update", "destination_drift_repaired", title="Standup", run_id="run-2"),
        _entry("update", "destination_drift_repaired", title="Standup", run_id="run-3"),
        _entry("ignore", "projection_current", title="Standup", run_id="run-4"),
        _entry("create", "source_created", source_event_id="other", title="Lunch", run_id="run-5"),
    )
    queries = SqliteActivityQueries(database, add_user(database))

    changes = queries.recent_changes(5)

    assert [(c.entry.id, c.repeats, c.entry.repeated) for c in changes] == [
        (5, 1, False),
        (3, 2, True),
        (1, 1, False),
    ]
    assert changes[1].first_occurred_at == changes[1].entry.occurred_at
    assert [change.entry.id for change in queries.recent_changes(1)] == [5]


def test_overview_counts_accounts_incidents_and_open_blocks(database: Path) -> None:
    second = replace(
        rule(),
        id=SyncRuleId("rule-2"),
        source=endpoint("other-account", "other-calendar"),
        destination=endpoint("work-account", "family-calendar"),
    )
    with sqlite_units(database, accounts=(*RULE_ACCOUNTS, "other-account"))() as uow:
        uow.rules.add(rule())
        uow.rules.add(second)
        uow.commit()
    _append(
        database,
        _entry("conflict", "destination_occurrence_missing", source_event_id="a"),
        _entry("conflict", "destination_occurrence_missing", source_event_id="b"),
        # A later decision about the event closes its block.
        _entry("update", "source_changed", source_event_id="b"),
        _entry("conflict", "recurring_unsupported", source_event_id="c"),
        _entry("conflict", "mapping_inconsistent", rule_id="rule-2", source_event_id="d"),
        # Removed rules keep their history but have no open blocks.
        _entry("conflict", "mapping_inconsistent", rule_id="removed", source_event_id="e"),
    )
    with sqlite3.connect(database) as connection:
        connection.executemany(
            """
            INSERT INTO connected_accounts
                (id, provider, display_name, email, encrypted_credentials, state,
                 created_at, updated_at, user_id)
            VALUES (?, 'google', 'Synthetic', ?, x'00', ?, '2026-09-01', '2026-09-01', 'user-1')
            """,
            [
                ("a1", "a1@example.test", "connected"),
                ("a2", "a2@example.test", "connected"),
                ("a3", "a3@example.test", "disconnected"),
            ],
        )
        connection.executemany(
            """
            INSERT INTO incidents (id, deduplication_key, rule_id, category, state, summary,
                opened_at, updated_at, user_id)
            VALUES (?, ?, 'rule-1', 'provider', ?, 'Synthetic', '2026-09-01', '2026-09-01',
                'user-1')
            """,
            [("i1", "k1", "open"), ("i2", "k2", "resolved")],
        )

    overview = SqliteOperationsQueries(database, add_user(database)).overview()

    # The three accounts the rules use, and the three recorded here.
    assert (overview.connected_accounts, overview.disconnected_accounts) == (5, 1)
    assert overview.open_incidents == 1
    assert overview.last_synced_at is None
    assert overview.open_blocks == (OpenBlock(5, "rule-2"), OpenBlock(1, "rule-1"))


def test_overview_of_an_empty_installation(database: Path) -> None:
    overview = SqliteOperationsQueries(database, add_user(database)).overview()

    assert overview.connected_accounts == overview.disconnected_accounts == 0
    assert overview.open_incidents == 0
    assert overview.open_blocks == ()


def test_the_overview_lists_each_account_state_and_provider(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    initialize_database(database)
    add_user(database)
    with sqlite3.connect(database) as connection:
        connection.executemany(
            """
            INSERT INTO connected_accounts (
                id, provider, display_name, email, encrypted_credentials,
                state, created_at, updated_at, user_id
            ) VALUES (?, 'google', ?, ?, x'00', ?, '2026-09-01', '2026-09-01',
                (SELECT id FROM users ORDER BY rowid LIMIT 1))
            """,
            [
                ("acct-a", "A", "a@example.test", "connected"),
                ("acct-b", "B", "b@example.test", "disconnected"),
            ],
        )

    overview = SqliteOperationsQueries(database, add_user(database)).overview()

    assert overview.accounts == (
        AccountStanding("acct-a", "connected", "google"),
        AccountStanding("acct-b", "disconnected", "google"),
    )
    assert (overview.connected_accounts, overview.disconnected_accounts) == (1, 1)


def test_incidents_list_open_ones_first_then_most_recently_updated(database: Path) -> None:
    with sqlite3.connect(database) as connection:
        connection.executemany(
            """
            INSERT INTO incidents (
                id, deduplication_key, rule_id, category, state, summary, opened_at, updated_at,
                resolved_at, resolution, user_id
            )
            VALUES (?, ?, NULL, 'provider', ?, 'Synthetic', '2026-09-01', ?, ?, ?,
                (SELECT id FROM users ORDER BY rowid LIMIT 1))
            """,
            [
                ("old-open", "k1", "open", "2026-09-02", None, None),
                ("resolved", "k2", "resolved", "2026-09-05", "2026-09-05", "rule_removed"),
                ("new-open", "k3", "open", "2026-09-04", None, None),
            ],
        )

    incidents = SqliteOperationsQueries(database, add_user(database)).incidents()

    assert [incident.id for incident in incidents] == ["new-open", "old-open", "resolved"]
    assert incidents[0].rule_id is None
    assert (incidents[0].resolved_at, incidents[0].resolution) == (None, None)
    assert (incidents[2].resolved_at, incidents[2].resolution) == ("2026-09-05", "rule_removed")
