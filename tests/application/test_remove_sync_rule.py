from __future__ import annotations

from dataclasses import replace

import pytest

from calendar_sync.application.errors import (
    DuplicateDirectionalRelationship,
    NotACalendarChange,
    ProviderFailure,
    ProviderFailureKind,
    RemovalInterrupted,
    RemovalRequiresAuthorization,
    RemovalRequiresProvider,
    ReplacementInterrupted,
)
from calendar_sync.application.locking import RuleLocks
from calendar_sync.application.ports import AccountAuthorizations, CalendarProvider
from calendar_sync.application.removal import RemoveSyncRule
from calendar_sync.application.rules import CreateSyncRule, ReplaceSyncRuleCalendars
from calendar_sync.domain.model import (
    ConnectedAccountId,
    EventId,
    EventMapping,
    EventMappingId,
    EventRef,
    PrivacyPolicy,
    ProjectionFingerprint,
    ProjectionHandling,
    SyncRule,
    SyncRuleId,
    SyncRuleState,
    TransformationPolicy,
)
from calendar_sync.infrastructure.persistence.memory import InMemoryUnitOfWorkFactory
from tests.application.test_execute_sync_rule import FakeCalendarProvider, FixedClock
from tests.helpers import endpoint, event, rule


class Accounts:
    def __init__(self, connected: bool = True) -> None:
        self.connected = connected

    def is_connected(self, account_id: ConnectedAccountId) -> bool:
        return self.connected


class RecordingProvider(FakeCalendarProvider):
    def __init__(self, fail_on_call: int | None = None) -> None:
        super().__init__(event())
        self.deleted_refs: list[EventRef] = []
        self.fail_on_call = fail_on_call

    def delete_projection(
        self,
        destination: EventRef,
        source: EventRef,
        rule_id: SyncRuleId,
        operation_key: str,
    ) -> None:
        if self.fail_on_call is not None and len(self.deleted_refs) + 1 == self.fail_on_call:
            raise ProviderFailure(ProviderFailureKind.AUTHORIZATION, "denied")
        self.deleted_refs.append(destination)


class Ids:
    def new(self) -> str:
        return "replacement-rule"


def _with_mappings(
    count: int, state: SyncRuleState = SyncRuleState.ENABLED
) -> InMemoryUnitOfWorkFactory:
    unit_of_work = InMemoryUnitOfWorkFactory()
    unit_of_work.state.rules[rule().id] = rule(state=state)
    for index in range(count):
        source = EventRef(rule().source, EventId(f"source-{index}"))
        unit_of_work.state.mappings[(rule().id, source)] = EventMapping(
            EventMappingId(f"mapping-{index}"),
            rule().id,
            source,
            EventRef(rule().destination, EventId(f"destination-{index}")),
            "revision-1",
            ProjectionFingerprint("fingerprint"),
        )
    return unit_of_work


def _remover(
    unit_of_work: InMemoryUnitOfWorkFactory,
    provider: CalendarProvider | None = None,
    accounts: AccountAuthorizations | None = None,
) -> RemoveSyncRule:
    return RemoveSyncRule(
        unit_of_work,
        provider if provider is not None else RecordingProvider(),
        accounts if accounts is not None else Accounts(),
        FixedClock(),
        RuleLocks(),
    )


def test_delete_removes_each_mapped_projection_then_the_rule() -> None:
    unit_of_work = _with_mappings(2)
    provider = RecordingProvider()

    result = _remover(unit_of_work, provider).execute(rule().id, ProjectionHandling.DELETE)

    assert (result.deleted, result.detached) == (2, 0)
    assert len(provider.deleted_refs) == 2
    assert unit_of_work.state.rules == {}
    assert unit_of_work.state.mappings == {}
    assert [entry.action for entry in unit_of_work.state.audit] == [
        "remove_projection",
        "remove_projection",
        "rule_removed",
    ]


def test_detach_makes_no_provider_calls_even_without_google_configured() -> None:
    unit_of_work = _with_mappings(2)

    result = RemoveSyncRule(unit_of_work, None, None, FixedClock(), RuleLocks()).execute(
        rule().id, ProjectionHandling.DETACH
    )

    assert (result.deleted, result.detached) == (0, 2)
    assert unit_of_work.state.rules == {}
    assert unit_of_work.state.mappings == {}
    assert unit_of_work.state.audit[-1].action == "rule_removed"


def test_delete_is_blocked_when_destination_is_disconnected_or_provider_missing() -> None:
    unit_of_work = _with_mappings(1)
    provider = RecordingProvider()

    with pytest.raises(RemovalRequiresAuthorization):
        _remover(unit_of_work, provider, Accounts(connected=False)).execute(
            rule().id, ProjectionHandling.DELETE
        )
    with pytest.raises(RemovalRequiresProvider):
        RemoveSyncRule(unit_of_work, None, None, FixedClock(), RuleLocks()).execute(
            rule().id, ProjectionHandling.DELETE
        )
    assert provider.deleted_refs == []
    assert unit_of_work.state.rules[rule().id].state is SyncRuleState.ENABLED
    assert len(unit_of_work.state.mappings) == 1


def test_interrupted_delete_leaves_rule_inert_and_retry_completes() -> None:
    unit_of_work = _with_mappings(3)

    with pytest.raises(RemovalInterrupted) as interrupted:
        _remover(unit_of_work, RecordingProvider(fail_on_call=2)).execute(
            rule().id, ProjectionHandling.DELETE
        )

    assert (interrupted.value.processed, interrupted.value.remaining) == (1, 2)
    assert "retry" in str(interrupted.value)
    assert unit_of_work.state.rules[rule().id].state is SyncRuleState.DISABLED
    assert len(unit_of_work.state.mappings) == 2

    result = _remover(unit_of_work).execute(rule().id, ProjectionHandling.DETACH)

    assert result.detached == 2
    assert unit_of_work.state.rules == {}


def test_replacement_rejects_a_duplicate_relationship_before_removing_anything() -> None:
    unit_of_work = _with_mappings(1)
    new_destination = endpoint("work-account", "other-calendar")
    unit_of_work.state.rules[SyncRuleId("existing")] = SyncRule(
        SyncRuleId("existing"), rule().source, new_destination
    )
    provider = RecordingProvider()
    replace_rule = ReplaceSyncRuleCalendars(
        unit_of_work, _remover(unit_of_work, provider), CreateSyncRule(unit_of_work), Ids()
    )

    with pytest.raises(DuplicateDirectionalRelationship):
        replace_rule.execute(rule().id, rule().source, new_destination, ProjectionHandling.DELETE)

    assert provider.deleted_refs == []
    assert unit_of_work.state.rules[rule().id].state is SyncRuleState.ENABLED


def test_replacement_rejects_unchanged_calendars() -> None:
    unit_of_work = _with_mappings(0)
    replace_rule = ReplaceSyncRuleCalendars(
        unit_of_work, _remover(unit_of_work), CreateSyncRule(unit_of_work), Ids()
    )

    with pytest.raises(NotACalendarChange):
        replace_rule.execute(
            rule().id, rule().source, rule().destination, ProjectionHandling.DELETE
        )
    assert rule().id in unit_of_work.state.rules


def test_replacement_removes_the_rule_and_creates_a_draft_with_the_same_policy() -> None:
    unit_of_work = _with_mappings(1)
    details = TransformationPolicy(privacy=PrivacyPolicy.COPY_DETAILS)
    unit_of_work.state.rules[rule().id] = replace(rule(), transformation=details)
    new_destination = endpoint("work-account", "other-calendar")
    replace_rule = ReplaceSyncRuleCalendars(
        unit_of_work, _remover(unit_of_work), CreateSyncRule(unit_of_work), Ids()
    )

    replacement = replace_rule.execute(
        rule().id, rule().source, new_destination, ProjectionHandling.DETACH
    )

    assert replacement.removal.detached == 1
    assert list(unit_of_work.state.rules) == [SyncRuleId("replacement-rule")]
    assert replacement.rule.state is SyncRuleState.DRAFT
    assert replacement.rule.transformation == details
    assert replacement.rule.destination == new_destination


class CompetingCreate(CreateSyncRule):
    """Simulates another request creating the same relationship just before this one."""

    def execute(self, rule: SyncRule) -> SyncRule:
        self.unit_of_work.state.rules[SyncRuleId("competitor")] = SyncRule(  # type: ignore[attr-defined]
            SyncRuleId("competitor"), rule.source, rule.destination
        )
        return CreateSyncRule.execute(self, rule)


def test_replacement_reserves_the_new_rule_before_removing_the_old_one() -> None:
    unit_of_work = _with_mappings(1)
    provider = RecordingProvider()
    replace_rule = ReplaceSyncRuleCalendars(
        unit_of_work,
        _remover(unit_of_work, provider),
        CompetingCreate(unit_of_work),
        Ids(),
    )

    with pytest.raises(DuplicateDirectionalRelationship):
        replace_rule.execute(
            rule().id,
            rule().source,
            endpoint("work-account", "other-calendar"),
            ProjectionHandling.DELETE,
        )

    assert provider.deleted_refs == []
    assert unit_of_work.state.rules[rule().id].state is SyncRuleState.ENABLED
    assert len(unit_of_work.state.mappings) == 1


def test_replacement_creates_nothing_when_removal_cannot_start() -> None:
    unit_of_work = _with_mappings(1)
    replace_rule = ReplaceSyncRuleCalendars(
        unit_of_work,
        _remover(unit_of_work, accounts=Accounts(connected=False)),
        CreateSyncRule(unit_of_work),
        Ids(),
    )

    with pytest.raises(RemovalRequiresAuthorization):
        replace_rule.execute(
            rule().id,
            rule().source,
            endpoint("work-account", "other-calendar"),
            ProjectionHandling.DELETE,
        )

    assert list(unit_of_work.state.rules) == [rule().id]


def test_interrupted_replacement_keeps_the_new_draft_and_a_retryable_old_rule() -> None:
    unit_of_work = _with_mappings(2)
    replace_rule = ReplaceSyncRuleCalendars(
        unit_of_work,
        _remover(unit_of_work, RecordingProvider(fail_on_call=2)),
        CreateSyncRule(unit_of_work),
        Ids(),
    )

    with pytest.raises(ReplacementInterrupted) as interrupted:
        replace_rule.execute(
            rule().id,
            rule().source,
            endpoint("work-account", "other-calendar"),
            ProjectionHandling.DELETE,
        )

    assert interrupted.value.replacement_rule_id == SyncRuleId("replacement-rule")
    assert "retry" in str(interrupted.value)
    assert unit_of_work.state.rules[SyncRuleId("replacement-rule")].state is SyncRuleState.DRAFT
    assert unit_of_work.state.rules[rule().id].state is SyncRuleState.DISABLED
