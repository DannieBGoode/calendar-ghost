from __future__ import annotations

import sqlite3
from collections.abc import Collection, Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime

from calendar_sync.application.shared.ports import Clock
from calendar_sync.application.sync.errors import DuplicateDirectionalRelationship
from calendar_sync.application.sync.record_ports import RulePreviewSummary
from calendar_sync.domain.access import UserId
from calendar_sync.domain.incidents import IncidentResolution
from calendar_sync.domain.model import (
    KEEPS_PLACE,
    AllDaySyncPolicy,
    BirthdayPolicy,
    CalendarEndpoint,
    CalendarId,
    ConnectedAccountId,
    ProjectionContent,
    SyncRule,
    SyncRuleId,
    SyncRuleState,
    TentativeEventPolicy,
    TransformationPolicy,
    UnansweredInvitationPolicy,
)
from calendar_sync.domain.plan_hold import RulePlace, RuleStanding
from calendar_sync.infrastructure.persistence.refusals import refusals
from calendar_sync.infrastructure.persistence.sqlite.shared import _require_own


class SqliteSyncRuleRepository:
    def __init__(self, connection: sqlite3.Connection, user_id: UserId, clock: Clock) -> None:
        self._connection = connection
        self._user = user_id.value
        self._clock = clock

    def get(self, rule_id: SyncRuleId) -> SyncRule | None:
        row = self._connection.execute(
            "SELECT * FROM sync_rules WHERE id = ? AND user_id = ?", (rule_id.value, self._user)
        ).fetchone()
        return rule_from_row(row) if row else None

    def list(self) -> Sequence[SyncRule]:
        rows = self._connection.execute(
            "SELECT * FROM sync_rules WHERE user_id = ? ORDER BY id", (self._user,)
        ).fetchall()
        return tuple(rule_from_row(row) for row in rows)

    def standings(self) -> Sequence[RuleStanding]:
        rows = self._connection.execute(
            "SELECT * FROM sync_rules WHERE user_id = ? "
            "ORDER BY (plan_kept != 0) DESC, creation_order, id",
            (self._user,),
        ).fetchall()
        standings = []
        for row in rows:
            rule = rule_from_row(row)
            if not rule.counts_toward_plan and not rule.stopped_by_plan_hold:
                continue
            place = (
                RulePlace.HELD
                if rule.stopped_by_plan_hold
                else RulePlace.RESERVED
                if rule.keeps_place
                else RulePlace.COUNTED
            )
            standings.append(
                RuleStanding(rule.id, place, int(row["creation_order"]), bool(row["plan_kept"]))
            )
        return tuple(standings)

    def keep(self, chosen: Collection[SyncRuleId]) -> None:
        placeholders = ", ".join("?" for _ in chosen)
        # Interpolates only `?` placeholders; every identifier stays bound.
        self._connection.execute(
            f"UPDATE sync_rules SET plan_kept = (id IN ({placeholders})) WHERE user_id = ?",  # noqa: S608
            (*(rule.value for rule in chosen), self._user),
        )

    def add(self, rule: SyncRule) -> None:
        with refusals(), _rule_refusals():
            self._connection.execute(
                """
                INSERT INTO sync_rules (
                    id, source_account_id, source_calendar_id,
                    destination_account_id, destination_calendar_id,
                    privacy_policy, all_day_policy, busy_title,
                    tentative_policy, unanswered_policy, birthday_policy,
                    initial_lookback_days, state, reprojection_required,
                    awaiting_reauthorization, keeps_place, user_id, creation_order
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    (SELECT COALESCE(MAX(creation_order), 0) + 1 FROM sync_rules)
                )
                """,
                (*_rule_values(rule), self._user),
            )

    def save(self, rule: SyncRule) -> None:
        with refusals(), _rule_refusals():
            cursor = self._update(rule)
        if cursor.rowcount != 1:
            raise KeyError(f"sync rule {rule.id.value} does not exist")

    def _update(self, rule: SyncRule) -> sqlite3.Cursor:
        return self._connection.execute(
            """
            UPDATE sync_rules SET
                source_account_id = ?, source_calendar_id = ?,
                destination_account_id = ?, destination_calendar_id = ?,
                privacy_policy = ?, all_day_policy = ?, busy_title = ?,
                tentative_policy = ?, unanswered_policy = ?, birthday_policy = ?,
                initial_lookback_days = ?, state = ?, reprojection_required = ?,
                awaiting_reauthorization = ?, keeps_place = ?
            WHERE id = ? AND user_id = ?
            """,
            (*_rule_values(rule)[1:], rule.id.value, self._user),
        )

    def remove(self, rule_id: SyncRuleId) -> None:
        now = self._clock.now().isoformat()
        self._connection.execute(
            """
            UPDATE incidents SET state = 'resolved', updated_at = ?, resolved_at = ?, resolution = ?
            WHERE rule_id = ? AND user_id = ? AND state = 'open'
            """,
            (now, now, IncidentResolution.RULE_REMOVED.value, rule_id.value, self._user),
        )
        self._connection.execute(
            "DELETE FROM sync_rules WHERE id = ? AND user_id = ?", (rule_id.value, self._user)
        )

    def purge(self, rule_id: SyncRuleId) -> None:
        # Neither table references sync_rules, so nothing cascades to them.
        owned = (rule_id.value, self._user)
        self._connection.execute(
            "DELETE FROM audit_entries WHERE rule_id = ? AND user_id = ?", owned
        )
        self._connection.execute("DELETE FROM incidents WHERE rule_id = ? AND user_id = ?", owned)
        self._connection.execute("DELETE FROM sync_rules WHERE id = ? AND user_id = ?", owned)

    def inherit_place(self, rule: SyncRuleId, of: SyncRuleId) -> None:
        # creation_order is not unique: until `of` is removed, the two rank together, by id.
        self._connection.execute(
            """
            UPDATE sync_rules SET (creation_order, plan_kept) = (
                SELECT creation_order, plan_kept FROM sync_rules WHERE id = :of AND user_id = :user
            )
            WHERE id = :rule AND user_id = :user
                AND EXISTS (SELECT 1 FROM sync_rules WHERE id = :of AND user_id = :user)
            """,
            {"rule": rule.value, "of": of.value, "user": self._user},
        )

    def relationship_exists(self, source: CalendarEndpoint, destination: CalendarEndpoint) -> bool:
        row = self._connection.execute(
            """
            SELECT 1 FROM sync_rules
            WHERE source_account_id = ? AND source_calendar_id = ?
              AND destination_account_id = ? AND destination_calendar_id = ? AND user_id = ?
            LIMIT 1
            """,
            (
                source.connected_account_id.value,
                source.calendar_id.value,
                destination.connected_account_id.value,
                destination.calendar_id.value,
                self._user,
            ),
        ).fetchone()
        return row is not None


@contextmanager
def _rule_refusals() -> Iterator[None]:
    """A rule's refusals. Apart from its identifier, only its direction is unique per User, so a
    uniqueness failure naming its source is a second rule for one direction. Its accounts are
    checked when the unit commits, as their references are deferred."""
    try:
        yield
    except sqlite3.IntegrityError as error:
        if "sync_rules.source_account_id" not in str(error):
            raise
        raise DuplicateDirectionalRelationship(
            "a rule already exists for this source and destination"
        ) from error


def _rule_values(rule: SyncRule) -> tuple[object, ...]:
    return (
        rule.id.value,
        rule.source.connected_account_id.value,
        rule.source.calendar_id.value,
        rule.destination.connected_account_id.value,
        rule.destination.calendar_id.value,
        rule.transformation.content.value,
        rule.transformation.all_day.value,
        rule.transformation.busy_title,
        rule.transformation.tentative.value,
        rule.transformation.unanswered.value,
        rule.transformation.birthdays.value,
        rule.initial_lookback_days,
        rule.state.value,
        int(rule.reprojection_required),
        2 if rule.held_by_plan else int(rule.awaiting_reauthorization),
        int(rule.keeps_place),
    )


def rule_from_row(row: sqlite3.Row) -> SyncRule:
    state = SyncRuleState(str(row["state"]))
    # An unknown stop code must never authorize execution or automatic recovery.
    if row["awaiting_reauthorization"] not in (0, 1, 2):
        state = SyncRuleState.DEGRADED
    return SyncRule(
        id=SyncRuleId(str(row["id"])),
        source=CalendarEndpoint(
            ConnectedAccountId(str(row["source_account_id"])),
            CalendarId(str(row["source_calendar_id"])),
        ),
        destination=CalendarEndpoint(
            ConnectedAccountId(str(row["destination_account_id"])),
            CalendarId(str(row["destination_calendar_id"])),
        ),
        transformation=TransformationPolicy(
            content=ProjectionContent(str(row["privacy_policy"])),
            all_day=AllDaySyncPolicy(str(row["all_day_policy"])),
            busy_title=str(row["busy_title"]),
            tentative=TentativeEventPolicy(str(row["tentative_policy"])),
            unanswered=UnansweredInvitationPolicy(str(row["unanswered_policy"])),
            birthdays=BirthdayPolicy(str(row["birthday_policy"])),
        ),
        initial_lookback_days=int(row["initial_lookback_days"]),
        state=state,
        reprojection_required=bool(row["reprojection_required"]),
        awaiting_reauthorization=row["awaiting_reauthorization"] == 1,
        held_by_plan=row["awaiting_reauthorization"] == 2 and state is SyncRuleState.DEGRADED,
        # A mark left on a row in any other state reads as none.
        keeps_place=bool(row["keeps_place"]) and state in KEEPS_PLACE,
    )


class SqliteRulePreviewRepository:
    def __init__(self, connection: sqlite3.Connection, user_id: UserId) -> None:
        self._connection = connection
        self._user = user_id.value

    def record(self, summary: RulePreviewSummary) -> None:
        with refusals():
            cursor = self._insert(summary)
        _require_own(cursor, summary.rule_id)

    def _insert(self, summary: RulePreviewSummary) -> sqlite3.Cursor:
        return self._connection.execute(
            """
            INSERT INTO rule_previews (
                rule_id, completed_at, eligible_events, excluded_events, recurring_series,
                occurrence_changes, user_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(rule_id) DO UPDATE SET
                completed_at = excluded.completed_at,
                eligible_events = excluded.eligible_events,
                excluded_events = excluded.excluded_events,
                recurring_series = excluded.recurring_series,
                occurrence_changes = excluded.occurrence_changes
            WHERE user_id = excluded.user_id
            """,
            (
                summary.rule_id.value,
                summary.completed_at.isoformat(),
                summary.eligible_events,
                summary.excluded_events,
                summary.recurring_series,
                summary.occurrence_changes,
                self._user,
            ),
        )

    def latest(self, rule_id: SyncRuleId) -> RulePreviewSummary | None:
        row = self._connection.execute(
            "SELECT * FROM rule_previews WHERE rule_id = ? AND user_id = ?",
            (rule_id.value, self._user),
        ).fetchone()
        return preview_from_row(row) if row is not None else None


def preview_from_row(row: sqlite3.Row) -> RulePreviewSummary:
    return RulePreviewSummary(
        rule_id=SyncRuleId(str(row["rule_id"])),
        completed_at=datetime.fromisoformat(str(row["completed_at"])),
        eligible_events=int(row["eligible_events"]),
        excluded_events=int(row["excluded_events"]),
        recurring_series=int(row["recurring_series"]),
        occurrence_changes=int(row["occurrence_changes"]),
    )
