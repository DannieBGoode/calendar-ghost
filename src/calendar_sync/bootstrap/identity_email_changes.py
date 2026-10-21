"""Compose verified email changes through their narrow identity ports."""

from dataclasses import dataclass

from calendar_sync.application.identity.credentials import CredentialChanges
from calendar_sync.application.identity.email_change_admission import EmailChangeAdmission
from calendar_sync.application.identity.email_changes import (
    CancelEmailChange,
    CheckEmailChange,
    ConfirmEmailChange,
    DirectEmailChange,
    EmailChangeProofs,
    EmailChangeQueue,
    EmailChangeServices,
    RequestEmailChange,
    ShowEmailChange,
)
from calendar_sync.application.identity.identity_email import IdentityEmailSetup
from calendar_sync.application.identity.ports import PasswordHasher, UserDirectory
from calendar_sync.application.identity.sign_in import SetOwnEmail
from calendar_sync.application.shared.ports import Clock, IdGenerator
from calendar_sync.bootstrap.config import Settings
from calendar_sync.infrastructure.persistence.email_change_admission import (
    EmailChangeAdmission as SqliteEmailChangeAdmission,
)
from calendar_sync.infrastructure.persistence.email_changes import SqliteEmailChangeProofs


@dataclass(frozen=True, slots=True)
class EmailChangeAdapters:
    setup: IdentityEmailSetup
    smtp_present: bool
    proofs: EmailChangeProofs
    admission: EmailChangeAdmission


def build_email_changes(
    settings: Settings, ids: IdGenerator, clock: Clock, setup: IdentityEmailSetup
) -> EmailChangeAdapters:
    present = bool(
        settings.smtp_host
        or settings.smtp_sender
        or settings.smtp_username
        or settings.smtp_password
        or settings.smtp_recipient
    )
    return EmailChangeAdapters(
        setup,
        present,
        SqliteEmailChangeProofs(settings.database_path, ids, clock, master_key=settings.master_key),
        SqliteEmailChangeAdmission(settings.database_path, settings.master_key, clock),
    )


def compose_email_changes(
    adapters: EmailChangeAdapters,
    users: UserDirectory,
    passwords: PasswordHasher,
    credentials: CredentialChanges,
    queue: EmailChangeQueue,
) -> EmailChangeServices:
    show = ShowEmailChange(users, adapters.proofs, adapters.setup, adapters.smtp_present)
    return EmailChangeServices(
        show,
        DirectEmailChange(show, SetOwnEmail(users, passwords, credentials)),
        RequestEmailChange(show, credentials, passwords, adapters.admission, queue),
        CancelEmailChange(adapters.proofs),
        CheckEmailChange(adapters.proofs, adapters.admission),
        ConfirmEmailChange(adapters.proofs, credentials, passwords, adapters.admission, queue),
    )
