from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SetupStatusResponse(BaseModel):
    administrator_configured: bool


class PasswordRequest(BaseModel):
    password: str = Field(min_length=12, max_length=256)


class SessionResponse(BaseModel):
    authenticated: bool


class CalendarEndpointPayload(BaseModel):
    connected_account_id: str = Field(min_length=1)
    calendar_id: str = Field(min_length=1)


class CreateRuleRequest(BaseModel):
    source: CalendarEndpointPayload
    destination: CalendarEndpointPayload
    privacy_policy: str = "busy_only"
    sync_all_day_events: bool = True


class RuleResponse(BaseModel):
    id: str
    source: CalendarEndpointPayload
    destination: CalendarEndpointPayload
    privacy_policy: str
    sync_all_day_events: bool
    state: str


class DashboardResponse(BaseModel):
    health: str
    connected_accounts: int
    sync_rules: int
    open_incidents: int


class GoogleConfigurationResponse(BaseModel):
    configured: bool


class ConnectedAccountResponse(BaseModel):
    id: str
    display_name: str
    email: str
    state: str
    rule_count: int


class GoogleAccountAccessResponse(BaseModel):
    calendar_api: bool
    calendar_list_access: bool
    event_access: bool
    calendars_visible: int
    writable_calendars: int


class DiscoveredCalendarResponse(BaseModel):
    id: str
    summary: str
    access_role: str
    primary: bool


class AuditEntryResponse(BaseModel):
    id: int
    run_id: str | None
    occurred_at: str
    rule_id: str
    action: str
    outcome: str
    category: Literal["changed", "unchanged", "skipped", "blocked"]
    reason: str | None
    detail: str
    source_event_id: str | None
    destination_event_id: str | None


class EventSnapshotResponse(BaseModel):
    found: bool
    cancelled: bool = False
    title: str = ""
    all_day: bool = False
    starts: str | None = None
    ends: str | None = None
    recurring: bool = False
    web_link: str | None = None


class ActivityEventResponse(BaseModel):
    source: EventSnapshotResponse
    destination: EventSnapshotResponse | None


class IncidentResponse(BaseModel):
    id: str
    rule_id: str | None
    category: str
    state: str
    summary: str
    opened_at: str
    updated_at: str
