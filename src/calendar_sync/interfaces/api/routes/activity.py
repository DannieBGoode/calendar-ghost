from __future__ import annotations

import asyncio
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, HTTPException, Query, status

from calendar_sync.application.activity import (
    ActivityCategory,
    ActivityEntry,
    ActivityEvent,
    ActivityFilter,
    ActivityQueries,
    GetDashboard,
    InspectActivityEvent,
    RecordedTime,
)
from calendar_sync.application.errors import (
    ActivityEventNotFound,
    ActivityRuleRemoved,
    EventInspectionUnavailable,
    ProviderFailure,
)
from calendar_sync.domain.model import CalendarEvent, EventStatus, TimedInterval
from calendar_sync.interfaces.api.dependencies import app_services, require_admin
from calendar_sync.interfaces.api.schemas import (
    ActivityEventResponse,
    AuditEntryResponse,
    DashboardResponse,
    EventSnapshotResponse,
    RecentChangeResponse,
    RecordedEventResponse,
    RecordedTimeResponse,
)


class ActivityServices(Protocol):
    @property
    def activity(self) -> ActivityQueries: ...
    @property
    def get_dashboard(self) -> GetDashboard: ...
    @property
    def inspect_activity_event(self) -> InspectActivityEvent: ...


Services = Annotated[ActivityServices, Depends(app_services)]
router = APIRouter()


@router.get(
    "/api/v1/dashboard",
    response_model=DashboardResponse,
    dependencies=[Depends(require_admin)],
)
def dashboard(services: Services) -> DashboardResponse:
    summary = services.get_dashboard.execute()
    return DashboardResponse(
        health="healthy" if summary.healthy else "attention",
        connected_accounts=summary.connected_accounts,
        disconnected_accounts=summary.disconnected_accounts,
        sync_rules=summary.sync_rules,
        enabled_rules=summary.enabled_rules,
        stopped_rules=summary.stopped_rules,
        open_incidents=summary.open_incidents,
        last_synced_at=summary.last_synced_at,
        blocked_events=summary.blocked_events,
        blocked_entry_id=summary.blocked_entry_id,
        blocked_rule_id=summary.blocked_rule_id,
    )


@router.get(
    "/api/v1/audit-entries",
    response_model=list[AuditEntryResponse],
    dependencies=[Depends(require_admin)],
)
def list_activity(
    services: Services,
    rule_id: str | None = None,
    category: Annotated[list[ActivityCategory] | None, Query()] = None,
    before: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> list[AuditEntryResponse]:
    selection = ActivityFilter(
        rule_id=rule_id,
        categories=frozenset(category or ()),
        before=before,
        limit=limit,
        search=q,
    )
    return [_entry_response(entry) for entry in services.activity.entries(selection)]


@router.get(
    "/api/v1/audit-entries/{entry_id}",
    response_model=AuditEntryResponse,
    dependencies=[Depends(require_admin)],
)
def get_activity_entry(entry_id: int, services: Services) -> AuditEntryResponse:
    entry = services.activity.entry(entry_id)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "activity entry not found")
    return _entry_response(entry)


@router.get(
    "/api/v1/recent-changes",
    response_model=list[RecentChangeResponse],
    dependencies=[Depends(require_admin)],
)
def recent_changes(
    services: Services,
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
) -> list[RecentChangeResponse]:
    return [
        RecentChangeResponse(
            entry=_entry_response(change.entry),
            repeats=change.repeats,
            first_occurred_at=change.first_occurred_at,
        )
        for change in services.activity.recent_changes(limit)
    ]


@router.get(
    "/api/v1/audit-entries/{entry_id}/event",
    response_model=ActivityEventResponse,
    dependencies=[Depends(require_admin)],
)
async def inspect_activity_event(entry_id: int, services: Services) -> ActivityEventResponse:
    try:
        inspected = await asyncio.to_thread(services.inspect_activity_event.execute, entry_id)
    except ActivityEventNotFound as error:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "activity entry has no source event"
        ) from error
    except ActivityRuleRemoved as error:
        raise HTTPException(
            status.HTTP_410_GONE,
            "the rule for this activity entry was removed, so its events cannot be looked up",
        ) from error
    except EventInspectionUnavailable as error:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "configure Google OAuth and the installation master key before inspecting events",
        ) from error
    except ProviderFailure as error:
        raise HTTPException(
            status.HTTP_424_FAILED_DEPENDENCY,
            f"Google could not return this event: {error.kind.value}",
        ) from error
    return ActivityEventResponse(
        source=_event_snapshot(inspected.source),
        destination=(
            _event_snapshot(inspected.destination) if inspected.destination_recorded else None
        ),
    )


def _entry_response(entry: ActivityEntry) -> AuditEntryResponse:
    return AuditEntryResponse(
        id=entry.id,
        run_id=entry.run_id,
        occurred_at=entry.occurred_at,
        rule_id=entry.rule_id,
        action=entry.action,
        outcome=entry.outcome,
        category=entry.category,
        reason=entry.reason,
        detail=entry.detail,
        source_event_id=entry.source_event_id,
        destination_event_id=entry.destination_event_id,
        event=_recorded_event_response(entry.event) if entry.event is not None else None,
        repeated=entry.repeated,
    )


def _recorded_event_response(event: ActivityEvent) -> RecordedEventResponse:
    return RecordedEventResponse(
        title=event.title,
        all_day=event.all_day,
        starts=event.starts,
        ends=event.ends,
        recurring=event.recurring,
        cancelled=event.cancelled,
        renamed_from=event.renamed_from,
        moved_from=_recorded_time_response(event.moved_from) if event.moved_from else None,
    )


def _recorded_time_response(time: RecordedTime) -> RecordedTimeResponse:
    return RecordedTimeResponse(all_day=time.all_day, starts=time.starts, ends=time.ends)


def _event_snapshot(event: CalendarEvent | None) -> EventSnapshotResponse:
    if event is None:
        return EventSnapshotResponse(found=False)
    # Google keeps a cancelled event's title for a while; it names what was removed.
    cancelled = event.status is EventStatus.CANCELLED
    time = event.time
    if time is None:
        return EventSnapshotResponse(
            found=True, cancelled=True, title=event.title, web_link=event.web_link
        )
    if isinstance(time, TimedInterval):
        starts, ends = time.starts_at.isoformat(), time.ends_at.isoformat()
    else:
        starts, ends = time.starts_on.isoformat(), time.ends_before.isoformat()
    return EventSnapshotResponse(
        found=True,
        cancelled=cancelled,
        title=event.title,
        all_day=event.is_all_day,
        starts=starts,
        ends=ends,
        recurring=event.recurrence is not None or event.occurrence is not None,
        web_link=event.web_link,
    )
