"""A User's Plan grace and monotonic admission counter, in the caller's transaction."""

import sqlite3
from datetime import UTC, datetime

from calendar_sync.application.sync.errors import MissingReference
from calendar_sync.domain.access import UserId
from calendar_sync.domain.plan_hold import PlanGrace


class SqlitePlanGraceRecord:
    def __init__(self, connection: sqlite3.Connection, user: UserId) -> None:
        self._connection = connection
        self._user = user.value

    def acquire(self) -> None:
        cursor = self._connection.execute(
            "UPDATE users SET plan_admissions = plan_admissions WHERE id = ?", (self._user,)
        )
        self._require_user(cursor)

    def get(self) -> PlanGrace | None:
        row = self._connection.execute(
            "SELECT plan_holds_at, plan_grace_limit, plan_grace_admissions FROM users WHERE id = ?",
            (self._user,),
        ).fetchone()
        if row is None or row["plan_holds_at"] is None:
            return None
        return PlanGrace(
            datetime.fromisoformat(row["plan_holds_at"]),
            int(row["plan_grace_limit"]),
            int(row["plan_grace_admissions"]),
        )

    def save(self, grace: PlanGrace | None) -> None:
        values = (
            (grace.holds_at.astimezone(UTC).isoformat(), grace.rule_limit, grace.admissions)
            if grace is not None
            else (None, None, None)
        )
        cursor = self._connection.execute(
            "UPDATE users SET plan_holds_at = ?, plan_grace_limit = ?, plan_grace_admissions = ? "
            "WHERE id = ?",
            (*values, self._user),
        )
        self._require_user(cursor)

    def admissions(self) -> int:
        row = self._connection.execute(
            "SELECT plan_admissions FROM users WHERE id = ?", (self._user,)
        ).fetchone()
        if row is None:
            raise MissingReference("the Plan grace's User does not exist")
        return int(row["plan_admissions"])

    def admit(self, count: int = 1) -> None:
        cursor = self._connection.execute(
            "UPDATE users SET plan_admissions = plan_admissions + ? WHERE id = ?",
            (count, self._user),
        )
        self._require_user(cursor)

    @staticmethod
    def _require_user(cursor: sqlite3.Cursor) -> None:
        if cursor.rowcount != 1:
            raise MissingReference("the Plan grace's User does not exist")
