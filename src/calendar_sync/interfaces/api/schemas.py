from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ProjectionChoice = Literal["delete", "detach"]


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
    reprojection_required: bool


class RunOutcomeResponse(BaseModel):
    completed_at: str
    succeeded: bool
    full_run: bool
    created: int
    updated: int
    deleted: int
    conflicts: int
    checked_mappings: int
    drift: int
    failure_kind: str | None


class RuleDetailResponse(RuleResponse):
    initial_lookback_days: int
    mapping_count: int
    last_sync: RunOutcomeResponse | None
    last_reconciliation: RunOutcomeResponse | None


class UpdateRulePolicyRequest(BaseModel):
    privacy_policy: str
    sync_all_day_events: bool


class ReplaceRuleRequest(BaseModel):
    source: CalendarEndpointPayload
    destination: CalendarEndpointPayload
    projections: ProjectionChoice


class RemovalResponse(BaseModel):
    deleted: int
    detached: int


class RuleReplacementResponse(BaseModel):
    rule: RuleResponse
    deleted: int
    detached: int


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
    avatar_url: str | None
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
