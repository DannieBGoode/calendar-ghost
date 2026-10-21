"""Resolve identity email readiness from installation configuration."""

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from calendar_sync.application.identity.credentials import CredentialChanges
from calendar_sync.application.identity.email_changes import (
    EmailChangeServices,
)
from calendar_sync.application.identity.identity_email import (
    DeliverIdentityEmailTest,
    IdentityEmailReason,
    IdentityEmailSetup,
    IdentityEmailTests,
    IdentityTestSender,
    RequestIdentityEmailTest,
    ShowIdentityEmail,
)
from calendar_sync.application.identity.password_reset import (
    DeliverPasswordReset,
    IdentityResetSender,
    RequestPasswordReset,
    SelfServicePasswordResets,
)
from calendar_sync.application.identity.ports import PasswordHasher, UserDirectory
from calendar_sync.application.identity.registration import DeliverRegistration
from calendar_sync.application.identity.registration_ports import (
    IdentityRegistrationSender,
)
from calendar_sync.application.identity.reset_admission import ResetAdmission
from calendar_sync.application.shared.ports import Clock, IdGenerator
from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.identity_email_changes import (
    EmailChangeAdapters,
    build_email_changes,
    compose_email_changes,
)
from calendar_sync.bootstrap.registration import RegistrationAdapters, build_registration
from calendar_sync.infrastructure.identity_email import (
    IdentitySmtp,
    identity_loopback,
    identity_origin,
)
from calendar_sync.infrastructure.identity_email_changes import (
    EmailChangeDelivery,
    EmailChangeMaintenance,
    IdentityChangeSender,
)
from calendar_sync.infrastructure.identity_front_gate import MemoryIdentityFrontGate
from calendar_sync.infrastructure.identity_mail_worker import IdentityMailWorker
from calendar_sync.infrastructure.identity_registration import RegistrationMaintenance
from calendar_sync.infrastructure.persistence.identity_email import SqliteIdentityEmailTests
from calendar_sync.infrastructure.persistence.reset_admission import SqliteResetAdmission
from calendar_sync.infrastructure.security import identity_email_fingerprint


def identity_setup(settings: Settings) -> IdentityEmailSetup:
    reason = _reason(settings)
    if reason is not None:
        return IdentityEmailSetup(None, reason)
    origin = identity_origin(settings.public_url)
    assert origin is not None
    values = (
        settings.smtp_host,
        settings.smtp_port,
        settings.smtp_sender,
        settings.smtp_username,
        settings.smtp_password,
        settings.smtp_starttls,
        origin,
    )
    return IdentityEmailSetup(identity_email_fingerprint(settings.master_key, values), None)


def _reason(settings: Settings) -> IdentityEmailReason | None:
    if not settings.smtp_host or not settings.smtp_sender:
        return IdentityEmailReason.SMTP_MISSING
    if not settings.smtp_starttls and not identity_loopback(settings.smtp_host):
        return IdentityEmailReason.SMTP_SECURITY
    if not settings.public_url:
        return IdentityEmailReason.ORIGIN_MISSING
    if identity_origin(settings.public_url) is None:
        try:
            parsed = urlsplit(settings.public_url)
            insecure = (
                parsed.scheme == "http"
                and identity_origin(parsed._replace(scheme="https").geturl()) is not None
            )
        except ValueError:
            insecure = False
        return (
            IdentityEmailReason.ORIGIN_INSECURE if insecure else IdentityEmailReason.ORIGIN_INVALID
        )
    if not settings.master_key:
        return IdentityEmailReason.MASTER_KEY_MISSING
    return None


class IdentitySender(
    IdentityTestSender,
    IdentityResetSender,
    IdentityChangeSender,
    IdentityRegistrationSender,
    Protocol,
):
    """Security-email operations sharing one verified transport."""


@dataclass(frozen=True, slots=True)
class IdentityEmailAdapters:
    setup: IdentityEmailSetup
    tests: IdentityEmailTests
    sender: IdentitySender | None
    email_changes: EmailChangeAdapters
    registrations: RegistrationAdapters


@dataclass(frozen=True, slots=True)
class IdentityEmailServices:
    show: ShowIdentityEmail
    request_test: RequestIdentityEmailTest
    request_reset: RequestPasswordReset
    email_changes: EmailChangeServices

    @property
    def configured(self) -> bool:
        return self.request_reset.setup.fingerprint is not None


def build_reset_admission(settings: Settings, clock: Clock) -> ResetAdmission:
    attempts = (
        SqliteResetAdmission(settings.database_path, settings.master_key, clock)
        if settings.master_key
        else None
    )
    return ResetAdmission(MemoryIdentityFrontGate(clock), attempts, clock)


def build_identity_email(
    settings: Settings, ids: IdGenerator, clock: Clock
) -> IdentityEmailAdapters:
    setup = identity_setup(settings)
    sender = (
        IdentitySmtp(
            settings.smtp_host,
            settings.smtp_port,
            settings.smtp_sender,
            settings.smtp_username,
            settings.smtp_password,
            settings.smtp_starttls,
            settings.public_url,
        )
        if setup.fingerprint is not None
        else None
    )
    return IdentityEmailAdapters(
        setup,
        SqliteIdentityEmailTests(settings.database_path, ids),
        sender,
        build_email_changes(settings, ids, clock, setup),
        build_registration(settings, ids, clock, setup),
    )


def compose_identity_email(
    adapters: IdentityEmailAdapters,
    users: UserDirectory,
    clock: Clock,
    resets: SelfServicePasswordResets,
    admission: ResetAdmission,
    passwords: PasswordHasher,
    credentials: CredentialChanges,
) -> tuple[IdentityEmailServices, IdentityMailWorker]:
    worker = IdentityMailWorker(
        DeliverIdentityEmailTest(users, adapters.tests, adapters.setup, adapters.sender, clock)
        if adapters.sender is not None
        else None,
        adapters.tests,
        clock,
        reset_delivery=DeliverPasswordReset(resets, adapters.setup, adapters.sender)
        if adapters.sender is not None
        else None,
        reset_admission=admission,
        email_changes=EmailChangeMaintenance(
            EmailChangeDelivery(adapters.email_changes.proofs, adapters.setup, adapters.sender)
            if adapters.sender is not None
            else None,
            adapters.email_changes.proofs,
            adapters.email_changes.admission,
        ),
        registrations=RegistrationMaintenance(
            DeliverRegistration(adapters.registrations.proofs, adapters.setup, adapters.sender)
            if adapters.sender is not None
            else None,
            adapters.registrations.proofs,
            adapters.registrations.admission,
        ),
    )
    return IdentityEmailServices(
        ShowIdentityEmail(users, adapters.tests, adapters.setup, worker),
        RequestIdentityEmailTest(users, adapters.tests, adapters.setup, worker, clock),
        RequestPasswordReset(admission, adapters.setup, worker),
        compose_email_changes(adapters.email_changes, users, passwords, credentials, worker),
    ), worker


class IdentityMailAdapters(Protocol):
    @property
    def identity_email(self) -> IdentityEmailAdapters: ...

    @property
    def users(self) -> UserDirectory: ...

    @property
    def clock(self) -> Clock: ...

    @property
    def self_service_resets(self) -> SelfServicePasswordResets: ...

    @property
    def reset_admission(self) -> ResetAdmission: ...

    @property
    def passwords(self) -> PasswordHasher: ...

    @property
    def credential_changes(self) -> CredentialChanges: ...


def compose_identity_mail(
    adapters: IdentityMailAdapters,
) -> tuple[IdentityEmailServices, IdentityMailWorker]:
    return compose_identity_email(
        adapters.identity_email,
        adapters.users,
        adapters.clock,
        adapters.self_service_resets,
        adapters.reset_admission,
        adapters.passwords,
        adapters.credential_changes,
    )
