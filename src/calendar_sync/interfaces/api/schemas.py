from __future__ import annotations

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
    redirect_uri: str | None


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
    occurred_at: str
    rule_id: str
    action: str
    outcome: str
    detail: str


class IncidentResponse(BaseModel):
    id: str
    rule_id: str | None
    category: str
    state: str
    summary: str
    opened_at: str
    updated_at: str
