from collections.abc import Callable
from dataclasses import dataclass, field, replace

from calendar_sync.application.errors import (
    ApplicationError,
    ConnectedAccountRequired,
    DuplicateDirectionalRelationship,
    NotACalendarChange,
    RemovalInterrupted,
    ReplacementInterrupted,
    RuleNotFound,
)
from calendar_sync.application.locking import RuleLocks, RuleWork
from calendar_sync.application.ports import (
    AuditAction,
    AuditEntry,
    AuditOutcome,
    Clock,
    IdGenerator,
    RulePreviewSummary,
    RuleRunOutcome,
    RunKind,
    UnitOfWorkFactory,
)
from calendar_sync.application.removal import RemovalResult, RemoveSyncRule
from calendar_sync.domain.model import (
    AllDaySyncPolicy,
    CalendarEndpoint,
    PrivacyPolicy,
    ProjectionHandling,
    SyncRule,
    SyncRuleId,
    TransformationPolicy,
)


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
            # Checked after the insert holds the write lock, so an account deleted meanwhile
            # cannot be left with a rule that names it. Raising rolls the insert back.
            for endpoint in (rule.source, rule.destination):
                if uow.accounts.state(endpoint.connected_account_id) is None:
                    raise ConnectedAccountRequired(
                        "connect both Google accounts before creating a rule"
                    )
            uow.commit()
        return rule


@dataclass(slots=True)
class CreateDraftSyncRule:
    """Creates a new rule as a Draft under a generated identity; it must pass a Rule Preview."""

    create_rule: CreateSyncRule
    ids: IdGenerator

    def execute(
        self,
        source: CalendarEndpoint,
        destination: CalendarEndpoint,
        transformation: TransformationPolicy,
    ) -> SyncRule:
        return self.create_rule.execute(
            SyncRule(
                id=SyncRuleId(self.ids.new()),
                source=source,
                destination=destination,
                transformation=transformation,
            )
        )


@dataclass(slots=True)
class EnableSyncRule:
    """Enables a previewed rule; its next run reconciles before scheduled synchronization."""

    unit_of_work: UnitOfWorkFactory
    locks: RuleLocks

    def execute(self, rule_id: SyncRuleId) -> SyncRule:
        return _transition(self.unit_of_work, self.locks, rule_id, SyncRule.enable)


@dataclass(slots=True)
class PauseSyncRule:
    """Pauses a rule, preserving its mappings and projections."""

    unit_of_work: UnitOfWorkFactory
    locks: RuleLocks

    def execute(self, rule_id: SyncRuleId) -> SyncRule:
        # Waiting for any in-flight provider write means nothing is written after this returns.
        return _transition(self.unit_of_work, self.locks, rule_id, SyncRule.pause)


def _transition(
    unit_of_work: UnitOfWorkFactory,
    locks: RuleLocks,
    rule_id: SyncRuleId,
    change: Callable[[SyncRule], SyncRule],
) -> SyncRule:
    with locks.for_writes(rule_id), unit_of_work() as uow:
        rule = uow.rules.get(rule_id)
        if rule is None:
            raise RuleNotFound(f"sync rule {rule_id.value} does not exist")
        changed = change(rule)
        uow.rules.save(changed)
        uow.commit()
    return changed


@dataclass(slots=True)
class ChangeSyncRulePolicy:
    """Saves a Material Rule Change without writing to any calendar provider."""

    unit_of_work: UnitOfWorkFactory
    clock: Clock
    locks: RuleLocks = field(default_factory=RuleLocks)

    def execute(
        self, rule_id: SyncRuleId, privacy: PrivacyPolicy, all_day: AllDaySyncPolicy
    ) -> SyncRule:
        # Waiting for any in-flight provider write means none happens under the old policy
        # once this returns; the run's next stop check then sees the paused rule.
        with self.locks.for_writes(rule_id), self.unit_of_work() as uow:
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
                    action=AuditAction.POLICY_CHANGED,
                    outcome=AuditOutcome.COMPLETED,
                    detail=f"privacy={privacy.value}, all_day={all_day.value}",
                )
            )
            uow.commit()
        return changed


@dataclass(frozen=True, slots=True)
class SyncRuleSummary:
    rule: SyncRule
    last_sync: RuleRunOutcome | None
    latest_preview: RulePreviewSummary | None
    running: RuleWork | None
    """What runs for the rule in this process now, so a reloaded page can show it again."""


@dataclass(slots=True)
class ListSyncRules:
    unit_of_work: UnitOfWorkFactory
    locks: RuleLocks

    def execute(self) -> tuple[SyncRuleSummary, ...]:
        with self.unit_of_work() as uow:
            return tuple(
                SyncRuleSummary(
                    rule=rule,
                    last_sync=uow.run_outcomes.latest(rule.id, RunKind.SYNC),
                    latest_preview=uow.previews.latest(rule.id),
                    running=self.locks.current_work(rule.id),
                )
                for rule in uow.rules.list()
            )


@dataclass(frozen=True, slots=True)
class SyncRuleDetails:
    rule: SyncRule
    mapping_count: int
    last_sync: RuleRunOutcome | None
    last_reconciliation: RuleRunOutcome | None
    latest_preview: RulePreviewSummary | None = None
    running: RuleWork | None = None


@dataclass(slots=True)
class GetSyncRuleDetails:
    unit_of_work: UnitOfWorkFactory
    locks: RuleLocks = field(default_factory=RuleLocks)

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
                latest_preview=uow.previews.latest(rule_id),
                running=self.locks.current_work(rule_id),
            )


@dataclass(frozen=True, slots=True)
class RuleReplacement:
    rule: SyncRule
    removal: RemovalResult


@dataclass(slots=True)
class ReplaceSyncRuleCalendars:
    """Rule Replacement: reserve a new Draft with the same policy, then remove the old rule."""

    unit_of_work: UnitOfWorkFactory
    remove_rule: RemoveSyncRule
    create_rule: CreateSyncRule
    ids: IdGenerator

    def execute(
        self,
        rule_id: SyncRuleId,
        source: CalendarEndpoint,
        destination: CalendarEndpoint,
        handling: ProjectionHandling,
    ) -> RuleReplacement:
        with self.unit_of_work() as uow:
            current = uow.rules.get(rule_id)
            if current is None:
                raise RuleNotFound(f"sync rule {rule_id.value} does not exist")
            duplicate = uow.rules.relationship_exists(source, destination)
        if (source, destination) == (current.source, current.destination):
            raise NotACalendarChange("the calendars are unchanged; edit the policy instead")
        replacement = SyncRule(
            id=SyncRuleId(self.ids.new()),
            source=source,
            destination=destination,
            transformation=current.transformation,
            initial_lookback_days=current.initial_lookback_days,
        )
        if duplicate:
            raise DuplicateDirectionalRelationship(
                "a rule already exists for this source and destination"
            )
        self.remove_rule.check(rule_id, handling)
        # Creating first reserves the relationship through its uniqueness constraint, so a
        # concurrent duplicate fails here, before anything destructive happens.
        self.create_rule.execute(replacement)
        try:
            removal = self.remove_rule.execute(rule_id, handling)
        except RemovalInterrupted as interrupted:
            raise ReplacementInterrupted(replacement.id, interrupted) from interrupted
        except ApplicationError:
            # Removal did not start, so withdraw the unused draft and leave the old rule as is.
            with self.unit_of_work() as uow:
                uow.rules.remove(replacement.id)
                uow.commit()
            raise
        return RuleReplacement(replacement, removal)
