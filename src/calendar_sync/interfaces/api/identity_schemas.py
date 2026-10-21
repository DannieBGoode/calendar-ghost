"""Bounded request and response models for a User's sign-in email changes."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from calendar_sync.application.identity.identity_email import IdentityEmailReason
from calendar_sync.domain.access import InvalidEmail, email_address
from calendar_sync.domain.email_changes import EmailChangeMode


class EmailAddressRequest(BaseModel):
    email: str = Field(repr=False)

    @field_validator("email")
    @classmethod
    def normalized_email(cls, value: str) -> str:
        try:
            return email_address(value)
        except InvalidEmail:
            raise ValueError("enter a valid email address of at most 254 characters") from None


class DirectEmailChangeRequest(EmailAddressRequest):
    password: str | None = Field(default=None, max_length=1024, repr=False)


class RequestEmailChangeRequest(EmailAddressRequest):
    password: str = Field(max_length=1024, repr=False)


class EmailChangeTokenRequest(BaseModel):
    token: str = Field(min_length=1, max_length=128, pattern=r"^[\x00-\x7f]+$", repr=False)


class ConfirmEmailChangeRequest(EmailChangeTokenRequest):
    password: str = Field(max_length=1024, repr=False)


class PendingEmailChangeResponse(BaseModel):
    id: str
    email: str
    expires_at: datetime


class EmailChangeStatusResponse(BaseModel):
    mode: EmailChangeMode
    reason: IdentityEmailReason | None
    pending: PendingEmailChangeResponse | None


class EmailChangeAcceptedResponse(BaseModel):
    accepted: Literal[True] = True


class EmailChangeCheckResponse(BaseModel):
    usable: bool
