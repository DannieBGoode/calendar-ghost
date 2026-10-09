from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from calendar_sync.application.errors import ProviderFailureKind
from calendar_sync.application.ports import IdGenerator, IncidentReport, IncidentResolution
from calendar_sync.domain.access import UserId
from calendar_sync.domain.model import ConnectedAccountId, SyncRuleId
from calendar_sync.infrastructure.identifiers import UuidIdGenerator
from calendar_sync.infrastructure.persistence.activity_queries import open_blocks
from calendar_sync.infrastructure.persistence.connections import transaction


class SqliteRuleHealthRecords:
    """One User's failure streaks and daily block checks."""

    def __init__(self, database_path: Path, user_id: UserId) -> None:
        self._database_path = database_path
        self._user = user_id.value

    def record_failure(self, rule_id: SyncRuleId, kind: ProviderFailureKind, at: datetime) -> int:
        """The rule's consecutive failures, counting this one; 1 for a rule removed meanwhile."""
        with transaction(self._database_path) as connection:
            # A rule removed while its run failed has no failures to count; inserting one for it
            # would break the foreign key, so nothing is recorded.
            connection.execute(
                """
                INSERT INTO rule_failures(
                    rule_id, user_id, consecutive_failures, last_category, updated_at
                )
                SELECT id, user_id, 1, ?, ? FROM sync_rules WHERE id = ? AND user_id = ?
                ON CONFLICT(rule_id) DO UPDATE SET
                    consecutive_failures = consecutive_failures + 1,
                    last_category = excluded.last_category,
                    updated_at = excluded.updated_at
                WHERE user_id = excluded.user_id
                """,
                (kind.value, at.isoformat(), rule_id.value, self._user),
            )
            # An orphaned row left by an earlier release is neither updated nor counted.
            row = connection.execute(
                """
                SELECT consecutive_failures FROM rule_failures
                WHERE rule_id = ? AND user_id = ? AND EXISTS (
                    SELECT 1 FROM sync_rules WHERE id = rule_id AND user_id = ?
                )
                """,
                (rule_id.value, self._user, self._user),
            ).fetchone()
        return 1 if row is None else int(row[0])

    def clear_failures(self, rule_id: SyncRuleId) -> None:
        with transaction(self._database_path) as connection:
            connection.execute(
                "DELETE FROM rule_failures WHERE rule_id = ? AND user_id = ?",
                (rule_id.value, self._user),
            )

    def audit_floor(self) -> int:
        with transaction(self._database_path) as connection:
            return int(
                connection.execute(
                    "SELECT COALESCE(MAX(id), 0) FROM audit_entries WHERE user_id = ?",
                    (self._user,),
                ).fetchone()[0]
            )

    def record_block_check(
        self, rule_id: SyncRuleId, floor: int, run_id: str | None, at: datetime
    ) -> int | None:
        with transaction(self._database_path) as connection:
            if not connection.execute(
                "SELECT 1 FROM sync_rules WHERE id = ? AND user_id = ?",
                (rule_id.value, self._user),
            ).fetchone():
                return None
            persisting = len(
                open_blocks(
                    connection,
                    self._user,
                    rule_id=rule_id.value,
                    after=floor,
                    persisting=True,
                    run_id=run_id,
                )
            )
            connection.execute(
                """
                INSERT INTO rule_block_checks (rule_id, user_id, audit_floor, checked_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(rule_id) DO UPDATE SET
                    audit_floor = excluded.audit_floor, checked_at = excluded.checked_at
                WHERE user_id = excluded.user_id
                """,
                (rule_id.value, self._user, floor, at.isoformat()),
            )
        return persisting


class SqliteIncidentRepository:
    """One User's Incidents."""

    def __init__(
        self, database_path: Path, user_id: UserId, ids: IdGenerator | None = None
    ) -> None:
        self._database_path = database_path
        self._user = user_id.value
        self._ids = ids or UuidIdGenerator()

    def open(self, incident: IncidentReport, at: datetime) -> bool:
        # An Incident about an account alone is its Lapsed Authorization, so it opens only while
        # the account exists and is lapsed, checked in the same statement: neither a deletion
        # nor a restoration that ran just before it can leave it open.
        account_only = incident.account_id if incident.rule_id is None else None
        with transaction(self._database_path) as connection:
            # Held from the read to the write, so two reports of one Incident cannot both find
            # it closed and both notify.
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT state FROM incidents WHERE deduplication_key = ? AND user_id = ?",
                (incident.key, self._user),
            ).fetchone()
            cursor = connection.execute(
                """
                INSERT INTO incidents (
                    id, deduplication_key, rule_id, account_id, category, state,
                    summary, opened_at, updated_at, message_code, message_params, user_id
                )
                SELECT ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, ?, ?
                WHERE ? IS NULL OR EXISTS (
                    SELECT 1 FROM connected_accounts
                    WHERE id = ? AND user_id = ? AND authorization_lapsed_at IS NOT NULL
                )
                ON CONFLICT(user_id, deduplication_key) DO UPDATE SET
                    account_id = excluded.account_id,
                    category = excluded.category,
                    opened_at = CASE WHEN state = 'open' THEN opened_at ELSE excluded.opened_at END,
                    state = 'open',
                    summary = excluded.summary,
                    updated_at = excluded.updated_at,
                    resolved_at = NULL,
                    resolution = NULL,
                    message_code = excluded.message_code,
                    message_params = excluded.message_params
                """,
                (
                    self._ids.new(),
                    incident.key,
                    incident.rule_id.value if incident.rule_id else None,
                    incident.account_id.value if incident.account_id else None,
                    incident.category,
                    incident.summary,
                    at.isoformat(),
                    at.isoformat(),
                    incident.message.code if incident.message else None,
                    json.dumps(dict(incident.message.params), sort_keys=True)
                    if incident.message
                    else None,
                    self._user,
                    account_only.value if account_only else None,
                    account_only.value if account_only else None,
                    self._user,
                ),
            )
        if cursor.rowcount == 0:
            return False
        return existing is None or existing[0] != "open"

    def resolve(
        self,
        key: str,
        at: datetime,
        resolution: IncidentResolution,
        *,
        while_authorized: ConnectedAccountId | None = None,
    ) -> None:
        account = while_authorized.value if while_authorized else None
        with transaction(self._database_path) as connection:
            connection.execute(
                """
                UPDATE incidents SET
                    state = 'resolved', updated_at = ?, resolved_at = ?, resolution = ?
                WHERE deduplication_key = ? AND user_id = ? AND state = 'open' AND (
                    ? IS NULL OR EXISTS (
                        SELECT 1 FROM connected_accounts
                        WHERE id = ? AND user_id = ? AND state = 'connected'
                            AND authorization_lapsed_at IS NULL
                    )
                )
                """,
                (
                    at.isoformat(),
                    at.isoformat(),
                    resolution.value,
                    key,
                    self._user,
                    account,
                    account,
                    self._user,
                ),
            )
