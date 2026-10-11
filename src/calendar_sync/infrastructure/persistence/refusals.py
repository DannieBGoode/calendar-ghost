"""SQLite's constraint failures as the refusals every unit of work raises.

A use case catches `RecordRefused` and its subclasses, never `sqlite3.IntegrityError`, so the
in-memory unit of work and SQLite refuse the same writes with the same errors.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from calendar_sync.application.sync.errors import (
    IdentityCollision,
    MissingReference,
    RecordRefused,
)

_REFUSALS: dict[str, type[RecordRefused]] = {
    "SQLITE_CONSTRAINT_PRIMARYKEY": IdentityCollision,
    "SQLITE_CONSTRAINT_UNIQUE": IdentityCollision,
    "SQLITE_CONSTRAINT_FOREIGNKEY": MissingReference,
}


def refusal(error: sqlite3.IntegrityError) -> RecordRefused | None:
    """The refusal a constraint failure stands for; None for one no write is refused for, such
    as a CHECK, which only a defect breaks."""
    refused = _REFUSALS.get(error.sqlite_errorname)
    return refused(str(error)) if refused is not None else None


@contextmanager
def refusals() -> Iterator[None]:
    """Raise a constraint failure inside the block as its refusal."""
    try:
        yield
    except sqlite3.IntegrityError as error:
        refused = refusal(error)
        if refused is None:
            raise
        raise refused from error
