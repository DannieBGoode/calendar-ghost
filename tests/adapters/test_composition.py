"""The composed installation shares one rule lock registry across every use case, and one
Plans store across every Plan use case.

Rule execution is serialized only when every use case that runs, previews, reconciles, removes,
or changes a rule holds the same `RuleLocks`. No use case creates a registry of its own, so the
container is the one place a registry is made.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest

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


def test_composed_users_share_process_settlement_locks(tmp_path: Path) -> None:
    settings = Settings(tmp_path / "test.db")
    adapters = build_adapters(settings)
    container = compose(settings, adapters)
    first = container.for_user(USER)
    second = container.for_user(USER)
    other = container.for_user(OTHER_USER)
    assert first.plan_holds.settle_locks is second.plan_holds.settle_locks
    assert first.plan_holds.settle_locks is other.plan_holds.settle_locks
    assert first.choose_kept_rules.holds is first.plan_holds
    assert first.plan_holds.settle_locks.for_user(USER) is second.plan_holds.settle_locks.for_user(
        USER
    )


def test_production_composition_starts_grace_holds_and_releases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace
    from datetime import timedelta

    from calendar_sync.domain.model import (
        EventMapping,
        EventMappingId,
        ManagedOrigin,
        ProjectionFingerprint,
        SyncRuleId,
    )
    from calendar_sync.domain.plan_hold import PlanGrace, PlanNoticeKind
    from tests.adapters.test_notifications import RecordingSmtp
    from tests.fake_calendar import FakeCalendars, FixedClock
    from tests.helpers import NOW, endpoint, event, rule
    from tests.plans import FREE
    from tests.users import sqlite_units

    RecordingSmtp.sent = []
    monkeypatch.setattr("calendar_sync.infrastructure.notifications.smtplib.SMTP", RecordingSmtp)
    settings = Settings(
        tmp_path / "test.db",
        master_key=CredentialCipher.generate_key(),
        smtp_host="smtp.example.test",
        smtp_sender="ghost@example.test",
        public_url="https://ghost.example.test",
    )
    clock, provider = FixedClock(), FakeCalendars()
    adapters = replace(build_adapters(settings), clock=clock, calendar_provider=provider)
    container = compose(settings, adapters)
    admin = administrator(adapters)
    member = limited_user(settings.database_path)
    container.plans.define_plan.execute(admin, as_new(FREE))
    container.plans.set_plans_setting.execute(admin, True, FREE.key)
    units = sqlite_units(settings.database_path, user=member)
    grace = PlanGrace(NOW + timedelta(days=7), 1, 0)
    second = replace(rule(), id=SyncRuleId("second"), source=endpoint("personal-account", "second"))
    projection = replace(
        event("managed", calendar=second.destination),
        managed_origin=ManagedOrigin(second.id, event(calendar=second.source).reference),
    )
    mapping = EventMapping(
        EventMappingId("mapping"),
        second.id,
        event(calendar=second.source).reference,
        projection.reference,
        "revision",
        ProjectionFingerprint("hash"),
    )
    provider.events[projection.reference] = projection
    with units() as uow:
        uow.rules.add(rule())
        uow.rules.add(second)
        uow.mappings.save(mapping)
        uow.commit()
    assert container.scheduler is not None
    production = container.scheduler._pass
    preparation = production.prepare()
    assert len(preparation.begin()) == 2
    (delivery,) = preparation.notices_due()
    assert delivery.owner_key == member.value
    assert RecordingSmtp.sent == []
    delivery.deliver()
    (mail,) = RecordingSmtp.sent
    assert mail["To"] == "user-2@example.test"
    assert mail["Subject"] == "Calendar Ghost: your plan"
    assert "/settings/account#your-plan" in mail.get_content()
    assert all(
        marker not in mail.get_content()
        for marker in ("second", "personal-calendar", "Private appointment")
    )
    with units() as uow:
        assert all(each.synchronizes for each in uow.rules.list())
        assert uow.plan_grace.get() == grace
    monkeypatch.setattr(clock, "now", lambda: NOW + timedelta(days=7) - timedelta(seconds=1))
    assert len(production.begin()) == 2
    assert production.plan_notices_due() == ()
    monkeypatch.setattr(clock, "now", lambda: NOW + timedelta(days=7))
    assert [run.scheduled.rule.id for run in production.begin()] == [rule().id]
    ((owner, notice),) = production.plan_notices_due()
    assert owner == member
    assert notice.kind is PlanNoticeKind.RULES_HELD
    assert notice.held == 1
    production.send_plan_notice(owner, notice)
    assert len(RecordingSmtp.sent) == 2
    assert "now held by your plan" in RecordingSmtp.sent[-1].get_content()
    with units() as uow:
        held = uow.rules.get(second.id)
        assert held is not None
        assert held.held_by_plan
        assert uow.plan_grace.get() is None
        assert uow.mappings.for_source(second.id, mapping.source) == mapping
        uow.rules.save(rule().pause())
        uow.commit()
    assert [run.scheduled.rule.id for run in production.begin()] == [second.id]
    with units() as uow:
        released = uow.rules.get(second.id)
        assert released is not None
        assert released.synchronizes
        assert uow.mappings.for_source(second.id, mapping.source) == mapping
    assert provider.events == {projection.reference: projection}
    assert production.plan_notices_due() == ()
    from calendar_sync.infrastructure.persistence.connections import transaction

    with transaction(settings.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM audit_entries").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM incidents").fetchone()[0] == 0


@pytest.mark.parametrize("exemption", ["off", "administrator"])
def test_production_release_is_authorization_aware_and_exempts_off_and_admin(
    tmp_path: Path, exemption: str
) -> None:
    from dataclasses import replace
    from datetime import timedelta

    from calendar_sync.domain.access import Role
    from calendar_sync.domain.model import SyncRuleId
    from calendar_sync.domain.plan_hold import PlanGrace
    from calendar_sync.infrastructure.persistence.connections import transaction
    from tests.fake_calendar import FakeCalendars, FixedClock
    from tests.helpers import NOW, endpoint, rule
    from tests.plans import FREE
    from tests.users import sqlite_units

    settings = Settings(tmp_path / "test.db", master_key=CredentialCipher.generate_key())
    adapters = replace(
        build_adapters(settings), clock=FixedClock(), calendar_provider=FakeCalendars()
    )
    container = compose(settings, adapters)
    admin = administrator(adapters)
    member = limited_user(settings.database_path)
    container.plans.define_plan.execute(admin, as_new(FREE))
    container.plans.set_plans_setting.execute(admin, True, FREE.key)
    units = sqlite_units(settings.database_path, user=member)
    second = replace(rule(), id=SyncRuleId("second"), source=endpoint("personal-account", "second"))
    with units() as uow:
        uow.rules.add(rule().hold())
        uow.rules.add(second.hold())
        uow.commit()
    with transaction(settings.database_path) as connection:
        connection.execute(
            "UPDATE connected_accounts SET state = 'disconnected' WHERE user_id = ?",
            (member.value,),
        )
    assert container.scheduler is not None
    production = container.scheduler._pass
    assert production.begin() == ()
    with units() as uow:
        first = uow.rules.get(rule().id)
        held = uow.rules.get(second.id)
        assert first is not None
        assert first.awaiting_reauthorization
        assert held is not None
        assert held.held_by_plan
        uow.plan_grace.save(PlanGrace(NOW + timedelta(days=7), 1, 0))
        uow.commit()
    if exemption == "off":
        container.plans.set_plans_setting.execute(admin, False, FREE.key)
    else:
        adapters.users.set_role(member, Role.INSTALLATION_ADMINISTRATOR)
    assert production.begin() == ()
    with units() as uow:
        assert all(each.awaiting_reauthorization for each in uow.rules.list())
        assert uow.plan_grace.get() is None
    assert production.plan_notices_due() == ()
