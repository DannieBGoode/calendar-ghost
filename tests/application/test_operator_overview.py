"""The Operator Overview shows each User's Installation Status with calendars by neutral labels."""

from dataclasses import replace
from datetime import datetime, timedelta

from calendar_sync.application.locking import RuleLocks
from calendar_sync.application.operator_overview import UserStatuses, calendar_labels
from calendar_sync.application.ports import (
    CalendarAccess,
    ConnectedAccountState,
    DiscoveredCalendar,
    RuleRunOutcome,
    RunKind,
)
from calendar_sync.application.status import StatusVerdict
from calendar_sync.domain.model import ConnectedAccountId, SyncRuleId, SyncRuleState
from calendar_sync.infrastructure.persistence.memory import InMemoryUnitOfWorkFactory
from tests.helpers import NOW, RecentSchedulerHeartbeat, endpoint, rule
from tests.users import OTHER_USER, USER


class FixedClock:
    def now(self) -> datetime:
        return NOW


FAMILY = endpoint("personal-account", "family@group.calendar.example")
WORK = endpoint("work-account", "work-calendar")
TRIPS = endpoint("personal-account", "trips-calendar")


def _statuses(units: InMemoryUnitOfWorkFactory) -> UserStatuses:
    return UserStatuses(
        units.installation(), RuleLocks(), FixedClock(), RecentSchedulerHeartbeat(FixedClock())
    )


def test_calendars_are_numbered_in_the_order_their_rules_were_created() -> None:
    first = replace(rule(), id=SyncRuleId("rule-z"), source=FAMILY, destination=WORK)
    second = replace(rule(), id=SyncRuleId("rule-a"), source=WORK, destination=TRIPS)

    assert calendar_labels([first, second]) == {
        FAMILY: "Calendar 1",
        WORK: "Calendar 2",
        TRIPS: "Calendar 3",
    }


def test_each_users_status_names_calendars_only_by_their_labels() -> None:
    units = InMemoryUnitOfWorkFactory()
    created_first = replace(rule(), id=SyncRuleId("rule-z"), source=FAMILY, destination=WORK)
    created_second = replace(rule(), id=SyncRuleId("rule-a"), source=WORK, destination=TRIPS)
    with units.for_user(USER)() as uow:
        uow.rules.add(created_first)
        uow.rules.add(created_second)
        uow.calendar_names.remember(
            ConnectedAccountId("work-account"),
            [DiscoveredCalendar("work-calendar", "Secret project", CalendarAccess.OWNER, False)],
        )
        uow.commit()

    statuses = _statuses(units).of([USER, OTHER_USER])

    names = {status.summary.rule.id.value: status.name for status in statuses[USER].rules}
    assert names == {"rule-a": "Calendar 2 → Calendar 3", "rule-z": "Calendar 1 → Calendar 2"}
    assert "Secret project" not in repr(statuses)
    assert statuses[OTHER_USER].rules == ()


def test_a_users_verdict_and_problems_are_their_own_overviews() -> None:
    units = InMemoryUnitOfWorkFactory()
    stopped = replace(rule(), state=SyncRuleState.DEGRADED)
    state = units.for_user(USER).state
    for account in (FAMILY, WORK):
        state.accounts[account.connected_account_id] = ConnectedAccountState.CONNECTED
    with units.for_user(USER)() as uow:
        uow.rules.add(stopped)
        uow.run_outcomes.record(
            RuleRunOutcome(stopped.id, RunKind.SYNC, NOW - timedelta(days=2), True)
        )
        uow.commit()

    status = _statuses(units).of([USER])[USER]

    assert status.health is StatusVerdict.STOPPED
    assert [(problem.kind.value, problem.rule_id) for problem in status.problems] == [
        ("stopped", stopped.id.value)
    ]
    assert status.summary == "Calendar 1 → Calendar 2: Stopped syncing."
