"""Google's reason codes, translated to Causes (ADR 0031).

Only the reason code is read: `error.errors[].reason` and `error.details[].reason` in a Calendar
API answer, and the `error` field of the OAuth token endpoint's answer to a refresh. Google's
message text can quote the request, so it is never kept, logged, or returned.

Sources, checked 2026-10-10:
- Calendar API errors: https://developers.google.com/workspace/calendar/api/guides/errors
- Google APIs' standard errors: https://cloud.google.com/resource-manager/docs/core_errors
- OAuth token errors: RFC 6749 section 5.2, https://www.rfc-editor.org/rfc/rfc6749#section-5.2,
  and https://developers.google.com/identity/protocols/oauth2/web-server
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping

from google.auth.exceptions import RefreshError, TransportError

from calendar_sync.application.causes import Cause

logger = logging.getLogger(__name__)

# Standard errors: "accessNotConfigured" (403), "Your project is not configured to access this
# API." Newer answers say the same as an ErrorInfo detail whose reason is SERVICE_DISABLED.
API_DISABLED_REASONS = frozenset({"accessNotConfigured", "SERVICE_DISABLED"})
# Standard errors: "dailyLimitExceeded" (403), "A daily quota limit for the API has been reached."
# It is the Google Cloud project's quota, which only its administrator can raise.
QUOTA_REASONS = frozenset({"dailyLimitExceeded"})
# Calendar API errors: "rateLimitExceeded" (403 and 429) and "userRateLimitExceeded" (403) ask for
# backoff. "quotaExceeded" (403) is "Calendar usage limits exceeded" for one account, which Google
# lifts by itself, not the project's quota.
RATE_LIMIT_REASONS = frozenset({"rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded"})
# Calendar API errors: "forbiddenForNonOrganizer" (403); "requiredAccessLevel" (403) is "You need
# to have writer access to this calendar."; standard errors: "forbidden" (403).
FORBIDDEN_REASONS = frozenset({"requiredAccessLevel", "forbidden", "forbiddenForNonOrganizer"})
# Standard errors: "insufficientPermissions" (403), the grant lacks a permission the request needs;
# reauthorizing grants it again, as for a revoked grant.
GRANT_REASONS = frozenset({"insufficientPermissions"})
# Calendar API errors: "notFound" (404) and "deleted" (410).
NOT_FOUND_STATUSES = frozenset({404, 410})

# RFC 6749 5.2: "invalid_grant", the refresh token is "invalid, expired, revoked". Google's OAuth
# guide lists why: revoked access, six months unused, or 7 days old for an app in Testing mode.
REVOKED_GRANT_ERRORS = frozenset({"invalid_grant"})
# RFC 6749 5.2: "invalid_client", client authentication failed, and "unauthorized_client", the
# client may not use this grant type. Google's web-server guide adds "deleted_client".
CLIENT_ERRORS = frozenset({"invalid_client", "unauthorized_client", "deleted_client"})

# What an unrecognized reason may be logged as: a code, never a sentence.
_LOGGABLE_REASON = re.compile(r"[A-Za-z0-9_]{1,64}")


def http_reasons(error: Exception) -> frozenset[str]:
    """The reason codes of a Calendar API answer; none when its body is not Google's JSON."""
    payload = _json(getattr(error, "content", b""))
    body = payload.get("error") if isinstance(payload, Mapping) else None
    if not isinstance(body, Mapping):
        return frozenset()
    items = [*_list(body.get("errors")), *_list(body.get("details"))]
    return frozenset(
        str(item["reason"])
        for item in items
        if isinstance(item, Mapping) and isinstance(item.get("reason"), str)
    )


def cause_of(error: Exception, status: int | None, *, event_scoped: bool = False) -> Cause:
    """Why Google refused, from its reason code and status; `unknown` for anything else.

    `event_scoped` says the request named one event in a calendar that answered just before, so
    a not-found means the event, not the calendar, is gone: no Cause the adapter knows.
    """
    if isinstance(error, TransportError):
        return Cause.TEMPORARY
    if isinstance(error, RefreshError):
        return _refresh_cause(error)
    reasons = http_reasons(error)
    cause = _http_cause(reasons, status)
    if event_scoped and cause is Cause.CALENDAR_NOT_FOUND:
        return Cause.UNKNOWN
    # Without a status Google never answered, so there is no reason to name.
    if cause is Cause.UNKNOWN and status is not None:
        _log_unrecognized(sorted(reasons)[0] if reasons else None, status)
    return cause


def _http_cause(reasons: frozenset[str], status: int | None) -> Cause:
    if reasons & API_DISABLED_REASONS:
        return Cause.API_DISABLED
    if reasons & QUOTA_REASONS:
        return Cause.QUOTA_EXCEEDED
    if reasons & RATE_LIMIT_REASONS or status == 429:
        return Cause.RATE_LIMITED
    if reasons & GRANT_REASONS or status == 401:
        return Cause.ACCESS_REVOKED
    if reasons & FORBIDDEN_REASONS:
        return Cause.CALENDAR_FORBIDDEN
    if status in NOT_FOUND_STATUSES:
        return Cause.CALENDAR_NOT_FOUND
    if status is not None and status >= 500:
        return Cause.TEMPORARY
    return Cause.UNKNOWN


def _refresh_cause(error: RefreshError) -> Cause:
    # google-auth marks a token endpoint it could not get an answer from as retryable.
    if error.retryable:
        return Cause.TEMPORARY
    code = _token_error(error)
    if code in REVOKED_GRANT_ERRORS:
        return Cause.ACCESS_REVOKED
    if code in CLIENT_ERRORS:
        return Cause.OAUTH_CLIENT_INVALID
    _log_unrecognized(code, None)
    return Cause.UNKNOWN


def _token_error(error: RefreshError) -> str | None:
    """The token endpoint's `error` field. google-auth passes its answer as the second argument,
    or only "error: description" as the first, so the code is the text before any colon."""
    answer = error.args[1] if len(error.args) > 1 else None
    if isinstance(answer, Mapping) and isinstance(answer.get("error"), str):
        return str(answer["error"])
    first = error.args[0] if error.args else None
    if not isinstance(first, str):
        return None
    code = first.split(":", 1)[0].strip()
    return code if _LOGGABLE_REASON.fullmatch(code) else None


def _log_unrecognized(reason: str | None, status: int | None) -> None:
    """Name a reason this release does not map, so it can be: only a short token, never text."""
    shown = "none" if reason is None else reason if _LOGGABLE_REASON.fullmatch(reason) else None
    logger.warning(
        "unrecognized provider reason provider=google status=%s reason=%s",
        status if status is not None else "none",
        shown or "unreadable",
    )


def _json(content: object) -> object:
    try:
        if isinstance(content, bytes):
            return json.loads(content.decode())
        if isinstance(content, str):
            return json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return None


def _list(value: object) -> list[object]:
    return value if isinstance(value, list) else []
