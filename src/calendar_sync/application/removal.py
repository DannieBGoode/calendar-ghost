from __future__ import annotations

import hashlib
from dataclasses import dataclass

from calendar_sync.application.errors import (
    ProviderFailure,
    RemovalInterrupted,
    RemovalRequiresAuthorization,
    RemovalRequiresProvider,
    RuleNotFound,
)
from calendar_sync.application.locking import RuleLocks
from calendar_sync.application.ports import (
    AccountAuthorizations,
    AuditEntry,
    CalendarProvider,
    Clock,
    UnitOfWorkFactory,
)
from calendar_sync.domain.model import EventMapping, ProjectionHandling, SyncRule, SyncRuleId


@dataclass(frozen=True, slots=True)
class RemovalResult:
    deleted: int
    detached: int


@dataclass(slots=True)
class RemoveSyncRule:
    """Permanently removes a rule after deleting or detaching its mapped projections."""

    unit_of_work: UnitOfWorkFactory
    provider: CalendarProvider | None
    accounts: AccountAuthorizations | None
    clock: Clock
    locks: RuleLocks

    def check(self, rule_id: SyncRuleId, handling: ProjectionHandling) -> None:
        """Raise the error execute() would raise before changing anything."""
        with self.unit_of_work() as uow:
            rule = uow.rules.get(rule_id)
        self._require_possible(rule, rule_id, handling)

    def execute(self, rule_id: SyncRuleId, handling: ProjectionHandling) -> RemovalResult:
        with self.locks.for_rule(rule_id), self.unit_of_work() as uow:
            with self.locks.for_writes(rule_id):
                rule = self._require_possible(uow.rules.get(rule_id), rule_id, handling)
                uow.rules.save(rule.begin_removal())
                uow.commit()
            deleting = handling is ProjectionHandling.DELETE

            mappings = uow.mappings.for_rule(rule.id)
            deleted = 0
            for mapping in mappings:
                if deleting:
                    assert self.provider is not None
                    try:
                        self.provider.delete_projection(
                            mapping.destination, mapping.source, rule.id, _operation_key(mapping)
                        )
                    except ProviderFailure as failure:
                        raise RemovalInterrupted(
                            deleted, len(mappings) - deleted, failure
                        ) from failure
                    deleted += 1
                uow.mappings.delete(mapping)
                uow.audit.append(self._projection_entry(mapping, deleting))
                if deleting:
                    uow.commit()

            detached = len(mappings) - deleted
            uow.rules.remove(rule.id)
            uow.audit.append(
                AuditEntry(
                    occurred_at=self.clock.now(),
                    rule_id=rule.id,
                    action="rule_removed",
                    outcome="completed",
                    detail=f"{deleted} projections deleted, {detached} kept as detached events",
                )
            )
            uow.commit()
        return RemovalResult(deleted, detached)

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

    def _projection_entry(self, mapping: EventMapping, deleting: bool) -> AuditEntry:
        return AuditEntry(
            occurred_at=self.clock.now(),
            rule_id=mapping.rule_id,
            action="remove_projection" if deleting else "detach_projection",
            outcome="completed",
            source_event_id=mapping.source.event_id.value,
            destination_event_id=mapping.destination.event_id.value,
            detail=(
                "managed projection deleted during rule removal"
                if deleting
                else "mapping removed; projection kept as a detached event"
            ),
        )


def _operation_key(mapping: EventMapping) -> str:
    raw = "|".join((mapping.rule_id.value, mapping.id.value, "remove"))
    return hashlib.sha256(raw.encode()).hexdigest()
