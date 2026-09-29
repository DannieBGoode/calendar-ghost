from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
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
    AuditEntry,
    CalendarProvider,
    Clock,
    RemovalIncidents,
    UnitOfWorkFactory,
)
from calendar_sync.application.retry import with_retries
from calendar_sync.domain.model import EventMapping, ProjectionHandling, SyncRule, SyncRuleId


@dataclass(frozen=True, slots=True)
class RemovalResult:
    deleted: int
    detached: int
    conflicts: int


@dataclass(slots=True)
class RemoveSyncRule:
    """Permanently removes a rule after deleting or detaching its mapped projections."""

    unit_of_work: UnitOfWorkFactory
    provider: CalendarProvider | None
    accounts: AccountAuthorizations | None
    clock: Clock
    locks: RuleLocks
    incidents: RemovalIncidents | None = None
    sleep: Callable[[float], None] = field(default=time.sleep)

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
            self.unit_of_work() as uow,
        ):
            with self.locks.for_writes(rule_id):
                rule = self._require_possible(uow.rules.get(rule_id), rule_id, handling)
                uow.rules.save(rule.begin_removal())
                uow.commit()
            deleting = handling is ProjectionHandling.DELETE

            mappings = uow.mappings.for_rule(rule.id)
            work.total = len(mappings)
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
                    action="rule_removed",
                    outcome="completed",
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
                    "configure Google OAuth and the installation master key before "
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
            action = "removal_conflict"
            detail = "mapping removed; event left because its ownership could not be verified"
        elif deleting:
            action = "remove_projection"
            detail = "managed projection deleted during rule removal"
        else:
            action = "detach_projection"
            detail = "mapping removed; projection kept as a detached event"
        return AuditEntry(
            occurred_at=self.clock.now(),
            rule_id=mapping.rule_id,
            action=action,
            outcome="completed" if owned else "blocked",
            source_event_id=mapping.source.event_id.value,
            destination_event_id=mapping.destination.event_id.value,
            detail=detail,
        )


def _operation_key(mapping: EventMapping) -> str:
    raw = "|".join((mapping.rule_id.value, mapping.id.value, "remove"))
    return hashlib.sha256(raw.encode()).hexdigest()
