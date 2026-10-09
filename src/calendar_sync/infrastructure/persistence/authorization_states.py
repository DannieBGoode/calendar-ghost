from __future__ import annotations

import hashlib
from datetime import timedelta
from pathlib import Path

from calendar_sync.application.ports import Clock
from calendar_sync.domain.access import UserId
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.scheduling import SystemClock

STATE_LIFETIME = timedelta(minutes=10)


class SqliteAuthorizationStates:
    """Single-use OAuth states, stored only as hashes, that protect the authorization callback."""

    def __init__(self, database_path: Path, clock: Clock | None = None) -> None:
        self._database_path = database_path
        self._clock = clock or SystemClock()

    def store(self, state: str, owner: UserId) -> None:
        """Remember a state for the User who began the flow; the callback connects for them."""
        now = self._clock.now()
        with transaction(self._database_path) as connection:
            connection.execute(
                """
                INSERT INTO oauth_states(state_hash, user_id, created_at, expires_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    _state_hash(state),
                    owner.value,
                    now.isoformat(),
                    (now + STATE_LIFETIME).isoformat(),
                ),
            )

    def consume(self, state: str) -> UserId | None:
        """Use a state once: the User who began its flow; None when it is missing, expired, or
        already used."""
        now = self._clock.now().isoformat()
        with transaction(self._database_path) as connection:
            row = connection.execute(
                """
                UPDATE oauth_states SET consumed_at = ?
                WHERE state_hash = ? AND consumed_at IS NULL AND expires_at > ?
                RETURNING user_id
                """,
                (now, _state_hash(state), now),
            ).fetchone()
        return UserId(str(row[0])) if row is not None else None


def _state_hash(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()
