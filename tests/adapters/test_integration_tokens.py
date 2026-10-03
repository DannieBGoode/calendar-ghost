from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from calendar_sync.application.errors import InvalidIntegrationTokenName
from calendar_sync.application.ports import IntegrationTokenScope, IntegrationTokenSummary
from calendar_sync.infrastructure.identifiers import UuidIdGenerator
from calendar_sync.infrastructure.integration_tokens import SqliteIntegrationTokens
from calendar_sync.infrastructure.persistence.sqlite import initialize_database
from calendar_sync.infrastructure.security import token_hash

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
    return SqliteIntegrationTokens(database, clock, UuidIdGenerator()), clock, database


def test_an_issued_token_authenticates_and_only_its_hash_is_stored(tmp_path: Path) -> None:
    tokens, _, database = _tokens(tmp_path)

    issued = tokens.issue("  Uptime Kuma ")

    assert issued.token.startswith("cgs_")
    assert len(issued.token) == 47
    assert issued.summary.name == "Uptime Kuma"
    assert issued.summary.scope is IntegrationTokenScope.STATUS_READ
    # The first use records itself, so last_used_at is the moment of that use.
    assert tokens.authenticate(issued.token) == IntegrationTokenSummary(
        issued.summary.id, "Uptime Kuma", IntegrationTokenScope.STATUS_READ, ISSUED, ISSUED, None
    )
    with sqlite3.connect(database) as connection:
        stored = connection.execute("SELECT * FROM integration_tokens").fetchall()
    assert issued.token not in repr(stored)
    assert token_hash(issued.token) in repr(stored)


def test_unknown_malformed_and_revoked_tokens_are_refused(tmp_path: Path) -> None:
    tokens, _, _ = _tokens(tmp_path)
    issued = tokens.issue("Claude Code")

    assert tokens.authenticate("cgs_" + "A" * 43) is None
    assert tokens.authenticate(issued.token + "x") is None
    assert tokens.authenticate(issued.token[:-1]) is None
    assert tokens.revoke(issued.summary.id) is True
    assert tokens.revoke(issued.summary.id) is False
    assert tokens.revoke("missing") is False
    assert tokens.authenticate(issued.token) is None


def test_use_is_recorded_at_most_every_five_minutes(tmp_path: Path) -> None:
    tokens, clock, _ = _tokens(tmp_path)
    issued = tokens.issue("Homepage")

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


def test_tokens_are_listed_newest_first_with_revoked_ones_last(tmp_path: Path) -> None:
    tokens, clock, _ = _tokens(tmp_path)
    first = tokens.issue("First")
    clock.moment = ISSUED + timedelta(minutes=1)
    second = tokens.issue("Second")
    clock.moment = ISSUED + timedelta(minutes=2)
    third = tokens.issue("Third")
    tokens.revoke(third.summary.id)

    assert [token.name for token in tokens.list()] == ["Second", "First", "Third"]
    assert tokens.list()[2].revoked_at == ISSUED + timedelta(minutes=2)
    assert first.summary.last_used_at is None
    assert second.summary.last_used_at is None


def test_invalid_names_are_refused_before_anything_is_stored(tmp_path: Path) -> None:
    tokens, _, _ = _tokens(tmp_path)
    with pytest.raises(InvalidIntegrationTokenName):
        tokens.issue("Kuma\nadmin")
    assert tokens.list() == []


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
