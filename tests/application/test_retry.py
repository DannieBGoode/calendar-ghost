from __future__ import annotations

import pytest

from calendar_sync.application.errors import (
    ProjectionOwnershipMismatch,
    ProviderFailure,
    ProviderFailureKind,
)
from calendar_sync.application.retry import RETRY_ATTEMPTS, with_retries


class Operation:
    def __init__(self, *failures: ProviderFailure) -> None:
        self.failures = list(failures)
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return "done"


def test_transient_failures_are_retried_with_exponential_backoff_and_jitter() -> None:
    delays: list[float] = []
    operation = Operation(
        ProviderFailure(ProviderFailureKind.TEMPORARY, "outage"),
        ProviderFailure(ProviderFailureKind.RATE_LIMIT, "slow down"),
    )

    assert with_retries(operation, delays.append) == "done"

    assert operation.calls == 3
    assert [int(delay) for delay in delays] == [1, 2]
    assert all(0 <= delay - int(delay) <= 0.25 for delay in delays)


def test_a_provider_retry_after_replaces_the_backoff() -> None:
    delays: list[float] = []
    operation = Operation(ProviderFailure(ProviderFailureKind.RATE_LIMIT, "slow", 30))

    with_retries(operation, delays.append)

    assert 30 <= delays[0] <= 30.25


def test_transient_failures_give_up_after_the_last_attempt() -> None:
    outage = ProviderFailure(ProviderFailureKind.TEMPORARY, "outage")
    operation = Operation(*([outage] * RETRY_ATTEMPTS))

    with pytest.raises(ProviderFailure):
        with_retries(operation, lambda _: None)

    assert RETRY_ATTEMPTS == 3
    assert operation.calls == RETRY_ATTEMPTS


@pytest.mark.parametrize(
    "failure",
    [
        ProviderFailure(ProviderFailureKind.AUTHENTICATION, "expired"),
        ProviderFailure(ProviderFailureKind.AUTHORIZATION, "denied"),
        ProviderFailure(ProviderFailureKind.PERMANENT, "rejected"),
        ProjectionOwnershipMismatch("not ours"),
    ],
)
def test_authorization_and_ownership_failures_are_never_retried(failure: ProviderFailure) -> None:
    operation = Operation(failure)
    delays: list[float] = []

    with pytest.raises(type(failure)):
        with_retries(operation, delays.append)

    assert operation.calls == 1
    assert delays == []
