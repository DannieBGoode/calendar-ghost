from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from calendar_sync.application.errors import (
    ProjectionOwnershipMismatch,
    ProviderFailure,
    RemovalInterrupted,
    RemovalRequiresAuthorization,
    RemovalRequiresProvider,
    RuleNotFound,
)
from calendar_sync.application.locking import RuleLocks, RuleWork, RuleWorkKind
from calendar_sync.application.ports import (
    AccountAuthorizations,
    AuditAction,
    AuditEntry,
    AuditOutcome,
    Clock,
    ProjectionDeleter,
    ProviderCallStats,
    RemovalIncidents,
    UnitOfWork,
    UnitOfWorkFactory,
)
from calendar_sync.application.retry import with_retries
from calendar_sync.application.run_log import UntalliedProviderCalls, call_summary, duration
from calendar_sync.domain.model import EventMapping, ProjectionHandling, SyncRule, SyncRuleId

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RemovalResult:
    deleted: int
    detached: int
    conflicts: int


@dataclass(slots=True)
class RemoveSyncRule:
    """Permanently removes a rule after deleting or detaching its mapped projections."""

    unit_of_work: UnitOfWorkFactory
    provider: ProjectionDeleter | None
    accounts: AccountAuthorizations | None
    clock: Clock
    locks: RuleLocks
    incidents: RemovalIncidents | None = None
    sleep: Callable[[float], None] = field(default=time.sleep)
    call_stats: ProviderCallStats = field(default_factory=UntalliedProviderCalls)

    def check(self, rule_id: SyncRuleId, handling: ProjectionHandling) -> None:
        """Raise the error execute() would raise before changing anything."""
        with self.unit_of_work() as uow:
            rule = uow.rules.get(rule_id)
        self._require_possible(rule, rule_id, handling)

    def execute(self, rule_id: SyncRuleId, handling: ProjectionHandling) -> RemovalResult:
        work = RuleWork(RuleWorkKind.REMOVAL, self.clock.now(), handling=handling)
        with (
            self.locks.for_rule(rule_id),
            self.locks.working(rule_id, work),
            self.call_stats.measure() as calls,
            self.unit_of_work() as uow,
        ):
            with self.locks.for_writes(rule_id):
                rule = self._require_possible(uow.rules.get(rule_id), rule_id, handling)
                uow.rules.save(rule.begin_removal())
                uow.commit()
            mappings = uow.mappings.for_rule(rule.id)
            work.total = len(mappings)
            logger.info(
                "removal started rule=%s handling=%s mappings=%d",
                rule_id.value,
                handling.value,
                len(mappings),
            )
            try:
                result = self._remove(uow, rule, mappings, handling, work)
            except RemovalInterrupted as interrupted:
                logger.warning(
                    "removal interrupted rule=%s kind=%s after %s handled=%d remaining=%d %s",
                    rule_id.value,
                    interrupted.failure.kind.value,
                    duration(self.clock.now() - work.started_at),
                    interrupted.processed,
                    interrupted.remaining,
                    call_summary(calls),
                )
                raise
            logger.info(
                "removal finished rule=%s in %s deleted=%d detached=%d conflicts=%d %s",
                rule_id.value,
                duration(self.clock.now() - work.started_at),
                result.deleted,
                result.detached,
                result.conflicts,
                call_summary(calls),
            )
        return result

    def _remove(
        self,
        uow: UnitOfWork,
        rule: SyncRule,
        mappings: Sequence[EventMapping],
        handling: ProjectionHandling,
        work: RuleWork,
    ) -> RemovalResult:
        """Delete or detach every mapped projection, then remove the rule itself."""
        deleting = handling is ProjectionHandling.DELETE
        deleted = 0
        conflicts = 0
        for mapping in mappings:
            owned = True
            if deleting:
                try:
                    self._delete_with_retry(mapping)
                except ProjectionOwnershipMismatch:
                    # Unproven ownership blocks this event only; it stays in Google untouched.
                    owned = False
                    conflicts += 1
                except ProviderFailure as failure:
                    if failure.requires_authorization and self.incidents is not None:
                        self.incidents.removal_blocked(rule.id, failure)
                    raise RemovalInterrupted(
                        deleted + conflicts, len(mappings) - deleted - conflicts, failure
                    ) from failure
                else:
                    deleted += 1
            uow.mappings.delete(mapping)
            uow.audit.append(self._projection_entry(mapping, deleting, owned))
            if deleting:
                uow.commit()
            work.done += 1

        detached = len(mappings) - deleted - conflicts
        uow.rules.remove(rule.id)
        detail = f"{deleted} projections deleted, {detached} kept as detached events"
        if conflicts:
            detail += f", {conflicts} left because ownership could not be verified"
        uow.audit.append(
            AuditEntry(
                occurred_at=self.clock.now(),
                rule_id=rule.id,
                action=AuditAction.RULE_REMOVED,
                outcome=AuditOutcome.COMPLETED,
                detail=detail,
            )
        )
        uow.commit()
        return RemovalResult(deleted, detached, conflicts)

    def _delete_with_retry(self, mapping: EventMapping) -> None:
        provider = self.provider
        assert provider is not None
        operation_key = _operation_key(mapping)
        with_retries(
            lambda: provider.delete_projection(
                mapping.destination, mapping.source, mapping.rule_id, operation_key
            ),
            self.sleep,
        )

    def _require_possible(
        self, rule: SyncRule | None, rule_id: SyncRuleId, handling: ProjectionHandling
    ) -> SyncRule:
        if rule is None:
            raise RuleNotFound(f"sync rule {rule_id.value} does not exist")
        if handling is ProjectionHandling.DELETE:
            if self.provider is None or self.accounts is None:
                raise RemovalRequiresProvider(
                    "configure a calendar provider and the installation master key before "
                    "deleting projections"
                )
            if not self.accounts.is_connected(rule.destination.connected_account_id):
                raise RemovalRequiresAuthorization(
                    "reauthorize the destination account before deleting projections, "
                    "or keep them as detached events"
                )
        return rule

    def _projection_entry(self, mapping: EventMapping, deleting: bool, owned: bool) -> AuditEntry:
        if not owned:
            action = AuditAction.REMOVAL_CONFLICT
            detail = "mapping removed; event left because its ownership could not be verified"
        elif deleting:
            action = AuditAction.REMOVE_PROJECTION
            detail = "managed projection deleted during rule removal"
        else:
            action = AuditAction.DETACH_PROJECTION
            detail = "mapping removed; projection kept as a detached event"
        return AuditEntry(
            occurred_at=self.clock.now(),
            rule_id=mapping.rule_id,
            action=action,
            outcome=AuditOutcome.COMPLETED if owned else AuditOutcome.BLOCKED,
            source_event_id=mapping.source.event_id.value,
            destination_event_id=mapping.destination.event_id.value,
            detail=detail,
        )


def _operation_key(mapping: EventMapping) -> str:
    raw = "|".join((mapping.rule_id.value, mapping.id.value, "remove"))
    return hashlib.sha256(raw.encode()).hexdigest()
