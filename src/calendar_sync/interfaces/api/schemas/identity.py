from __future__ import annotations

from datetime import (
    datetime,
)
from typing import (
    Literal,
)

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)

from calendar_sync.domain.access import (
    email_address,
)
from calendar_sync.interfaces.api.schemas.shared import (
    _STATUS_READ,
    ApiResponse,
    InstantSyncAvailabilityValue,
    ProjectionChoice,
    SyncIntervalValue,
    TokenScope,
)


class SetupStatusResponse(ApiResponse):
    administrator_configured: bool
    password_reset_available: bool = False
    public_registration_available: bool = False
    password_only_sign_in: bool
    """Whether the upgraded first User may still sign in by password alone."""


class SetupRequest(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(min_length=12, max_length=256)


class SignInRequest(BaseModel):
    email: str | None = Field(default=None, max_length=320)
    """Left out only by the upgraded first User, until they add an email."""
    password: str = Field(min_length=1, max_length=1024)


class SignedInUserResponse(ApiResponse):
    id: str
    email: str | None
    """None until the upgraded first User adds one, which they must do first."""
    role: Literal["installation_administrator", "user"]
    notify_by_email: bool
    language: str | None
    instant_sync: bool
    """Whether the User wants Instant Sync; it is on only while the availability is "on"."""
    instant_sync_availability: InstantSyncAvailabilityValue
    instant_sync_help: str | None
    """The section of docs/instant-sync.md that explains why it is unavailable, and the fix."""


class SessionResponse(ApiResponse):
    authenticated: bool
    user: SignedInUserResponse | None = None
    installation_sends_email: bool = False
    """Whether Incident Notifications can also reach a User by email."""


class SetEmailRequest(BaseModel):
    email: str = Field(max_length=320)
    password: str | None = Field(default=None, max_length=1024)
    """The current password, needed to change an email but not to add the first one."""


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(max_length=1024)
    new_password: str = Field(max_length=256)


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
    policy: Literal["only_me", "invitation_only", "open"]
    only_me_available: bool
    """Whether Only Me may be chosen now: only while no other User exists."""
    open_available: bool = False
    open_unavailable_reason: (
        Literal["identity_email_not_configured", "identity_email_not_tested"] | None
    ) = None


class RegistrationRequest(BaseModel):
    policy: Literal["only_me", "invitation_only", "open"]


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
    token: str = Field(min_length=1, max_length=128, pattern=r"^[\x00-\x7f]+$", repr=False)


class LinkStatusResponse(ApiResponse):
    usable: bool


class InvitationStatusResponse(LinkStatusResponse):
    acceptance: Literal["direct", "verified"] | None


class AcceptInvitationRequest(LinkRequest):
    email: str = Field(max_length=320)
    password: str = Field(max_length=256, repr=False)


class RequestPasswordResetRequest(BaseModel):
    email: str = Field(repr=False)

    @field_validator("email")
    @classmethod
    def normalized_email(cls, value: str) -> str:
        return email_address(value)


class PasswordResetAcceptedResponse(ApiResponse):
    accepted: Literal[True] = True


class PasswordResetLinkRequest(BaseModel):
    token: str = Field(min_length=1, max_length=128, pattern=r"^[\x00-\x7f]+$", repr=False)


class ResetPasswordRequest(PasswordResetLinkRequest):
    password: str = Field(min_length=12, max_length=1024, repr=False)


class SignUpRequest(RequestPasswordResetRequest):
    model_config = ConfigDict(extra="forbid")
    invitation_token: str | None = Field(
        default=None, min_length=1, max_length=128, pattern=r"^[\x00-\x7f]+$", repr=False
    )


class SignUpAcceptedResponse(ApiResponse):
    accepted: Literal[True] = True


class RegistrationCheckRequest(PasswordResetLinkRequest):
    model_config = ConfigDict(extra="forbid")


class RegistrationCheckResponse(LinkStatusResponse):
    email: str | None


class CompleteRegistrationRequest(RegistrationCheckRequest):
    password: str = Field(min_length=12, max_length=1024, repr=False)


class UserResponse(ApiResponse):
    id: str
    email: str | None
    role: Literal["installation_administrator", "user"]
    state: Literal["active", "disabled"]
    created_at: str
    last_sign_in_at: str | None


class PlanNameResponse(ApiResponse):
    """A Plan as people know it: its key, which never changes, and its name."""

    key: str
    name: str


class AppliedPlanResponse(PlanNameResponse):
    """A Plan a User has, such as the one that limits them now."""

    on_default: bool
    """It is the Default Plan, because they have no Plan of their own."""


class PlanLimitsResponse(ApiResponse):
    """What a Plan allows; null is unlimited."""

    rules: int | None
    """Rules that count: enabled, stopped only by Lapsed Authorization, or a Rule Replacement
    draft that keeps its place."""
    connected_accounts: int | None
    """Calendar accounts, Disconnected Accounts included."""
    integration_tokens: int | None
    """Unrevoked Integration Tokens; 0 offers none."""
    sync_interval: SyncIntervalValue


class UseCountResponse(ApiResponse):
    """How many of the people a Plan limits have exactly `in_use` of one resource."""

    in_use: int
    people: int


class PlanUseCountsResponse(ApiResponse):
    """How much the people a Plan limits have of each resource it limits: each count above 0,
    highest first, with how many people have it, so a lower limit can say how many people it
    would leave with more than it allows. Counts only; never who."""

    rules: list[UseCountResponse]
    """Rules that count toward the rule limit."""
    connected_accounts: list[UseCountResponse]
    """Calendar accounts, Disconnected Accounts included."""
    integration_tokens: list[UseCountResponse]
    """Unrevoked Integration Tokens."""


class PlanResponse(ApiResponse):
    """One Plan, as Administration lists it."""

    key: str
    name: str
    limits: PlanLimitsResponse
    is_default: bool
    people: int
    """Everyone who has it: their own Plan, plus, for the default, everyone with none. People
    finds the same people by the Plan."""
    limited_people: int
    """Active Users who do not administer and have it, whom it limits while Plans are on."""
    over_people: int
    """Of `limited_people`, how many have more than it allows of rules, calendar accounts, or
    Integration Tokens, as after a limit was lowered, whether or not Plans are on."""
    use: PlanUseCountsResponse


class PlansResponse(ApiResponse):
    """The Plans setting, the sync intervals offered now, and every Plan by name."""

    enabled: bool
    """Whether Plans limit anyone; while they are off, nobody is limited."""
    default_plan: str | None
    """The Default Plan's key; null until an administrator chooses one."""
    sync_intervals: list[SyncIntervalValue]
    """The sync intervals a Plan may be given now, in order."""
    followers: int
    """Everyone with no Plan of their own, whatever their role or state: whom making another Plan
    the default moves to it."""
    plans: list[PlanResponse]


class PlanLimitsRequest(BaseModel):
    """Each limit is a whole number, or null for unlimited."""

    rules: int | None
    connected_accounts: int | None
    integration_tokens: int | None
    sync_interval: SyncIntervalValue


class DefinePlanRequest(BaseModel):
    key: str | None = Field(default=None, max_length=200)
    """Optional: 1 to 32 lower-case letters, digits, and hyphens, which another Plan must not
    have. Without one, the server makes the key from the name: lower-case letters, digits, and
    hyphens, with "-2", "-3", and so on when another Plan has it. It never changes."""
    name: str = Field(max_length=200)
    limits: PlanLimitsRequest


class ChangePlanRequest(BaseModel):
    name: str = Field(max_length=200)
    limits: PlanLimitsRequest


class PlansSettingRequest(BaseModel):
    enabled: bool
    # No length bound here: a key of any length that names no Plan answers 404 plan_not_found,
    # and the Plan key's own check refuses one over 32 characters before anything reads it.
    default_plan: str | None
    """Required. Null clears the default, which Plans allow only while they are off."""


class RoleRequest(BaseModel):
    role: Literal["installation_administrator", "user"]


class UserStateRequest(BaseModel):
    state: Literal["active", "disabled"]


class DeleteOwnAccountRequest(BaseModel):
    password: str = Field(max_length=1024)
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


class NotificationPreferenceRequest(BaseModel):
    notify_by_email: bool


class InstantSyncPreferenceRequest(BaseModel):
    instant_sync: bool


class IdentityEmailResponse(ApiResponse):
    configured: bool
    unavailable_reason: (
        Literal[
            "smtp_missing",
            "smtp_security",
            "origin_missing",
            "origin_invalid",
            "origin_insecure",
            "master_key_missing",
        ]
        | None
    )
    tested_at: datetime | None
    test_state: Literal["idle", "queued", "sending", "accepted", "failed"]
