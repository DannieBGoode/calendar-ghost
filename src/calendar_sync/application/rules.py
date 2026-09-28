from dataclasses import dataclass, replace

from calendar_sync.application.errors import DuplicateDirectionalRelationship, RuleNotFound
from calendar_sync.application.ports import (
    AuditEntry,
    Clock,
    RuleRunOutcome,
    RunKind,
    UnitOfWorkFactory,
)
from calendar_sync.domain.model import AllDaySyncPolicy, PrivacyPolicy, SyncRule, SyncRuleId


@dataclass(slots=True)
class CreateSyncRule:
    unit_of_work: UnitOfWorkFactory

    def execute(self, rule: SyncRule) -> SyncRule:
        with self.unit_of_work() as uow:
            if uow.rules.relationship_exists(rule.source, rule.destination):
                raise DuplicateDirectionalRelationship(
                    "a rule already exists for this source and destination"
                )
            uow.rules.add(rule)
            uow.commit()
        return rule


@dataclass(slots=True)
class ChangeSyncRulePolicy:
    """Saves a Material Rule Change without writing to any calendar provider."""

    unit_of_work: UnitOfWorkFactory
    clock: Clock

    def execute(
        self, rule_id: SyncRuleId, privacy: PrivacyPolicy, all_day: AllDaySyncPolicy
    ) -> SyncRule:
        with self.unit_of_work() as uow:
            rule = uow.rules.get(rule_id)
            if rule is None:
                raise RuleNotFound(f"sync rule {rule_id.value} does not exist")
            changed = rule.change_policy(
                replace(rule.transformation, privacy=privacy, all_day=all_day)
            )
            if changed == rule:
                return rule
            uow.rules.save(changed)
            uow.audit.append(
                AuditEntry(
                    occurred_at=self.clock.now(),
                    rule_id=rule.id,
                    action="policy_changed",
                    outcome="completed",
                    detail=f"privacy={privacy.value}, all_day={all_day.value}",
                )
            )
            uow.commit()
        return changed


@dataclass(frozen=True, slots=True)
class SyncRuleDetails:
    rule: SyncRule
    mapping_count: int
    last_sync: RuleRunOutcome | None
    last_reconciliation: RuleRunOutcome | None


@dataclass(slots=True)
class GetSyncRuleDetails:
    unit_of_work: UnitOfWorkFactory

    def execute(self, rule_id: SyncRuleId) -> SyncRuleDetails:
        with self.unit_of_work() as uow:
            rule = uow.rules.get(rule_id)
            if rule is None:
                raise RuleNotFound(f"sync rule {rule_id.value} does not exist")
            return SyncRuleDetails(
                rule=rule,
                mapping_count=uow.mappings.count_for_rule(rule_id),
                last_sync=uow.run_outcomes.latest(rule_id, RunKind.SYNC),
                last_reconciliation=uow.run_outcomes.latest(rule_id, RunKind.RECONCILIATION),
            )
