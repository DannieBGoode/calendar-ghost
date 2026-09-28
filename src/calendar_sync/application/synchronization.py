from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from threading import Lock
from uuid import uuid4

from calendar_sync.application.errors import RuleNotExecutable
from calendar_sync.application.ports import (
    AuditEntry,
    CalendarProvider,
    Clock,
    UnitOfWork,
    UnitOfWorkFactory,
)
from calendar_sync.domain.model import (
    CalendarEvent,
    EventMapping,
    EventMappingId,
    EventRef,
    EventStatus,
    ProjectionFingerprint,
    SyncAction,
    SyncReason,
    SyncRule,
    SyncRuleId,
    SyncRuleState,
)
from calendar_sync.domain.services import ProjectionFingerprinter, SyncDecisionService

_OUTCOMES = {SyncAction.IGNORE: "skipped", SyncAction.CONFLICT: "blocked"}


@dataclass(frozen=True, slots=True)
class SyncRunResult:
    rule_id: SyncRuleId
    created: int = 0
    updated: int = 0
    deleted: int = 0
    ignored: int = 0
    conflicts: int = 0


@dataclass(slots=True)
class ExecuteSyncRule:
    unit_of_work: UnitOfWorkFactory
    provider: CalendarProvider
    decisions: SyncDecisionService
    fingerprinter: ProjectionFingerprinter
    clock: Clock
    new_run_id: Callable[[], str] = field(default=lambda: uuid4().hex)
    _rule_locks: dict[SyncRuleId, Lock] = field(default_factory=dict, init=False, repr=False)
    _locks_guard: Lock = field(default_factory=Lock, init=False, repr=False)

    def execute(self, rule_id: SyncRuleId, *, full: bool = False) -> SyncRunResult:
        with self._rule_lock(rule_id):
            return self._execute_serialized(rule_id, full=full)

    def _execute_serialized(self, rule_id: SyncRuleId, *, full: bool) -> SyncRunResult:
        with self.unit_of_work() as uow:
            rule = uow.rules.get(rule_id)
            if rule is None:
                raise RuleNotExecutable(f"sync rule {rule_id.value} does not exist")
            if rule.state is not SyncRuleState.ENABLED:
                raise RuleNotExecutable(f"sync rule is {rule.state}, not enabled")

            run_id = self.new_run_id()
            cursor = None if full else uow.cursors.get(rule.id)
            destination_cursor = None if full else uow.destination_cursors.get(rule.id)
            cutoff = self.clock.now() - timedelta(days=rule.initial_lookback_days)
            changes = self.provider.changes(rule.source, cursor, cutoff)
            destination_changes = self.provider.changes(
                rule.destination, destination_cursor, cutoff
            )
            counts = {action: 0 for action in SyncAction}

            for source_event in changes.events:
                self._synchronize_event(
                    uow,
                    rule,
                    run_id,
                    source_event,
                    counts,
                    destination_loaded=False,
                    actual_destination=None,
                )
                uow.commit()

            for destination_event in destination_changes.events:
                mapping = uow.mappings.for_destination(rule.id, destination_event.reference)
                if mapping is None:
                    continue
                authoritative_source = self.provider.get_event(mapping.source)
                if authoritative_source is None:
                    counts[SyncAction.CONFLICT] += 1
                    uow.audit.append(
                        AuditEntry(
                            occurred_at=self.clock.now(),
                            rule_id=rule.id,
                            action=SyncAction.CONFLICT.value,
                            outcome="blocked",
                            source_event_id=mapping.source.event_id.value,
                            destination_event_id=mapping.destination.event_id.value,
                            reason=SyncReason.SOURCE_UNVERIFIABLE.value,
                            run_id=run_id,
                        )
                    )
                    uow.commit()
                    continue
                self._synchronize_event(
                    uow,
                    rule,
                    run_id,
                    authoritative_source,
                    counts,
                    destination_loaded=True,
                    actual_destination=(
                        None
                        if destination_event.status is EventStatus.CANCELLED
                        else destination_event
                    ),
                )
                uow.commit()

            uow.cursors.save(rule.id, changes.next_cursor)
            uow.destination_cursors.save(rule.id, destination_changes.next_cursor)
            uow.commit()

        return SyncRunResult(
            rule_id=rule_id,
            created=counts[SyncAction.CREATE],
            updated=counts[SyncAction.UPDATE],
            deleted=counts[SyncAction.DELETE],
            ignored=counts[SyncAction.IGNORE],
            conflicts=counts[SyncAction.CONFLICT],
        )

    def _rule_lock(self, rule_id: SyncRuleId) -> Lock:
        with self._locks_guard:
            return self._rule_locks.setdefault(rule_id, Lock())

    def _synchronize_event(
        self,
        uow: UnitOfWork,
        rule: SyncRule,
        run_id: str,
        source_event: CalendarEvent,
        counts: dict[SyncAction, int],
        *,
        destination_loaded: bool,
        actual_destination: CalendarEvent | None,
    ) -> None:
        mapping = uow.mappings.for_source(rule.id, source_event.reference)
        actual = (
            actual_destination
            if destination_loaded
            else self.provider.get_event(mapping.destination)
            if mapping
            else None
        )
        decision = self.decisions.decide(rule, source_event, mapping, actual)
        counts[decision.action] += 1
        operation_key = self._operation_key(
            rule.id, source_event.reference, source_event.revision, decision.action
        )

        if decision.action is SyncAction.CREATE and decision.projection is not None:
            created = self.provider.create_projection(
                rule.destination,
                source_event.reference,
                rule.id,
                decision.projection,
                operation_key,
            )
            mapping = EventMapping(
                id=mapping.id if mapping else EventMappingId(operation_key),
                rule_id=rule.id,
                source=source_event.reference,
                destination=created.destination_event.reference,
                source_revision=source_event.revision,
                projection_fingerprint=self.fingerprinter.fingerprint(decision.projection),
            )
            uow.mappings.save(mapping)
        elif decision.action is SyncAction.UPDATE and decision.projection is not None:
            assert mapping is not None
            updated = self.provider.update_projection(
                mapping.destination,
                source_event.reference,
                rule.id,
                decision.projection,
                operation_key,
            )
            mapping = EventMapping(
                id=mapping.id,
                rule_id=mapping.rule_id,
                source=mapping.source,
                destination=updated.reference,
                source_revision=source_event.revision,
                projection_fingerprint=self.fingerprinter.fingerprint(decision.projection),
            )
            uow.mappings.save(mapping)
        elif decision.action is SyncAction.DELETE:
            owned = self.decisions.require_delete_ownership(mapping)
            self.provider.delete_projection(
                owned.destination,
                owned.source,
                rule.id,
                operation_key,
            )
            uow.mappings.delete(owned)

        uow.audit.append(
            AuditEntry(
                occurred_at=self.clock.now(),
                rule_id=rule.id,
                action=decision.action.value,
                outcome=_OUTCOMES.get(decision.action, "completed"),
                source_event_id=source_event.reference.event_id.value,
                destination_event_id=mapping.destination.event_id.value if mapping else None,
                reason=decision.reason.value,
                run_id=run_id,
            )
        )

    @staticmethod
    def _operation_key(
        rule_id: SyncRuleId,
        source: EventRef,
        revision: str,
        action: SyncAction,
    ) -> str:
        raw = "|".join(
            (
                rule_id.value,
                source.calendar.connected_account_id.value,
                source.calendar.calendar_id.value,
                source.event_id.value,
                revision,
                action.value,
            )
        )
        return hashlib.sha256(raw.encode()).hexdigest()


def stored_fingerprint(value: str) -> ProjectionFingerprint:
    """Reconstitute a persisted fingerprint without exposing event content."""
    return ProjectionFingerprint(value)
