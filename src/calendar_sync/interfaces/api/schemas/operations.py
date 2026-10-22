from __future__ import annotations

from typing import (
    Literal,
)

from pydantic import (
    BaseModel,
    Field,
)

from calendar_sync.interfaces.api.schemas.identity import (
    AppliedPlanResponse,
    PlanLimitsResponse,
    PlanNameResponse,
    UserResponse,
)
from calendar_sync.interfaces.api.schemas.shared import (
    AllowanceBasisValue,
    ApiResponse,
    CauseValue,
    FieldChangeResponse,
    FoundByValue,
    HintKindValue,
    IncidentCategoryValue,
    IncidentMessageResponse,
    LimitedResourceValue,
    ProblemKindValue,
    RecordedTimeResponse,
    RulePlaceValue,
    RuleStopCauseValue,
    RunReasonValue,
    SourceComparisonValue,
    StatusVerdictValue,
    SyncIntervalValue,
)


class ProblemResponse(ApiResponse):
    kind: ProblemKindValue
    rule_id: str | None
    summary: str
    since: str | None
    message: IncidentMessageResponse | None
    """The message of the Incident behind the problem; None when no Incident names it."""
    cause: CauseValue | None = None
    """Why the provider failure behind it happened; None when no provider failure explains it."""
    last_tried_at: str | None = None
    """When that failure last happened, which is when the rule was last tried."""
    provider: str | None = None
    """The Provider Kind whose failure explains it; None when no provider failure does."""


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
    """Enabled rules, running or stopped."""
    running_rules: int
    """Enabled rules that have not stopped, as the status API's `counts.running`."""
    held_rules: int
    """Rules on Plan Hold, which release automatically when their Allowance permits."""
    stopped_rules: int
    """Rules that do not synchronize until someone acts, as the status API's `counts.stopped`."""
    open_incidents: int
    last_synced_at: str | None
    blocked_events: int = 0
    """Events of existing rules whose latest decision was a block."""
    blocked_entry_id: int | None = None
    blocked_rule_id: str | None = None
    next_pass_at: str | None = None
    """When the scheduler next tries every rule, so waiting on a provider says when it tries
    again."""


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
    run_reason: RunReasonValue | None = None
    """Why the Sync Run read the calendars as it did (ADR 0037); None for earlier entries."""
    found_by: FoundByValue | None = None
    """Which work led to the decision (ADR 0037); None for earlier entries."""
    source_comparison: SourceComparisonValue | None = None
    """How the source event compared with the rule's Source Observation; None when not compared."""


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
    next_pass_at: str | None = None
    """When the next pass begins; None while one runs or without a scheduler."""


class StatusCountsResponse(ApiResponse):
    rules: int
    running: int
    """Enabled rules that are not stopped."""
    stopped: int
    """Rules that do not synchronize until someone acts: each has a `stopped` problem."""
    paused: int
    held: int
    overdue: int
    open_incidents: int
    blocked_events: int
    disconnected_accounts: int
    lapsed_accounts: int
    """Connected accounts whose authorization lapsed and that need reauthorization."""


class StatusCalendarResponse(ApiResponse):
    calendar: str
    provider: str | None
    number: int | None
    """In the Operator Overview, the calendar's neutral number, as in "Calendar 1", which stands
    in for its name; None in a User's own status, which names the calendar."""


class StatusRuleResponse(ApiResponse):
    id: str
    name: str
    state: str
    stop_cause: RuleStopCauseValue | None
    source: StatusCalendarResponse
    destination: StatusCalendarResponse
    projection: str
    last_succeeded_at: str | None
    running: str | None
    problem: ProblemResponse | None


class StatusIncidentResponse(ApiResponse):
    rule_id: str | None
    category: IncidentCategoryValue
    summary: str
    opened_at: str
    cause: CauseValue | None = None


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


class OverLimitResponse(ApiResponse):
    """One limit a person has more of than their Plan allows: they keep everything, but cannot
    add another until they are within it."""

    limit: LimitedResourceValue
    in_use: int
    """Rules that count toward the rule limit, every calendar account, Disconnected Accounts
    included, or unrevoked Integration Tokens."""
    allowed: int


class LimitUseResponse(ApiResponse):
    """How many of one resource a person has, beside what the Plan they have allows."""

    in_use: int
    allowed: int | None
    """What the Plan allows; null when it sets no limit, and 0 for Integration Tokens it does
    not include."""


class PersonPlanUseResponse(ApiResponse):
    """How much of the Plan they have a person uses, each count beside its limit, for the
    meters on their page (ADR 0030, amended, for the token count). Counts only."""

    rules: LimitUseResponse
    """Rules that count toward the rule limit: Active Rules."""
    connected_accounts: LimitUseResponse
    """Calendar accounts, Disconnected Accounts included."""
    integration_tokens: LimitUseResponse
    """Unrevoked Integration Tokens."""
    sync_interval: SyncIntervalValue
    """How soon the Plan they have syncs their rules, which counts nothing."""


class PersonPlanOverviewResponse(ApiResponse):
    """A person's Plan, as the Operator Overview shows it on their page and their row of People
    (ADR 0038)."""

    basis: AllowanceBasisValue
    plan: AppliedPlanResponse | None
    """The Plan that limits them; null unless the basis is "plan"."""
    assigned: PlanNameResponse | None
    """Their own Plan, whatever the basis; null when they have the Default Plan."""
    has: AppliedPlanResponse | None
    """The Plan they have, whether or not it limits them now: their own, or else the Default
    Plan; null when they have neither. People finds them by it."""
    over: list[OverLimitResponse]
    """Each limit of the Plan they have that they have more of than it allows, rules first,
    whether or not Plans are on; empty for an administrator or a disabled person, whom no Plan
    limits."""
    assigned_by: str | None
    """The email of the administrator who gave them their own Plan; null while they have the
    Default Plan, and when billing gave it or that administrator was deleted or has no email."""
    assigned_at: str | None
    """When their own Plan was last given, in ISO 8601; null while they have the Default Plan,
    or when nothing recorded it."""
    use: PersonPlanUseResponse | None
    """How much of the Plan they have they use, whoever they are; null when they have no Plan."""


class OwnPlanGraceResponse(ApiResponse):
    holds_at: str
    rule_limit: int
    held: int
    reserved: int


class RuleStandingResponse(ApiResponse):
    rule_id: str
    place: RulePlaceValue
    kept: bool


class OwnPlanResponse(ApiResponse):
    """What the signed-in User's Plan allows and how much of it they have, for Your plan."""

    basis: AllowanceBasisValue
    plan: AppliedPlanResponse | None
    """The Plan that limits them; null unless the basis is "plan"."""
    limits: PlanLimitsResponse | None
    """What their Plan allows; null unless the basis is "plan", since then nothing limits them."""
    rules_counted: int
    held_rules: int
    grace: OwnPlanGraceResponse | None
    rules: list[RuleStandingResponse]
    connected_accounts: int
    """Every calendar account, Disconnected Accounts included."""
    integration_tokens: int
    """Unrevoked Integration Tokens."""
    instant: bool
    """Whether their Plan includes Instant Sync."""
    poll_every_minutes: int
    """How often Scheduled Sync runs their rules, as their Plan says."""
    may_connect_account: bool
    may_issue_token: bool
    over_rule_limit: bool
    """More rules count than the current rule limit."""


class PlanAssignmentsRequest(BaseModel):
    # No length bound here: more than 100 people, or none, answers 422 invalid_assignment with
    # its reason, and an identifier that names no User answers the same. Each Plan is bounded by
    # the Plan key's own check, as `PlansSettingRequest.default_plan` is.
    plans: dict[str, str | None]
    """1 to 100 Users by identifier, each with the key of the Plan to give them, or null to
    return them to the Default Plan; all of them move, or none does."""
    dry_run: bool = False
    """Give nothing, and answer what giving it would do."""


class PlanMoveResponse(ApiResponse):
    """One person given a Plan, or who would be in a dry run."""

    user_id: str
    email: str | None
    had: AppliedPlanResponse | None
    """The Plan they had: their own, or else the Default Plan; null when they had neither."""
    has: AppliedPlanResponse | None
    """The Plan they have now, or would have in a dry run; null when it is the Default Plan and
    there is none."""
    over: list[OverLimitResponse]
    """Each limit of the Plan they have that they have more of than it allows, rules first,
    whether or not Plans are on; empty for an administrator or a disabled person."""


class PlanAssignmentsResponse(ApiResponse):
    """Everyone a Plan was given to, in the order named, or would be in a dry run."""

    dry_run: bool
    """Whether nothing was given."""
    people: list[PlanMoveResponse]


class PersonResponse(UserResponse):
    """A row of People: who the User is, and the Operator Overview's summary of them."""

    verdict: StatusVerdictValue
    """Their Installation Status, as their own Overview shows it."""
    problems: int
    last_synced_at: str | None
    resources: ResourceUseResponse
    plan: PersonPlanOverviewResponse | None
    """Their Plan, as their page shows it; null while no Plan exists (ADR 0038)."""


class UserOverviewResponse(ApiResponse):
    """What the Operator Overview shows about one User, to an administrator and to that User:
    their Installation Status with calendars named "Calendar 1", "Calendar 2", and so on, and
    their resource use. Never a calendar's name or identifier, an account's email, or an event."""

    user: UserResponse
    status: StatusResponse
    resources: ResourceUseResponse
    plan: PersonPlanOverviewResponse | None
    """Their Plan, and their own if it differs; null while no Plan exists (ADR 0038)."""


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
    plan: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]{0,31}$")
    """Only people who have the Plan with this key: as their own, or, for the Default Plan, by
    having none of their own."""
    over: bool = False
    """Only people over a limit of the Plan they have, whether or not Plans are on; never an
    administrator or a disabled person."""
    sort: Literal["joined", "email", "last_sign_in", "verdict"] = "joined"
    """By verdict, the most urgent comes first in ascending order."""
    order: Literal["asc", "desc"] = "asc"
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=100)


class InstallationIncidentResponse(ApiResponse):
    kind: Literal["scheduler_stalled", "client_secret_expiring"]
    since: str
    provider: str | None = None
    """For an expiring client secret, the Provider Kind it belongs to."""
    expires_on: str | None = None
    """For an expiring client secret, the date it expires, as the administrator recorded it."""


class InstallationHintResponse(ApiResponse):
    """A likely cause from a pattern across Users; it names none of them (ADR 0031)."""

    kind: HintKindValue
    cause: CauseValue | None
    """The administrator's Cause the pattern shows; null for a hint about Instant Sync."""
    users: int
    """How many Users show the pattern."""
    anchor: str
    """The section of docs/troubleshooting.md that explains the fix."""
    provider: str | None = None
    """The Provider Kind whose answers show the pattern."""


class InstallationHealthResponse(ApiResponse):
    """The whole installation's verdict; it names no rule, calendar, or User (ADR 0030)."""

    status: StatusVerdictValue
    needs_attention: bool
    incidents: list[InstallationIncidentResponse]
    users: dict[StatusVerdictValue, int]
    """How many Users who may sign in are in each Installation Status verdict."""
    disabled_users: int
    checked_at: str
    hints: list[InstallationHintResponse] = Field(default_factory=list)
