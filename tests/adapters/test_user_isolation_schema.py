"""The schema and the code keep every User's records apart (ADR 0029)."""

import ast
import sqlite3
from pathlib import Path

from calendar_sync.infrastructure.persistence.sqlite import initialize_database

# Tables that hold no User's records: the migration ledger, and the Users themselves.
INSTALLATION_TABLES = {"schema_migrations", "users"}
SOURCE = Path(__file__).resolve().parents[2] / "src" / "calendar_sync"
# Only these may receive the installation-wide unit of work: the ports that declare it, the
# adapters that implement it and run migrations, the scheduler, and the composition root that
# hands it to the scheduler. The Operator Overview joins them when it is built.
INSTALLATION_UNIT_RECEIVERS = {
    "application/ports.py",
    "bootstrap/container.py",
    "infrastructure/persistence/memory.py",
    "infrastructure/persistence/sqlite.py",
    "infrastructure/scheduling.py",
}


def _owned_tables(connection: sqlite3.Connection) -> list[str]:
    return [
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
        if row[0] not in INSTALLATION_TABLES
    ]


def _references(connection: sqlite3.Connection, table: str) -> dict[str, dict[str, str]]:
    """Each foreign key of `table`: the table it refers to, and column pairs, local to remote."""
    references: dict[int, tuple[str, dict[str, str]]] = {}
    for row in connection.execute(f"PRAGMA foreign_key_list({table})"):
        key, parent, local, remote = int(row[0]), str(row[2]), str(row[3]), str(row[4])
        references.setdefault(key, (parent, {}))[1][local] = remote
    return dict(references.values())


def test_every_owned_table_carries_its_user_and_a_reference_through_it(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)

    with sqlite3.connect(database) as connection:
        tables = _owned_tables(connection)
        assert len(tables) >= 15
        for table in tables:
            columns = {
                str(row[1]): bool(row[3])
                for row in connection.execute(f"PRAGMA table_info({table})")
            }
            assert columns.get("user_id") is True, f"{table}.user_id must be NOT NULL"
            references = _references(connection, table)
            # A root refers to its User; a child to its parent by identifier and User together.
            assert any(
                pairs.get("user_id") == ("id" if parent == "users" else "user_id")
                for parent, pairs in references.items()
            ), f"{table} has no reference through its User"
            for parent, pairs in references.items():
                if parent != "users":
                    assert pairs.get("user_id") == "user_id", (
                        f"{table} refers to {parent} without its User"
                    )


def test_only_the_scheduler_and_migrations_receive_the_installation_unit_of_work() -> None:
    receivers = set()
    for module in SOURCE.rglob("*.py"):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        names = {
            name
            for node in ast.walk(tree)
            for name in (
                [node.id]
                if isinstance(node, ast.Name)
                else [node.attr]
                if isinstance(node, ast.Attribute)
                else [alias.name for alias in node.names]
                if isinstance(node, ast.ImportFrom)
                else []
            )
        }
        if {"InstallationUnitOfWork", "InstallationUnitOfWorkFactory"} & names:
            receivers.add(module.relative_to(SOURCE).as_posix())

    assert receivers <= INSTALLATION_UNIT_RECEIVERS, receivers - INSTALLATION_UNIT_RECEIVERS
    assert "infrastructure/scheduling.py" in receivers
