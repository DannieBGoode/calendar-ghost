from __future__ import annotations

import sqlite3
from datetime import datetime

from calendar_sync.application.sync.errors import MissingReference
from calendar_sync.domain.model import SyncRuleId


def optional_time(value: object) -> datetime | None:
    return None if value is None else datetime.fromisoformat(str(value))


def _require_own(cursor: sqlite3.Cursor, rule_id: SyncRuleId) -> None:
    """Refuse a write an upsert skipped because the record it met, so its rule, is another
    User's."""
    if cursor.rowcount != 1:
        raise MissingReference(f"a record of rule {rule_id.value} is another User's")
