"""Each calendar request reaches the adapter of its account's provider (ADR 0022)."""

from dataclasses import dataclass, field
from typing import cast
from unittest.mock import Mock

import pytest

from calendar_sync.application.errors import (
    AuthorizationNotConfigured,
    ConnectedAccountNotFound,
    ProviderFailure,
    ProviderFailureKind,
)
from calendar_sync.application.ports import AccountCalendars, CalendarAccess, DiscoveredCalendar
from calendar_sync.application.providers import ProviderKind
from calendar_sync.domain.model import ConnectedAccountId
from calendar_sync.infrastructure.providers.routing import (
    RoutingAccountCalendars,
    RoutingCalendarProvider,
)
from tests.fake_calendar import FakeCalendars
from tests.helpers import event

PERSONAL = ConnectedAccountId("personal-account")


@dataclass
class StoredKinds:
    kinds: dict[ConnectedAccountId, ProviderKind]
    lookups: list[ConnectedAccountId] = field(default_factory=list)

    def provider_of(self, account_id: ConnectedAccountId) -> ProviderKind | None:
        self.lookups.append(account_id)
        return self.kinds.get(account_id)


def test_a_request_reaches_the_adapter_of_its_accounts_provider() -> None:
    calendars = FakeCalendars()
    source = calendars.put(event())
    router = RoutingCalendarProvider(
        StoredKinds({PERSONAL: ProviderKind.GOOGLE}), {ProviderKind.GOOGLE: calendars}
    )

    assert router.get_event(source.reference) == source


def test_an_accounts_provider_is_looked_up_once() -> None:
    kinds = StoredKinds({PERSONAL: ProviderKind.GOOGLE})
    router = RoutingCalendarProvider(kinds, {ProviderKind.GOOGLE: FakeCalendars()})

    router.get_event(event().reference)
    router.get_event(event().reference)

    assert kinds.lookups == [PERSONAL]


def test_a_request_for_an_account_that_does_not_exist_fails_like_a_provider() -> None:
    calendars = FakeCalendars()
    kinds = StoredKinds({})
    router = RoutingCalendarProvider(kinds, {ProviderKind.GOOGLE: calendars})

    with pytest.raises(ProviderFailure) as raised:
        router.get_event(event().reference)

    assert raised.value.kind is ProviderFailureKind.PERMANENT
    assert raised.value.account_id == PERSONAL
    assert calendars.reads == []
    # An account that later connects is found: only answers are kept.
    kinds.kinds[PERSONAL] = ProviderKind.GOOGLE
    assert router.get_event(event().reference) is None


def test_a_provider_this_installation_has_not_configured_stops_the_rule() -> None:
    router = RoutingCalendarProvider(StoredKinds({PERSONAL: ProviderKind.GOOGLE}), {})

    with pytest.raises(ProviderFailure) as raised:
        router.get_event(event().reference)

    assert raised.value.kind is ProviderFailureKind.PERMANENT
    assert raised.value.provider is ProviderKind.GOOGLE
    assert str(raised.value) == "Google Calendar is not configured on this installation"


def test_account_calendars_reach_the_accounts_provider() -> None:
    family = DiscoveredCalendar("family", "Family", access=CalendarAccess.OWNER, primary=True)
    google = Mock()
    google.calendars.return_value = (family,)
    router = RoutingAccountCalendars(
        StoredKinds({PERSONAL: ProviderKind.GOOGLE}),
        {ProviderKind.GOOGLE: cast(AccountCalendars, google)},
    )

    assert router.calendars(PERSONAL) == (family,)
    google.calendars.assert_called_once_with(PERSONAL)


def test_account_calendars_of_an_account_that_does_not_exist_are_not_found() -> None:
    router = RoutingAccountCalendars(StoredKinds({}), {})

    with pytest.raises(ConnectedAccountNotFound):
        router.calendars(PERSONAL)


def test_account_calendars_of_an_unconfigured_provider_are_unavailable() -> None:
    router = RoutingAccountCalendars(StoredKinds({PERSONAL: ProviderKind.GOOGLE}), {})

    with pytest.raises(AuthorizationNotConfigured):
        router.verify_access(PERSONAL)
