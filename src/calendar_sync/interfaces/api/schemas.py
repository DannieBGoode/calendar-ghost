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


class PreviewSummaryResponse(BaseModel):
    completed_at: str
    eligible_events: int
    excluded_events: int
    recurring_series: int
    occurrence_changes: int


class RuleSummaryResponse(RuleResponse):
    last_sync: RunOutcomeResponse | None
    latest_preview: PreviewSummaryResponse | None


class RecentChangeResponse(BaseModel):
    run_key: str
    rule_id: str
    occurred_at: str
    created: int
    updated: int
    deleted: int
    repaired: int
    blocked: int
    entry_ids: list[int]


class RuleDetailResponse(RuleResponse):
    initial_lookback_days: int
    mapping_count: int
    last_sync: RunOutcomeResponse | None
    last_reconciliation: RunOutcomeResponse | None
    latest_preview: PreviewSummaryResponse | None


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
    conflicts: int


class RuleReplacementResponse(BaseModel):
    rule: RuleResponse
    deleted: int
    detached: int
    conflicts: int


class DashboardResponse(BaseModel):
    health: str
    connected_accounts: int
    disconnected_accounts: int
    sync_rules: int
    enabled_rules: int
    stopped_rules: int
    open_incidents: int
    last_synced_at: str | None


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
