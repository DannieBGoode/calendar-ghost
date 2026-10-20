"""Nonsecret identity email readiness and its dedicated delivery port."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from calendar_sync.application.shared.errors import InfrastructureFailure


class IdentityEmailReason(StrEnum):
    SMTP_MISSING = "smtp_missing"
    SMTP_SECURITY = "smtp_security"
    ORIGIN_MISSING = "origin_missing"
    ORIGIN_INVALID = "origin_invalid"
    ORIGIN_INSECURE = "origin_insecure"
    MASTER_KEY_MISSING = "master_key_missing"


@dataclass(frozen=True, slots=True)
class IdentityEmailSetup:
    fingerprint: str | None
    reason: IdentityEmailReason | None


class IdentityEmailDeliveryFailed(InfrastructureFailure):
    """Delivery failed; no provider detail or recipient is exposed."""

    def __init__(self) -> None:
        super().__init__("Identity email delivery failed")


class IdentityTestSender(Protocol):
    def send_test(self, recipient: str) -> None: ...
