"""A provider failure met while watching becomes the failure Instant Sync's upkeep acts on: only a
refusal of the account's credentials lapses it, and no provider text is kept (ADR 0036)."""

import pytest

from calendar_sync.application.sync.errors import ProviderFailure
from calendar_sync.application.sync.watch_ports import WatchFailureKind
from calendar_sync.domain.causes import Cause
from calendar_sync.domain.providers import ProviderFailureKind
from calendar_sync.infrastructure.watch_failures import account_unavailable, watch_failure


def failure(
    kind: ProviderFailureKind, cause: Cause | None = None, retry_after: int | None = None
) -> ProviderFailure:
    return ProviderFailure(
        kind,
        "private-marker said no",
        retry_after,
        cause=cause,
        provider_label="Example Calendar",
    )


@pytest.mark.parametrize(
    ("provider_failure", "kind"),
    [
        (
            failure(ProviderFailureKind.AUTHENTICATION, Cause.ACCESS_REVOKED),
            WatchFailureKind.UNAUTHORIZED,
        ),
        (
            failure(ProviderFailureKind.AUTHORIZATION, Cause.ACCESS_REVOKED),
            WatchFailureKind.UNAUTHORIZED,
        ),
        # A bare refusal may concern watching this calendar alone: it never lapses the account.
        (failure(ProviderFailureKind.AUTHORIZATION, Cause.UNKNOWN), WatchFailureKind.UNSUPPORTED),
        (
            failure(ProviderFailureKind.PERMANENT, Cause.CALENDAR_FORBIDDEN),
            WatchFailureKind.UNSUPPORTED,
        ),
        (
            failure(ProviderFailureKind.RATE_LIMIT, Cause.RATE_LIMITED, 30),
            WatchFailureKind.RATE_LIMITED,
        ),
        (failure(ProviderFailureKind.TEMPORARY, Cause.TEMPORARY), WatchFailureKind.TEMPORARY),
    ],
)
def test_a_provider_failure_is_classed_for_upkeep_in_calendar_ghosts_words(
    provider_failure: ProviderFailure, kind: WatchFailureKind
) -> None:
    watched = watch_failure(provider_failure)

    assert watched.kind is kind
    assert watched.detail.startswith("Example Calendar ")
    assert "private-marker" not in watched.detail


def test_only_a_refusal_of_credentials_carries_the_failure_that_lapses_the_account() -> None:
    refused = failure(ProviderFailureKind.AUTHENTICATION, Cause.ACCESS_REVOKED)

    assert watch_failure(refused).failure is refused
    assert watch_failure(failure(ProviderFailureKind.PERMANENT)).failure is None
    assert watch_failure(failure(ProviderFailureKind.TEMPORARY)).failure is None


def test_a_rate_limit_keeps_the_providers_retry_after() -> None:
    limited = watch_failure(failure(ProviderFailureKind.RATE_LIMIT, Cause.RATE_LIMITED, 30))

    assert limited.retry_after_seconds == 30


def test_an_unnamed_provider_is_named_neutrally() -> None:
    unnamed = ProviderFailure(ProviderFailureKind.TEMPORARY, "private-marker")

    assert watch_failure(unnamed).detail == "The calendar provider is temporarily unavailable"


def test_an_unavailable_account_is_unsupported_and_named_by_nothing() -> None:
    unavailable = account_unavailable()

    assert unavailable.kind is WatchFailureKind.UNSUPPORTED
    assert unavailable.failure is None
    assert "account-" not in unavailable.detail
