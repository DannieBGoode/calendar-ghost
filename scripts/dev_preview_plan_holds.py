"""Synthetic Plan Hold fixtures for the isolated, scheduler-free development preview."""

from dataclasses import replace
from datetime import datetime, timedelta
from enum import StrEnum

from calendar_sync.bootstrap.container import Adapters
from calendar_sync.domain.access import UserId
from calendar_sync.domain.model import SyncRuleId, SyncRuleState
from calendar_sync.domain.plan_hold import PlanGrace
from calendar_sync.domain.plans import NewPlan, PlanKey, PlanLimits, SyncInterval
from calendar_sync.domain.runs import RuleRunOutcome, RunKind


class PlanHoldsFixture(StrEnum):
    GRACE = "grace"
    HELD = "held"
    MIXED = "mixed"
    RESERVED = "reserved"


def seed_plan_holds(
    adapters: Adapters, owner: UserId, now: datetime, fixture: PlanHoldsFixture
) -> None:
    """Layer two eligible rules and a one-rule Default Plan onto healthy Robin.

    The all-held fixture captures the moment before settlement releases one rule. No scheduler
    runs here, so that place stays free until the User explicitly saves their keep choice.
    No credentials, environment settings, provider calls, or email are needed.
    """
    key = PlanKey("preview-small")
    adapters.plan_catalog.add(
        NewPlan("Small", PlanLimits(1, 2, 1, SyncInterval.EVERY_5_MINUTES), key), now
    )
    adapters.plan_catalog.change_settings(True, key, now)
    with adapters.unit_of_work(owner)() as uow:
        (original,) = uow.rules.list()
        second = replace(
            original,
            id=SyncRuleId("preview-robin-work-personal"),
            source=original.destination,
            destination=original.source,
        )
        if fixture is PlanHoldsFixture.HELD:
            uow.rules.save(original.hold())
        if fixture in (PlanHoldsFixture.HELD, PlanHoldsFixture.MIXED):
            second = second.hold()
        elif fixture is PlanHoldsFixture.RESERVED:
            second = replace(second, state=SyncRuleState.DRAFT, keeps_place=True)
        uow.rules.add(second)
        uow.rules.keep((original.id,))
        if fixture in (PlanHoldsFixture.GRACE, PlanHoldsFixture.RESERVED):
            uow.plan_grace.save(PlanGrace(now + timedelta(days=3), 1, 0))
        if fixture is not PlanHoldsFixture.RESERVED:
            uow.run_outcomes.record(
                RuleRunOutcome(second.id, RunKind.SYNC, now - timedelta(hours=2), succeeded=True)
            )
        uow.commit()
