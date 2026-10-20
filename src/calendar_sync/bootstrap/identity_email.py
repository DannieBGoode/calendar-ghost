"""Resolve identity email readiness from installation configuration."""

from urllib.parse import urlsplit

from calendar_sync.application.identity.identity_email import (
    IdentityEmailReason,
    IdentityEmailSetup,
)
from calendar_sync.bootstrap.config import Settings
from calendar_sync.infrastructure.identity_email import identity_loopback, identity_origin
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
