"""Resolve identity email readiness from installation configuration."""

from dataclasses import dataclass
from urllib.parse import urlsplit

from calendar_sync.application.identity.identity_email import (
    DeliverIdentityEmailTest,
    EmailTest,
    EmailTestState,
    IdentityEmailQueue,
    IdentityEmailReason,
    IdentityEmailSetup,
    IdentityEmailTests,
    IdentityTestSender,
    RequestIdentityEmailTest,
    ShowIdentityEmail,
)
from calendar_sync.application.identity.ports import UserDirectory
from calendar_sync.application.shared.ports import Clock, IdGenerator
from calendar_sync.bootstrap.config import Settings
from calendar_sync.domain.access import UserId
from calendar_sync.infrastructure.identity_email import (
    IdentitySmtp,
    identity_loopback,
    identity_origin,
)
from calendar_sync.infrastructure.identity_mail_worker import IdentityMailWorker
from calendar_sync.infrastructure.persistence.identity_email import SqliteIdentityEmailTests
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


@dataclass(frozen=True, slots=True)
class IdentityEmailAdapters:
    setup: IdentityEmailSetup
    tests: IdentityEmailTests
    sender: IdentityTestSender | None


@dataclass(frozen=True, slots=True)
class IdentityEmailServices:
    show: ShowIdentityEmail
    request_test: RequestIdentityEmailTest


def build_identity_email(settings: Settings, ids: IdGenerator) -> IdentityEmailAdapters:
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
        setup, SqliteIdentityEmailTests(settings.database_path, ids), sender
    )


def compose_identity_email(
    adapters: IdentityEmailAdapters, users: UserDirectory, clock: Clock
) -> tuple[IdentityEmailServices, IdentityMailWorker | None]:
    worker = (
        IdentityMailWorker(
            DeliverIdentityEmailTest(users, adapters.tests, adapters.setup, adapters.sender, clock),
            adapters.tests,
            clock,
        )
        if adapters.sender is not None
        else None
    )
    queue: IdentityEmailQueue = worker if worker is not None else _UnavailableQueue()
    return IdentityEmailServices(
        ShowIdentityEmail(users, adapters.tests, adapters.setup, queue),
        RequestIdentityEmailTest(users, adapters.tests, adapters.setup, queue, clock),
    ), worker


class _UnavailableQueue:
    def submit(self, _test: EmailTest) -> bool:
        return False

    def state(self, _actor: UserId) -> EmailTestState:
        return EmailTestState.IDLE
