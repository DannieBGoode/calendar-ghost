"""Bounded provider sign-in payloads; no provider claims cross this boundary."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

Proof = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[\x21-\x7e]+$")]
Email = Annotated[str, Field(min_length=1, max_length=254)]
Password = Annotated[str, Field(min_length=1, max_length=1024)]


class ProviderStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    invitation_token: Proof | None = None
    email: Email | None = None

    @model_validator(mode="after")
    def invitation_pair(self) -> "ProviderStartRequest":
        if (self.invitation_token is None) != (self.email is None):
            raise ValueError("Invitation and email must be supplied together")
        return self


class ProviderStartResponse(BaseModel):
    authorization_url: str


class AvailableProvidersResponse(BaseModel):
    providers: list[str]


class PendingProviderResponse(BaseModel):
    password_required: bool


class ConfirmProviderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: Email
    password: Password


class SetPasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: Annotated[str, Field(min_length=12, max_length=256)]


class LinkedIdentityResponse(BaseModel):
    id: str
    provider: str


class SignInMethodsResponse(BaseModel):
    has_password: bool
    identities: list[LinkedIdentityResponse]


class ProviderSettingResponse(BaseModel):
    callback_uri: str | None
    provider: str
    enabled: bool
    available: bool
    reason: str | None


class ProviderSettingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
