"""Accounts an administrator's Cause stopped restart on their own once it is fixed (ADR 0031).

Such as an expired client secret: the administrator puts a new one in place, and every account
it stopped restarts without its owner choosing Check access.
"""

from collections.abc import Collection
from datetime import datetime

import pytest

from calendar_sync.application.sync.account_ports import AccountAccess
from calendar_sync.application.sync.accounts import CheckAccountAccess, RecheckAdministratorLapses
from calendar_sync.application.sync.errors import AccountAccessCheckFailed, ProviderFailure
from calendar_sync.application.sync.lapsed_authorization import LapsedAuthorizations
from calendar_sync.application.sync.locking import RuleLocks
from calendar_sync.domain.accounts import ConnectedAccount, ConnectedAccountState, ProviderKind
from calendar_sync.domain.causes import Cause
from calendar_sync.domain.incidents import IncidentReport, IncidentResolution
from calendar_sync.domain.model import ConnectedAccountId, SyncRuleState
from calendar_sync.domain.providers import ProviderFailureKind
from calendar_sync.infrastructure.persistence.memory import InMemoryUserUnitOfWorkFactory
from tests.application.test_accounts import CountingCalendars, RecordingAccounts
from tests.fake_calendar import FixedClock
from tests.helpers import NOW, rule
from tests.users import memory_units, rule_accounts

ACCOUNT = rule().source.connected_account_id


class Incidents:
    """Account Incidents by key, with the Cause each was opened with."""

    def __init__(self) -> None:
        self.open_ones: dict[str, IncidentReport] = {}
        self.notified: list[IncidentReport] = []

    def open(self, incident: IncidentReport, at: datetime, *, refresh: bool = True) -> bool:
        opened = incident.key not in self.open_ones
        if opened or refresh:
            self.open_ones[incident.key] = incident
        return opened

    def resolve(
        self,
        key: str,
        at: datetime,
        resolution: IncidentResolution,
        *,
        while_authorized: ConnectedAccountId | None = None,
    ) -> None:
        self.open_ones.pop(key, None)

    def accounts_with_open_incidents(self) -> frozenset[ConnectedAccountId]:
        return frozenset(i.account_id for i in self.open_ones.values() if i.account_id)

    def accounts_lapsed_by(self, causes: Collection[Cause]) -> frozenset[ConnectedAccountId]:
        return frozenset(
            i.account_id
            for i in self.open_ones.values()
            if i.rule_id is None and i.account_id is not None and i.cause in causes
        )


class Notifications:
    def __init__(self) -> None:
        self.opened: list[IncidentReport] = []

    def incident_opened(self, incident: IncidentReport, at: datetime) -> None:
        self.opened.append(incident)


class StillRefusing(CountingCalendars):
    def verify_access(self, account_id: ConnectedAccountId) -> AccountAccess:
        self.asked.append(account_id)
        raise AccountAccessCheckFailed(
            "refused", ProviderFailureKind.AUTHENTICATION, Cause.OAUTH_CLIENT_INVALID
        )


def _lapsed_by(
    cause: Cause, calendars: CountingCalendars
) -> tuple[InMemoryUserUnitOfWorkFactory, Incidents, Notifications, RecheckAdministratorLapses]:
    units = memory_units(accounts=rule_accounts(rule()))
    with units() as uow:
        uow.rules.add(rule())
        uow.commit()
    incidents, notifications = Incidents(), Notifications()
    lapses = LapsedAuthorizations(units, incidents, FixedClock(), RuleLocks(), notifications)
    refusal = ProviderFailure(
        ProviderFailureKind.AUTHENTICATION,
        "refused",
        account_id=ACCOUNT,
        provider=ProviderKind.GOOGLE,
        cause=cause,
    )
    lapses.lapsed(ACCOUNT, refusal, attempted_at=NOW)
    notifications.opened.clear()
    account = ConnectedAccount(
        ACCOUNT,
        "Personal",
        "personal@example.test",
        ConnectedAccountState.CONNECTED,
        provider=ProviderKind.GOOGLE,
    )
    check = CheckAccountAccess(calendars, RecordingAccounts(account), lapses)
    return units, incidents, notifications, RecheckAdministratorLapses(check, incidents)


def _state(units: InMemoryUserUnitOfWorkFactory) -> SyncRuleState:
    return units.state.rules[rule().id].state


@pytest.mark.parametrize("cause", [Cause.OAUTH_CLIENT_INVALID, Cause.API_DISABLED])
def test_an_account_an_administrators_cause_stopped_restarts_once_its_check_passes(
    cause: Cause,
) -> None:
    calendars = CountingCalendars()
    units, incidents, _, recheck = _lapsed_by(cause, calendars)
    assert _state(units) is SyncRuleState.DEGRADED

    resumed = recheck.execute()

    assert resumed == 1
    assert calendars.asked == [ACCOUNT]
    assert _state(units) is SyncRuleState.ENABLED
    assert units.state.lapsed == {}
    assert incidents.open_ones == {}


def test_an_account_only_its_owner_can_fix_is_left_for_them() -> None:
    calendars = CountingCalendars()
    units, _, _, recheck = _lapsed_by(Cause.ACCESS_REVOKED, calendars)

    assert recheck.execute() == 0
    assert calendars.asked == []
    assert _state(units) is SyncRuleState.DEGRADED


def test_a_check_that_still_fails_changes_nothing_and_notifies_nobody() -> None:
    calendars = StillRefusing()
    units, incidents, notifications, recheck = _lapsed_by(Cause.OAUTH_CLIENT_INVALID, calendars)

    assert recheck.execute() == 0

    assert calendars.asked == [ACCOUNT]
    assert _state(units) is SyncRuleState.DEGRADED
    assert [i.cause for i in incidents.open_ones.values()] == [Cause.OAUTH_CLIENT_INVALID]
    assert notifications.opened == []
