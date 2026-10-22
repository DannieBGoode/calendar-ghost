from __future__ import annotations

from typing import (
    Literal,
)

from pydantic import (
    BaseModel,
    ConfigDict,
)

from calendar_sync.application.operations.ports import (
    IncidentResolutionValue,
    IncidentState,
)

ProjectionChoice = Literal["delete", "detach"]


# What a rule does with events its source calendar answered Maybe to, or has not answered yet.
TentativeChoice = Literal["sync", "mark", "skip"]


UnansweredChoice = Literal["wait", "as_tentative"]


PrivacyPolicy = Literal["busy_only", "copy_details"]


# The values of application.status.StatusVerdict and ProblemKind, so the schema lists them.
StatusVerdictValue = Literal[
    "stalled", "stopped", "review", "waiting", "paused", "setup", "healthy"
]


RuleStopCauseValue = Literal["lapsed_authorization", "plan_hold"]


RulePlaceValue = Literal["counted", "reserved", "held"]


ProblemKindValue = Literal["stalled", "stopped", "review", "overdue", "blocked", "waiting"]


CauseValue = Literal[
    "api_disabled",
    "quota_exceeded",
    "oauth_client_invalid",
    "access_revoked",
    "calendar_forbidden",
    "calendar_not_found",
    "rate_limited",
    "temporary",
    "unknown",
]
"""Why a provider call failed (ADR 0031). A client that meets one it does not know shows it as
unknown."""


IncidentCategoryValue = Literal[
    "authentication",
    "authorization",
    "rate_limit",
    "temporary",
    "permanent",
    "infrastructure",
    "conflict",
    "unknown",
]
"""What kind of condition an Incident reports; one stored by another release reads as unknown."""


IncidentStepValue = Literal[
    "reauthorize",
    "recover_rule",
    "review_rule",
    "see_blocked",
    "wait",
    "administrator",
    "see_history",
]
"""An Incident's one next step (ADR 0033), as the domain decides it for the Web UI and email."""


HintKindValue = Literal[
    "shared_cause", "testing_mode", "unrecognized", "plain_http_address", "notices_not_arriving"
]


InstantSyncAvailabilityValue = Literal[
    "on", "off_by_user", "not_in_plan", "no_public_address", "not_reaching"
]
"""Whether Instant Sync is on for a User, or why not (ADR 0036)."""


EffectiveCadenceValue = Literal[
    "instant",
    "not_watchable",
    "waiting_for_provider",
    "off_by_user",
    "not_in_plan",
    "no_public_address",
    "not_reaching",
]
"""How a rule syncs: "instant", or why Scheduled Sync runs it instead."""


SyncIntervalValue = Literal[
    "instant", "5_minutes", "10_minutes", "15_minutes", "30_minutes", "60_minutes"
]
"""How soon a Plan's rules sync (ADR 0038); only the offered ones may be saved."""


AllowanceBasisValue = Literal["plans_off", "administrator", "plan"]
"""Why a User has the limits they have: Plans are off, they administer, or a Plan limits them."""


LimitedResourceValue = Literal["rules", "connected_accounts", "integration_tokens"]
"""What a Plan limits by count: rules that count toward it, calendar accounts, and Integration
Tokens."""


RunReasonValue = Literal[
    "changes", "first_run", "daily_pass", "reconcile_now", "reprojection", "relisted"
]


FoundByValue = Literal[
    "source_feed", "destination_feed", "reprojection", "pending_replay", "reconciliation"
]


SourceComparisonValue = Literal["changed", "untracked", "same_revision", "cancelled", "no_baseline"]


class ApiResponse(BaseModel):
    """A response body. Every field is always sent, so the schema marks defaulted ones required,
    and the frontend types generated from it (web/openapi.json) do not make them optional."""

    model_config = ConfigDict(
        json_schema_mode_override="serialization",
        json_schema_serialization_defaults_required=True,
    )


WorkKind = Literal["preview", "sync", "reconciliation", "removal"]


class IncidentMessageResponse(ApiResponse):
    """What an Incident says as a stable code and parameters the Web UI translates (ADR 0026)."""

    code: str
    params: dict[str, str | int | None]


class RecordedTimeResponse(ApiResponse):
    all_day: bool = False
    starts: str | None = None
    ends: str | None = None


class FieldChangeResponse(ApiResponse):
    field: str
    before: str | None = None
    after: str | None = None
    before_time: RecordedTimeResponse | None = None
    after_time: RecordedTimeResponse | None = None
    added: list[str] = []
    removed: list[str] = []


class IncidentResponse(ApiResponse):
    id: str
    rule_id: str | None
    category: IncidentCategoryValue
    state: IncidentState
    summary: str
    opened_at: str
    updated_at: str
    resolved_at: str | None
    resolution: IncidentResolutionValue | None
    account_id: str | None
    message: IncidentMessageResponse | None
    """None for an Incident recorded before messages, or one whose message is unreadable."""
    cause: CauseValue | None = None
    """Why the provider failure behind it happened; unknown when that was not recorded, and None
    for blocked events, which no provider failure opened."""
    step: IncidentStepValue | None = None
    """Its one next step; None when there is none, such as for a rule since removed."""
    provider: str | None = None
    """The Provider Kind whose failure opened it, when that was recorded."""
    cursor: str
    """Pass the last incident's as `before` for the next page; opaque, and fixed when read."""


TokenScope = Literal["installation:read", "status:read"]


_STATUS_READ: TokenScope = "status:read"
