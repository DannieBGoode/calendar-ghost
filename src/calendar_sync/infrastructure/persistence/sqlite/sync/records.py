from __future__ import annotations

import sqlite3
from datetime import date, datetime

from calendar_sync.application.sync.run_ports import ProviderCallCounts
from calendar_sync.domain.access import UserId
from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.audit import AuditAction, AuditEntry, RecordedDecision, RecordedEvent
from calendar_sync.domain.causes import NO_CAUSE, WITHOUT_CAUSE, Cause
from calendar_sync.domain.model import AllDayRange, SyncReason, SyncRuleId, TimedInterval
from calendar_sync.domain.providers import ProviderFailureKind
from calendar_sync.domain.runs import RuleRunOutcome, RunKind
from calendar_sync.infrastructure.persistence.refusals import refusals
from calendar_sync.infrastructure.persistence.source_changes import change_columns
from calendar_sync.infrastructure.persistence.sqlite.shared import _require_own, optional_time
from calendar_sync.infrastructure.security import HistoryCipher


class SqliteSyncCursorRepository:
    """A rule's incremental position in one of its calendars, kept in `table`."""

    def __init__(
        self, connection: sqlite3.Connection, user_id: UserId, table: str = "sync_cursors"
    ) -> None:
        self._connection = connection
        self._user = user_id.value
        self._table = table

    def get(self, rule_id: SyncRuleId) -> str | None:
        # Interpolates only one of the two constant table names.
        row = self._connection.execute(
            f"SELECT cursor FROM {self._table} WHERE rule_id = ? AND user_id = ?",  # noqa: S608
            (rule_id.value, self._user),
        ).fetchone()
        return str(row["cursor"]) if row else None

    def save(self, rule_id: SyncRuleId, cursor: str) -> None:
        # Interpolates only one of the two constant table names.
        with refusals():
            written = self._connection.execute(
                f"""
                INSERT INTO {self._table}(rule_id, cursor, user_id) VALUES (?, ?, ?)
                ON CONFLICT(rule_id) DO UPDATE SET cursor = excluded.cursor
                WHERE user_id = excluded.user_id
                """,  # noqa: S608
                (rule_id.value, cursor, self._user),
            )
        _require_own(written, rule_id)


class SqliteAuditRepository:
    LATEST_FOR_SQL = """
        SELECT action, reason, destination_event_id, event_title, event_starts, event_ends,
               event_all_day, event_recurring, event_cancelled
        FROM audit_entries INDEXED BY audit_entries_source_event
        WHERE rule_id = ? AND source_event_id = ? AND user_id = ?
        ORDER BY id DESC LIMIT 1
    """

    def __init__(
        self, connection: sqlite3.Connection, user_id: UserId, history: HistoryCipher | None
    ) -> None:
        self._connection = connection
        self._user = user_id.value
        self._history = history

    def append(self, entry: AuditEntry) -> None:
        event = entry.event
        starts = ends = None
        if event is not None and isinstance(event.time, TimedInterval):
            starts, ends = event.time.starts_at.isoformat(), event.time.ends_at.isoformat()
        elif event is not None and isinstance(event.time, AllDayRange):
            starts, ends = event.time.starts_on.isoformat(), event.time.ends_before.isoformat()
        changed = change_columns(self._history, entry.rule_id, entry.source_event_id, entry.change)
        self._connection.execute(
            """
            INSERT INTO audit_entries (
                occurred_at, rule_id, action, outcome,
                source_event_id, destination_event_id, detail, reason, run_id,
                event_title, event_starts, event_ends,
                event_all_day, event_recurring, event_cancelled,
                change_fields, change_title_before, change_sealed,
                run_reason, found_by, source_comparison, user_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry.occurred_at.isoformat(),
                entry.rule_id.value,
                entry.action,
                entry.outcome,
                entry.source_event_id,
                entry.destination_event_id,
                entry.detail,
                entry.reason,
                entry.run_id,
                event.title if event else None,
                starts,
                ends,
                event is not None and isinstance(event.time, AllDayRange),
                event is not None and event.recurring,
                event is not None and event.cancelled,
                *changed,
                entry.run_reason,
                entry.found_by,
                entry.source_comparison,
                self._user,
            ),
        )

    def latest_for(self, rule_id: SyncRuleId, source_event_id: str) -> RecordedDecision | None:
        row = self._connection.execute(
            self.LATEST_FOR_SQL, (rule_id.value, source_event_id, self._user)
        ).fetchone()
        if row is None:
            return None
        try:
            action = AuditAction(row["action"])
            reason = SyncReason(row["reason"]) if row["reason"] is not None else None
            event = _recorded_event(row)
        except ValueError:
            # A value this release cannot read proves nothing, so the decision is recorded.
            return None
        return RecordedDecision(action, reason, row["destination_event_id"], event)

    def forget_change_values(self, before: datetime) -> None:
        self._connection.execute(
            """
            UPDATE audit_entries SET change_sealed = NULL
            WHERE change_sealed IS NOT NULL AND occurred_at < ? AND user_id = ?
            """,
            (before.isoformat(), self._user),
        )


def _recorded_event(row: sqlite3.Row) -> RecordedEvent | None:
    """The event an entry recorded, as `append` wrote it."""
    if row["event_title"] is None:
        return None
    time: TimedInterval | AllDayRange | None = None
    if row["event_starts"] is not None and row["event_all_day"]:
        time = AllDayRange(
            date.fromisoformat(row["event_starts"]), date.fromisoformat(row["event_ends"])
        )
    elif row["event_starts"] is not None:
        time = TimedInterval(
            datetime.fromisoformat(row["event_starts"]), datetime.fromisoformat(row["event_ends"])
        )
    return RecordedEvent(
        title=row["event_title"],
        time=time,
        recurring=bool(row["event_recurring"]),
        cancelled=bool(row["event_cancelled"]),
    )


class SqliteRuleRunOutcomeRepository:
    def __init__(self, connection: sqlite3.Connection, user_id: UserId) -> None:
        self._connection = connection
        self._user = user_id.value

    def record(self, outcome: RuleRunOutcome) -> None:
        with refusals():
            cursor = self._insert(outcome)
        _require_own(cursor, outcome.rule_id)

    def _insert(self, outcome: RuleRunOutcome) -> sqlite3.Cursor:
        return self._connection.execute(
            """
            INSERT INTO rule_run_outcomes (
                rule_id, kind, completed_at, succeeded, full_run, created, updated,
                deleted, conflicts, checked_mappings, drift, failure_kind, failure_cause,
                failure_provider, last_succeeded_at, last_full_succeeded_at, user_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(rule_id, kind) DO UPDATE SET
                last_succeeded_at = CASE WHEN excluded.succeeded
                    THEN excluded.completed_at ELSE rule_run_outcomes.last_succeeded_at END,
                last_full_succeeded_at = CASE WHEN excluded.succeeded AND excluded.full_run
                    THEN excluded.completed_at ELSE rule_run_outcomes.last_full_succeeded_at END,
                completed_at = excluded.completed_at,
                succeeded = excluded.succeeded,
                full_run = excluded.full_run,
                created = excluded.created,
                updated = excluded.updated,
                deleted = excluded.deleted,
                conflicts = excluded.conflicts,
                checked_mappings = excluded.checked_mappings,
                drift = excluded.drift,
                failure_kind = excluded.failure_kind,
                failure_cause = excluded.failure_cause,
                failure_provider = excluded.failure_provider
            WHERE rule_run_outcomes.user_id = excluded.user_id
            """,
            (
                outcome.rule_id.value,
                outcome.kind.value,
                outcome.completed_at.isoformat(),
                int(outcome.succeeded),
                int(outcome.full_run),
                outcome.created,
                outcome.updated,
                outcome.deleted,
                outcome.conflicts,
                outcome.checked_mappings,
                outcome.drift,
                outcome.failure_kind.value if outcome.failure_kind else None,
                None
                if outcome.succeeded or outcome.failure_kind in WITHOUT_CAUSE
                else outcome.failure_cause.value
                if outcome.failure_cause
                else NO_CAUSE,
                outcome.failure_provider.value
                if outcome.failure_provider and _caused(outcome)
                else None,
                outcome.completed_at.isoformat() if outcome.succeeded else None,
                outcome.completed_at.isoformat()
                if outcome.succeeded and outcome.full_run
                else None,
                self._user,
            ),
        )

    def latest(self, rule_id: SyncRuleId, kind: RunKind) -> RuleRunOutcome | None:
        row = self._connection.execute(
            "SELECT * FROM rule_run_outcomes WHERE rule_id = ? AND kind = ? AND user_id = ?",
            (rule_id.value, kind.value, self._user),
        ).fetchone()
        return outcome_from_row(row) if row is not None else None


def _caused(outcome: RuleRunOutcome) -> bool:
    """Whether a provider's answer explains the outcome: a failure that is not local."""
    return not outcome.succeeded and outcome.failure_kind not in WITHOUT_CAUSE


def outcome_from_row(row: sqlite3.Row) -> RuleRunOutcome:
    return RuleRunOutcome(
        rule_id=SyncRuleId(str(row["rule_id"])),
        kind=RunKind(str(row["kind"])),
        completed_at=datetime.fromisoformat(str(row["completed_at"])),
        succeeded=bool(row["succeeded"]),
        full_run=bool(row["full_run"]),
        created=int(row["created"]),
        updated=int(row["updated"]),
        deleted=int(row["deleted"]),
        conflicts=int(row["conflicts"]),
        checked_mappings=int(row["checked_mappings"]),
        drift=int(row["drift"]),
        failure_kind=None
        if row["failure_kind"] is None
        else ProviderFailureKind(str(row["failure_kind"])),
        failure_cause=None
        if row["succeeded"] or row["failure_kind"] in WITHOUT_CAUSE
        else Cause.recorded(row["failure_cause"]),
        failure_provider=ProviderKind.recorded(row["failure_provider"]),
        last_succeeded_at=optional_time(row["last_succeeded_at"]),
        last_full_succeeded_at=optional_time(row["last_full_succeeded_at"]),
    )


class SqliteProviderCallRepository:
    def __init__(self, connection: sqlite3.Connection, user_id: UserId) -> None:
        self._connection = connection
        self._user = user_id.value

    def add(self, day: date, provider: ProviderKind, counts: ProviderCallCounts) -> None:
        self._connection.execute(
            """
            INSERT INTO provider_calls (user_id, provider, day, calls, rate_limited, failed)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (user_id, provider, day) DO UPDATE SET
                calls = calls + excluded.calls,
                rate_limited = rate_limited + excluded.rate_limited,
                failed = failed + excluded.failed
            """,
            (
                self._user,
                provider.value,
                day.isoformat(),
                counts.calls,
                counts.rate_limited,
                counts.failed,
            ),
        )
