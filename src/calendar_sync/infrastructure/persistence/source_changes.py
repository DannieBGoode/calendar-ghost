"""SQLite storage of Source Observations and Source Change values, sealed at rest (ADR 0017)."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, date, datetime
from typing import Any

from calendar_sync.domain.changes import SourceChange, SourceField, SourceObservation
from calendar_sync.domain.model import (
    AllDayRange,
    CalendarEndpoint,
    EventRef,
    EventTime,
    SyncRuleId,
    TimedInterval,
)
from calendar_sync.infrastructure.security import HistoryCipher


class SqliteSourceObservationRepository:
    """Without a History Cipher, nothing is observed, so no change is ever described."""

    def __init__(self, connection: sqlite3.Connection, history: HistoryCipher | None) -> None:
        self._connection = connection
        self._history = history

    def get(self, rule_id: SyncRuleId, source: EventRef) -> SourceObservation | None:
        if self._history is None:
            return None
        row = self._connection.execute(
            """
            SELECT revision, title, sealed FROM source_observations
            WHERE rule_id = ? AND source_account_id = ? AND source_calendar_id = ?
              AND source_event_id = ?
            """,
            _key(rule_id, source),
        ).fetchone()
        if row is None:
            return None
        opened = self._history.open(bytes(row["sealed"]), _observation_context(rule_id, source))
        # Details sealed under another master key are unknown; the next revision starts afresh.
        if opened is None:
            return None
        details = json.loads(opened)
        return SourceObservation(
            revision=str(row["revision"]),
            title=str(row["title"]),
            time=_time(details["time"]),
            description=details["description"],
            location=details["location"],
            recurrence=tuple(details["recurrence"]),
            guests=_optional_tuple(details["guests"]),
            conferencing=_optional_tuple(details["conferencing"]),
        )

    def save(
        self,
        rule_id: SyncRuleId,
        source: EventRef,
        observation: SourceObservation,
        observed_at: datetime,
    ) -> None:
        if self._history is None:
            return
        details = {
            "time": _time_json(observation.time),
            "description": observation.description,
            "location": observation.location,
            "recurrence": list(observation.recurrence),
            "guests": _optional_list(observation.guests),
            "conferencing": _optional_list(observation.conferencing),
        }
        sealed = self._history.seal(json.dumps(details), _observation_context(rule_id, source))
        self._connection.execute(
            """
            INSERT INTO source_observations (
                rule_id, source_account_id, source_calendar_id, source_event_id,
                revision, observed_at, title, recurring, ends, sealed
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(rule_id, source_account_id, source_calendar_id, source_event_id)
            DO UPDATE SET
                revision = excluded.revision,
                observed_at = excluded.observed_at,
                title = excluded.title,
                recurring = excluded.recurring,
                ends = excluded.ends,
                sealed = excluded.sealed
            """,
            (
                *_key(rule_id, source),
                observation.revision,
                observed_at.isoformat(),
                observation.title,
                int(bool(observation.recurrence)),
                _ends(observation.time),
                sealed,
            ),
        )

    def forget_stale(
        self, rule_id: SyncRuleId, source: CalendarEndpoint, ended_before: datetime
    ) -> None:
        # An all-day end is a date, which sorts before any instant of that day, so it is
        # forgotten once its exclusive end date is reached.
        self._connection.execute(
            """
            DELETE FROM source_observations
            WHERE rule_id = ? AND (
                source_account_id != ? OR source_calendar_id != ?
                OR (recurring = 0 AND ends < ?)
            )
            """,
            (
                rule_id.value,
                source.connected_account_id.value,
                source.calendar_id.value,
                ended_before.astimezone(UTC).isoformat(),
            ),
        )


def change_columns(
    history: HistoryCipher | None,
    rule_id: SyncRuleId,
    source_event_id: str | None,
    change: SourceChange | None,
) -> tuple[str | None, str | None, bytes | None]:
    """An Audit Entry's change columns: fields, previous title, and the sealed other values."""
    if change is None:
        return None, None, None
    fields = json.dumps([field.value for field in change.fields])
    title_before = change.before.title if SourceField.TITLE in change.fields else None
    values = {
        field.value: _field_values(field, change)
        for field in change.fields
        if field is not SourceField.TITLE
    }
    sealed = (
        history.seal(json.dumps(values), _change_context(rule_id.value, source_event_id))
        if history is not None and values
        else None
    )
    return fields, title_before, sealed


def open_change_values(history: HistoryCipher | None, row: sqlite3.Row) -> dict[str, Any] | None:
    """The sealed values of an entry's change, or None once forgotten or when they cannot open."""
    sealed = row["change_sealed"]
    if history is None or sealed is None:
        return None
    opened = history.open(
        bytes(sealed), _change_context(str(row["rule_id"]), row["source_event_id"])
    )
    if opened is None:
        return None
    values: dict[str, Any] = json.loads(opened)
    return values


def _field_values(field: SourceField, change: SourceChange) -> dict[str, Any]:
    before, after = change.before, change.after
    if field is SourceField.TIME:
        return {"before": _time_json(before.time), "after": _time_json(after.time)}
    if field is SourceField.GUESTS:
        was, now = set(before.guests or ()), set(after.guests or ())
        return {"added": sorted(now - was), "removed": sorted(was - now)}
    if field in {SourceField.RECURRENCE, SourceField.CONFERENCING}:
        return {
            "before": list(getattr(before, field.value) or ()),
            "after": list(getattr(after, field.value) or ()),
        }
    return {"before": getattr(before, field.value), "after": getattr(after, field.value)}


def _key(rule_id: SyncRuleId, source: EventRef) -> tuple[str, str, str, str]:
    return (
        rule_id.value,
        source.calendar.connected_account_id.value,
        source.calendar.calendar_id.value,
        source.event_id.value,
    )


def _observation_context(rule_id: SyncRuleId, source: EventRef) -> str:
    return "observation|" + "|".join(_key(rule_id, source))


def _change_context(rule_id: str, source_event_id: str | None) -> str:
    return f"change|{rule_id}|{source_event_id or ''}"


def _time_json(time: EventTime) -> dict[str, Any]:
    if isinstance(time, TimedInterval):
        return {
            "all_day": False,
            "starts": time.starts_at.isoformat(),
            "ends": time.ends_at.isoformat(),
            "time_zone": time.time_zone,
        }
    return {
        "all_day": True,
        "starts": time.starts_on.isoformat(),
        "ends": time.ends_before.isoformat(),
    }


def _time(value: dict[str, Any]) -> EventTime:
    if value["all_day"]:
        return AllDayRange(date.fromisoformat(value["starts"]), date.fromisoformat(value["ends"]))
    return TimedInterval(
        datetime.fromisoformat(value["starts"]),
        datetime.fromisoformat(value["ends"]),
        value.get("time_zone"),
    )


def _ends(time: EventTime) -> str:
    if isinstance(time, TimedInterval):
        return time.ends_at.astimezone(UTC).isoformat()
    return time.ends_before.isoformat()


def _optional_list(values: tuple[str, ...] | None) -> list[str] | None:
    return None if values is None else list(values)


def _optional_tuple(values: list[str] | None) -> tuple[str, ...] | None:
    return None if values is None else tuple(values)
