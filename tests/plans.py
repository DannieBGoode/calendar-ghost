"""Plans for tests: a small free Plan and a larger family Plan (ADR 0038)."""

from calendar_sync.application.identity.ports import PlanCatalog
from calendar_sync.domain.plans import Plan, PlanKey, PlanLimits, SyncInterval
from tests.helpers import NOW

FREE = Plan(PlanKey("free"), "Free", PlanLimits(1, 1, 0, SyncInterval.EVERY_5_MINUTES))
"""One rule, one calendar account, no Integration Tokens, and no Instant Sync."""
FAMILY = Plan(PlanKey("family"), "Family", PlanLimits(5, 3, 2, SyncInterval.INSTANT))
"""Five rules, three calendar accounts, two Integration Tokens, and Instant Sync."""


def plans_on(catalog: PlanCatalog, default: Plan = FREE, *others: Plan) -> None:
    """Define `default` and `others`, and turn Plans on with `default` as the Default Plan."""
    for plan in (default, *others):
        catalog.add(plan, NOW)
    catalog.change_settings(True, default.key)
