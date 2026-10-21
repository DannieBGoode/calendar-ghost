from __future__ import annotations

from typing import (
    Literal,
)

from pydantic import (
    BaseModel,
    Field,
)

from calendar_sync.interfaces.api.schemas.shared import (
    ApiResponse,
    CauseValue,
    EffectiveCadenceValue,
    PrivacyPolicy,
    ProjectionChoice,
    TentativeChoice,
    UnansweredChoice,
    WorkKind,
)


class CalendarEndpointPayload(BaseModel):
    connected_account_id: str = Field(min_length=1)
    calendar_id: str = Field(min_length=1)


class NamedCalendarEndpointResponse(CalendarEndpointPayload):
    # The name the provider last gave the calendar, shown until it lists its calendars again.
    calendar_name: str | None


class CreateRuleRequest(BaseModel):
    source: CalendarEndpointPayload
    destination: CalendarEndpointPayload
    privacy_policy: PrivacyPolicy = "busy_only"
    sync_all_day_events: bool = True
    tentative_events: TentativeChoice = "mark"
    unanswered_invitations: UnansweredChoice = "as_tentative"
    # Whether to project the birthdays a provider keeps among the source calendar's events.
    sync_birthdays: bool = False


class RuleResponse(ApiResponse):
    id: str
    source: CalendarEndpointPayload
    destination: CalendarEndpointPayload
    privacy_policy: PrivacyPolicy
    sync_all_day_events: bool
    tentative_events: TentativeChoice
    unanswered_invitations: UnansweredChoice
    sync_birthdays: bool
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
    failure_provider: str | None = None
    """The Provider Kind of the calendar that failed, when a provider did."""
    last_succeeded_at: str | None


class PreviewSummaryResponse(ApiResponse):
    completed_at: str
    eligible_events: int
    excluded_events: int
    recurring_series: int
    occurrence_changes: int


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


class PreviewProjectionResponse(ApiResponse):
    """What the destination would hold for a previewed event."""

    title: str
    carries_details: bool
    """It copies the event's description or location (Details Projection)."""
    recurrence: list[str] | None
    """iCalendar recurrence lines, for the interface to describe in the reader's language."""


class PreviewItemResponse(ApiResponse):
    """One source event and what the rule would do with it; shown once, never stored."""

    source_event_id: str
    kind: Literal["single", "series", "occurrence"]
    title: str
    starts_at: str | None
    """A timed event's start, as an ISO 8601 instant; None for an all-day or cancelled event."""
    ends_at: str | None
    time_zone: str | None
    """The IANA zone a timed series repeats in, so its dates are stepped there; None otherwise."""
    starts_on: str | None
    """An all-day event's first day, as an ISO 8601 date."""
    ends_before: str | None
    """The day after an all-day event's last day."""
    recurrence: list[str] | None
    series_event_id: str | None
    original_start: str | None
    """An occurrence's regular start in its series: an instant, or a date for an all-day series."""
    cancelled: bool
    response: Literal["accepted", "tentative", "declined", "needs_action"]
    birthday: bool
    planned_action: Literal["create", "update", "delete", "ignore", "conflict"]
    reason: str
    projection: PreviewProjectionResponse | None
    """None when the destination would hold nothing for this event."""


class RulePreviewResponse(ApiResponse):
    rule_id: str
    eligible_events: int
    excluded_events: int
    recurring_series: int
    occurrence_changes: int
    items: list[PreviewItemResponse]


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
    effective_cadence: EffectiveCadenceValue
    poll_every_minutes: int
    """How often Scheduled Sync runs the rule, as the User's Plan says."""
    last_sync: RunOutcomeResponse | None
    latest_preview: PreviewSummaryResponse | None
    running: RuleWorkResponse | None
    keeps_place: bool
    """A Rule Replacement draft that keeps the previous rule's place under its User's rule limit,
    so starting it adds no rule to the count (ADR 0038)."""


class RuleDetailResponse(RuleResponse):
    source: NamedCalendarEndpointResponse
    destination: NamedCalendarEndpointResponse
    effective_cadence: EffectiveCadenceValue
    poll_every_minutes: int
    """How often Scheduled Sync runs the rule, as the User's Plan says."""
    initial_lookback_days: int
    mapping_count: int
    last_sync: RunOutcomeResponse | None
    last_reconciliation: RunOutcomeResponse | None
    latest_preview: PreviewSummaryResponse | None
    running: RuleWorkResponse | None
    can_start: bool
    """Whether the rule may start now under its User's rule limit; Start checks again."""
    rule_limit: int | None
    """The rule limit that applies to the User; null when none does."""
    keeps_place: bool
    """A Rule Replacement draft that keeps the previous rule's place under its User's rule limit,
    so starting it adds no rule to the count (ADR 0038)."""


class UpdateRulePolicyRequest(BaseModel):
    privacy_policy: PrivacyPolicy
    sync_all_day_events: bool
    tentative_events: TentativeChoice
    unanswered_invitations: UnansweredChoice
    sync_birthdays: bool


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


class ProviderConfigurationResponse(ApiResponse):
    configured: bool
    redirect_uri: str | None


class ProviderResponse(ApiResponse):
    """A calendar provider Users of this installation can connect, and how."""

    kind: str
    """Its Provider Kind, as Connected Accounts and problems name it."""
    display_name: str
    connect_url: str
    """Where the browser goes to connect an account of this provider."""
    redirect_uri: str
    """Where the provider returns the browser, as registered with it."""
    cause_anchors: dict[CauseValue, str]
    """The section of docs/troubleshooting.md explaining each administrator's Cause it can
    raise."""


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


class AccountAccessResponse(ApiResponse):
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
