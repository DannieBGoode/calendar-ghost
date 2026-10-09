from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from calendar_sync.application.ports import IncidentResolutionValue, IncidentState

ProjectionChoice = Literal["delete", "detach"]
# What a rule does with events its source calendar answered Maybe to, or has not answered yet.
TentativeChoice = Literal["sync", "mark", "skip"]
UnansweredChoice = Literal["wait", "as_tentative"]
PrivacyPolicy = Literal["busy_only", "copy_details"]
# The values of application.status.StatusVerdict and ProblemKind, so the schema lists them.
StatusVerdictValue = Literal[
    "stalled", "stopped", "review", "waiting", "paused", "setup", "healthy"
]
ProblemKindValue = Literal["stalled", "stopped", "review", "overdue", "blocked", "waiting"]


class ApiResponse(BaseModel):
    """A response body. Every field is always sent, so the schema marks defaulted ones required,
    and the frontend types generated from it (web/openapi.json) do not make them optional."""

    model_config = ConfigDict(
        json_schema_mode_override="serialization",
        json_schema_serialization_defaults_required=True,
    )


class SetupStatusResponse(ApiResponse):
    administrator_configured: bool
    password_only_sign_in: bool
    """Whether the upgraded first User may still sign in by password alone."""


class SetupRequest(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(min_length=12, max_length=256)


class SignInRequest(BaseModel):
    email: str | None = Field(default=None, max_length=320)
    """Left out only by the upgraded first User, until they add an email."""
    password: str = Field(min_length=1, max_length=256)


class SignedInUserResponse(ApiResponse):
    id: str
    email: str | None
    """None until the upgraded first User adds one, which they must do first."""
    role: Literal["installation_administrator", "user"]
    notify_by_email: bool
    language: str | None


class SessionResponse(ApiResponse):
    authenticated: bool
    user: SignedInUserResponse | None = None
    installation_sends_email: bool = False
    """Whether Incident Notifications can also reach a User by email."""


class SetEmailRequest(BaseModel):
    email: str = Field(max_length=320)
    password: str | None = Field(default=None, max_length=256)
    """The current password, needed to change an email but not to add the first one."""


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


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


class IncidentMessageResponse(ApiResponse):
    """What an Incident says as a stable code and parameters the Web UI translates (ADR 0026)."""

    code: str
    params: dict[str, str | int | None]


class ProblemResponse(ApiResponse):
    kind: ProblemKindValue
    rule_id: str | None
    summary: str
    since: str | None
    message: IncidentMessageResponse | None
    """The message of the Incident behind the problem; None when no Incident names it."""


class DashboardResponse(ApiResponse):
    status: StatusVerdictValue
    needs_attention: bool
    problems: list[ProblemResponse]
    connected_accounts: int
    disconnected_accounts: int
    lapsed_accounts: int
    """Connected accounts whose authorization lapsed and that need reauthorization."""
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
    authorization_lapsed_at: str | None
    """While the provider refuses the account, when the latest refused request began; null while
    it accepts it (ADR 0027)."""


class GoogleAccountAccessResponse(ApiResponse):
    calendar_api: bool
    calendar_list_access: bool
    event_access: bool
    calendars_visible: int
    writable_calendars: int
    rules_resumed: int
    """Rules that Lapsed Authorization alone had stopped, resumed because the check passed."""


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
    message: IncidentMessageResponse | None
    """None for an Incident recorded before messages, or one whose message is unreadable."""


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


class SchedulerResponse(ApiResponse):
    configured: bool
    """Whether this installation runs a scheduler; `status` says whether it is keeping up."""
    last_pass_completed_at: str | None
    current_pass_started_at: str | None


class StatusCountsResponse(ApiResponse):
    rules: int
    running: int
    """Enabled rules that are not stopped."""
    stopped: int
    paused: int
    overdue: int
    open_incidents: int
    blocked_events: int
    disconnected_accounts: int
    lapsed_accounts: int
    """Connected accounts whose authorization lapsed and that need reauthorization."""


class StatusCalendarResponse(ApiResponse):
    calendar: str
    provider: str | None


class StatusRuleResponse(ApiResponse):
    id: str
    name: str
    state: str
    source: StatusCalendarResponse
    destination: StatusCalendarResponse
    projection: str
    last_succeeded_at: str | None
    running: str | None
    problem: ProblemResponse | None


class StatusIncidentResponse(ApiResponse):
    rule_id: str | None
    category: str
    summary: str
    opened_at: str


class StatusResponse(ApiResponse):
    status: StatusVerdictValue
    needs_attention: bool
    summary: str
    version: str
    checked_at: str
    last_synced_at: str | None
    scheduler: SchedulerResponse
    counts: StatusCountsResponse
    problems: list[ProblemResponse]
    rules: list[StatusRuleResponse]
    incidents: list[StatusIncidentResponse]


TokenScope = Literal["installation:read", "status:read"]
_STATUS_READ: TokenScope = "status:read"


class IntegrationTokenResponse(ApiResponse):
    id: str
    name: str
    scopes: list[TokenScope]
    created_at: str
    last_used_at: str | None
    revoked_at: str | None


class IssuedIntegrationTokenResponse(IntegrationTokenResponse):
    token: str


class IssueIntegrationTokenRequest(BaseModel):
    name: str = Field(max_length=200)
    scopes: list[TokenScope] = Field(default_factory=lambda: [_STATUS_READ], min_length=1)
    """installation:read is for Installation Administrators only (ADR 0030)."""


class RegistrationResponse(ApiResponse):
    policy: Literal["only_me", "invitation_only"]
    only_me_available: bool
    """Whether Only Me may be chosen now: only while no other User exists."""


class RegistrationRequest(BaseModel):
    policy: Literal["only_me", "invitation_only"]


class IssuedLinkResponse(ApiResponse):
    id: str
    token: str
    """Shown once: the Web UI builds the link from it; only its hash is kept."""
    expires_at: str


class PendingInvitationResponse(ApiResponse):
    id: str
    created_at: str
    expires_at: str


class LinkRequest(BaseModel):
    token: str = Field(min_length=1, max_length=200)


class LinkStatusResponse(ApiResponse):
    usable: bool


class AcceptInvitationRequest(BaseModel):
    token: str = Field(min_length=1, max_length=200)
    email: str = Field(max_length=320)
    password: str = Field(max_length=256)


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=1, max_length=200)
    password: str = Field(max_length=256)


class UserResponse(ApiResponse):
    id: str
    email: str | None
    role: Literal["installation_administrator", "user"]
    state: Literal["active", "disabled"]
    created_at: str
    last_sign_in_at: str | None


class ProviderCallsResponse(ApiResponse):
    provider: str
    calls: int
    rate_limited: int
    """Calls the provider refused for its rate limit or quota."""
    failed: int
    """Calls with no answer, or answered with an error other than a rate limit or not found."""


class ResourceUseResponse(ApiResponse):
    """How much one User uses, in counts; never what their records say."""

    rules: int
    connected_accounts: int
    activity_entries: int
    provider_calls: list[ProviderCallsResponse]
    """Each provider's calls from `since` on, by provider."""
    since: str
    """The first UTC day the provider calls count, as an ISO date."""


class PersonResponse(UserResponse):
    """A row of People: who the User is, and the Operator Overview's summary of them."""

    verdict: StatusVerdictValue
    """Their Installation Status, as their own Overview shows it."""
    problems: int
    last_synced_at: str | None
    resources: ResourceUseResponse


class UserOverviewResponse(ApiResponse):
    """What the Operator Overview shows about one User, to an administrator and to that User:
    their Installation Status with calendars named "Calendar 1", "Calendar 2", and so on, and
    their resource use. Never a calendar's name or identifier, an account's email, or an event."""

    user: UserResponse
    status: StatusResponse
    resources: ResourceUseResponse


class UserPageResponse(ApiResponse):
    users: list[PersonResponse]
    total: int
    """How many people match, across every page."""
    page: int
    page_size: int


class PeopleQuery(BaseModel):
    """Which people one page of People shows, as its address names them."""

    search: str = Field(default="", max_length=200)
    role: Literal["installation_administrator", "user"] | None = None
    state: Literal["active", "disabled"] | None = None
    verdict: StatusVerdictValue | None = None
    """Only people whose Installation Status has this verdict."""
    sort: Literal["joined", "email", "last_sign_in", "verdict"] = "joined"
    """By verdict, the most urgent comes first in ascending order."""
    order: Literal["asc", "desc"] = "asc"
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=100)


class RoleRequest(BaseModel):
    role: Literal["installation_administrator", "user"]


class UserStateRequest(BaseModel):
    state: Literal["active", "disabled"]


class DeleteOwnAccountRequest(BaseModel):
    password: str = Field(max_length=256)
    projections: ProjectionChoice


class UserDeletionResponse(ApiResponse):
    rules: int
    deleted: int
    detached: int
    left: int
    """Rules whose projections nothing could delete; they stay in their calendars."""


class OwnAccountDeletionResponse(ApiResponse):
    needs_another_administrator: bool
    """The User is the last Installation Administrator and someone else remains."""
    last_user: bool
    """Nobody would remain, so the installation would return to setup."""


class InstallationIncidentResponse(ApiResponse):
    kind: Literal["scheduler_stalled"]
    since: str


class InstallationHealthResponse(ApiResponse):
    """The whole installation's verdict; it names no rule, calendar, or User (ADR 0030)."""

    status: StatusVerdictValue
    needs_attention: bool
    incidents: list[InstallationIncidentResponse]
    users: dict[StatusVerdictValue, int]
    """How many Users who may sign in are in each Installation Status verdict."""
    disabled_users: int
    checked_at: str


class NotificationPreferenceRequest(BaseModel):
    notify_by_email: bool
