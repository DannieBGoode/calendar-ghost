"""Plans, the Plans setting, and each User's own Plan (ADR 0038)."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Collection, Mapping, Sequence
from datetime import datetime
from pathlib import Path

from calendar_sync.application.identity.errors import PlanKeyTaken, PlanNotFound
from calendar_sync.application.identity.ports import AssignmentChange, PlanListing, PlansSetting
from calendar_sync.domain.access import Role, UserId
from calendar_sync.domain.plans import (
    NO_LIMITS_PLAN,
    UNLIMITED,
    Allowance,
    InvalidPlan,
    NewPlan,
    Plan,
    PlanInUse,
    PlanKey,
    PlanLimits,
    SyncInterval,
    allowance_for,
    needs_no_limits_plan,
    require_removable,
    require_unique_name,
)
from calendar_sync.infrastructure.persistence.connections import USERS_PER_QUERY, transaction

logger = logging.getLogger(__name__)


class SqlitePlans:
    """Plans, the Plans setting, and each User's own Plan (ADR 0038). Implements Allowances,
    PlanCatalog, and PlanAssignments; each client depends only on the port it uses.

    Reads never catch a database error: a limit check fails closed on it, and every other caller
    decides to fail open. Writes hold the write lock from their first read, so a limit check that
    already holds it either sees the change or makes it wait.
    """

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path

    # Allowances

    def of(self, user: UserId) -> Allowance:
        return self.of_users([user])[user]

    def of_users(self, users: Collection[UserId]) -> Mapping[UserId, Allowance]:
        allowances = dict.fromkeys(users, UNLIMITED)
        ordered = sorted({user.value for user in users})
        with transaction(self._database_path) as connection:
            for start in range(0, len(ordered), USERS_PER_QUERY):
                for row in _allowance_rows(connection, ordered[start : start + USERS_PER_QUERY]):
                    allowances[UserId(str(row["id"]))] = _allowance(row)
        return allowances

    # PlanCatalog

    def settings(self) -> PlansSetting:
        with transaction(self._database_path) as connection:
            return _setting(connection)

    def change_settings(self, enabled: bool, default: PlanKey | None, at: datetime) -> PlansSetting:
        with transaction(self._database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            if default is not None:
                _require_plan(connection, default)
            if needs_no_limits_plan(enabled, default, _setting(connection).default):
                # Made in this transaction, so it exists only if the setting is saved.
                made = NO_LIMITS_PLAN.named_apart(_names(connection).values())
                default = _insert(connection, made, at).key
            # Migration 22 creates the one row.
            connection.execute(
                """
                UPDATE installation_settings SET plans_enabled = ?, default_plan_key = ?
                WHERE singleton = 1
                """,
                (int(enabled), default.value if default is not None else None),
            )
            return _setting(connection)

    def plans(self) -> Sequence[PlanListing]:
        with transaction(self._database_path) as connection:
            rows = connection.execute(
                """
                SELECT plans.*, plans.key IS setting.default_plan_key AS is_default,
                    COUNT(holder.id) AS people,
                    COUNT(CASE WHEN holder.role = 'user' AND holder.state = 'active'
                        THEN holder.id END) AS limited_people
                FROM plans
                LEFT JOIN installation_settings setting ON setting.singleton = 1
                LEFT JOIN users holder ON holder.plan_key = plans.key
                    OR (holder.plan_key IS NULL AND plans.key IS setting.default_plan_key)
                GROUP BY plans.key
                ORDER BY plans.name, plans.key
                """
            ).fetchall()
        listings = (_listing(row) for row in rows)
        return tuple(listing for listing in listings if listing is not None)

    def any_plans(self) -> bool:
        with transaction(self._database_path) as connection:
            return connection.execute("SELECT 1 FROM plans LIMIT 1").fetchone() is not None

    def get(self, key: PlanKey) -> Plan | None:
        with transaction(self._database_path) as connection:
            row = connection.execute("SELECT * FROM plans WHERE key = ?", (key.value,)).fetchone()
        return _plan(row) if row is not None else None

    def add(self, plan: NewPlan, at: datetime) -> Plan:
        with transaction(self._database_path) as connection:
            # Held from reading the keys to the insert, so no other Plan takes the key meanwhile.
            connection.execute("BEGIN IMMEDIATE")
            return _insert(connection, plan, at)

    def change(self, plan: Plan, at: datetime) -> None:
        with transaction(self._database_path) as connection:
            # Held from reading the names to the update, so no other Plan takes the name meanwhile.
            connection.execute("BEGIN IMMEDIATE")
            others = _names(connection)
            if others.pop(plan.key.value, None) is None:
                raise PlanNotFound(f"plan {plan.key.value} does not exist")
            require_unique_name(plan.name, others.values())
            connection.execute(
                """
                UPDATE plans SET name = ?, rule_limit = ?, account_limit = ?, token_limit = ?,
                    sync_interval = ?, updated_at = ?
                WHERE key = ?
                """,
                (*_plan_values(plan)[1:], at.isoformat(), plan.key.value),
            )

    def remove(self, key: PlanKey) -> None:
        with transaction(self._database_path) as connection:
            # Held from the counts to the delete, so nobody is given the Plan meanwhile.
            connection.execute("BEGIN IMMEDIATE")
            _require_plan(connection, key)
            people = int(
                connection.execute(
                    "SELECT COUNT(*) FROM users WHERE plan_key = ?", (key.value,)
                ).fetchone()[0]
            )
            require_removable(key, _setting(connection).default, people)
            try:
                connection.execute("DELETE FROM plans WHERE key = ?", (key.value,))
            except sqlite3.IntegrityError as error:
                # A reference this release cannot read, such as a default a later one wrote.
                raise PlanInUse(people) from error

    # PlanAssignments

    def assign(self, user: UserId, plan: PlanKey | None, change: AssignmentChange) -> bool:
        with transaction(self._database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            if plan is not None:
                _require_plan(connection, plan)
            assigned = connection.execute(
                """
                UPDATE users SET plan_key = ?, plan_assigned_by = ?, plan_assigner_id = ?,
                    plan_assigned_at = ?
                WHERE id = ?
                """,
                (
                    plan.value if plan is not None else None,
                    change.source.value,
                    change.actor.value if change.actor is not None else None,
                    change.at.isoformat(),
                    user.value,
                ),
            ).rowcount
        return assigned == 1


def _insert(connection: sqlite3.Connection, new: NewPlan, at: datetime) -> Plan:
    """Store `new` under the key it asks for, or under one made from its name that no Plan has;
    raises PlanNameTaken when another Plan reads as its name, and PlanKeyTaken when another Plan
    has the key it asks for."""
    names = _names(connection)
    require_unique_name(new.name, names.values())
    if new.key is not None and new.key.value in names:
        raise PlanKeyTaken(f"a plan with the key {new.key.value} already exists")
    plan = new.keyed(names)
    connection.execute(
        """
        INSERT INTO plans (
            key, name, rule_limit, account_limit, token_limit, sync_interval,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (*_plan_values(plan), at.isoformat(), at.isoformat()),
    )
    return plan


def _names(connection: sqlite3.Connection) -> dict[str, str]:
    """Every stored Plan's name by its key, including a Plan a later release wrote that this one
    cannot read, so neither its key nor its name is taken again."""
    return {
        str(row["key"]): str(row["name"])
        for row in connection.execute("SELECT key, name FROM plans")
    }


def _allowance_rows(connection: sqlite3.Connection, users: Sequence[str]) -> list[sqlite3.Row]:
    """Each of `users` with the setting, their own Plan, and the Default Plan, in one row."""
    marks = ", ".join("?" * len(users))
    # Interpolates only `?` placeholders; values stay bound.
    return connection.execute(
        f"""
        SELECT users.id, users.role, COALESCE(setting.plans_enabled, 0) AS plans_enabled,
            own.key AS own_key, own.name AS own_name, own.rule_limit AS own_rule_limit,
            own.account_limit AS own_account_limit, own.token_limit AS own_token_limit,
            own.sync_interval AS own_sync_interval,
            default_plan.key AS default_key, default_plan.name AS default_name,
            default_plan.rule_limit AS default_rule_limit,
            default_plan.account_limit AS default_account_limit,
            default_plan.token_limit AS default_token_limit,
            default_plan.sync_interval AS default_sync_interval
        FROM users
        LEFT JOIN installation_settings setting ON setting.singleton = 1
        LEFT JOIN plans own ON own.key = users.plan_key
        LEFT JOIN plans default_plan ON default_plan.key = setting.default_plan_key
        WHERE users.id IN ({marks})
        """,  # noqa: S608
        users,
    ).fetchall()


def _allowance(row: sqlite3.Row) -> Allowance:
    plans_on = bool(row["plans_enabled"])
    administers = row["role"] == Role.INSTALLATION_ADMINISTRATOR.value
    own, default = _plan(row, "own_"), _plan(row, "default_")
    if plans_on and not administers and own is None and default is None:
        # Plans are never on without a default, so this cannot happen; a fault never limits
        # anyone.
        logger.warning("Plans are on, but User %s has no Plan; nothing limits them", row["id"])
    return allowance_for(plans_on=plans_on, administers=administers, own=own, default=default)


def _setting(connection: sqlite3.Connection) -> PlansSetting:
    row = connection.execute(
        "SELECT plans_enabled, default_plan_key FROM installation_settings WHERE singleton = 1"
    ).fetchone()
    if row is None:
        return PlansSetting(enabled=False, default=None)
    return PlansSetting(bool(row["plans_enabled"]), _stored_key(row["default_plan_key"]))


def _require_plan(connection: sqlite3.Connection, key: PlanKey) -> None:
    if connection.execute("SELECT 1 FROM plans WHERE key = ?", (key.value,)).fetchone() is None:
        raise PlanNotFound(f"plan {key.value} does not exist")


def _listing(row: sqlite3.Row) -> PlanListing | None:
    plan = _plan(row)
    if plan is None:
        return None
    return PlanListing(
        plan, bool(row["is_default"]), int(row["people"]), int(row["limited_people"])
    )


def _plan(row: sqlite3.Row, prefix: str = "") -> Plan | None:
    """The Plan in `row`'s columns named with `prefix`. None when there is none, or when a later
    release stored it in a form this one cannot read, so a stored Plan never breaks a read."""
    key = row[f"{prefix}key"]
    if key is None:
        return None
    try:
        return Plan(
            PlanKey(str(key)),
            str(row[f"{prefix}name"]),
            PlanLimits(
                _count(row[f"{prefix}rule_limit"]),
                _count(row[f"{prefix}account_limit"]),
                _count(row[f"{prefix}token_limit"]),
                _interval(str(key), str(row[f"{prefix}sync_interval"])),
            ),
        )
    except InvalidPlan:
        logger.warning("Plan %s is stored in a form this release cannot read; it is left out", key)
        return None


def _stored_key(stored: str | None) -> PlanKey | None:
    if stored is None:
        return None
    try:
        return PlanKey(stored)
    except InvalidPlan:
        logger.warning(
            "Plan %s is stored in a form this release cannot read; it is left out", stored
        )
        return None


def _count(stored: int | None) -> int | None:
    """A stored limit; NULL is unlimited."""
    return None if stored is None else int(stored)


def _interval(key: str, stored: str) -> SyncInterval:
    try:
        return SyncInterval(stored)
    except ValueError:
        logger.warning(
            "Plan %s has a sync interval this release does not know; it syncs instantly", key
        )
        return SyncInterval.INSTANT


def _plan_values(plan: Plan) -> tuple[object, ...]:
    limits = plan.limits
    return (
        plan.key.value,
        plan.name,
        limits.rules,
        limits.connected_accounts,
        limits.integration_tokens,
        limits.sync_interval.value,
    )
