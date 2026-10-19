"""Run ADR 0034's live provider checks against real Google and Outlook calendars.

Opt-in and manual; CI never runs it, since tests must not need a personal account (AGENTS.md).
It needs a running local installation with exactly one Outlook and one Google account connected,
and two empty Google calendars the operator creates, named `CG live source` and
`CG live destination` unless `CALENDAR_GHOST_GOOGLE_SOURCE` and `CALENDAR_GHOST_GOOGLE_DESTINATION`
name others: the installation's Google grant may not create calendars. Each Outlook
calendar it needs it creates, named `CG live ...`. It writes only to those, notifies nobody (it
imports invitations rather than sending them, and every other write asks for no notification),
compares every occurrence, fails on any error answer rather than reading it as an empty calendar,
and deletes what it made whatever the outcome. Its events fall in the year after the run. See
docs/development.md, Live provider checks.

    set -a; . ./.env; set +a
    CALENDAR_GHOST_URL=http://127.0.0.1:8000 CALENDAR_GHOST_EMAIL=you@example.test \\
    CALENDAR_GHOST_PASSWORD=... .venv/bin/python scripts/live_provider_checks.py

It stops at once, before it makes anything, when a Plan limits the signed-in User: one run starts
more manual runs than the limit allows in an hour. Sign in as an administrator, or turn Plans off.

It prints one Markdown table of results and exits 1 if any check failed.
"""

from __future__ import annotations

import os
import sys
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

import httpx

from calendar_sync.application.sync.manual_runs import MANUAL_RUNS
from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import calendar_providers
from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.model import ConnectedAccountId
from calendar_sync.infrastructure.clock import SystemClock
from calendar_sync.infrastructure.identifiers import UuidIdGenerator
from calendar_sync.infrastructure.persistence.accounts import SqliteConnectedAccountStore
from calendar_sync.infrastructure.security import CredentialCipher

GRAPH = "https://graph.microsoft.com/v1.0"
PREFIX = "CG live"
GOOGLE_SOURCE = os.environ.get("CALENDAR_GHOST_GOOGLE_SOURCE", f"{PREFIX} source")
GOOGLE_DESTINATION = os.environ.get("CALENDAR_GHOST_GOOGLE_DESTINATION", f"{PREFIX} destination")
# Every event falls in the year after the run, so none ages out of a new rule's first window.
YEAR = date.today().year + 1
# The last Sunday of October that year, when Madrid's clocks go back: the fold.
FOLD = max(date(YEAR, 10, day) for day in range(25, 32) if date(YEAR, 10, day).weekday() == 6)
WINDOW = (f"{YEAR}-01-01T00:00:00Z", f"{YEAR + 2}-01-01T00:00:00Z")
MADRID, WINDOWS_MADRID = "Europe/Madrid", "W. Europe Standard Time"
PROPERTY = "String {8EF42533-0AD0-4C67-A411-7FD5CF9F109E} Name CalendarGhostOperation"
Json = dict[str, Any]
# An occurrence as both calendars are compared: UTC start and end, title, all-day.
Row = tuple[str, str, str, bool]


@dataclass
class Live:
    """The running installation, and its connected accounts' provider access."""

    api: httpx.Client
    outlook_token: Callable[[], str]
    google: Any
    outlook_account: str
    google_account: str
    created_calendars: list[str] = field(default_factory=list)
    created_rules: list[str] = field(default_factory=list)
    results: list[tuple[str, str, bool, str]] = field(default_factory=list)

    # Results -----------------------------------------------------------------------------

    def check(self, scenario: str, name: str, ok: bool, detail: object = "") -> None:
        self.results.append((scenario, name, ok, str(detail)[:160]))

    # Outlook -----------------------------------------------------------------------------

    def graph(
        self, method: str, path: str, *, allow: tuple[int, ...] = (), **kwargs: Any
    ) -> httpx.Response:
        """One Graph request; an error answer raises, unless a probe `allow`s its status, so a
        refused read can never pass for an empty calendar."""
        url = path if path.startswith("https://") else f"{GRAPH}{path}"
        headers = {
            "Authorization": f"Bearer {self.outlook_token()}",
            "Prefer": 'outlook.timezone="UTC", outlook.body-content-type="text"',
            **kwargs.pop("headers", {}),
        }
        answer = httpx.request(method, url, headers=headers, timeout=60, **kwargs)
        if answer.status_code >= 400 and answer.status_code not in allow:
            answer.raise_for_status()
        return answer

    def outlook_calendar(self, name: str) -> str:
        calendar = self.graph("POST", "/me/calendars", json={"name": f"{PREFIX} {name}"})
        calendar.raise_for_status()
        self.created_calendars.append(calendar.json()["id"])
        return str(calendar.json()["id"])

    def outlook_event(self, calendar: str, body: Json) -> Json:
        assert calendar in self.created_calendars, "writes only to its own calendars"
        made = self.graph(
            "POST", f"/me/calendars/{calendar}/events", json={"isReminderOn": False, **body}
        )
        made.raise_for_status()
        return dict(made.json())

    def outlook_view(self, calendar: str) -> list[Row]:
        rows: list[Row] = []
        url: str | None = f"/me/calendars/{calendar}/calendarView"
        params: Json | None = {
            "startDateTime": WINDOW[0],
            "endDateTime": WINDOW[1],
            "$select": "subject,start,end,isAllDay",
            "$top": "200",
        }
        while url:
            page = self.graph("GET", url, params=params).json()
            params = None
            rows += [
                (
                    e["start"]["dateTime"][:16],
                    e["end"]["dateTime"][:16],
                    e["subject"],
                    e["isAllDay"],
                )
                for e in page["value"]
            ]
            url = page.get("@odata.nextLink")
        return sorted(rows)

    def instances(self, event_id: str) -> list[Json]:
        listed = self.graph(
            "GET",
            f"/me/events/{event_id}/instances",
            params={
                "startDateTime": WINDOW[0],
                "endDateTime": WINDOW[1],
                "$select": "id,start,changeKey",
            },
        )
        return list(listed.json()["value"])

    # Google ------------------------------------------------------------------------------

    def google_calendar(self, name: str) -> str:
        found = [
            c["id"]
            for c in self.google.calendarList().list().execute()["items"]
            if c["summary"] == name
        ]
        if len(found) != 1:
            raise SystemExit(f"Create one empty Google calendar named {name!r} first.")
        return str(found[0])

    def google_event(self, calendar: str, body: Json) -> Json:
        self._google_owned(calendar)
        made = self.google.events().insert(calendarId=calendar, body=body, sendUpdates="none")
        return dict(made.execute())

    def google_invitation(self, calendar: str, title: str, answer: str, when: str) -> Json:
        """An event the calendar was invited to and answered `answer`, imported as such: an
        import notifies nobody, and the organizer is a placeholder address."""
        self._google_owned(calendar)
        organizer = "organizer@example.test"
        body = {
            "summary": title,
            "iCalUID": f"calendar-ghost-live-{uuid.uuid4().hex}@example.test",
            "start": google_time(f"{when}T10:00:00"),
            "end": google_time(f"{when}T11:00:00"),
            "organizer": {"email": organizer},
            "attendees": [
                {"email": calendar, "responseStatus": answer},
                {"email": organizer, "organizer": True, "responseStatus": "accepted"},
            ],
        }
        return dict(self.google.events().import_(calendarId=calendar, body=body).execute())

    def google_patch(self, calendar: str, event_id: str, body: Json) -> None:
        self._google_owned(calendar)
        self.google.events().patch(
            calendarId=calendar, eventId=event_id, body=body, sendUpdates="none"
        ).execute()

    def google_items(self, calendar: str, *, single_events: bool = False) -> list[Json]:
        """Every page: Google may answer an empty page with a token for the next one."""
        items: list[Json] = []
        token = None
        while True:
            page = (
                self.google.events()
                .list(
                    calendarId=calendar,
                    maxResults=250,
                    singleEvents=single_events,
                    pageToken=token,
                )
                .execute()
            )
            items += page.get("items", [])
            token = page.get("nextPageToken")
            if not token:
                return items

    def google_view(self, calendar: str) -> list[Row]:
        rows: list[Row] = []
        token = None
        while True:
            page = (
                self.google.events()
                .list(
                    calendarId=calendar,
                    timeMin=WINDOW[0],
                    timeMax=WINDOW[1],
                    singleEvents=True,
                    pageToken=token,
                    maxResults=250,
                )
                .execute()
            )
            for e in page.get("items", []):
                if "date" in e["start"]:
                    rows.append(
                        (
                            f"{e['start']['date']}T00:00",
                            f"{e['end']['date']}T00:00",
                            e.get("summary", ""),
                            True,
                        )
                    )
                else:
                    begin, end = (
                        datetime.fromisoformat(e[side]["dateTime"])
                        .astimezone(UTC)
                        .strftime("%Y-%m-%dT%H:%M")
                        for side in ("start", "end")
                    )
                    rows.append((begin, end, e.get("summary", ""), False))
            token = page.get("nextPageToken")
            if not token:
                return sorted(rows)

    def google_empty(self, calendar: str) -> None:
        """Delete every event: series first, then whatever single events remain, such as
        exceptions a deleted series left behind, which only a listing of single events shows."""
        self._google_owned(calendar)
        failed: Exception | None = None
        for single_events in (False, True, True):
            for item in self.google_items(calendar, single_events=single_events):
                try:
                    self.google.events().delete(
                        calendarId=calendar, eventId=item["id"], sendUpdates="none"
                    ).execute()
                except Exception as error:
                    status = getattr(getattr(error, "resp", None), "status", None)
                    if status not in (404, 410):  # 404 and 410: gone already, with its series.
                        failed = error
        # Whatever went wrong, the calendar is empty or the cleanup fails.
        left = self.google_items(calendar, single_events=True)
        if left:
            raise RuntimeError(f"{len(left)} Google test events left; last error {failed!r}")

    def _google_owned(self, calendar: str) -> None:
        summary = self.google.calendarList().get(calendarId=calendar).execute()["summary"]
        assert summary in (GOOGLE_SOURCE, GOOGLE_DESTINATION), f"refusing to write to {summary!r}"

    # Calendar Ghost ----------------------------------------------------------------------

    def rule(self, source: tuple[str, str], destination: tuple[str, str], **settings: Any) -> str:
        made = self.api.post(
            "/api/v1/rules",
            json={
                "source": {"connected_account_id": source[0], "calendar_id": source[1]},
                "destination": {
                    "connected_account_id": destination[0],
                    "calendar_id": destination[1],
                },
                "privacy_policy": "copy_details",
                **settings,
            },
        )
        made.raise_for_status()
        rule_id = str(made.json()["id"])
        self.created_rules.append(rule_id)
        self.api.post(f"/api/v1/rules/{rule_id}/preview").raise_for_status()
        self.api.post(f"/api/v1/rules/{rule_id}/enable").raise_for_status()
        return rule_id

    def sync(self, rule_id: str) -> Json:
        """One Sync now; a failed run raises, so it can never pass for a run that wrote nothing."""
        answer = self.api.post(f"/api/v1/rules/{rule_id}/sync")
        if answer.status_code != 200:
            raise RuntimeError(f"Sync now answered {answer.status_code}: {answer.text[:200]}")
        return dict(answer.json())

    def settle(self, rule_id: str, runs: int = 3) -> Json:
        """Sync until a run writes nothing; the last run's counts."""
        counts: Json = {}
        for _ in range(runs):
            counts = self.sync(rule_id)
            if not any(counts.get(k) for k in ("created", "updated", "deleted")):
                break
        return counts

    def policy(self, rule_id: str, **fields: Any) -> None:
        current = self.api.get(f"/api/v1/rules/{rule_id}").json()
        current = current.get("rule", current)
        body = {
            k: current[k]
            for k in (
                "privacy_policy",
                "sync_all_day_events",
                "tentative_events",
                "unanswered_invitations",
                "sync_birthdays",
            )
        }
        changed = self.api.patch(f"/api/v1/rules/{rule_id}", json={**body, **fields})
        changed.raise_for_status()
        if changed.json().get("state") != "enabled":
            self.api.post(f"/api/v1/rules/{rule_id}/preview")
            self.api.post(f"/api/v1/rules/{rule_id}/enable")

    def blocked_reasons(self, rule_id: str) -> set[str]:
        listed = self.api.get(
            "/api/v1/audit-entries", params={"rule_id": rule_id, "limit": 200}
        ).json()
        entries = listed.get("items", listed) if isinstance(listed, dict) else listed
        return {str(e["reason"]) for e in entries if e.get("action") == "conflict"}

    def remove(self, rule_id: str, projections: str = "delete") -> Json:
        answer = self.api.delete(f"/api/v1/rules/{rule_id}", params={"projections": projections})
        answer.raise_for_status()
        if rule_id in self.created_rules:
            self.created_rules.remove(rule_id)
        return dict(answer.json()) if answer.content else {}


def matches(
    source: list[Row], destination: list[Row], *, busy_only: bool = False
) -> tuple[bool, str]:
    def key(row: Row) -> tuple[Any, ...]:
        return (row[0], row[1], row[3]) if busy_only else row

    wanted, found = sorted(map(key, source)), sorted(map(key, destination))
    missing = [r for r in wanted if r not in found]
    extra = [r for r in found if r not in wanted]
    return not missing and not extra, f"missing {missing[:2]} extra {extra[:2]}"


def writes(counts: Json) -> int:
    return sum(int(counts.get(k) or 0) for k in ("created", "updated", "deleted"))


def day_of(instance: Json) -> date:
    """The day an occurrence Graph listed starts on, in UTC, which is Madrid's day for morning
    and afternoon occurrences."""
    return date.fromisoformat(str(instance["start"]["dateTime"])[:10])


def outlook_time(local: str, zone: str = WINDOWS_MADRID) -> Json:
    return {"dateTime": local, "timeZone": zone}


def google_time(local: str, zone: str = MADRID) -> Json:
    return {"dateTime": local, "timeZone": zone}


def weekly(day: str, start: str, *, count: int | None = None, zone: str = WINDOWS_MADRID) -> Json:
    span: Json = {"type": "numbered", "numberOfOccurrences": count} if count else {"type": "noEnd"}
    return {
        "pattern": {"type": "weekly", "interval": 1, "daysOfWeek": [day]},
        "range": {**span, "startDate": start, "recurrenceTimeZone": zone},
    }


# Scenarios -----------------------------------------------------------------------------------


def outlook_kinds(live: Live, calendar: str) -> dict[str, Json]:
    """One Outlook event of each kind the checks found worth keeping."""
    kinds: dict[str, Json] = {
        "single": {
            "subject": "CG single",
            "start": outlook_time(f"{YEAR}-01-12T10:00:00"),
            "end": outlook_time(f"{YEAR}-01-12T11:00:00"),
        },
        "all-day": {
            "subject": "CG all-day",
            "isAllDay": True,
            "start": outlook_time(f"{YEAR}-01-13T00:00:00"),
            "end": outlook_time(f"{YEAR}-01-14T00:00:00"),
        },
        "multi-day": {
            "subject": "CG three days",
            "isAllDay": True,
            "start": outlook_time(f"{YEAR}-01-14T00:00:00"),
            "end": outlook_time(f"{YEAR}-01-17T00:00:00"),
        },
        "zero-length": {
            "subject": "CG reminder",
            "start": outlook_time(f"{YEAR}-01-15T09:00:00"),
            "end": outlook_time(f"{YEAR}-01-15T09:00:00"),
        },
        "unicode": {
            "subject": "CG café 🎉 漢字",
            "location": {"displayName": "Sala ñ"},
            "start": outlook_time(f"{YEAR}-01-15T12:00:00"),
            "end": outlook_time(f"{YEAR}-01-15T13:00:00"),
        },
        "DST fold": {
            "subject": "CG fold",
            "start": outlook_time(f"{FOLD}T02:30:00"),
            "end": outlook_time(f"{FOLD}T03:00:00"),
        },
        "weekly": {
            "subject": "CG weekly",
            "start": outlook_time(f"{YEAR}-01-04T09:00:00"),
            "end": outlook_time(f"{YEAR}-01-04T09:30:00"),
            "recurrence": weekly("monday", f"{YEAR}-01-04"),
        },
        "New York daily": {
            "subject": "CG New York",
            "start": outlook_time(f"{YEAR}-03-08T08:00:00", "Eastern Standard Time"),
            "end": outlook_time(f"{YEAR}-03-08T08:30:00", "Eastern Standard Time"),
            "recurrence": {
                "pattern": {"type": "daily", "interval": 1},
                "range": {
                    "type": "numbered",
                    "numberOfOccurrences": 10,
                    "startDate": f"{YEAR}-03-08",
                    "recurrenceTimeZone": "Eastern Standard Time",
                },
            },
        },
        "day 31": {
            "subject": "CG day 31",
            "start": outlook_time(f"{YEAR}-01-31T12:00:00"),
            "end": outlook_time(f"{YEAR}-01-31T12:30:00"),
            "recurrence": {
                "pattern": {"type": "absoluteMonthly", "interval": 1, "dayOfMonth": 31},
                "range": {
                    "type": "numbered",
                    "numberOfOccurrences": 6,
                    "startDate": f"{YEAR}-01-31",
                    "recurrenceTimeZone": WINDOWS_MADRID,
                },
            },
        },
    }
    return {name: live.outlook_event(calendar, body) for name, body in kinds.items()}


def outlook_changes(live: Live, made: dict[str, Json]) -> None:
    """Move, cancel, retime, end early, and delete, as a person would in Outlook."""
    weekly_series = live.instances(made["weekly"]["id"])
    live.graph(
        "PATCH",
        f"/me/events/{weekly_series[1]['id']}",
        # To the next day: an occurrence never moves to or past its neighbour's day.
        json={
            "start": outlook_time(f"{day_of(weekly_series[1]) + timedelta(days=1)}T15:00:00"),
            "end": outlook_time(f"{day_of(weekly_series[1]) + timedelta(days=1)}T15:30:00"),
        },
    )
    live.graph("DELETE", f"/me/events/{weekly_series[2]['id']}")
    live.graph(
        "PATCH",
        f"/me/events/{made['weekly']['id']}",
        json={
            "start": outlook_time(f"{YEAR}-01-04T10:00:00"),
            "end": outlook_time(f"{YEAR}-01-04T10:30:00"),
        },
    )
    live.graph(
        "PATCH",
        f"/me/events/{made['New York daily']['id']}",
        json={
            "recurrence": {
                "pattern": {"type": "daily", "interval": 1},
                "range": {
                    "type": "numbered",
                    "numberOfOccurrences": 4,
                    "startDate": f"{YEAR}-03-08",
                    "recurrenceTimeZone": "Eastern Standard Time",
                },
            }
        },
    )
    live.graph("DELETE", f"/me/events/{made['single']['id']}")


def outlook_to_outlook(live: Live) -> None:
    scenario = "Outlook to Outlook"
    source, destination = live.outlook_calendar("O source"), live.outlook_calendar("O destination")
    made = outlook_kinds(live, source)
    rule = live.rule((live.outlook_account, source), (live.outlook_account, destination))
    live.settle(rule)
    live.check(
        scenario,
        "every kind of event",
        *matches(live.outlook_view(source), live.outlook_view(destination)),
    )
    outlook_changes(live, made)
    live.settle(rule)
    live.check(
        scenario,
        "moves, cancellations, series changes",
        *matches(live.outlook_view(source), live.outlook_view(destination)),
    )
    idle = live.sync(rule)
    live.check(scenario, "an idle run writes nothing", writes(idle) == 0, idle)
    projected = live.graph(
        "GET",
        f"/me/calendars/{destination}/events",
        params={"$filter": "subject eq 'CG weekly'", "$select": "id"},
    ).json()["value"][0]["id"]
    live.graph("DELETE", f"/me/events/{live.instances(projected)[0]['id']}")
    live.settle(rule)
    live.check(
        scenario,
        "an occurrence deleted in Outlook is rebuilt",
        *matches(live.outlook_view(source), live.outlook_view(destination)),
    )
    removed = live.remove(rule)
    left = live.graph(
        "GET", f"/me/calendars/{destination}/events", params={"$select": "id"}
    ).json()["value"]
    live.check(
        scenario,
        "Rule Removal deletes its projections",
        not left and removed.get("conflicts") == 0,
        removed,
    )


def google_to_outlook(live: Live, google_source: str) -> None:
    scenario = "Google to Outlook"
    destination = live.outlook_calendar("G destination")
    live.google_event(
        google_source,
        {
            "summary": "CG single",
            "start": google_time(f"{YEAR}-02-02T10:00:00"),
            "end": google_time(f"{YEAR}-02-02T11:00:00"),
        },
    )
    live.google_event(
        google_source,
        {
            "summary": "CG all-day",
            "start": {"date": f"{YEAR}-02-03"},
            "end": {"date": f"{YEAR}-02-04"},
        },
    )
    weekly_series = live.google_event(
        google_source,
        {
            "summary": "CG weekly",
            "start": google_time(f"{YEAR}-02-01T09:00:00"),
            "end": google_time(f"{YEAR}-02-01T09:30:00"),
            "recurrence": ["RRULE:FREQ=WEEKLY;COUNT=6"],
        },
    )
    live.google_event(
        google_source,
        {
            "summary": "CG 5th Monday",
            "start": google_time(f"{YEAR}-03-29T10:00:00"),
            "end": google_time(f"{YEAR}-03-29T10:30:00"),
            "recurrence": ["RRULE:FREQ=MONTHLY;BYDAY=5MO"],
        },
    )
    for answer in ("accepted", "tentative", "declined", "needsAction"):
        live.google_invitation(google_source, f"CG invite {answer}", answer, f"{YEAR}-02-04")
    rule = live.rule((live.google_account, google_source), (live.outlook_account, destination))
    live.settle(rule)
    titles = {row[2] for row in live.outlook_view(destination)}
    live.check(
        scenario,
        "invitations follow their answers",
        {"CG invite accepted", "Maybe: CG invite tentative", "Maybe: CG invite needsAction"}
        <= titles
        and not any("declined" in t for t in titles),
        sorted(titles),
    )
    expected = [
        r
        for r in live.google_view(google_source)
        if "5th Monday" not in r[2] and "invite" not in r[2]
    ]
    projected = [r for r in live.outlook_view(destination) if "invite" not in r[2]]
    live.check(scenario, "every kind of event", *matches(expected, projected))
    live.check(
        scenario,
        "a rule Outlook cannot repeat is blocked",
        "projection_unsupported" in live.blocked_reasons(rule),
        live.blocked_reasons(rule),
    )
    occurrences = (
        live.google.events()
        .instances(calendarId=google_source, eventId=weekly_series["id"])
        .execute()["items"]
    )
    # The second occurrence, moved to the day after the third: past its neighbour.
    past = datetime.fromisoformat(occurrences[2]["start"]["dateTime"]).date() + timedelta(days=1)
    live.google_patch(
        google_source,
        occurrences[1]["id"],
        {"start": google_time(f"{past}T09:00:00"), "end": google_time(f"{past}T09:30:00")},
    )
    live.sync(rule)
    live.check(
        scenario,
        "an occurrence moved past its neighbour is blocked",
        "occurrence_past_neighbour" in live.blocked_reasons(rule),
        live.blocked_reasons(rule),
    )
    live.policy(rule, privacy_policy="busy_only", sync_all_day_events=False)
    live.settle(rule)
    rows = live.outlook_view(destination)
    # Every timed event the rule projects, each still there: the blocked occurrence keeps its old
    # time, and neither the declined invitation nor the series Outlook cannot repeat is shown.
    timed = [
        r
        for r in live.google_view(google_source)
        if not r[3] and "5th Monday" not in r[2] and "declined" not in r[2]
    ]
    live.check(
        scenario,
        "Busy-Only and all-day off rewrite every projection",
        len(rows) == len(timed) > 0
        and {r[2] for r in rows} <= {"Busy", "Busy (tentative)"}
        and not any(r[3] for r in rows),
        f"{len(rows)} projected, {len(timed)} expected, titles {sorted({r[2] for r in rows})}",
    )
    idle = live.sync(rule)
    live.check(scenario, "an idle run writes nothing", writes(idle) == 0, idle)
    live.remove(rule)


def outlook_to_google(live: Live, google_destination: str) -> None:
    scenario = "Outlook to Google"
    source = live.outlook_calendar("source for Google")
    made = outlook_kinds(live, source)
    rule = live.rule((live.outlook_account, source), (live.google_account, google_destination))
    live.settle(rule)

    def view() -> list[Row]:
        rows = live.google_view(google_destination)
        return [r for r in rows if not r[2].startswith("CG invite")]

    live.check(scenario, "every kind of event", *matches(live.outlook_view(source), view()))
    outlook_changes(live, made)
    live.settle(rule)
    live.check(
        scenario,
        "moves, cancellations, series changes",
        *matches(live.outlook_view(source), view()),
    )
    idle = live.sync(rule)
    live.check(
        scenario,
        "an idle run writes nothing, though Google reorders rules",
        writes(idle) == 0,
        idle,
    )
    single = next(
        i for i in live.google_items(google_destination) if i.get("summary") == "CG all-day"
    )
    live.google_patch(google_destination, single["id"], {"summary": "CG edited in Google"})
    live.settle(rule)
    live.check(
        scenario, "an edit in Google is put back", *matches(live.outlook_view(source), view())
    )
    live.remove(rule)


def graph_answers(live: Live) -> None:
    """The Graph behaviors ADR 0034 relies on, asked directly."""
    scenario = "Graph v1.0"
    calendar = live.outlook_calendar("probes")
    series = live.outlook_event(
        calendar,
        {
            "subject": "CG probe",
            "start": outlook_time(f"{YEAR}-04-05T09:00:00"),
            "end": outlook_time(f"{YEAR}-04-05T09:30:00"),
            "recurrence": weekly("monday", f"{YEAR}-04-05", count=5),
        },
    )
    occurrences = live.instances(series["id"])
    live.graph(
        "PATCH",
        f"/me/events/{occurrences[1]['id']}",
        json={
            "start": outlook_time(f"{day_of(occurrences[1])}T14:00:00"),
            "end": outlook_time(f"{day_of(occurrences[1])}T14:30:00"),
        },
    )
    whole = live.graph(
        "GET", f"/me/events/{series['id']}", params={"$expand": "exceptionOccurrences"}
    ).json()
    live.check(
        scenario,
        "item 15: a bare $expand lists exceptions with attendees",
        [e.get("attendees") for e in whole.get("exceptionOccurrences", [])] == [[]],
        whole.get("exceptionOccurrences"),
    )
    selected = live.graph(
        "GET",
        f"/me/events/{series['id']}",
        params={
            "$select": "id,exceptionOccurrences",
            "$expand": "exceptionOccurrences($select=id,attendees)",
        },
    ).json()
    live.check(
        scenario,
        "item 15: any $select lists exceptions by id only (still true?)",
        all("attendees" not in e for e in selected.get("exceptionOccurrences", [])),
        selected.get("exceptionOccurrences"),
    )
    before = live.graph(
        "GET", f"/me/events/{series['id']}", params={"$select": "lastModifiedDateTime"}
    ).json()["lastModifiedDateTime"]
    time.sleep(2)
    live.graph("DELETE", f"/me/events/{occurrences[3]['id']}")
    after = live.graph(
        "GET", f"/me/events/{series['id']}", params={"$select": "lastModifiedDateTime"}
    ).json()["lastModifiedDateTime"]
    live.check(scenario, "item 2: cancelling an occurrence touches its master", before != after)
    stale = live.graph("GET", f"/me/events/{series['id']}", params={"$select": "changeKey"}).json()[
        "changeKey"
    ]
    live.graph("PATCH", f"/me/events/{series['id']}", json={"subject": "CG probe v2"})
    refused = live.graph(
        "PATCH",
        f"/me/events/{series['id']}",
        json={"subject": "CG probe v3"},
        headers={"If-Match": f'W/"{stale}"'},
        allow=(412,),
    )
    live.check(
        scenario,
        "item 16: PATCH of an older version answers 412",
        refused.status_code == 412,
        refused.status_code,
    )
    key = f"calendar-ghost-live-{uuid.uuid4().hex}"
    body = {
        "subject": "CG probe key",
        "transactionId": key,
        "start": outlook_time(f"{YEAR}-04-20T09:00:00"),
        "end": outlook_time(f"{YEAR}-04-20T09:15:00"),
        "singleValueExtendedProperties": [{"id": PROPERTY, "value": key}],
    }
    first, second = (live.outlook_event(calendar, body) for _ in range(2))
    live.check(
        scenario,
        "item 10: a repeated transactionId answers the stored event",
        first["id"] == second["id"],
    )
    found = (
        live.graph(
            "GET",
            f"/me/calendars/{calendar}/events",
            params={
                "$filter": (
                    "singleValueExtendedProperties/Any("
                    f"ep: ep/id eq '{PROPERTY}' and ep/value eq '{key}')"
                ),
                "$select": "id",
            },
        )
        .json()
        .get("value", [])
    )
    live.check(
        scenario,
        "items 3 and 11: the property filter finds a new event at once",
        len(found) == 1,
        len(found),
    )
    wide = live.graph(
        "GET",
        f"/me/events/{series['id']}/instances",
        params={
            "startDateTime": "1601-01-01T00:00:00Z",
            "endDateTime": "4500-01-01T00:00:00Z",
            "$select": "id",
        },
    )
    live.check(
        scenario,
        "item 9: instances accepts 1601 to 4500",
        wide.status_code == 200,
        wide.status_code,
    )
    me = live.graph("GET", "/me", params={"$select": "mail,userPrincipalName"}).json()
    live.check(
        scenario,
        "item 7: /me names the account's address",
        "@" in str(me.get("mail") or me.get("userPrincipalName") or ""),
    )


@contextmanager
def cleanup(live: Live, google_calendars: tuple[str, str]) -> Iterator[None]:
    """Remove what the run made, each step on its own, so one failure leaves no other behind; a
    step that fails is a failed check, so the run exits 1 and names what is left."""
    try:
        yield
    finally:
        steps: list[Callable[[], object]] = [
            *(lambda r=r: live.remove(r, projections="detach") for r in list(live.created_rules)),
            *(
                lambda c=c: live.graph("DELETE", f"/me/calendars/{c}")
                for c in live.created_calendars
            ),
            *(lambda c=c: live.google_empty(c) for c in google_calendars),
        ]
        for step in steps:
            try:
                step()
            except Exception as error:  # Cleanup goes on; the failure fails the run.
                live.check("cleanup", "everything the run made is removed", False, repr(error))


def require_unlimited_runs(api: httpx.Client) -> None:
    """Stop before anything is made when a Plan limits the signed-in User: one run of the checks
    starts more manual runs than the limit allows in an hour (ADR 0038)."""
    plan = api.get("/api/v1/account/plan")
    plan.raise_for_status()
    if plan.json()["basis"] == "plan":
        raise SystemExit(
            f"A Plan limits this User to {MANUAL_RUNS} manual runs an hour, and the checks need "
            "more: sign in as an administrator, or turn Plans off."
        )


def connect() -> Live:
    settings = Settings.from_environment()
    clock = SystemClock()
    store = SqliteConnectedAccountStore(
        settings.database_path, CredentialCipher(settings.master_key), clock, UuidIdGenerator()
    )
    directory = calendar_providers(settings, store, clock)
    outlook, google = directory.of(ProviderKind.OUTLOOK), directory.of(ProviderKind.GOOGLE)
    if outlook is None or outlook.calendars is None or google is None or google.calendars is None:
        raise SystemExit("Configure both Google and Microsoft in the environment first.")
    api = httpx.Client(
        base_url=os.environ.get("CALENDAR_GHOST_URL", "http://127.0.0.1:8000"), timeout=900
    )
    api.post(
        "/api/v1/session",
        json={
            "email": os.environ["CALENDAR_GHOST_EMAIL"],
            "password": os.environ["CALENDAR_GHOST_PASSWORD"],
        },
    ).raise_for_status()
    require_unlimited_runs(api)
    accounts: dict[str, list[str]] = {}
    for account in api.get("/api/v1/accounts").json():
        accounts.setdefault(account["provider"], []).append(account["id"])
    if len(accounts.get("outlook", [])) != 1 or len(accounts.get("google", [])) != 1:
        raise SystemExit("Connect exactly one Outlook and one Google account first.")
    outlook_id = ConnectedAccountId(accounts["outlook"][0])
    google_id = ConnectedAccountId(accounts["google"][0])
    return Live(
        api=api,
        outlook_token=lambda: outlook.calendars.access_token(outlook_id),  # type: ignore[union-attr]
        google=cast(Any, google.calendars).service_for(google_id),
        outlook_account=outlook_id.value,
        google_account=google_id.value,
    )


def main() -> int:
    live = connect()
    google_source, google_destination = (
        live.google_calendar(GOOGLE_SOURCE),
        live.google_calendar(GOOGLE_DESTINATION),
    )
    for calendar in (google_source, google_destination):
        if live.google_items(calendar, single_events=True):
            raise SystemExit(f"{calendar} is not empty; the checks need empty test calendars.")
    with cleanup(live, (google_source, google_destination)):
        runs: list[Callable[[], None]] = [
            lambda: graph_answers(live),
            lambda: outlook_to_outlook(live),
            lambda: google_to_outlook(live, google_source),
            lambda: outlook_to_google(live, google_destination),
        ]
        for run in runs:
            try:
                run()
            except Exception as error:  # A scenario that breaks is a failed check, not the end.
                live.check("run", "scenario completed", False, repr(error))
    print("| Scenario | Check | Result | Detail |\n| --- | --- | --- | --- |")
    for scenario, name, ok, detail in live.results:
        print(f"| {scenario} | {name} | {'pass' if ok else 'FAIL'} | {'' if ok else detail} |")
    return 0 if all(ok for *_, ok, _ in live.results) else 1


if __name__ == "__main__":
    sys.exit(main())
