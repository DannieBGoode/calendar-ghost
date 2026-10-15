"""The checks every new Directional Sync Rule passes, inside the unit of work that adds it."""

from __future__ import annotations

from calendar_sync.application.sync.errors import (
    ConnectedAccountRequired,
    DuplicateDirectionalRelationship,
)
from calendar_sync.application.sync.ports import UnitOfWork
from calendar_sync.domain.model import SyncRule


def insert_rule(uow: UnitOfWork, rule: SyncRule) -> None:
    """Add a new rule inside an open unit of work, with the checks every new rule passes:
    raises DuplicateDirectionalRelationship before the insert, and ConnectedAccountRequired
    after it (the insert holds the write lock); the caller's unit then rolls back."""
    if uow.rules.relationship_exists(rule.source, rule.destination):
        raise DuplicateDirectionalRelationship(
            "a rule already exists for this source and destination"
        )
    uow.rules.add(rule)
    # Checked after the insert holds the write lock, so an account deleted meanwhile cannot be
    # left with a rule that names it. Raising rolls the insert back with the caller's unit.
    for endpoint in (rule.source, rule.destination):
        if uow.accounts.state(endpoint.connected_account_id) is None:
            raise ConnectedAccountRequired("connect both accounts before creating a rule")
