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
from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, NoReturn, cast

from calendar_sync.application.accounts import DiscoverCalendars, ListConnectedAccounts
from calendar_sync.application.activity import InspectActivityEvent
from calendar_sync.application.errors import ProviderFailure, ProviderFailureKind
from calendar_sync.application.ports import (
    AccountAuthorization,
    AccountCalendars,
    AuditAction,
    AuditEntry,
    AuditOutcome,
    CalendarAccess,
    CalendarProvider,
    Clock,
    ConnectedAccount,
    ConnectedAccountRepository,
    ConnectedAccountState,
    DiscoveredCalendar,
    RecordedEvent,
    RuleRunOutcome,
    RunKind,
    SchedulerProgress,
)
from calendar_sync.application.providers import ProviderKind
from calendar_sync.application.status import GetInstallationStatus
from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import Adapters, Container, build_adapters, compose
from calendar_sync.domain.changes import SourceChange, SourceObservation
from calendar_sync.domain.model import (
    AllDayRange,
    CalendarEndpoint,
    CalendarEvent,
    CalendarId,
    ConnectedAccountId,
    EventId,
    EventRef,
    EventStatus,
    InvitationResponse,
    Recurrence,
    SyncReason,
    SyncRule,
    SyncRuleId,
    SyncRuleState,
    TimedInterval,
)
from calendar_sync.infrastructure.persistence.activity_queries import SqliteActivityQueries
from calendar_sync.infrastructure.persistence.sqlite import SqliteUnitOfWorkFactory
from calendar_sync.infrastructure.security import CredentialCipher, HistoryCipher

REPOSITORY = Path(__file__).resolve().parents[1]
PREVIEW_DATABASE = REPOSITORY / "dev-preview.db"
PREVIEW_PASSWORD = "preview-password"  # noqa: S105
MARKER_TABLE = "dev_preview_marker"


class NotAPreviewDatabase(RuntimeError):
    """The target database was not created by this script, so it must not be changed."""


@dataclass(frozen=True, slots=True)
class _FixedClock:
    """The preview's own fictional "now": its seeded history stays current no matter how long
    after it was generated the preview is actually opened."""

    moment: datetime

    def now(self) -> datetime:
        return self.moment


@dataclass(frozen=True, slots=True)
class _RecentSchedulerHeartbeat:
    """Reports a pass that completed moments ago.

    The preview never configures a master key, so `compose` never builds a real scheduler; without
    this, every scenario with an enabled rule would read "stalled" instead of its own health, since
    Installation Status correctly treats "no scheduler at all" that way for a real installation.
    Like a real pass, it lists the scenario's enabled rules, so a stale one can read overdue.
    """

    clock: Clock
    listed: frozenset[str]

    def progress(self) -> SchedulerProgress:
        now = self.clock.now()
        return SchedulerProgress(
            running_since=now,
            pass_started_at=None,
            last_completed_at=now,
            last_pass_rule_ids=self.listed,
        )


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


# Three synthetic Google identities make Sam's different contexts legible: the same fictional
# person appears in each portrait, while the email domains and styling show Personal, Family, and
# Work. Local generated portraits keep it deterministic and offline; a real installation uses the
# profile photo returned by Google instead.
PERSONAL_ACCOUNT = ConnectedAccountId("preview-sam-personal")
FAMILY_ACCOUNT = ConnectedAccountId("preview-sam-family")
WORK_ACCOUNT = ConnectedAccountId("preview-sam-work")
PERSONAL = CalendarEndpoint(PERSONAL_ACCOUNT, CalendarId("sam@personal.example"))
FAMILY = CalendarEndpoint(FAMILY_ACCOUNT, CalendarId("sam@family.example"))
WORK = CalendarEndpoint(WORK_ACCOUNT, CalendarId("sam@work.example"))
ACCOUNTS = (
    ConnectedAccount(
        PERSONAL_ACCOUNT,
        "Sam Rivera",
        "sam@personal.example",
        ConnectedAccountState.CONNECTED,
        avatar_url="/avatars/sam-personal.png",
        provider=ProviderKind.GOOGLE,
    ),
    ConnectedAccount(
        FAMILY_ACCOUNT,
        "Sam Rivera",
        "sam@family.example",
        ConnectedAccountState.CONNECTED,
        avatar_url="/avatars/sam-family.png",
        provider=ProviderKind.GOOGLE,
    ),
    ConnectedAccount(
        WORK_ACCOUNT,
        "Sam Rivera",
        "sam@work.example",
        ConnectedAccountState.CONNECTED,
        avatar_url="/avatars/sam-work.png",
        provider=ProviderKind.GOOGLE,
    ),
)
CALENDARS = {
    "preview-sam-personal": [
        DiscoveredCalendar(
            "sam@personal.example", "Personal", access=CalendarAccess.OWNER, primary=True
        )
    ],
    "preview-sam-family": [
        DiscoveredCalendar(
            "sam@family.example", "Family", access=CalendarAccess.OWNER, primary=True
        )
    ],
    "preview-sam-work": [
        DiscoveredCalendar("sam@work.example", "Work", access=CalendarAccess.OWNER, primary=True)
    ],
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


@dataclass(frozen=True)
class PreviewAccounts:
    accounts: tuple[ConnectedAccount, ...]

    def list(self) -> tuple[ConnectedAccount, ...]:
        return self.accounts


class PreviewGoogle:
    def calendars(self, account_id: ConnectedAccountId) -> list[DiscoveredCalendar]:
        return CALENDARS.get(account_id.value, [])

    def __getattr__(self, name: str) -> Any:
        def refuse(*_: object, **__: object) -> NoReturn:
            raise RuntimeError(f"the development preview cannot {name}")

        return refuse


class Scenario(StrEnum):
    """The Overview state the preview starts in, so every health state can be seen."""

    REVIEW = "review"
    """Blocked events, one persisting into an Incident; every rule keeps running."""
    HEALTHY = "healthy"
    STOPPED = "stopped"
    """The Personal account's authorization expired, so both of its rules are Degraded."""
    WAITING = "waiting"
    """Google is limiting Family → Work's requests; the rule keeps retrying by itself."""
    SEVERAL = "several"
    """Stopped, waiting, and blocked at once, so the Overview lists every problem."""
    PAUSED = "paused"
    SETUP = "setup"
    """A new installation: no Google account, rule, or history."""


_EXPIRED = frozenset({Scenario.STOPPED, Scenario.SEVERAL})
_LIMITED = frozenset({Scenario.WAITING, Scenario.SEVERAL})
_BLOCKED = frozenset({Scenario.REVIEW, Scenario.SEVERAL})
LIMITED_RULE = SyncRuleId("preview-family-work")


def _scenario_accounts(scenario: Scenario) -> tuple[ConnectedAccount, ...]:
    if scenario is Scenario.SETUP:
        return ()
    if scenario in _EXPIRED:
        return tuple(
            replace(account, state=ConnectedAccountState.DISCONNECTED)
            if account.id == PERSONAL_ACCOUNT
            else account
            for account in ACCOUNTS
        )
    return ACCOUNTS


def _scenario_rules(scenario: Scenario) -> tuple[SyncRule, ...]:
    if scenario is Scenario.PAUSED:
        return tuple(replace(rule, state=SyncRuleState.PAUSED) for rule in PREVIEW_RULES)
    if scenario in _EXPIRED:
        return tuple(
            replace(rule, state=SyncRuleState.DEGRADED) if _uses_personal(rule) else rule
            for rule in PREVIEW_RULES
        )
    return PREVIEW_RULES


def _enabled_rule_ids(scenario: Scenario) -> frozenset[str]:
    return frozenset(
        rule.id.value for rule in _scenario_rules(scenario) if rule.state is SyncRuleState.ENABLED
    )


def _uses_personal(rule: SyncRule) -> bool:
    return PERSONAL_ACCOUNT in {
        rule.source.connected_account_id,
        rule.destination.connected_account_id,
    }


def build_preview_container(
    path: Path = PREVIEW_DATABASE,
    now: datetime | None = None,
    *,
    scenario: Scenario = Scenario.REVIEW,
) -> Container:
    reset_preview_database(path)
    # Explicit settings: nothing is read from the environment or .env.
    settings = Settings(path)
    adapters = build_adapters(settings)
    # A key of this process only, so seeded Source Changes can be unsealed; it never syncs.
    history = HistoryCipher(CredentialCipher.generate_key())
    adapters = replace(
        adapters,
        unit_of_work=SqliteUnitOfWorkFactory(path, adapters.clock, history),
        activity=SqliteActivityQueries(path, history),
    )
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(f"CREATE TABLE {MARKER_TABLE} (created_at TEXT NOT NULL)")
        # The marker table name is a constant.
        connection.execute(
            f"INSERT INTO {MARKER_TABLE} VALUES (?)",  # noqa: S608
            (adapters.clock.now().isoformat(),),
        )
    moment = now or adapters.clock.now()
    google = PreviewGoogle()
    composed = compose(settings, adapters)
    # Only reads are substituted: without a master key nothing synchronizes or writes.
    container = replace(
        composed,
        inspect_activity_event=InspectActivityEvent(
            adapters.activity,
            adapters.unit_of_work,
            cast(CalendarProvider, PreviewCalendar(moment)),
        ),
        list_connected_accounts=ListConnectedAccounts(
            adapters.unit_of_work,
            cast(ConnectedAccountRepository, PreviewAccounts(_scenario_accounts(scenario))),
        ),
        authorization=cast(AccountAuthorization, google),
        account_calendars=cast(AccountCalendars, google),
        discover_calendars=DiscoverCalendars(cast(AccountCalendars, google), adapters.unit_of_work),
        # The preview has no scheduler (no master key is ever configured here); a heartbeat that
        # always reports a recent pass keeps each scenario's own health visible instead of
        # "stalled", which is correct for a real installation with no scheduler at all. The clock
        # is pinned to the preview's own fictional `moment`, so its seeded history never reads as
        # overdue just because real time moved on since it was generated.
        get_installation_status=GetInstallationStatus(
            composed.list_sync_rules,
            adapters.operations,
            _FixedClock(moment),
            _RecentSchedulerHeartbeat(_FixedClock(moment), _enabled_rule_ids(scenario)),
        ),
    )
    if scenario is not Scenario.SETUP:
        _seed(adapters, path, moment, scenario)
    adapters.administrator.create_admin(PREVIEW_PASSWORD)
    return container


PREVIEW_RULES = (
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
    SyncRule(
        id=SyncRuleId("preview-work-personal"),
        source=WORK,
        destination=PERSONAL,
        state=SyncRuleState.ENABLED,
    ),
)


@dataclass(frozen=True)
class SeededEntry:
    """One synthetic Audit Entry, described by the values that vary across the history."""

    minutes_ago: int
    rule: str
    run: str | None
    action: str
    reason: str | None
    event: str | None
    projection: bool = True
    title: str | None = None
    """Overrides the recorded title, as Google's reports of renamed or deleted events do."""


def _history() -> Iterator[SeededEntry]:
    personal, family = "preview-personal-work", "preview-family-work"
    entry = SeededEntry
    # Oldest first, so identifiers ascend with time like a real history.
    yield entry(60 * 30, "preview-removed-rule", None, "create", "source_created", "standup")
    yield entry(60 * 29, "preview-removed-rule", None, "rule_removed", None, None)
    for event in ("dentist", "gym", "school", "piano", "pta", "vet", "dinner"):
        yield entry(60 * 26, personal, "preview-run-1", "create", "source_created", event)
    yield entry(
        60 * 26, personal, "preview-run-1", "create", "source_created", "flight", title="Flight"
    )
    yield entry(60 * 26, personal, "preview-run-1", "ignore", "all_day_excluded", "holiday", False)
    for event in ("dentist", "gym", "school", "piano", "pta"):
        yield entry(60 * 5, personal, "preview-run-2", "ignore", "projection_current", event)
    yield entry(60 * 5, personal, "preview-run-2", "update", "source_changed", "flight")
    yield entry(60 * 4, family, "preview-run-3", "create", "source_created", "yoga")
    yield entry(60 * 4, family, "preview-run-3", "ignore", "occurrence_current", "yoga")
    yield entry(60 * 4, family, "preview-run-3", "update", "occurrence_changed", "piano")
    for event in ("gym", "school", "piano", "dentist"):
        yield entry(60, personal, "preview-run-4", "ignore", "projection_current", event)
    yield entry(60, personal, "preview-run-4", "update", "destination_drift_repaired", "flight")
    yield entry(
        60, personal, "preview-run-4", "conflict", "destination_ownership_inconsistent", "vet"
    )
    # Runs that only confirmed events were up to date, as scheduled checks usually do.
    for minutes, run in ((50, "preview-quiet-1"), (40, "preview-quiet-2")):
        for event in ("dentist", "gym", "school"):
            yield entry(minutes, personal, run, "ignore", "projection_current", event)
    # A reconciliation large enough that its no-change checks load in pages.
    for _ in range(150):
        yield entry(30, family, "preview-reconcile", "ignore", "projection_current", "yoga")
    yield entry(30, family, "preview-reconcile", "update", "occurrence_drift_repaired", "piano")
    # Google reports a deleted event without its title; Activity names it from earlier entries.
    yield entry(20, personal, "preview-run-5", "delete", "source_cancelled", "dinner", title="")
    yield entry(20, personal, "preview-run-5", "delete", "source_cancelled", "deleted-event")
    yield entry(20, personal, "preview-run-5", "ignore", "projection_current", "gym")
    # The same repair on consecutive runs, which Recent changes counts on one line.
    for minutes, run in ((15, "preview-run-6"), (10, "preview-run-7")):
        yield entry(minutes, personal, run, "create", "projection_missing", "gym")
    # An occurrence the destination series does not have, blocked after checking the series.
    yield entry(8, family, "preview-run-8", "conflict", "destination_occurrence_missing", "piano")
    yield entry(5, personal, None, "policy_changed", None, None)
    # Answers to invitations: accepting a Maybe, declining, and one not answered yet.
    yield entry(3, personal, "preview-run-9", "update", "source_changed", "pta")
    yield entry(3, personal, "preview-run-9", "delete", "declined_removed", "school")
    yield entry(3, personal, "preview-run-9", "ignore", "awaiting_response", "dentist", False)


def _audit_entry(seeded: SeededEntry, calendar: PreviewCalendar, now: datetime) -> AuditEntry:
    event = seeded.event
    # Entries of the removed rule predate recorded events, as an upgraded installation's do.
    found = (
        calendar.get_event(EventRef(PERSONAL, EventId(event)))
        if event and seeded.rule != "preview-removed-rule"
        else None
    )
    recorded = RecordedEvent.of(found) if found else None
    if recorded is not None and seeded.title is not None:
        recorded = replace(recorded, title=seeded.title)
    change = _preview_change(found, seeded) if found else None
    return AuditEntry(
        occurred_at=now - timedelta(minutes=seeded.minutes_ago),
        rule_id=SyncRuleId(seeded.rule),
        action=AuditAction(seeded.action),
        outcome={"ignore": AuditOutcome.SKIPPED, "conflict": AuditOutcome.BLOCKED}.get(
            seeded.action, AuditOutcome.COMPLETED
        ),
        source_event_id=event,
        destination_event_id=f"copy-{event}" if event and seeded.projection else None,
        reason=SyncReason(seeded.reason) if seeded.reason is not None else None,
        run_id=seeded.run,
        event=recorded,
        change=change,
    )


# Seeded Source Changes: an update, and a guest change a Busy-Only rule does not show.
PREVIEW_CHANGES = {
    ("preview-run-2", "flight"): {
        "title": "Flight",
        "description": "Gate B12",
        "guests": ("ana@example.com", "ben@example.com"),
    },
    ("preview-run-4", "gym"): {"guests": ("ana@example.com",)},
    ("preview-run-9", "pta"): {"response": InvitationResponse.TENTATIVE},
}


def _preview_change(found: CalendarEvent, seeded: SeededEntry) -> SourceChange | None:
    earlier = PREVIEW_CHANGES.get((seeded.run or "", seeded.event or ""))
    if earlier is None:
        return None
    now = replace(
        found,
        description="Gate B14, boarding 9:40.\nBring the printed pass.",
        guests=("ana@example.com", "cleo@example.com"),
        conferencing=(),
    )
    before = SourceObservation.of(replace(now, revision="preview-0", **earlier))  # type: ignore[arg-type]
    after = SourceObservation.of(now)
    assert before is not None
    assert after is not None
    return SourceChange.between(before, after)


def _seed(adapters: Adapters, path: Path, now: datetime, scenario: Scenario) -> None:
    calendar = PreviewCalendar(now)
    rules = _scenario_rules(scenario)
    with adapters.unit_of_work() as uow:
        for rule in rules:
            uow.rules.add(rule)
        for seeded in _history():
            uow.audit.append(_audit_entry(seeded, calendar, now))
        # Each rule's latest scheduled sync, so the Overview and Rules show when it last ran. A
        # failed run keeps the last success from before authorization expired or Google pushed back.
        for rule, minutes_ago in zip(rules, (3, 4, 2), strict=True):
            completed = now - timedelta(minutes=minutes_ago)
            failure = (
                "authentication"
                if rule.state is SyncRuleState.DEGRADED
                else "rate_limit"
                if scenario in _LIMITED and rule.id == LIMITED_RULE
                else None
            )
            if failure is not None:
                # The repository keeps this success as the last one when the failure follows.
                earlier = now - timedelta(minutes=40)
                uow.run_outcomes.record(
                    RuleRunOutcome(rule.id, RunKind.SYNC, completed_at=earlier, succeeded=True)
                )
            uow.run_outcomes.record(
                RuleRunOutcome(
                    rule_id=rule.id,
                    kind=RunKind.SYNC,
                    completed_at=completed,
                    succeeded=failure is None,
                    failure_kind=failure,
                )
            )
        uow.commit()
    with closing(sqlite3.connect(path)) as connection, connection:
        # Records only, so the preview's accounts can be used by new rules; no credentials.
        connection.executemany(
            """
            INSERT INTO connected_accounts (
                id, provider, display_name, email, encrypted_credentials,
                state, created_at, updated_at
            ) VALUES (?, 'google', ?, ?, x'00', ?, ?, ?)
            """,
            [
                (
                    account.id.value,
                    account.display_name,
                    account.email,
                    account.state.value,
                    now.isoformat(),
                    now.isoformat(),
                )
                for account in _scenario_accounts(scenario)
            ],
        )
        if scenario not in _BLOCKED:
            # A daily pass after the seeded history found nothing still blocked.
            connection.executemany(
                """
                INSERT INTO rule_block_checks (rule_id, audit_floor, checked_at)
                VALUES (?, (SELECT MAX(id) FROM audit_entries), ?)
                """,
                [(rule.id.value, now.isoformat()) for rule in PREVIEW_RULES],
            )
        # Provider Incidents, worded as the service words them.
        provider_incidents = [
            (rule.id, "authentication", "Google authorization expired", 60)
            for rule in PREVIEW_RULES
            if scenario in _EXPIRED and _uses_personal(rule)
        ]
        if scenario in _LIMITED:
            provider_incidents.append(
                (LIMITED_RULE, "rate_limit", "Google Calendar is limiting requests", 25)
            )
        connection.executemany(
            """
            INSERT INTO incidents (
                id, deduplication_key, rule_id, category, state, summary, opened_at, updated_at
            ) VALUES (?, ?, ?, ?, 'open', ?, ?, ?)
            """,
            [
                (
                    f"provider:{rule_id.value}",
                    f"provider:{rule_id.value}",
                    rule_id.value,
                    category,
                    summary,
                    (now - timedelta(minutes=minutes_ago)).isoformat(),
                    (now - timedelta(minutes=2)).isoformat(),
                )
                for rule_id, category, summary, minutes_ago in provider_incidents
            ],
        )
        if scenario is Scenario.REVIEW:
            connection.execute(
                """
                INSERT INTO incidents (
                    id, deduplication_key, rule_id, category, state, summary, opened_at, updated_at
                ) VALUES (?, ?, ?, ?, 'open', ?, ?, ?)
                """,
                (
                    "preview-incident",
                    "blocked:preview-personal-work",
                    "preview-personal-work",
                    "conflict",
                    "1 event could not be synced and was still blocked at the daily check.",
                    (now - timedelta(hours=1)).isoformat(),
                    (now - timedelta(hours=1)).isoformat(),
                ),
            )
        connection.executemany(
            """
            INSERT INTO incidents (
                id, deduplication_key, rule_id, category, state, summary,
                opened_at, updated_at, resolved_at, resolution
            ) VALUES (?, ?, ?, ?, 'resolved', ?, ?, ?, ?, ?)
            """,
            [
                (
                    f"preview-resolved-{resolution}",
                    f"preview-resolved-{resolution}",
                    rule_id,
                    category,
                    summary,
                    (now - timedelta(days=days, hours=2)).isoformat(),
                    (now - timedelta(days=days)).isoformat(),
                    (now - timedelta(days=days)).isoformat(),
                    resolution,
                )
                for rule_id, category, summary, days, resolution in (
                    (
                        "preview-personal-work",
                        "temporary",
                        "Google Calendar is temporarily unavailable",
                        1,
                        "sync_succeeded",
                    ),
                    (
                        "preview-removed-rule",
                        "permanent",
                        "Google Calendar rejected synchronization",
                        2,
                        "rule_removed",
                    ),
                )
            ],
        )
    # The names Google last gave each calendar, kept after an account's access expires.
    with adapters.unit_of_work() as uow:
        for account_id, calendars in CALENDARS.items():
            uow.calendar_names.remember(ConnectedAccountId(account_id), calendars)
        uow.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Development-only preview with synthetic data.")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument(
        "--scenario",
        type=Scenario,
        choices=list(Scenario),
        default=Scenario.REVIEW,
        help="the Overview state to start in (default: review)",
    )
    arguments = parser.parse_args()
    port = arguments.port
    container = build_preview_container(scenario=arguments.scenario)

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
