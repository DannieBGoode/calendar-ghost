from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from calendar_sync.application.activity import IncidentResolutionValue, IncidentState

ProjectionChoice = Literal["delete", "detach"]
# What a rule does with events its source calendar answered Maybe to, or has not answered yet.
TentativeChoice = Literal["sync", "mark", "skip"]
UnansweredChoice = Literal["wait", "as_tentative"]
PrivacyPolicy = Literal["busy_only", "copy_details"]


class ApiResponse(BaseModel):
    """A response body. Every field is always sent, so the schema marks defaulted ones required,
    and the frontend types generated from it (web/openapi.json) do not make them optional."""

    model_config = ConfigDict(
        json_schema_mode_override="serialization",
        json_schema_serialization_defaults_required=True,
    )


class SetupStatusResponse(ApiResponse):
    administrator_configured: bool


class PasswordRequest(BaseModel):
    password: str = Field(min_length=12, max_length=256)


class SessionResponse(ApiResponse):
    authenticated: bool


class CalendarEndpointPayload(BaseModel):
    connected_account_id: str = Field(min_length=1)
    calendar_id: str = Field(min_length=1)


class NamedCalendarEndpointResponse(CalendarEndpointPayload):
    # The name Google last gave the calendar, shown until Google lists its calendars again.
    calendar_name: str | None


class CreateRuleRequest(BaseModel):
    source: CalendarEndpointPayload
    destination: CalendarEndpointPayload
    privacy_policy: PrivacyPolicy = "busy_only"
    sync_all_day_events: bool = True
    tentative_events: TentativeChoice = "mark"
    unanswered_invitations: UnansweredChoice = "as_tentative"


class RuleResponse(ApiResponse):
    id: str
    source: CalendarEndpointPayload
    destination: CalendarEndpointPayload
    privacy_policy: PrivacyPolicy
    sync_all_day_events: bool
    tentative_events: TentativeChoice
    unanswered_invitations: UnansweredChoice
    state: str
    reprojection_required: bool


class RunOutcomeResponse(ApiResponse):
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


class PreviewSummaryResponse(ApiResponse):
    completed_at: str
    eligible_events: int
    excluded_events: int
    recurring_series: int
    occurrence_changes: int


WorkKind = Literal["preview", "sync", "reconciliation", "removal"]


class SyncResultResponse(ApiResponse):
    rule_id: str
    created: int
    updated: int
    deleted: int
    ignored: int
    conflicts: int


class DriftResponse(ApiResponse):
    kind: str
    detail: str


class ReconciliationConflictResponse(ApiResponse):
    reason: str
    detail: str


class ReconcileResultResponse(SyncResultResponse):
    consistent: bool
    checked_mappings: int
    drift: list[DriftResponse]
    """What is still different after the sync; reported, not repaired."""
    reconciliation_conflicts: list[ReconciliationConflictResponse]
    """Blocked by the reconciliation itself, beside the sync's own `conflicts`."""


class PreviewItemResponse(ApiResponse):
    source_event_id: str
    projected_title: str
    all_day: bool
    kind: Literal["single", "series", "occurrence"]
    planned_action: Literal["create", "update", "delete", "ignore", "conflict"]


class RulePreviewResponse(ApiResponse):
    rule_id: str
    eligible_events: int
    excluded_events: int
    recurring_series: int
    occurrence_changes: int
    sample: list[PreviewItemResponse]


class RuleWorkResponse(ApiResponse):
    kind: WorkKind
    started_at: str
    handling: Literal["delete", "detach"] | None
    total: int | None
    done: int
    # Reconcile Now's part running now: its full pass ("sync"), then the check.
    stage: WorkKind | None


class RuleSummaryResponse(RuleResponse):
    source: NamedCalendarEndpointResponse
    destination: NamedCalendarEndpointResponse
    last_sync: RunOutcomeResponse | None
    latest_preview: PreviewSummaryResponse | None
    running: RuleWorkResponse | None


class RuleDetailResponse(RuleResponse):
    source: NamedCalendarEndpointResponse
    destination: NamedCalendarEndpointResponse
    initial_lookback_days: int
    mapping_count: int
    last_sync: RunOutcomeResponse | None
    last_reconciliation: RunOutcomeResponse | None
    latest_preview: PreviewSummaryResponse | None
    running: RuleWorkResponse | None


class UpdateRulePolicyRequest(BaseModel):
    privacy_policy: PrivacyPolicy
    sync_all_day_events: bool
    tentative_events: TentativeChoice
    unanswered_invitations: UnansweredChoice


class ReplaceRuleRequest(BaseModel):
    source: CalendarEndpointPayload
    destination: CalendarEndpointPayload
    projections: ProjectionChoice


class RemovalResponse(ApiResponse):
    deleted: int
    detached: int
    conflicts: int


class RuleReplacementResponse(ApiResponse):
    rule: RuleResponse
    deleted: int
    detached: int
    conflicts: int


class DashboardResponse(ApiResponse):
    health: Literal["healthy", "attention"]
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


class GoogleConfigurationResponse(ApiResponse):
    configured: bool
    redirect_uri: str | None


class ConnectedAccountResponse(ApiResponse):
    id: str
    display_name: str
    email: str
    provider: str
    avatar_url: str | None
    state: str
    rule_count: int
    authorized_at: str | None


class GoogleAccountAccessResponse(ApiResponse):
    calendar_api: bool
    calendar_list_access: bool
    event_access: bool
    calendars_visible: int
    writable_calendars: int


class DiscoveredCalendarResponse(ApiResponse):
    id: str
    summary: str
    access_role: str
    """Kept for compatibility at its original values; `writable` is the provider-neutral answer
    (ADR 0022)."""
    writable: bool
    primary: bool


class RecordedTimeResponse(ApiResponse):
    all_day: bool = False
    starts: str | None = None
    ends: str | None = None


class RecordedEventResponse(ApiResponse):
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


class AuditEntryResponse(ApiResponse):
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
    changed_fields: list[str] | None = None
    """The source fields this entry's Source Change touched (ADR 0017); None when none."""


class FieldChangeResponse(ApiResponse):
    field: str
    before: str | None = None
    after: str | None = None
    before_time: RecordedTimeResponse | None = None
    after_time: RecordedTimeResponse | None = None
    added: list[str] = []
    removed: list[str] = []


class SourceChangeResponse(ApiResponse):
    """What changed in the entry's source event; values are kept for 90 days."""

    fields: list[str]
    values_available: bool
    changes: list[FieldChangeResponse]


class EventSnapshotResponse(ApiResponse):
    found: bool
    cancelled: bool = False
    title: str = ""
    all_day: bool = False
    starts: str | None = None
    ends: str | None = None
    recurring: bool = False
    web_link: str | None = None


class ActivityEventResponse(ApiResponse):
    source: EventSnapshotResponse
    destination: EventSnapshotResponse | None


class IncidentResponse(ApiResponse):
    id: str
    rule_id: str | None
    category: str
    state: IncidentState
    summary: str
    opened_at: str
    updated_at: str
    resolved_at: str | None
    resolution: IncidentResolutionValue | None
    account_id: str | None


class DatabaseUsageResponse(ApiResponse):
    bytes: int
    reclaimable_bytes: int
    activity_entries: int
    oldest_activity_at: str | None


class LogUsageResponse(ApiResponse):
    bytes: int
    files: int
    oldest_at: str | None
    newest_at: str | None


class StorageResponse(ApiResponse):
    database: DatabaseUsageResponse
    logs: LogUsageResponse | None
    activity_ages: list[int]


class ClearableActivityResponse(ApiResponse):
    older_than_days: int
    entries: int


class ClearActivityRequest(BaseModel):
    older_than_days: int


class ClearedActivityResponse(ApiResponse):
    removed: int
    database: DatabaseUsageResponse


class RecentChangeResponse(ApiResponse):
    """One written event; an identical repair repeated among recent entries is counted on it."""

    entry: AuditEntryResponse
    repeats: int
    first_occurred_at: str
