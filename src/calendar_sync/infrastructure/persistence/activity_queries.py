"""SQLite answers to the Activity questions of the Web API and rule health."""

from __future__ import annotations

import json
import sqlite3
import unicodedata
from collections.abc import Iterator, Sequence
from contextlib import closing, contextmanager
from functools import lru_cache
from pathlib import Path

from calendar_sync.application.activity import (
    BLOCK_ACTIONS,
    LEGACY_SKIP_REASON,
    NO_CHANGE_REASONS,
    AccountStanding,
    ActivityEntry,
    ActivityEvent,
    ActivityFilter,
    EntryEvents,
    FieldChange,
    IncidentSummary,
    OpenBlock,
    OperationsOverview,
    RecentChange,
    RecordedChange,
    RecordedTime,
    activity_category,
)
from calendar_sync.application.ports import IncidentMessage
from calendar_sync.application.sync_run import UNRECORDED_REASONS
from calendar_sync.domain.model import SyncAction, SyncReason
from calendar_sync.infrastructure.persistence.connections import open_connection
from calendar_sync.infrastructure.persistence.source_changes import open_change_values
from calendar_sync.infrastructure.security import HistoryCipher

# A synchronization block. Recurring exclusions were recorded as conflicts before reason codes
# existed; they are skips.
_BLOCK = "{t}.action = 'conflict' AND COALESCE({t}.reason, '') != 'recurring_unsupported'"


def open_blocks(
    connection: sqlite3.Connection,
    *,
    rule_id: str | None = None,
    after: int | None = None,
    persisting: bool = False,
    run_id: str | None = None,
) -> list[tuple[int, str]]:
    """Entry and rule of each event whose latest decision was a block, newest first.

    Only blocks decided since each rule's latest daily pass count: that pass decides every blocked
    event again, so an older block it did not repeat, such as one of an occurrence whose series was
    deleted, is no longer open. That includes a block of an event that ended before the rule's sync
    window: the daily pass no longer lists it, and a past event no longer affects the destination
    calendar, so its block retires with it. `after` replaces the recorded pass with the audit
    identifier a pass began after, and `run_id` keeps only blocks that were that pass's own latest
    decision about their event, whatever other runs decided after it. A persisting
    block was already the event's latest decision before the pass began, so neither a failed
    attempt of the same pass nor a run interleaved with it counts as earlier evidence.
    """
    rules = (
        [rule_id]
        if rule_id is not None
        else [str(row[0]) for row in connection.execute("SELECT id FROM sync_rules")]
    )
    # With a named run, "latest" means that run's latest decision about the event, so a run
    # interleaved after it can neither hide nor supply the named run's verdict.
    same_run = "AND later.run_id = :run" if run_id is not None else ""
    # Rule Removal conflicts belong to a rule that no longer exists, so they are not blocks here.
    # Interpolates only constant SQL fragments and `?` placeholders; values stay bound.
    conditions = [
        "a.rule_id = :rule",
        "a.id > :floor",
        _BLOCK.format(t="a"),
        "a.source_event_id IS NOT NULL",
        f"""NOT EXISTS (
            SELECT 1 FROM audit_entries later
            WHERE later.rule_id = a.rule_id AND later.source_event_id = a.source_event_id
                AND later.id > a.id {same_run}
        )""",  # noqa: S608
    ]
    if run_id is not None:
        conditions.append("a.run_id = :run")
    if persisting:
        # Interpolates only constant SQL fragments and `?` placeholders; values stay bound.
        conditions.append(
            f"""(
                SELECT {_BLOCK.format(t="earlier")} FROM audit_entries earlier
                WHERE earlier.rule_id = a.rule_id AND earlier.source_event_id = a.source_event_id
                    AND earlier.id <= :floor
                ORDER BY earlier.id DESC LIMIT 1
            ) = 1"""  # noqa: S608
        )
    blocks: list[tuple[int, str]] = []
    for rule in rules:
        floor = after if after is not None else _checked_floor(connection, rule)
        blocks.extend(
            (int(row[0]), rule)
            # Interpolates only constant SQL fragments and `?` placeholders; values stay bound.
            for row in connection.execute(
                f"""
                SELECT a.id FROM audit_entries a INDEXED BY audit_entries_rule_id
                WHERE {" AND ".join(conditions)}
                """,  # noqa: S608
                {"rule": rule, "floor": floor, "run": run_id},
            )
        )
    return sorted(blocks, reverse=True)


def _checked_floor(connection: sqlite3.Connection, rule_id: str) -> int:
    row = connection.execute(
        "SELECT audit_floor FROM rule_block_checks WHERE rule_id = ?", (rule_id,)
    ).fetchone()
    return int(row[0]) if row else 0


def _sql_list(values: frozenset[str]) -> str:
    return ", ".join(f"'{value}'" for value in sorted(values))


# Mirrors `activity_category` case by case, so a category filter selects what the entry shows.
_CATEGORY_SQL = f"""(CASE
    WHEN reason = '{LEGACY_SKIP_REASON}' THEN 'skipped'
    WHEN action IN ({_sql_list(BLOCK_ACTIONS)}) THEN 'blocked'
    WHEN action = '{SyncAction.IGNORE.value}' THEN
        CASE WHEN reason IN ({_sql_list(NO_CHANGE_REASONS)}) THEN 'unchanged' ELSE 'skipped' END
    ELSE 'changed'
END)"""
# Earlier releases recorded these skips; Activity no longer lists them.
_UNRECORDED_SQL = _sql_list(frozenset(reason.value for reason in UNRECORDED_REASONS))

_WRITES = frozenset({"create", "update", "delete", "remove_projection"})
# Writes that put a destination event back to match its source.
_REPAIRS = frozenset(
    {
        SyncReason.PROJECTION_MISSING.value,
        SyncReason.DESTINATION_DRIFT_REPAIRED.value,
        SyncReason.OCCURRENCE_DRIFT_REPAIRED.value,
    }
)
# Recent changes read writes in pages until they find more distinct changes than requested, at
# most 10,000 writes; a repeated repair's count covers the writes read.
_RECENT_WRITE_PAGE_SIZE = 500
_RECENT_WRITE_PAGES = 20
_IDENTICAL_WRITE = (
    "rule_id",
    "source_event_id",
    "action",
    "reason",
    "event_title",
    "event_starts",
    "event_ends",
    "event_all_day",
    "event_recurring",
    "event_cancelled",
)

_ENTRY_COLUMNS = (
    "id, run_id, occurred_at, rule_id, action, outcome, reason, detail,"
    " source_event_id, destination_event_id,"
    " event_title, event_starts, event_ends, event_all_day, event_recurring, event_cancelled,"
    " change_fields"
)
# An entry observed its event's title unless Google reported a cancellation without one.
_TITLE_OBSERVED = "event_title IS NOT NULL AND (event_title <> '' OR NOT event_cancelled)"


class SqliteActivityQueries:
    def __init__(self, database_path: Path, history: HistoryCipher | None = None) -> None:
        self._database_path = database_path
        self._history = history

    def entries(self, selection: ActivityFilter) -> list[ActivityEntry]:
        conditions = [f"COALESCE(reason, '') NOT IN ({_UNRECORDED_SQL})"]
        parameters: list[object] = []
        search = selection.search.strip() if selection.search is not None else ""
        if search:
            conditions.append("search_fold(event_title) LIKE ? ESCAPE '\\'")
            parameters.append(f"%{_like_escape(_search_fold(search))}%")
        if selection.rule_id is not None:
            conditions.append("rule_id = ?")
            parameters.append(selection.rule_id)
        if selection.categories:
            chosen = sorted(selection.categories)
            conditions.append(f"{_CATEGORY_SQL} IN ({', '.join('?' for _ in chosen)})")
            parameters.extend(chosen)
        if selection.before is not None:
            conditions.append("id < ?")
            parameters.append(selection.before)
        with _reading(self._database_path) as connection:
            # Interpolates only constant SQL fragments and `?` placeholders; values stay bound.
            rows = connection.execute(
                f"""
                SELECT {_ENTRY_COLUMNS} FROM audit_entries
                WHERE {" AND ".join(conditions)} ORDER BY id DESC LIMIT ?
                """,  # noqa: S608
                (*parameters, selection.limit),
            ).fetchall()
            return _entries(connection, rows)

    def entry(self, entry_id: int) -> ActivityEntry | None:
        with _reading(self._database_path) as connection:
            # Interpolates only constant SQL fragments and `?` placeholders; values stay bound.
            row = connection.execute(
                f"SELECT {_ENTRY_COLUMNS} FROM audit_entries WHERE id = ?",  # noqa: S608
                (entry_id,),
            ).fetchone()
            return _entries(connection, [row])[0] if row is not None else None

    def entry_events(self, entry_id: int) -> EntryEvents | None:
        with _reading(self._database_path) as connection:
            row = connection.execute(
                """
                SELECT rule_id, source_event_id, destination_event_id
                FROM audit_entries WHERE id = ?
                """,
                (entry_id,),
            ).fetchone()
        if row is None:
            return None
        return EntryEvents(
            rule_id=str(row["rule_id"]),
            source_event_id=_text(row["source_event_id"]),
            destination_event_id=_text(row["destination_event_id"]),
        )

    def entry_change(self, entry_id: int) -> RecordedChange | None:
        with _reading(self._database_path) as connection:
            row = connection.execute(
                """
                SELECT rule_id, source_event_id, event_title,
                    change_fields, change_title_before, change_sealed
                FROM audit_entries WHERE id = ?
                """,
                (entry_id,),
            ).fetchone()
        if row is None or row["change_fields"] is None:
            return None
        fields = tuple(str(field) for field in json.loads(row["change_fields"]))
        values = open_change_values(self._history, row)
        changes = tuple(
            change for field in fields if (change := _field_change(field, row, values)) is not None
        )
        return RecordedChange(
            fields=fields,
            values_available=values is not None or fields == ("title",),
            changes=changes,
        )

    def recent_changes(self, limit: int) -> list[RecentChange]:
        # The newest written events. A repair identical to a newer one, the same repair of the
        # same event as recorded at the same time, is counted on it rather than listed again, so a
        # repair repeated on every run shows as one line.
        with _reading(self._database_path) as connection:
            chosen = _recent_write_groups(connection, limit)
            heads = _entries(connection, [group[0] for group in chosen])
        return [
            RecentChange(entry=head, repeats=len(group), first_occurred_at=group[-1]["occurred_at"])
            for head, group in zip(heads, chosen, strict=True)
        ]


class SqliteOperationsQueries:
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path

    def overview(self) -> OperationsOverview:
        with _reading(self._database_path) as connection:
            accounts = tuple(
                AccountStanding(
                    str(row["id"]),
                    str(row["state"]),
                    str(row["provider"]),
                    lapsed=row["state"] == "connected"
                    and row["authorization_lapsed_at"] is not None,
                )
                for row in connection.execute(
                    """
                    SELECT id, state, provider, authorization_lapsed_at
                    FROM connected_accounts ORDER BY id
                    """
                )
            )
            incidents = int(
                connection.execute(
                    "SELECT COUNT(*) FROM incidents WHERE state = 'open'"
                ).fetchone()[0]
            )
            last_synced_at = connection.execute(
                "SELECT MAX(last_succeeded_at) FROM rule_run_outcomes WHERE kind = 'sync'"
            ).fetchone()[0]
            blocks = open_blocks(connection)
        return OperationsOverview(
            connected_accounts=sum(account.state == "connected" for account in accounts),
            disconnected_accounts=sum(account.state == "disconnected" for account in accounts),
            open_incidents=incidents,
            last_synced_at=last_synced_at,
            open_blocks=tuple(OpenBlock(entry_id, rule_id) for entry_id, rule_id in blocks),
            accounts=accounts,
        )

    def incidents(self) -> list[IncidentSummary]:
        with _reading(self._database_path) as connection:
            rows = connection.execute(
                """
                SELECT id, rule_id, account_id, category, state, summary, opened_at,
                    updated_at, resolved_at, resolution, message_code, message_params
                FROM incidents ORDER BY state ASC, updated_at DESC LIMIT 100
                """
            ).fetchall()
        return [
            IncidentSummary(
                id=row["id"],
                rule_id=row["rule_id"],
                category=row["category"],
                state=row["state"],
                summary=row["summary"],
                opened_at=row["opened_at"],
                updated_at=row["updated_at"],
                resolved_at=row["resolved_at"],
                resolution=row["resolution"],
                account_id=row["account_id"],
                message=_incident_message(row["message_code"], row["message_params"]),
            )
            for row in rows
        ]


@contextmanager
def _reading(database_path: Path) -> Iterator[sqlite3.Connection]:
    """A connection for reads only, closed afterwards; it never takes a write lock."""
    with closing(open_connection(database_path)) as connection:
        connection.create_function("search_fold", 1, _search_fold_column, deterministic=True)
        yield connection


def _text(value: object) -> str | None:
    return None if value is None else str(value)


def _incident_message(code: str | None, params: str | None) -> IncidentMessage | None:
    """The stored message, or None when recorded before messages or with unreadable params."""
    if code is None:
        return None
    try:
        parsed = json.loads(params) if params else {}
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict) or not all(
        (isinstance(value, str | int) and not isinstance(value, bool)) or value is None
        for value in parsed.values()
    ):
        return None
    return IncidentMessage(code, parsed)


@lru_cache(maxsize=4096)
def _search_fold(text: str) -> str:
    """Text without case or accents, so "reunion" finds "Reunión". Repeated titles hit the cache."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char)).casefold()


def _search_fold_column(text: str | None) -> str | None:
    return None if text is None else _search_fold(text)


def _like_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _recent_write_groups(connection: sqlite3.Connection, limit: int) -> list[list[sqlite3.Row]]:
    """The newest `limit` distinct writes, each with the identical repairs it stands for."""
    groups: dict[tuple[object, ...], list[sqlite3.Row]] = {}
    # Page backwards until more distinct changes than requested are found, so a repair repeated
    # on every run never hides older changes; the scan stays bounded.
    before: int | None = None
    for _ in range(_RECENT_WRITE_PAGES):
        # Interpolates only constant SQL fragments and `?` placeholders; values stay bound.
        rows = connection.execute(
            f"""
            SELECT {_ENTRY_COLUMNS} FROM audit_entries
            WHERE action IN ({_sql_list(_WRITES)}) AND source_event_id IS NOT NULL
                {"AND id < ?" if before is not None else ""}
            ORDER BY id DESC LIMIT ?
            """,  # noqa: S608
            (*([before] if before is not None else []), _RECENT_WRITE_PAGE_SIZE),
        ).fetchall()
        for row in rows:
            # Only repairs collapse; any other write is a change of its own.
            key = (
                tuple(row[column] for column in _IDENTICAL_WRITE)
                if row["reason"] in _REPAIRS
                else (row["id"],)
            )
            groups.setdefault(key, []).append(row)
        if len(rows) < _RECENT_WRITE_PAGE_SIZE or len(groups) > limit:
            break
        before = int(rows[-1]["id"])
    return list(groups.values())[:limit]


def _entries(connection: sqlite3.Connection, rows: Sequence[sqlite3.Row]) -> list[ActivityEntry]:
    """Entries with the event each names, falling back to the event's previous recorded name."""
    ids = [row["id"] for row in rows if row["source_event_id"] is not None]
    previous = _previous_names(connection, ids)
    # Only repairs can be told to repeat: a source change that kept the recorded title and time,
    # such as a new location, is a change of its own that the summary cannot distinguish.
    repeated = _repeated_repairs(
        connection, [row["id"] for row in rows if row["id"] in ids and row["reason"] in _REPAIRS]
    )
    return [
        ActivityEntry(
            id=row["id"],
            run_id=row["run_id"],
            occurred_at=row["occurred_at"],
            rule_id=row["rule_id"],
            action=row["action"],
            outcome=row["outcome"],
            category=activity_category(row["action"], row["reason"]),
            reason=row["reason"],
            detail=row["detail"],
            source_event_id=row["source_event_id"],
            destination_event_id=row["destination_event_id"],
            event=_recorded_event(row, previous.get(row["id"])),
            repeated=row["id"] in repeated,
            changed_fields=(
                tuple(json.loads(row["change_fields"]))
                if row["change_fields"] is not None
                else None
            ),
        )
        for row in rows
    ]


def _field_change(
    field: str, row: sqlite3.Row, values: dict[str, dict[str, object]] | None
) -> FieldChange | None:
    """One field of an entry's change; titles are plain, other fields need their values."""
    if field == "title":
        return FieldChange(field, before=row["change_title_before"], after=row["event_title"])
    value = values.get(field) if values is not None else None
    if value is None:
        return None
    if field == "time":
        return FieldChange(
            field,
            before_time=_change_time(value["before"]),
            after_time=_change_time(value["after"]),
        )
    if field == "guests":
        return FieldChange(field, added=_texts(value["added"]), removed=_texts(value["removed"]))
    if field == "conferencing":
        before, after = set(_texts(value["before"])), set(_texts(value["after"]))
        return FieldChange(
            field, added=tuple(sorted(after - before)), removed=tuple(sorted(before - after))
        )
    if field == "recurrence":
        return FieldChange(
            field,
            before="\n".join(_texts(value["before"])),
            after="\n".join(_texts(value["after"])),
        )
    return FieldChange(field, before=str(value["before"]), after=str(value["after"]))


def _change_time(value: object) -> RecordedTime:
    assert isinstance(value, dict)
    return RecordedTime(
        all_day=bool(value["all_day"]), starts=str(value["starts"]), ends=str(value["ends"])
    )


def _texts(value: object) -> tuple[str, ...]:
    assert isinstance(value, list)
    return tuple(str(item) for item in value)


def _previous_names(connection: sqlite3.Connection, ids: Sequence[int]) -> dict[int, sqlite3.Row]:
    """For each entry, the latest earlier entry of its rule and source event that saw a title."""
    if not ids:
        return {}
    return {
        row["entry_id"]: row
        # Interpolates only constant SQL fragments and `?` placeholders; values stay bound.
        for row in connection.execute(
            f"""
            SELECT a.id AS entry_id, p.event_title, p.event_starts, p.event_ends,
                p.event_all_day, p.event_recurring
            FROM audit_entries a JOIN audit_entries p ON p.id = (
                SELECT id FROM audit_entries
                WHERE rule_id = a.rule_id AND source_event_id = a.source_event_id
                    AND id < a.id AND {_TITLE_OBSERVED}
                ORDER BY id DESC LIMIT 1
            )
            WHERE a.id IN ({", ".join("?" for _ in ids)})
            """,  # noqa: S608
            ids,
        )
    }


def _repeated_repairs(connection: sqlite3.Connection, written: Sequence[int]) -> set[int]:
    """Repairs identical to the previous entry for their event, recorded by an earlier run."""
    if not written:
        return set()
    return {
        int(row[0])
        # Interpolates only constant SQL fragments and `?` placeholders; values stay bound.
        for row in connection.execute(
            f"""
            SELECT a.id FROM audit_entries a JOIN audit_entries p ON p.id = (
                SELECT id FROM audit_entries
                WHERE rule_id = a.rule_id AND source_event_id = a.source_event_id
                    AND id < a.id
                ORDER BY id DESC LIMIT 1
            )
            WHERE a.id IN ({", ".join("?" for _ in written)})
                AND p.action = a.action AND p.reason IS a.reason
                AND p.event_title IS a.event_title AND p.event_cancelled = a.event_cancelled
                AND p.event_recurring = a.event_recurring AND p.event_all_day = a.event_all_day
                AND p.event_starts IS a.event_starts AND p.event_ends IS a.event_ends
                AND COALESCE(p.run_id, '') != COALESCE(a.run_id, '')
            """,  # noqa: S608
            written,
        )
    }


def _recorded_event(row: sqlite3.Row, previous: sqlite3.Row | None) -> ActivityEvent | None:
    own = row if row["event_title"] is not None else None
    if own is None and previous is None:
        return None
    cancelled = own is not None and bool(own["event_cancelled"])
    # A confirmed event's empty title is what the run saw; only a cancellation reported without a
    # title, or an entry that read no event, such as a projection removed with its rule, is named
    # by the event's last observed title.
    observed = own is not None and (bool(own["event_title"]) or not cancelled)
    earlier = previous["event_title"] if previous is not None else None
    title = own["event_title"] if observed and own is not None else earlier or ""
    # Time and recurrence come from one entry: this one if it saw the event's time, else the
    # earlier one, so a series converted to a single event stops showing as repeating.
    timed = (
        own
        if own is not None and (own["event_starts"] is not None or previous is None)
        else previous
    )
    assert timed is not None
    return ActivityEvent(
        title=title,
        all_day=bool(timed["event_all_day"]),
        starts=timed["event_starts"],
        ends=timed["event_ends"],
        recurring=bool(timed["event_recurring"]),
        cancelled=cancelled,
        renamed_from=earlier
        if observed and not cancelled and earlier is not None and earlier != title
        else None,
        moved_from=_moved_from(own, previous) if not cancelled else None,
    )


def _moved_from(own: sqlite3.Row | None, previous: sqlite3.Row | None) -> RecordedTime | None:
    """The previously recorded time, when this entry saw the event at a different one."""
    if own is None or previous is None or own["event_starts"] is None:
        return None
    if previous["event_starts"] is None:
        return None
    # Only a new start is a move; a change of end alone is a change of length.
    before = (previous["event_starts"], previous["event_ends"], bool(previous["event_all_day"]))
    if before[0] == own["event_starts"] and before[2] == bool(own["event_all_day"]):
        return None
    return RecordedTime(
        all_day=before[2], starts=previous["event_starts"], ends=previous["event_ends"]
    )
