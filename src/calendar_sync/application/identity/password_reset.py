"""Narrow email recovery preparation, used outside the anonymous request path."""

from dataclasses import dataclass, field
from typing import Protocol

from calendar_sync.application.identity.identity_email import (
    IdentityEmailNotConfigured,
    IdentityEmailSetup,
)
from calendar_sync.application.identity.ports import IssuedLink
from calendar_sync.application.identity.reset_admission import ResetAdmission
from calendar_sync.domain.access import email_address


@dataclass(frozen=True, slots=True)
class PreparedPasswordReset:
    recipient: str = field(repr=False)
    link: IssuedLink = field(repr=False)


class SelfServicePasswordResets(Protocol):
    def issue_for_email(self, email: str) -> PreparedPasswordReset | None:
        """Issue an active User a one-hour proof bound to their current credential.

        Earlier delivered links remain usable. Eligibility and the clock are read under the
        write lock. Unknown and disabled addresses return None.
        """
        ...


@dataclass(frozen=True, slots=True)
class ResetEmailRequest:
    email: str = field(repr=False)
    fingerprint: str


class ResetEmailQueue(Protocol):
    def submit_reset(self, request: ResetEmailRequest) -> bool: ...


class IdentityResetSender(Protocol):
    def send_reset(self, recipient: str, token: str) -> None: ...


@dataclass(frozen=True, slots=True)
class RequestPasswordReset:
    admission: ResetAdmission
    setup: IdentityEmailSetup
    queue: ResetEmailQueue

    def execute(self, email: str, client: str) -> None:
        normalized = email_address(email)
        if self.setup.fingerprint is None:
            raise IdentityEmailNotConfigured
        if self.admission.admit(normalized, client):
            try:
                self.queue.submit_reset(ResetEmailRequest(normalized, self.setup.fingerprint))
            except Exception:
                # A volatile queue failure reveals nothing about eligibility or delivery.
                return


@dataclass(frozen=True, slots=True)
class DeliverPasswordReset:
    resets: SelfServicePasswordResets
    setup: IdentityEmailSetup
    sender: IdentityResetSender

    def prepare(self, request: ResetEmailRequest) -> PreparedPasswordReset | None:
        if request.fingerprint != self.setup.fingerprint:
            return None
        return self.resets.issue_for_email(request.email)

    def send(self, prepared: PreparedPasswordReset) -> None:
        self.sender.send_reset(prepared.recipient, prepared.link.token)
