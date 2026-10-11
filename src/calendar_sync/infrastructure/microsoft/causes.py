"""Microsoft's reasons, translated to Causes (ADR 0031, ADR 0032).

Only codes are read: Graph's `error.code` and every nested `innerError.code`, the most detailed
first, and the identity platform's RFC 6749 `error` field. Microsoft says to code against these,
never against `message` or `error_description`, which can quote the request and are never kept,
logged, or returned. AADSTS numbers are "for diagnostics" and "subject to change", so they decide
nothing; they are logged, as short tokens, only when the reason is not recognized.

Sources, checked 2026-10-11:
- Graph errors: https://learn.microsoft.com/en-us/graph/errors
- Graph throttling: https://learn.microsoft.com/en-us/graph/throttling
- Exchange response codes, which Outlook answers in `error.code`:
  https://learn.microsoft.com/en-us/exchange/client-developer/web-service-reference/responsecode
- Token errors and AADSTS numbers:
  https://learn.microsoft.com/en-us/entra/identity-platform/reference-error-codes
- Authorization code flow errors:
  https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow
"""

from __future__ import annotations

import logging
import re

from calendar_sync.application.causes import Cause
from calendar_sync.infrastructure.microsoft.graph import GraphRefusal, TokenRefusal

logger = logging.getLogger(__name__)

# Token endpoint `error` values (reference-error-codes, "Handling error codes in your application").
TOKEN_CAUSES = {
    # "Client authentication failed": a wrong, missing, or expired client secret (AADSTS7000215,
    # 7000218, 7000222); "The authenticated client isn't authorized to use this authorization
    # grant type", as for an application not found in the directory (AADSTS700016). Only the
    # installation's administrator fixes the application registration.
    "invalid_client": Cause.OAUTH_CLIENT_INVALID,
    "unauthorized_client": Cause.OAUTH_CLIENT_INVALID,
    # "Some of the authentication material ... was invalid, unparseable, missing, or otherwise
    # unusable": an expired or revoked grant (AADSTS70008, 700082), a password reset (50173), or
    # an organization that has not consented (65001). The person reauthorizes; with a work account
    # their organization's administrator may first have to approve the application.
    "invalid_grant": Cause.ACCESS_REVOKED,
    # "The request requires user interaction" (AADSTS50076 multifactor authentication, 53003
    # Conditional Access) and "The request requires user consent" (v2-oauth2-auth-code-flow).
    "interaction_required": Cause.ACCESS_REVOKED,
    "consent_required": Cause.ACCESS_REVOKED,
    # "Retry the request."
    "temporarily_unavailable": Cause.TEMPORARY,
}

# Graph `error.code` values.
GRAPH_CAUSES = {
    # Graph throttling: 429 with "TooManyRequests"; Outlook's per-app and per-mailbox limits.
    "TooManyRequests": Cause.RATE_LIMITED,
    "ApplicationThrottled": Cause.RATE_LIMITED,
    "activityLimitReached": Cause.RATE_LIMITED,
    # Graph errors: "ServiceNotAvailable", "You can repeat the request after a delay".
    "ServiceNotAvailable": Cause.TEMPORARY,
    # Graph errors, 401: "Required authentication information is either missing or not valid".
    "InvalidAuthenticationToken": Cause.ACCESS_REVOKED,
    # The grant lacks a permission the request needs; reauthorizing grants it again.
    "Authorization_RequestDenied": Cause.ACCESS_REVOKED,
    # Exchange: "ErrorAccessDenied: ... the calling account does not have the rights to perform
    # the requested action", as for a calendar shared with the account to read only.
    "ErrorAccessDenied": Cause.CALENDAR_FORBIDDEN,
    "accessDenied": Cause.CALENDAR_FORBIDDEN,
    # Exchange: "ErrorItemNotFound: ... the item was not found or you do not have permission to
    # access the item"; "ErrorFolderNotFound" for a deleted calendar.
    "ErrorItemNotFound": Cause.CALENDAR_NOT_FOUND,
    "itemNotFound": Cause.CALENDAR_NOT_FOUND,
    "ErrorFolderNotFound": Cause.CALENDAR_NOT_FOUND,
}

# What an unrecognized reason may be logged as: a code, never a sentence.
_LOGGABLE = re.compile(r"[A-Za-z0-9_.]{1,64}")


def cause_of(error: GraphRefusal | TokenRefusal, *, event_scoped: bool = False) -> Cause:
    """Why Microsoft refused, from its codes and status; `unknown` for anything else.

    `event_scoped` says the request named one event in a calendar that answered just before, so
    a not-found means the event, not the calendar, is gone: no Cause the adapter knows.
    """
    if error.status is None:
        # No answer arrived, so there is no reason to name.
        return Cause.TEMPORARY
    if isinstance(error, TokenRefusal):
        return _token_cause(error)
    cause = _graph_cause(error)
    if event_scoped and cause is Cause.CALENDAR_NOT_FOUND:
        return Cause.UNKNOWN
    if cause is Cause.UNKNOWN:
        _log_unrecognized(error.codes[-1] if error.codes else None, error.status, ())
    return cause


def _graph_cause(error: GraphRefusal) -> Cause:
    # The innermost code Microsoft names is the most detailed.
    for code in reversed(error.codes):
        if code in GRAPH_CAUSES:
            return GRAPH_CAUSES[code]
    status = error.status or 0
    if status == 429:
        return Cause.RATE_LIMITED
    if status == 401:
        return Cause.ACCESS_REVOKED
    if status >= 500:
        return Cause.TEMPORARY
    return Cause.UNKNOWN


def _token_cause(error: TokenRefusal) -> Cause:
    if error.status is not None and error.status >= 500:
        return Cause.TEMPORARY
    cause = TOKEN_CAUSES.get(error.error or "", Cause.UNKNOWN)
    if cause is Cause.UNKNOWN:
        _log_unrecognized(error.error, error.status, error.codes)
    return cause


def _log_unrecognized(reason: str | None, status: int | None, codes: tuple[int, ...]) -> None:
    """Name a reason this release does not map, so it can be: only short tokens, never text."""
    shown = "none" if reason is None else reason if _LOGGABLE.fullmatch(reason) else "unreadable"
    logger.warning(
        "unrecognized provider reason provider=outlook status=%s reason=%s codes=%s",
        status if status is not None else "none",
        shown,
        ",".join(f"AADSTS{code}" for code in codes[:3]) or "none",
    )
