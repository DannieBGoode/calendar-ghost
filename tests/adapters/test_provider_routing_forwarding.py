"""Every calendar request reaches its account's adapter with its arguments unchanged (ADR 0022)."""

# Regression: ISSUE-001 — a router method that swapped or dropped arguments passed every test
# Found by /qa on 2026-10-03
# Report: .context/qa-reports/run-20261003T172929Z/qa-report-provider-routing-2026-10-03.md

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import cast

import pytest

from calendar_sync.application.ports import (
    CalendarProvider,
    CalendarReader,
    OccurrenceWriter,
    ProjectionDeleter,
    ProjectionWriter,
)
from calendar_sync.application.providers import ProviderKind
from calendar_sync.domain.model import (
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


class RecordingProvider:
    """Records each request it receives, as the router forwarded it."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def __getattr__(self, name: str) -> Callable[..., None]:
        def record(*args: object) -> None:
            self.calls.append((name, args))

        return record


@pytest.mark.parametrize(("method", "args"), CASES, ids=[method for method, _ in CASES])
def test_a_request_reaches_the_adapter_of_the_calendar_it_acts_on_unchanged(
    method: str, args: tuple[object, ...]
) -> None:
    adapter = RecordingProvider()
    router = RoutingCalendarProvider(
        OnlyRoutedAccount(), {ProviderKind.GOOGLE: cast(CalendarProvider, adapter)}
    )

    getattr(router, method)(*args)

    assert adapter.calls == [(method, args)]


def test_the_cases_cover_every_calendar_role() -> None:
    roles = (CalendarReader, ProjectionDeleter, ProjectionWriter, OccurrenceWriter)
    declared = {
        name
        for role in roles
        for name, value in vars(role).items()
        if callable(value) and not name.startswith("_")
    }

    assert {method for method, _ in CASES} == declared
