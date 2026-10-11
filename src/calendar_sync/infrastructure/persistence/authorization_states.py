from __future__ import annotations

import hashlib
from datetime import timedelta
from pathlib import Path

from calendar_sync.application.ports import Clock
from calendar_sync.application.providers import ProviderKind
from calendar_sync.domain.access import UserId
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.scheduling import SystemClock

STATE_LIFETIME = timedelta(minutes=10)


class SqliteAuthorizationStates:
    """Single-use OAuth states, stored only as hashes, that protect the authorization callback."""

    def __init__(self, database_path: Path, clock: Clock | None = None) -> None:
        self._database_path = database_path
        self._clock = clock or SystemClock()

    def store(self, state: str, owner: UserId, provider: ProviderKind) -> None:
        """Remember a state for the User who began a flow with `provider`; its callback connects
        for them."""
        now = self._clock.now()
        with transaction(self._database_path) as connection:
            connection.execute(
                """
                INSERT INTO oauth_states(state_hash, user_id, created_at, expires_at, provider)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    _state_hash(state),
                    owner.value,
                    now.isoformat(),
                    (now + STATE_LIFETIME).isoformat(),
                    provider.value,
                ),
            )

    def consume(self, state: str, provider: ProviderKind) -> UserId | None:
        """Use a state of a flow begun with `provider` once: the User who began it; None when it
        is missing, another provider's, expired, already used, or its User has been disabled
        since."""
        now = self._clock.now().isoformat()
        with transaction(self._database_path) as connection:
            row = connection.execute(
                """
                UPDATE oauth_states SET consumed_at = ?
                WHERE state_hash = ? AND provider = ? AND consumed_at IS NULL AND expires_at > ?
                    AND user_id IN (SELECT id FROM users WHERE state = 'active')
                RETURNING user_id
                """,
                (now, _state_hash(state), provider.value, now),
            ).fetchone()
        return UserId(str(row[0])) if row is not None else None


def _state_hash(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()
