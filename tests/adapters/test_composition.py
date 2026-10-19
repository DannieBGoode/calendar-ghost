"""The composed installation shares one rule lock registry across every use case, and one
Plans store across every Plan use case.

Rule execution is serialized only when every use case that runs, previews, reconciles, removes,
or changes a rule holds the same `RuleLocks`. No use case creates a registry of its own, so the
container is the one place a registry is made.
"""

from collections.abc import Iterator
from pathlib import Path

from calendar_sync.application.identity.ports import PlanListing
from calendar_sync.application.sync.locking import RuleLocks
from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import build_adapters, compose
from calendar_sync.domain.plans import Allowance, AllowanceBasis
from calendar_sync.infrastructure.security import CredentialCipher
from tests.plans import FAMILY, as_new
from tests.users import OTHER_USER, USER, administrator, limited_user

# Holders the walk must reach, so a change in how the container nests them cannot make it pass
# by finding nothing.
EXPECTED_HOLDERS = {
    "ExecuteSyncRule",
    "ChangeFeedCursors",
    "ReconcileSyncRule",
    "PreviewSyncRule",
    "RemoveSyncRule",
    "RuleHealth",
    "LapsedAuthorizations",
    "ListSyncRules",
    "EnableSyncRule",
    "PauseSyncRule",
    "ChangeSyncRulePolicy",
    "GetSyncRuleDetails",
    "DisconnectConnectedAccount",
    "DeleteConnectedAccount",
    "StorageAdministration",
    "UserStatuses",
}


def _attributes(value: object) -> Iterator[object]:
    if isinstance(value, (tuple, list, set, frozenset)):
        yield from value
        return
    if isinstance(value, dict):
        yield from value.values()
        return
    yield from getattr(value, "__dict__", {}).values()
    for cls in type(value).__mro__:
        for name in getattr(cls, "__slots__", ()):
            if hasattr(value, name):
                yield getattr(value, name)


def _lock_holders(root: object) -> list[tuple[str, RuleLocks]]:
    """Every Calendar Ghost object reachable from `root` that holds a `RuleLocks`."""
    holders: list[tuple[str, RuleLocks]] = []
    seen: set[int] = set()
    pending = [root]
    while pending:
        value = pending.pop()
        if id(value) in seen or isinstance(value, RuleLocks):
            continue
        seen.add(id(value))
        for attribute in _attributes(value):
            if isinstance(attribute, RuleLocks):
                holders.append((type(value).__name__, attribute))
            elif isinstance(attribute, (tuple, list, set, frozenset, dict)) or (
                type(attribute).__module__.startswith("calendar_sync.")
            ):
                pending.append(attribute)
    return holders


def test_every_composed_use_case_shares_the_installations_rule_locks(tmp_path: Path) -> None:
    settings = Settings(tmp_path / "test.db", master_key=CredentialCipher.generate_key())
    adapters = build_adapters(settings)
    container = compose(settings, adapters)

    holders = [
        *_lock_holders(container),
        *_lock_holders(container.for_user(USER)),
        *_lock_holders(container.for_user(OTHER_USER)),
    ]

    assert {name for name, _ in holders} >= EXPECTED_HOLDERS
    assert {id(locks) for _, locks in holders} == {id(adapters.locks)}


def test_the_plan_use_cases_share_the_installations_one_plans_store(tmp_path: Path) -> None:
    settings = Settings(tmp_path / "test.db")
    adapters = build_adapters(settings)
    container = compose(settings, adapters)
    admin = administrator(adapters)
    member = limited_user(settings.database_path)

    container.plans.define_plan.execute(admin, as_new(FAMILY))
    container.plans.assign_plans.execute(admin, {member: FAMILY.key})
    overview = container.plans.set_plans_setting.execute(admin, True, FAMILY.key)

    # FAMILY is the default and the member's own: both have it, and it limits the member.
    assert overview.plans == (PlanListing(FAMILY, True, 2, 1),)
    assert container.plans.show_plans.execute(admin) == overview
    assert adapters.allowances.of(member) == Allowance(
        AllowanceBasis.PLAN, plan=FAMILY, assigned=FAMILY
    )
