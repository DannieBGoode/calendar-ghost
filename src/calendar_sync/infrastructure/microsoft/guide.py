"""How Calendar Ghost names Microsoft and where its troubleshooting guide helps (ADR 0032)."""

from __future__ import annotations

from calendar_sync.application.causes import Cause
from calendar_sync.application.provider_descriptors import ProviderGuide
from calendar_sync.application.providers import ProviderKind

MICROSOFT = ProviderGuide(
    ProviderKind.OUTLOOK,
    # Every installation registers its redirect URI under this slug with Microsoft Entra.
    slug="microsoft",
    display_name="Microsoft",
    calendar_name="Outlook",
    # Sections of docs/troubleshooting.md, by their GitHub heading anchors, for every Cause the
    # Outlook adapter raises. Graph answers nothing that means the API is off or a project quota
    # is used up, so those two are never raised.
    cause_anchors={
        Cause.OAUTH_CLIENT_INVALID: "microsoft-no-longer-accepts-the-oauth-client",
        Cause.ACCESS_REVOKED: "microsoft-no-longer-accepts-your-microsoft-account",
        Cause.CALENDAR_FORBIDDEN: "your-microsoft-account-may-not-change-the-calendar",
        Cause.CALENDAR_NOT_FOUND: "the-calendar-no-longer-exists",
        Cause.RATE_LIMITED: "microsoft-is-slowing-calendar-ghost-down",
        Cause.TEMPORARY: "microsoft-is-slowing-calendar-ghost-down",
        Cause.UNKNOWN: "microsoft-refused-for-a-reason-calendar-ghost-does-not-recognize",
    },
)
