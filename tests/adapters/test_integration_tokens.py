from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path

import pytest

from calendar_sync.application.errors import InvalidIntegrationTokenName
from calendar_sync.application.ports import IntegrationTokenScope, IntegrationTokenSummary
from calendar_sync.infrastructure.identifiers import UuidIdGenerator
from calendar_sync.infrastructure.integration_tokens import SqliteIntegrationTokens
from calendar_sync.infrastructure.persistence.sqlite import initialize_database
from calendar_sync.infrastructure.security import token_hash
from tests.users import USER, add_user

ISSUED = datetime(2026, 10, 3, 9, 0, tzinfo=UTC)


@dataclass
class MovableClock:
    moment: datetime

    def now(self) -> datetime:
        return self.moment


def _tokens(tmp_path: Path) -> tuple[SqliteIntegrationTokens, MovableClock, Path]:
    database = tmp_path / "test.db"
    initialize_database(database)
    clock = MovableClock(ISSUED)
    add_user(database)
    return SqliteIntegrationTokens(database, clock, UuidIdGenerator()), clock, database


def test_an_issued_token_authenticates_and_only_its_hash_is_stored(tmp_path: Path) -> None:
    tokens, _, database = _tokens(tmp_path)

    issued = tokens.for_user(USER).issue("  Uptime Kuma ")

    assert issued.token.startswith("cgs_")
    assert len(issued.token) == 47
    assert issued.summary.name == "Uptime Kuma"
    assert issued.summary.scopes == frozenset({IntegrationTokenScope.STATUS_READ})
    # The first use records itself, so last_used_at is the moment of that use.
    assert tokens.authenticate(issued.token) == IntegrationTokenSummary(
        issued.summary.id,
        "Uptime Kuma",
        frozenset({IntegrationTokenScope.STATUS_READ}),
        ISSUED,
        ISSUED,
        None,
        owner=USER,
    )
    with sqlite3.connect(database) as connection:
        stored = connection.execute("SELECT * FROM integration_tokens").fetchall()
    assert issued.token not in repr(stored)
    assert token_hash(issued.token) in repr(stored)


def test_an_issued_token_never_shows_the_token_in_its_repr(tmp_path: Path) -> None:
    tokens, _, _ = _tokens(tmp_path)
    issued = tokens.for_user(USER).issue("Uptime Kuma")

    assert issued.token not in repr(issued)
    assert issued.summary.id in repr(issued)


def test_unknown_malformed_and_revoked_tokens_are_refused(tmp_path: Path) -> None:
    tokens, _, _ = _tokens(tmp_path)
    issued = tokens.for_user(USER).issue("Claude Code")

    assert tokens.authenticate("cgs_" + "A" * 43) is None
    assert tokens.authenticate(issued.token + "x") is None
    assert tokens.authenticate(issued.token[:-1]) is None
    assert tokens.for_user(USER).revoke(issued.summary.id) is True
    assert tokens.for_user(USER).revoke(issued.summary.id) is False
    assert tokens.for_user(USER).revoke("missing") is False
    assert tokens.authenticate(issued.token) is None


def test_use_is_recorded_at_most_every_five_minutes(tmp_path: Path) -> None:
    tokens, clock, _ = _tokens(tmp_path)
    issued = tokens.for_user(USER).issue("Homepage")

    clock.moment = ISSUED + timedelta(minutes=1)
    tokens.authenticate(issued.token)
    clock.moment = ISSUED + timedelta(minutes=4)
    first = tokens.authenticate(issued.token)
    assert first is not None
    assert first.last_used_at == ISSUED + timedelta(minutes=1)
    clock.moment = ISSUED + timedelta(minutes=6)
    second = tokens.authenticate(issued.token)
    assert second is not None
    assert second.last_used_at == ISSUED + timedelta(minutes=6)


def test_a_busy_database_does_not_refuse_a_valid_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tokens, clock, database = _tokens(tmp_path)
    issued = tokens.for_user(USER).issue("Uptime Kuma")
    clock.moment = ISSUED + timedelta(minutes=10)
    # Another connection holds the write lock, and this one gives up at once instead of waiting.
    holder = sqlite3.connect(database, isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    monkeypatch.setattr(sqlite3, "connect", partial(sqlite3.connect, timeout=0))
    try:
        busy = tokens.authenticate(issued.token)
    finally:
        holder.execute("ROLLBACK")
        holder.close()

    # Recording the use is best effort; the token is valid, so the request is allowed.
    assert busy == issued.summary
    used = tokens.authenticate(issued.token)
    assert used is not None
    assert used.last_used_at == ISSUED + timedelta(minutes=10)


def test_tokens_are_listed_newest_first_with_revoked_ones_last(tmp_path: Path) -> None:
    tokens, clock, _ = _tokens(tmp_path)
    first = tokens.for_user(USER).issue("First")
    clock.moment = ISSUED + timedelta(minutes=1)
    second = tokens.for_user(USER).issue("Second")
    clock.moment = ISSUED + timedelta(minutes=2)
    third = tokens.for_user(USER).issue("Third")
    tokens.for_user(USER).revoke(third.summary.id)

    assert [token.name for token in tokens.for_user(USER).list()] == ["Second", "First", "Third"]
    assert tokens.for_user(USER).list()[2].revoked_at == ISSUED + timedelta(minutes=2)
    assert first.summary.last_used_at is None
    assert second.summary.last_used_at is None


class _NamedIds:
    def __init__(self, *ids: str) -> None:
        self._ids = list(ids)

    def new(self) -> str:
        return self._ids.pop(0)


def test_tokens_issued_at_the_same_moment_are_listed_in_a_stable_order(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    initialize_database(database)
    add_user(database)
    tokens = SqliteIntegrationTokens(database, MovableClock(ISSUED), _NamedIds("id-b", "id-a"))
    tokens.for_user(USER).issue("Issued first")
    tokens.for_user(USER).issue("Issued second")

    assert [token.id for token in tokens.for_user(USER).list()] == ["id-a", "id-b"]


def test_invalid_names_are_refused_before_anything_is_stored(tmp_path: Path) -> None:
    tokens, _, _ = _tokens(tmp_path)
    with pytest.raises(InvalidIntegrationTokenName):
        tokens.for_user(USER).issue("Kuma\nadmin")
    assert tokens.for_user(USER).list() == []


def test_the_migration_applies_to_an_existing_database(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    initialize_database(database)
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TABLE integration_tokens")
        connection.execute("DELETE FROM schema_migrations WHERE version = 18")

    initialize_database(database)

    with sqlite3.connect(database) as connection:
        versions = [row[0] for row in connection.execute("SELECT version FROM schema_migrations")]
        indexes = connection.execute("PRAGMA index_list('integration_tokens')").fetchall()
    assert 18 in versions
    assert any(index[2] == 1 for index in indexes)


def test_a_token_may_also_read_installation_health(tmp_path: Path) -> None:
    tokens, _, _ = _tokens(tmp_path)
    both = frozenset({IntegrationTokenScope.STATUS_READ, IntegrationTokenScope.INSTALLATION_READ})

    issued = tokens.for_user(USER).issue("Uptime Kuma", both)

    summary = tokens.authenticate(issued.token)
    assert summary is not None
    assert summary.scopes == both
    assert tokens.for_user(USER).list()[0].scopes == both
