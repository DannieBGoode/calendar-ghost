"""A series deleted in Google before a rule existed, read through the real Google adapter.

Google keeps a deleted event: `events.list` with `showDeleted` reports it, and `events.get`
answers it cancelled rather than not found. A new rule therefore reads the deleted series and its
moved occurrence, and must leave no trace of either.
"""

from __future__ import annotations

from calendar_sync.application.sync.locking import RuleLocks
from calendar_sync.application.sync.preview import PreviewSyncRule
from calendar_sync.application.sync.synchronization import ExecuteSyncRule
from calendar_sync.domain.model import EventId, EventRef, EventStatus, SyncRuleState
from calendar_sync.domain.services import (
    EventProjector,
    ProjectionFingerprinter,
    SyncDecisionService,
)
from calendar_sync.infrastructure.google.provider import GoogleCalendarProvider
from calendar_sync.infrastructure.identifiers import UuidRunIdGenerator
from tests.fake_calendar import FixedClock, enabled_rule_factory
from tests.fake_google_calendar_api import FakeGoogleCalendarApi
from tests.helpers import rule

SERIES = "cgtesta"
MOVED = f"{SERIES}_20260903T090000Z"


def _deleted_series() -> tuple[FakeGoogleCalendarApi, GoogleCalendarProvider]:
    google = FakeGoogleCalendarApi()
    source = rule().source
    google.seed(
        source,
        {
            "id": SERIES,
            "summary": "CG test A",
            "start": {"dateTime": "2026-09-01T09:00:00Z"},
            "end": {"dateTime": "2026-09-01T09:30:00Z"},
            "recurrence": ["RRULE:FREQ=DAILY;COUNT=5"],
        },
    )
    google.seed(
        source,
        {
            "id": MOVED,
            "summary": "CG test A",
            "recurringEventId": SERIES,
            "originalStartTime": {"dateTime": "2026-09-03T09:00:00Z"},
            "start": {"dateTime": "2026-09-05T16:15:00Z"},
            "end": {"dateTime": "2026-09-05T16:45:00Z"},
        },
    )
    google.remove(source, MOVED)
    google.remove(source, SERIES)
    return google, GoogleCalendarProvider(google.service_for)


def _decisions() -> SyncDecisionService:
    return SyncDecisionService(EventProjector(), ProjectionFingerprinter())


def test_google_answers_a_deleted_series_as_cancelled_not_missing() -> None:
    _google, provider = _deleted_series()

    deleted = provider.get_event(EventRef(rule().source, EventId(SERIES)))

    assert deleted is not None
    assert deleted.status is EventStatus.CANCELLED


def test_a_new_rule_records_and_writes_nothing_for_a_series_deleted_before_it() -> None:
    google, provider = _deleted_series()
    factory = enabled_rule_factory()

    result = ExecuteSyncRule(
        factory,
        provider,
        _decisions(),
        ProjectionFingerprinter(),
        FixedClock(),
        UuidRunIdGenerator(),
        RuleLocks(),
    ).execute(rule().id)

    assert factory.state.audit == []
    assert google.writes == []
    assert result.ignored == 2


def test_a_new_rules_preview_lists_nothing_for_a_series_deleted_before_it() -> None:
    _google, provider = _deleted_series()

    preview = PreviewSyncRule(
        enabled_rule_factory(rule(state=SyncRuleState.DRAFT)),
        provider,
        EventProjector(),
        FixedClock(),
        _decisions(),
        locks=RuleLocks(),
    ).execute(rule().id)

    assert preview.items == ()
    assert (preview.eligible_events, preview.excluded_events) == (0, 0)
