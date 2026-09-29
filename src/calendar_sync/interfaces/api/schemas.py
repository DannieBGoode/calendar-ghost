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
    last_succeeded_at: str | None


class PreviewSummaryResponse(BaseModel):
    completed_at: str
    eligible_events: int
    excluded_events: int
    recurring_series: int
    occurrence_changes: int


class RuleWorkResponse(BaseModel):
    kind: Literal["preview", "sync", "reconciliation", "removal"]
    started_at: str
    handling: Literal["delete", "detach"] | None
    total: int | None
    done: int


class RuleSummaryResponse(RuleResponse):
    last_sync: RunOutcomeResponse | None
    latest_preview: PreviewSummaryResponse | None
    running: RuleWorkResponse | None


class RuleDetailResponse(RuleResponse):
    initial_lookback_days: int
    mapping_count: int
    last_sync: RunOutcomeResponse | None
    last_reconciliation: RunOutcomeResponse | None
    latest_preview: PreviewSummaryResponse | None
    running: RuleWorkResponse | None


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
    blocked_events: int = 0
    """Events of existing rules whose latest decision was a block."""
    blocked_entry_id: int | None = None
    blocked_rule_id: str | None = None


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


class RecordedTimeResponse(BaseModel):
    all_day: bool = False
    starts: str | None = None
    ends: str | None = None


class RecordedEventResponse(BaseModel):
    """The source event as its run recorded it; see ADR 0014."""

    title: str
    all_day: bool = False
    starts: str | None = None
    ends: str | None = None
    recurring: bool = False
    cancelled: bool = False
    renamed_from: str | None = None
    moved_from: RecordedTimeResponse | None = None
    """The time the previous entry for this event recorded, when this entry saw it move."""


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
    event: RecordedEventResponse | None = None
    repeated: bool = False
    """A repair that redoes the same event's previous one, recorded by an earlier run."""


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


class RecentChangeResponse(BaseModel):
    """One written event; an identical repair repeated among recent entries is counted on it."""

    entry: AuditEntryResponse
    repeats: int
    first_occurred_at: str
