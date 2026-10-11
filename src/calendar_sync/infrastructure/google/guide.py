"""How Calendar Ghost names Google and where its troubleshooting guide helps (ADR 0022)."""

from __future__ import annotations

from datetime import timedelta

from calendar_sync.application.causes import Cause
from calendar_sync.application.provider_descriptors import GrantLifetime, ProviderGuide
from calendar_sync.application.providers import ProviderKind

GOOGLE = ProviderGuide(
    ProviderKind.GOOGLE,
    slug="google",
    display_name="Google",
    calendar_name="Google Calendar",
    # Sections of docs/troubleshooting.md, by their GitHub heading anchors, for every Cause the
    # Google adapter raises; the first three only the installation's Google Cloud project fixes.
    cause_anchors={
        Cause.API_DISABLED: "the-google-calendar-api-is-turned-off",
        Cause.QUOTA_EXCEEDED: "the-google-cloud-projects-daily-quota-is-used-up",
        Cause.OAUTH_CLIENT_INVALID: "google-no-longer-accepts-the-oauth-client",
        Cause.ACCESS_REVOKED: "google-no-longer-accepts-your-google-account",
        Cause.CALENDAR_FORBIDDEN: "your-google-account-may-not-change-the-calendar",
        Cause.CALENDAR_NOT_FOUND: "the-calendar-no-longer-exists",
        Cause.RATE_LIMITED: "google-is-slowing-calendar-ghost-down",
        Cause.TEMPORARY: "google-is-slowing-calendar-ghost-down",
        Cause.UNKNOWN: "google-refused-for-a-reason-calendar-ghost-does-not-recognize",
    },
    # Google keeps a grant to an OAuth app whose publishing status is Testing for 7 days:
    # https://developers.google.com/identity/protocols/oauth2#expiration
    grant_lifetime=GrantLifetime(
        lifetime=timedelta(days=7),
        tolerance=timedelta(days=1),
        anchor="google-accounts-stop-working-7-days-after-connecting",
    ),
)
