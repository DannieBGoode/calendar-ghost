"""Every calendar request reaches its account's adapter with its arguments unchanged (ADR 0022)."""

# Regression: ISSUE-001 — a router method that swapped or dropped arguments passed every test
# Found by /qa on 2026-10-03
# Report: .context/qa-reports/run-20261003T172929Z/qa-report-provider-routing-2026-10-03.md

from __future__ import annotations

from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Lock
from typing import cast

import pytest

from calendar_sync.application.errors import ProviderFailure, ProviderFailureKind
from calendar_sync.application.ports import (
    CalendarProvider,
    CalendarReader,
    OccurrenceWriter,
    ProjectionDeleter,
    ProjectionWriter,
)
from calendar_sync.application.providers import ProviderKind
from calendar_sync.domain.model import (
    CalendarEvent,
    ConnectedAccountId,
    EventId,
    EventProjection,
    EventRef,
    SyncRuleId,
    TimedInterval,
    TransformationPolicy,
)
from calendar_sync.infrastructure.providers.routing import RoutingCalendarProvider
from tests.helpers import NOW, endpoint

# Only the account whose calendar a request acts on is known, so routing by any other endpoint
# fails instead of reaching the adapter.
ROUTED = endpoint("routed-account", "routed-calendar")
EVENT = EventRef(ROUTED, EventId("routed-event"))
SOURCE = EventRef(endpoint("unknown-account", "source-calendar"), EventId("source-event"))
RULE_ID = SyncRuleId("rule-1")
PROJECTION = EventProjection(time=TimedInterval(NOW, NOW + timedelta(hours=1)), title="Busy")

CASES: list[tuple[str, tuple[object, ...]]] = [
    ("changes", (ROUTED, "cursor", NOW)),
    ("get_event", (EVENT,)),
    ("find_projection", (ROUTED, "key")),
    ("list_events", (ROUTED, NOW)),
    ("managed_events", (ROUTED, RULE_ID, NOW)),
    ("get_occurrence", (EVENT, NOW)),
    ("list_occurrences", (EVENT, (NOW,))),
    ("has_live_occurrences", (EVENT, TransformationPolicy())),
    ("occurrence_exceptions", (EVENT, NOW)),
    ("create_projection", (ROUTED, SOURCE, RULE_ID, PROJECTION, "key")),
    ("update_projection", (EVENT, SOURCE, RULE_ID, PROJECTION, "key")),
    ("delete_projection", (EVENT, SOURCE, RULE_ID, "key")),
    ("write_occurrence", (EVENT, NOW, SOURCE, RULE_ID, PROJECTION, "key")),
    ("cancel_occurrence", (EVENT, NOW, SOURCE, RULE_ID, "key")),
]


class OnlyRoutedAccount:
    def provider_of(self, account_id: ConnectedAccountId) -> ProviderKind | None:
        return ProviderKind.GOOGLE if account_id == ROUTED.connected_account_id else None


# Methods the port contract declares as returning nothing.
VOID_METHODS = frozenset({"delete_projection", "cancel_occurrence"})


class RecordingProvider:
    """Records each request it receives, as the router forwarded it, and answers with a result.

    Every returning method answers with a distinct object unless the caller names a specific
    result in ``results``, so a test can tell the router handed back the adapter's actual answer
    rather than something it fabricated, swallowed, or dropped (a missing ``return`` would pass
    tests that only check the recorded call, not the returned value).
    """

    def __init__(self, results: Mapping[str, object] | None = None) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.results: dict[str, object] = dict(results) if results else {}

    def __getattr__(self, name: str) -> Callable[..., object]:
        def record(*args: object) -> object:
            self.calls.append((name, args))
            if name in VOID_METHODS:
                return None
            return self.results.setdefault(name, object())

        return record


@pytest.mark.parametrize(("method", "args"), CASES, ids=[method for method, _ in CASES])
def test_a_request_reaches_the_adapter_of_the_calendar_it_acts_on_unchanged(
    method: str, args: tuple[object, ...]
) -> None:
    adapter = RecordingProvider()
    router = RoutingCalendarProvider(
        OnlyRoutedAccount(), {ProviderKind.GOOGLE: cast(CalendarProvider, adapter)}
    )

    result = getattr(router, method)(*args)

    assert adapter.calls == [(method, args)]
    if method in VOID_METHODS:
        assert result is None
    else:
        assert result is adapter.results[method]


def test_falsy_results_reach_the_caller_unchanged() -> None:
    adapter = RecordingProvider(
        {
            "has_live_occurrences": False,
            "get_event": None,
            "managed_events": (),
            "occurrence_exceptions": (),
        }
    )
    router = RoutingCalendarProvider(
        OnlyRoutedAccount(), {ProviderKind.GOOGLE: cast(CalendarProvider, adapter)}
    )

    assert router.has_live_occurrences(EVENT, TransformationPolicy()) is False
    assert router.get_event(EVENT) is None
    assert router.managed_events(ROUTED, RULE_ID, NOW) == ()
    assert router.occurrence_exceptions(EVENT, NOW) == ()


def test_a_provider_failure_reaches_the_caller_as_the_same_object() -> None:
    failure = ProviderFailure(
        ProviderFailureKind.RATE_LIMIT,
        "rate limited, retry later",
        retry_after_seconds=30,
        account_id=ROUTED.connected_account_id,
        provider=ProviderKind.GOOGLE,
    )

    class FailingProvider:
        def get_event(self, reference: EventRef) -> CalendarEvent | None:
            raise failure

    router = RoutingCalendarProvider(
        OnlyRoutedAccount(), {ProviderKind.GOOGLE: cast(CalendarProvider, FailingProvider())}
    )

    with pytest.raises(ProviderFailure) as excinfo:
        router.get_event(EVENT)

    assert excinfo.value is failure
    assert excinfo.value.kind is ProviderFailureKind.RATE_LIMIT
    assert excinfo.value.account_id == ROUTED.connected_account_id
    assert excinfo.value.provider is ProviderKind.GOOGLE
    assert excinfo.value.retry_after_seconds == 30


def test_concurrent_calls_through_one_router_all_reach_the_adapter() -> None:
    class CountingKinds:
        """Answers like OnlyRoutedAccount, but counts how many times it is asked."""

        def __init__(self) -> None:
            self.lookups = 0
            self._guard = Lock()

        def provider_of(self, account_id: ConnectedAccountId) -> ProviderKind | None:
            with self._guard:
                self.lookups += 1
            return ProviderKind.GOOGLE if account_id == ROUTED.connected_account_id else None

    adapter = RecordingProvider({"get_event": object()})
    kinds = CountingKinds()
    router = RoutingCalendarProvider(kinds, {ProviderKind.GOOGLE: cast(CalendarProvider, adapter)})

    threads = 8
    calls_per_thread = 50

    with ThreadPoolExecutor(max_workers=threads) as pool:
        futures = [pool.submit(router.get_event, EVENT) for _ in range(threads * calls_per_thread)]
        results = [future.result() for future in futures]

    assert adapter.calls.count(("get_event", (EVENT,))) == threads * calls_per_thread
    assert all(result is adapter.results["get_event"] for result in results)
    # The cache only stores a kind once found; a race between threads that all miss the cache
    # before any of them stores its answer may cause a few duplicate lookups, but never more than
    # one per thread.
    assert kinds.lookups <= threads


def test_the_cases_cover_every_calendar_role() -> None:
    roles = (CalendarReader, ProjectionDeleter, ProjectionWriter, OccurrenceWriter)
    declared = {
        name
        for role in roles
        for name, value in vars(role).items()
        if callable(value) and not name.startswith("_")
    }

    assert {method for method, _ in CASES} == declared
