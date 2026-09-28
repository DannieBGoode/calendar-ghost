from __future__ import annotations

import hashlib
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import timedelta

from calendar_sync.application.errors import (
    ProviderFailure,
    ProviderFailureKind,
    RuleNotExecutable,
)
from calendar_sync.application.locking import RuleLocks
from calendar_sync.application.ports import (
    AuditEntry,
    CalendarProvider,
    Clock,
    RuleRunOutcome,
    RunKind,
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
    SyncRule,
    SyncRuleId,
    SyncRuleState,
)
from calendar_sync.domain.services import ProjectionFingerprinter, SyncDecisionService


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
    locks: RuleLocks = field(default_factory=RuleLocks)

    def execute(self, rule_id: SyncRuleId, *, full: bool = False) -> SyncRunResult:
        with self.locks.for_rule(rule_id):
            try:
                return self._execute_serialized(rule_id, full=full)
            except RuleNotExecutable:
                raise
            except ProviderFailure as failure:
                self._record_failure(rule_id, full, failure.kind.value)
                raise
            except Exception:
                self._record_failure(rule_id, full, ProviderFailureKind.INFRASTRUCTURE.value)
                raise

    def _record_failure(self, rule_id: SyncRuleId, full: bool, kind: str) -> None:
        # Recording evidence must never replace the failure the scheduler classifies.
        with suppress(Exception), self.unit_of_work() as uow:
            if uow.rules.get(rule_id) is not None:
                uow.run_outcomes.record(
                    RuleRunOutcome(
                        rule_id, RunKind.SYNC, self.clock.now(), False, full, failure_kind=kind
                    )
                )
                uow.commit()

    def _execute_serialized(self, rule_id: SyncRuleId, *, full: bool) -> SyncRunResult:
        with self.unit_of_work() as uow:
            rule = uow.rules.get(rule_id)
            if rule is None:
                raise RuleNotExecutable(f"sync rule {rule_id.value} does not exist")
            if rule.state is not SyncRuleState.ENABLED:
                raise RuleNotExecutable(f"sync rule is {rule.state}, not enabled")

            reproject = rule.reprojection_required
            full_run = full or reproject
            cursor = None if full_run else uow.cursors.get(rule.id)
            destination_cursor = None if full_run else uow.destination_cursors.get(rule.id)
            cutoff = self.clock.now() - timedelta(days=rule.initial_lookback_days)
            changes = self.provider.changes(rule.source, cursor, cutoff)
            destination_changes = self.provider.changes(
                rule.destination, destination_cursor, cutoff
            )
            counts = {action: 0 for action in SyncAction}
            handled: set[EventRef] = set()

            for source_event in changes.events:
                self._synchronize_event(
                    uow,
                    rule,
                    source_event,
                    counts,
                    destination_loaded=False,
                    actual_destination=None,
                )
                handled.add(source_event.reference)
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
                            detail=(
                                "source could not be verified while repairing a destination change"
                            ),
                        )
                    )
                    uow.commit()
                    continue
                self._synchronize_event(
                    uow,
                    rule,
                    authoritative_source,
                    counts,
                    destination_loaded=True,
                    actual_destination=(
                        None
                        if destination_event.status is EventStatus.CANCELLED
                        else destination_event
                    ),
                )
                handled.add(mapping.source)
                uow.commit()

            if reproject:
                self._reproject_remaining(uow, rule, handled, counts)

            uow.cursors.save(rule.id, changes.next_cursor)
            uow.destination_cursors.save(rule.id, destination_changes.next_cursor)
            if reproject:
                current = uow.rules.get(rule.id)
                # An edit made while this run was in flight keeps reprojection pending.
                if (
                    current is not None
                    and current.reprojection_required
                    and current.material_signature == rule.material_signature
                ):
                    uow.rules.save(current.complete_reprojection())
            uow.run_outcomes.record(
                RuleRunOutcome(
                    rule.id,
                    RunKind.SYNC,
                    self.clock.now(),
                    True,
                    full_run,
                    created=counts[SyncAction.CREATE],
                    updated=counts[SyncAction.UPDATE],
                    deleted=counts[SyncAction.DELETE],
                    conflicts=counts[SyncAction.CONFLICT],
                )
            )
            uow.commit()

        return SyncRunResult(
            rule_id=rule_id,
            created=counts[SyncAction.CREATE],
            updated=counts[SyncAction.UPDATE],
            deleted=counts[SyncAction.DELETE],
            ignored=counts[SyncAction.IGNORE],
            conflicts=counts[SyncAction.CONFLICT],
        )

    def _reproject_remaining(
        self,
        uow: UnitOfWork,
        rule: SyncRule,
        handled: set[EventRef],
        counts: dict[SyncAction, int],
    ) -> None:
        """Apply a changed policy to mappings the change feeds did not report."""
        for mapping in uow.mappings.for_rule(rule.id):
            if mapping.source in handled:
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
                        detail="source could not be verified during reprojection",
                    )
                )
                uow.commit()
                continue
            self._synchronize_event(
                uow,
                rule,
                authoritative_source,
                counts,
                destination_loaded=False,
                actual_destination=None,
            )
            uow.commit()

    def _synchronize_event(
        self,
        uow: UnitOfWork,
        rule: SyncRule,
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
                outcome="completed" if decision.action is not SyncAction.CONFLICT else "blocked",
                source_event_id=source_event.reference.event_id.value,
                destination_event_id=mapping.destination.event_id.value if mapping else None,
                detail=decision.reason,
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
