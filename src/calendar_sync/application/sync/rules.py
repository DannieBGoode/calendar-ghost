import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace

from calendar_sync.application.shared.ports import Clock, IdGenerator
from calendar_sync.application.sync.errors import (
    DuplicateDirectionalRelationship,
    NotACalendarChange,
    RemovalInterrupted,
    ReplacementInterrupted,
    RuleNotFound,
)
from calendar_sync.application.sync.locking import RuleLocks, RuleWork
from calendar_sync.application.sync.plan_ports import Allowances
from calendar_sync.application.sync.ports import UnitOfWork, UnitOfWorkFactory
from calendar_sync.application.sync.record_ports import RulePreviewSummary
from calendar_sync.application.sync.removal import RemovalResult, RemoveSyncRule
from calendar_sync.application.sync.rule_insertion import insert_rule
from calendar_sync.domain.access import UserId
from calendar_sync.domain.audit import AuditAction, AuditEntry, AuditOutcome
from calendar_sync.domain.model import (
    AllDaySyncPolicy,
    BirthdayPolicy,
    CalendarEndpoint,
    ProjectionContent,
    ProjectionHandling,
    SyncRule,
    SyncRuleId,
    TentativeEventPolicy,
    TransformationPolicy,
    UnansweredInvitationPolicy,
)
from calendar_sync.domain.plans import LimitedResource, PlanLimitReached, may_start
from calendar_sync.domain.runs import RuleRunOutcome, RunKind

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CreateSyncRule:
    unit_of_work: UnitOfWorkFactory

    def execute(self, rule: SyncRule) -> SyncRule:
        with self.unit_of_work() as uow:
            insert_rule(uow, rule)
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
    """Enables a previewed rule within its User's rule limit (ADR 0038); its next run reconciles
    before scheduled synchronization."""

    unit_of_work: UnitOfWorkFactory
    locks: RuleLocks
    allowances: Allowances
    owner: UserId

    def execute(self, rule_id: SyncRuleId) -> SyncRule:
        with self.locks.for_writes(rule_id), self.unit_of_work() as uow:
            rule = uow.rules.get(rule_id)
            if rule is None:
                raise RuleNotFound(f"sync rule {rule_id.value} does not exist")
            enabled = rule.enable()
            # Saved first: the save takes SQLite's writer lock, so no Start and no change of Plan
            # can commit between the limit read next and this unit's commit (ADR 0038). A read
            # that raises fails the Start, so a fault never admits a rule past the limit.
            uow.rules.save(enabled)
            limit = self.allowances.of(self.owner).limits.rules
            if limit is not None and not may_start(rule, _counted(uow.rules.list()), limit):
                raise PlanLimitReached(LimitedResource.RULES, limit)
            if not rule.counts_toward_plan:
                uow.plan_grace.admit()
            uow.commit()
        return enabled


def _counted(rules: Iterable[SyncRule]) -> int:
    """How many of a User's rules count toward their Plan's rule limit (ADR 0038)."""
    return sum(rule.counts_toward_plan for rule in rules)


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
    locks: RuleLocks

    def execute(
        self,
        rule_id: SyncRuleId,
        content: ProjectionContent,
        all_day: AllDaySyncPolicy,
        *,
        tentative: TentativeEventPolicy,
        unanswered: UnansweredInvitationPolicy,
        birthdays: BirthdayPolicy,
    ) -> SyncRule:
        # Waiting for any in-flight provider write means none happens under the old policy
        # once this returns; the run's next stop check then sees the paused rule.
        with self.locks.for_writes(rule_id), self.unit_of_work() as uow:
            rule = uow.rules.get(rule_id)
            if rule is None:
                raise RuleNotFound(f"sync rule {rule_id.value} does not exist")
            changed = rule.change_policy(
                replace(
                    rule.transformation,
                    content=content,
                    all_day=all_day,
                    tentative=tentative,
                    unanswered=unanswered,
                    birthdays=birthdays,
                )
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
                    detail=(
                        f"privacy={content.value}, all_day={all_day.value}, "
                        f"tentative={tentative.value}, unanswered={unanswered.value}, "
                        f"birthdays={birthdays.value}"
                    ),
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
    names: Mapping[CalendarEndpoint, str] = field(default_factory=dict)
    """The last name the provider gave each of the rule's calendars, when one was recorded."""


@dataclass(slots=True)
class ListSyncRules:
    unit_of_work: UnitOfWorkFactory
    locks: RuleLocks

    def execute(self) -> tuple[SyncRuleSummary, ...]:
        with self.unit_of_work() as uow:
            rules = tuple(uow.rules.list())
            names = uow.calendar_names.names(
                {endpoint for rule in rules for endpoint in (rule.source, rule.destination)}
            )
            return tuple(
                SyncRuleSummary(
                    rule=rule,
                    last_sync=uow.run_outcomes.latest(rule.id, RunKind.SYNC),
                    latest_preview=uow.previews.latest(rule.id),
                    running=self.locks.current_work(rule.id),
                    names=names,
                )
                for rule in rules
            )


@dataclass(frozen=True, slots=True)
class SyncRuleDetails:
    rule: SyncRule
    mapping_count: int
    last_sync: RuleRunOutcome | None
    last_reconciliation: RuleRunOutcome | None
    latest_preview: RulePreviewSummary | None = None
    running: RuleWork | None = None
    names: Mapping[CalendarEndpoint, str] = field(default_factory=dict)
    """The last name the provider gave each of the rule's calendars, when one was recorded."""
    can_start: bool = True
    """Whether Start would admit the rule now under its User's rule limit; Start checks again."""
    rule_limit: int | None = None
    """The rule limit that applies to the User; None when none does, or it could not be read."""


@dataclass(slots=True)
class GetSyncRuleDetails:
    unit_of_work: UnitOfWorkFactory
    locks: RuleLocks
    allowances: Allowances
    owner: UserId

    def execute(self, rule_id: SyncRuleId) -> SyncRuleDetails:
        with self.unit_of_work() as uow:
            rule = uow.rules.get(rule_id)
            if rule is None:
                raise RuleNotFound(f"sync rule {rule_id.value} does not exist")
            can_start, rule_limit = self._start_check(uow, rule)
            return SyncRuleDetails(
                rule=rule,
                mapping_count=uow.mappings.count_for_rule(rule_id),
                last_sync=uow.run_outcomes.latest(rule_id, RunKind.SYNC),
                last_reconciliation=uow.run_outcomes.latest(rule_id, RunKind.RECONCILIATION),
                latest_preview=uow.previews.latest(rule_id),
                running=self.locks.current_work(rule_id),
                names=uow.calendar_names.names((rule.source, rule.destination)),
                can_start=can_start,
                rule_limit=rule_limit,
            )

    def _start_check(self, uow: UnitOfWork, rule: SyncRule) -> tuple[bool, int | None]:
        """Whether Start would admit the rule now, and the rule limit it would apply.

        Fails open: when the User's Allowance cannot be read, Start shows as allowed with no
        limit, because Start reads it again and refuses then (ADR 0038).
        """
        try:
            limit = self.allowances.of(self.owner).limits.rules
        except Exception as error:
            # Only the class: the error's text could name more than the User.
            logger.warning(
                "Could not read the rule limit of User %s; Start checks it again (%s)",
                self.owner.value,
                error.__class__.__name__,
            )
            return True, None
        counting = _counted(uow.rules.list())
        after = counting if rule.counts_toward_plan else counting + 1
        return may_start(rule, after, limit), limit


@dataclass(frozen=True, slots=True)
class RuleReplacement:
    rule: SyncRule
    """The new draft as inserted; it keeps the previous rule's place when that rule counted."""
    removal: RemovalResult


@dataclass(slots=True)
class ReplaceSyncRuleCalendars:
    """Rule Replacement: remove the old rule, inserting a new Draft with the same policy in the
    step that begins the removal (ADR 0010, ADR 0038)."""

    unit_of_work: UnitOfWorkFactory
    remove_rule: RemoveSyncRule
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
        # The removal inserts the draft in the transaction that begins it, with the checks every
        # new rule passes: a duplicate that appeared meanwhile, or an account deleted meanwhile,
        # rolls both back before anything is removed, and no draft exists without its removal.
        try:
            removal = self.remove_rule.execute(rule_id, handling, successor=replacement)
        except RemovalInterrupted as interrupted:
            raise ReplacementInterrupted(replacement.id, interrupted) from interrupted
        assert removal.successor is not None
        return RuleReplacement(removal.successor, removal)
