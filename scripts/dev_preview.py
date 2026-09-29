"""Development-only preview of the Web UI with synthetic data.

    .venv/bin/python scripts/dev_preview.py

This never touches a real installation:

- It writes only to its own preview database, ``dev-preview.db`` in the repository root, and marks
  it so it will refuse to reset or seed any database it did not create, including the one
  ``CALENDAR_SYNC_DATABASE_PATH`` names.
- Settings are built explicitly, never from the environment, so ``.env`` credentials, Google OAuth,
  the master key, SMTP, webhooks, and the scheduler are never loaded.
- Google is replaced by a read-only fake that answers event lookups from synthetic data and refuses
  every write.
- It listens on 127.0.0.1 only.

The script lives outside ``src/``, so it is not part of the Python package or the container image.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, NoReturn, cast

from calendar_sync.application.errors import ProviderFailure, ProviderFailureKind
from calendar_sync.application.ports import (
    AuditAction,
    AuditEntry,
    AuditOutcome,
    CalendarProvider,
    RecordedEvent,
)
from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import Container, build_container
from calendar_sync.domain.model import (
    AllDayRange,
    CalendarEndpoint,
    CalendarEvent,
    CalendarId,
    ConnectedAccountId,
    EventId,
    EventRef,
    EventStatus,
    Recurrence,
    SyncReason,
    SyncRule,
    SyncRuleId,
    SyncRuleState,
    TimedInterval,
)
from calendar_sync.infrastructure.google.oauth import ConnectedGoogleAccount, DiscoveredCalendar

REPOSITORY = Path(__file__).resolve().parents[1]
PREVIEW_DATABASE = REPOSITORY / "dev-preview.db"
PREVIEW_PASSWORD = "preview-password"  # noqa: S105
MARKER_TABLE = "dev_preview_marker"


class NotAPreviewDatabase(RuntimeError):
    """The target database was not created by this script, so it must not be changed."""


def reset_preview_database(path: Path) -> None:
    """Delete a previous preview database; refuse anything else, including the configured one."""
    configured = Path(os.environ.get("CALENDAR_SYNC_DATABASE_PATH", "./calendar-sync.db"))
    if path.resolve() == configured.resolve():
        raise NotAPreviewDatabase(f"{path} is the configured installation database")
    if not path.exists():
        return
    with closing(sqlite3.connect(path)) as connection:
        marked = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (MARKER_TABLE,)
        ).fetchone()
    if marked is None:
        raise NotAPreviewDatabase(f"{path} was not created by the development preview")
    for candidate in (path, path.with_name(f"{path.name}-wal"), path.with_name(f"{path.name}-shm")):
        candidate.unlink(missing_ok=True)


PERSONAL = CalendarEndpoint(ConnectedAccountId("preview-personal"), CalendarId("sam@example.com"))
FAMILY = CalendarEndpoint(ConnectedAccountId("preview-personal"), CalendarId("family@example.com"))
WORK = CalendarEndpoint(ConnectedAccountId("preview-work"), CalendarId("sam@work.example"))
ACCOUNTS = (
    ConnectedGoogleAccount(
        ConnectedAccountId("preview-personal"), "Sam Rivera", "sam@example.com", "connected"
    ),
    ConnectedGoogleAccount(
        ConnectedAccountId("preview-work"), "Sam Rivera", "sam@work.example", "connected"
    ),
)
CALENDARS = {
    "preview-personal": [
        DiscoveredCalendar("sam@example.com", "Personal", "owner", True),
        DiscoveredCalendar("family@example.com", "Family", "owner", False),
    ],
    "preview-work": [DiscoveredCalendar("sam@work.example", "Work", "owner", True)],
}


@dataclass(frozen=True)
class SyntheticEvent:
    title: str
    day: int
    hour: int | None = 9
    status: EventStatus = EventStatus.CONFIRMED
    recurring: bool = False


# Event identifiers the seed refers to; "deleted-event" is deliberately absent.
EVENTS = {
    "dentist": SyntheticEvent("Dentist appointment", 2, 11),
    "gym": SyntheticEvent("Gym with Alex", 3, 7, recurring=True),
    "school": SyntheticEvent("School pickup", 3, 15),
    "piano": SyntheticEvent("Piano lesson", 4, 17, recurring=True),
    "dinner": SyntheticEvent("Dinner at Marta's", 5, 19, EventStatus.CANCELLED),
    "flight": SyntheticEvent("Flight to Lisbon", 6, 8),
    "vet": SyntheticEvent("Vet check-up", 7, 10),
    "pta": SyntheticEvent("PTA meeting", 8, 18),
    "holiday": SyntheticEvent("Bank holiday", 9, None),
    "yoga": SyntheticEvent("Yoga", 10, 7, recurring=True),
    "standup": SyntheticEvent("Team standup", 1, 9, recurring=True),
}


class PreviewCalendar:
    """Read-only stand-in for Google: event lookups answer from synthetic data."""

    def __init__(self, today: datetime) -> None:
        self.today = today.replace(hour=0, minute=0, second=0, microsecond=0)

    def get_event(self, reference: EventRef) -> CalendarEvent | None:
        synthetic = EVENTS.get(reference.event_id.value.removeprefix("copy-"))
        if synthetic is None:
            return None
        starts = self.today + timedelta(days=synthetic.day)
        time: TimedInterval | AllDayRange
        if synthetic.hour is None:
            time = AllDayRange(starts.date(), (starts + timedelta(days=1)).date())
        else:
            begins = starts + timedelta(hours=synthetic.hour)
            time = TimedInterval(begins, begins + timedelta(hours=1))
        projection = reference.event_id.value.startswith("copy-")
        return CalendarEvent(
            reference=reference,
            time=time,
            revision="preview",
            title="Busy" if projection else synthetic.title,
            status=synthetic.status,
            recurrence=Recurrence(("RRULE:FREQ=WEEKLY",)) if synthetic.recurring else None,
            web_link="https://calendar.google.com/calendar/",
        )

    def __getattr__(self, name: str) -> Any:
        def refuse(*_: object, **__: object) -> NoReturn:
            raise ProviderFailure(
                ProviderFailureKind.PERMANENT, f"the development preview cannot {name}"
            )

        return refuse


class PreviewAccounts:
    def list(self) -> tuple[ConnectedGoogleAccount, ...]:
        return ACCOUNTS


class PreviewGoogle:
    def calendars(self, account_id: ConnectedAccountId) -> list[DiscoveredCalendar]:
        return CALENDARS.get(account_id.value, [])

    def __getattr__(self, name: str) -> Any:
        def refuse(*_: object, **__: object) -> NoReturn:
            raise RuntimeError(f"the development preview cannot {name}")

        return refuse


def build_preview_container(
    path: Path = PREVIEW_DATABASE, now: datetime | None = None
) -> Container:
    reset_preview_database(path)
    # Explicit settings: nothing is read from the environment or .env.
    base = build_container(Settings(path))
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(f"CREATE TABLE {MARKER_TABLE} (created_at TEXT NOT NULL)")
        # The marker table name is a constant.
        connection.execute(
            f"INSERT INTO {MARKER_TABLE} VALUES (?)",  # noqa: S608
            (datetime.now(UTC).isoformat(),),
        )
    moment = now or datetime.now(UTC)
    container = replace(
        base,
        calendar_provider=cast(CalendarProvider, PreviewCalendar(moment)),
        connected_accounts=cast(Any, PreviewAccounts()),
        google_oauth=cast(Any, PreviewGoogle()),
    )
    _seed(container, path, moment)
    base.admin_auth.create_admin(PREVIEW_PASSWORD)
    return container


def _seed(container: Container, path: Path, now: datetime) -> None:  # noqa: C901
    rules = (
        SyncRule(
            id=SyncRuleId("preview-personal-work"),
            source=PERSONAL,
            destination=WORK,
            state=SyncRuleState.ENABLED,
        ),
        SyncRule(
            id=SyncRuleId("preview-family-work"),
            source=FAMILY,
            destination=WORK,
            state=SyncRuleState.ENABLED,
        ),
    )
    entries: list[AuditEntry] = []
    calendar = PreviewCalendar(now)

    def record(  # noqa: PLR0913
        minutes_ago: int,
        rule: str,
        run: str | None,
        action: str,
        reason: str | None,
        event: str | None,
        projection: bool = True,
        title: str | None = None,
    ) -> None:
        # Entries of the removed rule predate recorded events, as an upgraded installation's do.
        found = (
            calendar.get_event(EventRef(PERSONAL, EventId(event)))
            if event and rule != "preview-removed-rule"
            else None
        )
        recorded = RecordedEvent.of(found) if found else None
        if recorded is not None and title is not None:
            recorded = replace(recorded, title=title)
        entries.append(
            AuditEntry(
                occurred_at=now - timedelta(minutes=minutes_ago),
                rule_id=SyncRuleId(rule),
                action=AuditAction(action),
                outcome={"ignore": AuditOutcome.SKIPPED, "conflict": AuditOutcome.BLOCKED}.get(
                    action, AuditOutcome.COMPLETED
                ),
                source_event_id=event,
                destination_event_id=f"copy-{event}" if event and projection else None,
                reason=SyncReason(reason) if reason is not None else None,
                run_id=run,
                event=recorded,
            )
        )

    personal, family = "preview-personal-work", "preview-family-work"
    # Oldest first, so identifiers ascend with time like a real history.
    record(60 * 30, "preview-removed-rule", None, "create", "source_created", "standup")
    record(60 * 29, "preview-removed-rule", None, "rule_removed", None, None)
    for event in ("dentist", "gym", "school", "piano", "pta", "vet", "dinner"):
        record(60 * 26, personal, "preview-run-1", "create", "source_created", event)
    record(60 * 26, personal, "preview-run-1", "create", "source_created", "flight", title="Flight")
    record(60 * 26, personal, "preview-run-1", "ignore", "all_day_excluded", "holiday", False)
    for event in ("dentist", "gym", "school", "piano", "pta"):
        record(60 * 5, personal, "preview-run-2", "ignore", "projection_current", event)
    record(60 * 5, personal, "preview-run-2", "update", "source_changed", "flight")
    record(60 * 4, family, "preview-run-3", "create", "source_created", "yoga")
    record(60 * 4, family, "preview-run-3", "ignore", "occurrence_current", "yoga")
    record(60 * 4, family, "preview-run-3", "update", "occurrence_changed", "piano")
    for event in ("gym", "school", "piano", "dentist"):
        record(60, personal, "preview-run-4", "ignore", "projection_current", event)
    record(60, personal, "preview-run-4", "update", "destination_drift_repaired", "flight")
    record(60, personal, "preview-run-4", "conflict", "destination_ownership_inconsistent", "vet")
    # Runs that only confirmed events were up to date, as scheduled checks usually do.
    for minutes, run in ((50, "preview-quiet-1"), (40, "preview-quiet-2")):
        for event in ("dentist", "gym", "school"):
            record(minutes, personal, run, "ignore", "projection_current", event)
    # A reconciliation large enough that its no-change checks load in pages.
    for _ in range(150):
        record(30, family, "preview-reconcile", "ignore", "projection_current", "yoga")
    record(30, family, "preview-reconcile", "update", "occurrence_drift_repaired", "piano")
    # Google reports a deleted event without its title; Activity names it from earlier entries.
    record(20, personal, "preview-run-5", "delete", "source_cancelled", "dinner", title="")
    record(20, personal, "preview-run-5", "delete", "source_cancelled", "deleted-event")
    record(20, personal, "preview-run-5", "ignore", "projection_current", "gym")
    # The same repair on consecutive runs, which Recent changes counts on one line.
    for minutes, run in ((15, "preview-run-6"), (10, "preview-run-7")):
        record(minutes, personal, run, "create", "projection_missing", "gym")
    # An occurrence the destination series does not have, blocked after checking the series.
    record(8, family, "preview-run-8", "conflict", "destination_occurrence_missing", "piano")
    record(5, personal, None, "policy_changed", None, None)
    with container.unit_of_work() as uow:
        for rule in rules:
            uow.rules.add(rule)
        for entry in entries:
            uow.audit.append(entry)
        uow.commit()
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(
            """
            INSERT INTO incidents
                (id, deduplication_key, rule_id, category, state, summary, opened_at, updated_at)
            VALUES (?, ?, ?, ?, 'open', ?, ?, ?)
            """,
            (
                "preview-incident",
                "preview-incident",
                personal,
                "ownership",
                "A projection in Work is not owned by this rule, so it was left unchanged.",
                (now - timedelta(hours=1)).isoformat(),
                (now - timedelta(hours=1)).isoformat(),
            ),
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Development-only preview with synthetic data.")
    parser.add_argument("--port", type=int, default=8001)
    port = parser.parse_args().port
    container = build_preview_container()

    import uvicorn

    from calendar_sync.interfaces.api.app import create_app

    print(
        "\n  DEVELOPMENT PREVIEW with synthetic data. Not a real installation.\n"
        f"  Database: {PREVIEW_DATABASE}\n"
        f"  Open http://127.0.0.1:{port}/activity and sign in with: {PREVIEW_PASSWORD}\n"
    )
    uvicorn.run(create_app(container), host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
