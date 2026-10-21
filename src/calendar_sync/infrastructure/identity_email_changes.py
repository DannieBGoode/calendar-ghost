"""Concrete email-change delivery and bounded maintenance for the identity worker."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from calendar_sync.application.identity.email_change_admission import EmailChangeAdmission
from calendar_sync.application.identity.email_changes import (
    EmailChangedNotice,
    EmailChangeMailRequest,
    EmailChangeProofs,
    PreparedEmailChange,
)
from calendar_sync.application.identity.identity_email import IdentityEmailSetup


class IdentityChangeSender(Protocol):
    def send_email_change(self, recipient: str, token: str) -> None: ...

    def send_email_changed(self, recipient: str) -> None: ...


@dataclass(frozen=True, slots=True)
class EmailChangeDelivery:
    proofs: EmailChangeProofs
    setup: IdentityEmailSetup
    sender: IdentityChangeSender

    def prepare(self, request: EmailChangeMailRequest) -> PreparedEmailChange | None:
        if request.fingerprint != self.setup.fingerprint:
            return None
        return self.proofs.prepare(request.request_id)

    def send(self, prepared: PreparedEmailChange) -> None:
        self.sender.send_email_change(prepared.recipient, prepared.token)

    def notice(self, notice: EmailChangedNotice) -> None:
        self.sender.send_email_changed(notice.recipient)


@dataclass(frozen=True, slots=True)
class EmailChangeMaintenance:
    delivery: EmailChangeDelivery | None
    proofs: EmailChangeProofs
    admission: EmailChangeAdmission

    def purge(self, before: datetime, limit: int) -> int:
        # Attempt both independent stores even when one has a transient storage fault.
        from contextlib import suppress

        removed = 0
        with suppress(Exception):
            removed = self.proofs.purge(before, limit)
        with suppress(Exception):
            removed = max(removed, self.admission.purge(before, limit))
        return removed
