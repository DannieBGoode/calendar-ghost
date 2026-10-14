"""Watch call failures, from the provider failure an adapter already translated (ADR 0036).

Watching keeps its own failure classes, apart from a Sync Run's, so a provider that cannot watch
a calendar never stops a rule or lapses an account. Only a refusal of the account's credentials,
which its next Sync Run would meet as well, is `unauthorized`. The detail is Calendar Ghost's own
sentence: a provider's message text can quote the request, so it is never kept.
"""

from __future__ import annotations

from calendar_sync.application.sync.errors import (
    ConnectedAccountDisconnected,
    ConnectedAccountNotFound,
    ProviderFailure,
)
from calendar_sync.application.sync.watch_ports import WatchFailure, WatchFailureKind
from calendar_sync.domain.causes import Cause
from calendar_sync.domain.providers import ProviderFailureKind

ACCOUNT_UNAVAILABLE = (ConnectedAccountNotFound, ConnectedAccountDisconnected)
"""What the credential stores raise for an account removed or waiting for reauthorization."""


def account_unavailable() -> WatchFailure:
    """An account whose credentials are gone cannot be watched. Its rules meet the same and its
    owner is told there, so watching only backs off; the detail names no account."""
    return WatchFailure(
        kind=WatchFailureKind.UNSUPPORTED,
        detail="the connected account is no longer available",
    )


def watch_failure(failure: ProviderFailure) -> WatchFailure:
    """`failure`, met while watching, as the failure Instant Sync's upkeep acts on."""
    name = _named(failure)
    if _refuses_credentials(failure):
        return WatchFailure(
            kind=WatchFailureKind.UNAUTHORIZED,
            detail=f"{name} no longer accepts this account's access",
            failure=failure,
        )
    if failure.kind is ProviderFailureKind.RATE_LIMIT:
        return WatchFailure(
            kind=WatchFailureKind.RATE_LIMITED,
            detail=f"{name} is limiting requests",
            retry_after_seconds=failure.retry_after_seconds,
        )
    if failure.kind is ProviderFailureKind.TEMPORARY:
        return WatchFailure(
            kind=WatchFailureKind.TEMPORARY,
            detail=f"{name} is temporarily unavailable",
            retry_after_seconds=failure.retry_after_seconds,
        )
    return WatchFailure(
        kind=WatchFailureKind.UNSUPPORTED, detail=f"{name} cannot watch this calendar"
    )


def _refuses_credentials(failure: ProviderFailure) -> bool:
    """A refusal of the account's credentials or grant. A bare refusal may concern watching one
    calendar only, so it never lapses the account."""
    if failure.kind is ProviderFailureKind.AUTHENTICATION:
        return True
    return (
        failure.kind is ProviderFailureKind.AUTHORIZATION and failure.cause is Cause.ACCESS_REVOKED
    )


def _named(failure: ProviderFailure) -> str:
    name = failure.provider_name
    return name[:1].upper() + name[1:]
