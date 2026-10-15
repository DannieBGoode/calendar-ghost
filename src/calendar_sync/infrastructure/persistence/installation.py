"""The installation-wide unit of work: what reaches across Users (ADR 0029)."""

from __future__ import annotations

import sqlite3
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from types import TracebackType
from typing import Self

from calendar_sync.application.operations.ports import (
    CauseSighting,
    InstallationUnitOfWork,
    InstantSyncOwner,
    PendingInstantRun,
    ProviderCallUse,
    RecordedRule,
    ResourceUse,
    StatusRecords,
)
from calendar_sync.application.sync.ports import ScheduledRule
from calendar_sync.domain.access import UserId, UserState
from calendar_sync.domain.accounts import ConnectedAccountState, ProviderKind
from calendar_sync.domain.causes import Cause
from calendar_sync.domain.model import SyncRuleState
from calendar_sync.domain.watches import CalendarWatch, WatchRegistration
from calendar_sync.infrastructure.persistence.activity_queries import operations_of
from calendar_sync.infrastructure.persistence.connections import open_connection
from calendar_sync.infrastructure.persistence.sqlite import (
    optional_time,
    outcome_from_row,
    preview_from_row,
    rule_from_row,
)
from calendar_sync.infrastructure.persistence.watches import (
    registration_from_row,
    request_from_row,
    upkeep_due,
    watch_from_row,
)


def _cause_sighting(row: sqlite3.Row) -> CauseSighting:
    opened, authorized = optional_time(row["opened_at"]), optional_time(row["authorized_at"])
    lived = opened - authorized if row["open"] and opened and authorized else None
    return CauseSighting(
        UserId(str(row["user_id"])),
        Cause.read(row["cause"]),
        datetime.fromisoformat(str(row["at"])),
        bool(row["open"]),
        lived,
        provider=ProviderKind.recorded(row["provider"]),
    )


class SqliteInstallationUnitOfWork:
    """What the scheduler and the Operator Overview read across Users (ADR 0029)."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._connection: sqlite3.Connection | None = None

    def __enter__(self) -> Self:
        self._connection = open_connection(self._database_path)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        assert self._connection is not None
        if exc_type is not None:
            self._connection.rollback()
        self._connection.close()
        self._connection = None
        return None

    def commit(self) -> None:
        assert self._connection is not None
        self._connection.commit()

    def scheduled_rules(self) -> Sequence[ScheduledRule]:
        assert self._connection is not None
        rows = self._connection.execute(
            """
            SELECT sync_rules.*, outcome.last_full_succeeded_at
            FROM sync_rules
            JOIN users ON users.id = sync_rules.user_id AND users.state = 'active'
            LEFT JOIN rule_run_outcomes outcome
              ON outcome.rule_id = sync_rules.id AND outcome.kind = 'sync'
            WHERE sync_rules.state = ?
            ORDER BY sync_rules.user_id, sync_rules.id
            """,
            (SyncRuleState.ENABLED.value,),
        ).fetchall()
        return tuple(
            ScheduledRule(
                UserId(str(row["user_id"])),
                rule_from_row(row),
                optional_time(row["last_full_succeeded_at"]),
            )
            for row in rows
        )

    def users_with_unfinished_lapses(self) -> Sequence[UserId]:
        assert self._connection is not None
        rows = self._connection.execute(
            """
            SELECT users.id FROM users
            WHERE users.state = 'active' AND (
                EXISTS (
                    SELECT 1 FROM sync_rules
                    WHERE sync_rules.user_id = users.id
                        AND sync_rules.state = :degraded
                        AND sync_rules.awaiting_reauthorization = 1
                )
                OR EXISTS (
                    SELECT 1 FROM connected_accounts account
                    LEFT JOIN incidents incident
                        ON incident.user_id = account.user_id
                        AND incident.account_id = account.id
                        AND incident.rule_id IS NULL
                        AND incident.state = 'open'
                    WHERE account.user_id = users.id AND account.state = :connected AND (
                        -- Authorized again while its Incident is open: a restoration.
                        (account.authorization_lapsed_at IS NULL AND incident.id IS NOT NULL)
                        -- Lapsed with no Incident open, or a rule still enabled: a lapse.
                        OR (account.authorization_lapsed_at IS NOT NULL AND (
                            incident.id IS NULL OR EXISTS (
                                SELECT 1 FROM sync_rules
                                WHERE sync_rules.user_id = account.user_id
                                    AND sync_rules.state = :enabled
                                    AND account.id IN (
                                        sync_rules.source_account_id,
                                        sync_rules.destination_account_id
                                    )
                            )
                        ))
                    )
                )
            )
            ORDER BY users.id
            """,
            {
                "degraded": SyncRuleState.DEGRADED.value,
                "enabled": SyncRuleState.ENABLED.value,
                "connected": ConnectedAccountState.CONNECTED.value,
            },
        ).fetchall()
        return tuple(UserId(str(row[0])) for row in rows)

    def forget_change_values(self, before: datetime) -> None:
        assert self._connection is not None
        self._connection.execute(
            """
            UPDATE audit_entries SET change_sealed = NULL
            WHERE change_sealed IS NOT NULL AND occurred_at < ?
            """,
            (before.isoformat(),),
        )

    def resource_use(self, users: Collection[UserId], since: date) -> dict[UserId, ResourceUse]:
        assert self._connection is not None
        use: dict[UserId, ResourceUse] = {}
        ordered = sorted({user.value for user in users})
        for start in range(0, len(ordered), _USERS_PER_QUERY):
            chunk = ordered[start : start + _USERS_PER_QUERY]
            use |= _resource_use(self._connection, chunk, since)
        return use

    def forget_provider_calls(self, before: date) -> None:
        assert self._connection is not None
        self._connection.execute("DELETE FROM provider_calls WHERE day < ?", (before.isoformat(),))

    def failure_causes(self, since: datetime) -> list[CauseSighting]:
        assert self._connection is not None
        # A lapsed account's Incident is joined to the account, whose last authorization time
        # tells how long its grant lived; only that time is read, never who the account is.
        rows = self._connection.execute(
            """
            SELECT user_id, failure_cause AS cause, completed_at AS at, 0 AS open,
                NULL AS opened_at, NULL AS authorized_at, failure_provider AS provider
            FROM rule_run_outcomes
            WHERE succeeded = 0 AND failure_cause IS NOT NULL AND failure_cause != 'none'
                AND completed_at >= ?
                AND failure_kind NOT IN ('infrastructure', 'conflict')
            UNION ALL
            SELECT incident.user_id, incident.cause, incident.updated_at,
                incident.state = 'open', incident.opened_at, account.updated_at,
                incident.provider
            FROM incidents incident
            LEFT JOIN connected_accounts account
                ON incident.rule_id IS NULL
                AND account.id = incident.account_id
                AND account.user_id = incident.user_id
                AND account.state = 'connected'
                AND account.authorization_lapsed_at IS NOT NULL
            WHERE incident.cause IS NOT NULL AND incident.cause != 'none'
                AND incident.category NOT IN ('infrastructure', 'conflict')
                AND (incident.state = 'open' OR incident.updated_at >= ?)
            ORDER BY user_id, at
            """,
            (since.isoformat(), since.isoformat()),
        ).fetchall()
        return [_cause_sighting(row) for row in rows]

    def status_records(self, users: Collection[UserId]) -> dict[UserId, StatusRecords]:
        assert self._connection is not None
        records: dict[UserId, StatusRecords] = {}
        ordered = sorted({user.value for user in users})
        for start in range(0, len(ordered), _USERS_PER_QUERY):
            chunk = ordered[start : start + _USERS_PER_QUERY]
            rules = _recorded_rules(self._connection, chunk)
            for user, operations in operations_of(self._connection, chunk).items():
                records[UserId(user)] = StatusRecords(
                    rules=tuple(rules.get(user, ())),
                    overview=operations.overview,
                    incidents=operations.incidents,
                )
        return records

    def instant_sync_owners(self) -> Sequence[InstantSyncOwner]:
        assert self._connection is not None
        due = _upkeep_due(self._connection)
        rows = self._connection.execute(
            """
            SELECT id, state, instant_sync FROM users
            WHERE EXISTS (
                SELECT 1 FROM sync_rules
                WHERE sync_rules.user_id = users.id AND sync_rules.state = ?
            ) OR EXISTS (
                SELECT 1 FROM calendar_watches WHERE calendar_watches.user_id = users.id
            )
            ORDER BY id
            """,
            (SyncRuleState.ENABLED.value,),
        ).fetchall()
        return tuple(
            InstantSyncOwner(
                UserId(str(row["id"])),
                wanted=bool(row["instant_sync"]),
                disabled=row["state"] == UserState.DISABLED.value,
                next_due=due.get(str(row["id"])),
            )
            for row in rows
        )

    def pending_instant_runs(self) -> Sequence[PendingInstantRun]:
        assert self._connection is not None
        rows = self._connection.execute(
            """
            SELECT sync_rules.*, outcome.last_full_succeeded_at,
                outcome.succeeded AS last_succeeded, request.rule_id, request.requested_seq,
                request.handled_seq, request.first_requested_at, request.last_requested_at,
                request.last_run_at
            FROM instant_sync_requests request
            JOIN sync_rules
                ON sync_rules.id = request.rule_id AND sync_rules.user_id = request.user_id
            JOIN users ON users.id = sync_rules.user_id AND users.state = 'active'
            LEFT JOIN rule_run_outcomes outcome
                ON outcome.rule_id = sync_rules.id AND outcome.kind = 'sync'
            WHERE sync_rules.state = ? AND request.requested_seq > request.handled_seq
            ORDER BY sync_rules.user_id, sync_rules.id
            """,
            (SyncRuleState.ENABLED.value,),
        ).fetchall()
        return tuple(
            PendingInstantRun(
                ScheduledRule(
                    UserId(str(row["user_id"])),
                    rule_from_row(row),
                    optional_time(row["last_full_succeeded_at"]),
                ),
                request_from_row(row),
                last_run_failed=row["last_succeeded"] == 0,
            )
            for row in rows
        )


_USERS_PER_QUERY = 500
"""Users read together, well under SQLite's limit on bound values in one statement."""


def _upkeep_due(connection: sqlite3.Connection) -> dict[str, datetime | None]:
    """When upkeep next has work for each User with a watch."""
    watches: dict[str, list[CalendarWatch]] = {}
    for row in connection.execute("SELECT * FROM calendar_watches"):
        watches.setdefault(str(row["user_id"]), []).append(watch_from_row(row))
    registrations: dict[str, list[WatchRegistration]] = {}
    for row in connection.execute("SELECT * FROM watch_registrations"):
        registrations.setdefault(str(row["user_id"]), []).append(registration_from_row(row))
    return {user: upkeep_due(kept, registrations.get(user, ())) for user, kept in watches.items()}


def _resource_use(
    connection: sqlite3.Connection, users: Sequence[str], since: date
) -> dict[UserId, ResourceUse]:
    marks = ", ".join("?" * len(users))

    def counted(table: str) -> dict[str, int]:
        # Interpolates only constant table names and `?` placeholders; values stay bound.
        return dict(
            connection.execute(
                f"""
                SELECT user_id, COUNT(*) FROM {table}
                WHERE user_id IN ({marks}) GROUP BY user_id
                """,  # noqa: S608
                users,
            ).fetchall()
        )

    rules, accounts, entries = (
        counted("sync_rules"),
        counted("connected_accounts"),
        counted("audit_entries"),
    )
    calls: dict[str, list[ProviderCallUse]] = {}
    for row in connection.execute(
        f"""
        SELECT user_id, provider, SUM(calls), SUM(rate_limited), SUM(failed)
        FROM provider_calls WHERE user_id IN ({marks}) AND day >= ?
        GROUP BY user_id, provider ORDER BY user_id, provider
        """,  # noqa: S608
        (*users, since.isoformat()),
    ):
        calls.setdefault(str(row[0]), []).append(
            ProviderCallUse(ProviderKind(str(row[1])), int(row[2]), int(row[3]), int(row[4]))
        )
    return {
        UserId(user): ResourceUse(
            rules=rules.get(user, 0),
            connected_accounts=accounts.get(user, 0),
            activity_entries=entries.get(user, 0),
            provider_calls=tuple(calls.get(user, ())),
        )
        for user in users
    }


def _recorded_rules(
    connection: sqlite3.Connection, users: Sequence[str]
) -> dict[str, list[RecordedRule]]:
    """Each of `users`' rules in the order they were created, with what status reads of them."""
    marks = ", ".join("?" * len(users))
    # Interpolates only `?` placeholders; values stay bound.
    outcomes = {
        str(row["rule_id"]): outcome_from_row(row)
        for row in connection.execute(
            f"SELECT * FROM rule_run_outcomes WHERE kind = 'sync' AND user_id IN ({marks})",  # noqa: S608
            users,
        )
    }
    previews = {
        str(row["rule_id"]): preview_from_row(row)
        for row in connection.execute(
            f"SELECT * FROM rule_previews WHERE user_id IN ({marks})",  # noqa: S608
            users,
        )
    }
    rules: dict[str, list[RecordedRule]] = {}
    for row in connection.execute(
        f"""
        SELECT * FROM sync_rules WHERE user_id IN ({marks})
        ORDER BY user_id, creation_order, id
        """,  # noqa: S608
        users,
    ):
        rule_id = str(row["id"])
        rules.setdefault(str(row["user_id"]), []).append(
            RecordedRule(rule_from_row(row), outcomes.get(rule_id), previews.get(rule_id))
        )
    return rules


@dataclass(frozen=True, slots=True)
class SqliteInstallationUnitOfWorkFactory:
    database_path: Path

    def __call__(self) -> InstallationUnitOfWork:
        return SqliteInstallationUnitOfWork(self.database_path)
