"""Whether a User's rules may sync instantly, and how each rule syncs now, decided from facts."""

from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.cadence import DEFAULT_CADENCE, SyncCadence
from calendar_sync.domain.model import CalendarId, ConnectedAccountId
from calendar_sync.domain.watches import (
    AVAILABILITY_ANCHORS,
    LONGEST_REGISTRATION,
    Availability,
    CadenceReason,
    CalendarWatch,
    CalendarWatchId,
    DeliveryEvidence,
    DeliveryState,
    RegistrationState,
    WatchRegistration,
    WatchRegistrationId,
    WatchScope,
    effective_cadence,
    instant_sync_availability,
    token_hash,
)
from tests.helpers import NOW

ADDRESS = "https://ghost.example.test"
NO_INSTANT = SyncCadence(instant=False, poll_every=timedelta(minutes=5))
WORKING, FAILING, UNKNOWN = DeliveryState.WORKING, DeliveryState.FAILING, DeliveryState.UNKNOWN
WATCH = CalendarWatch(
    CalendarWatchId("watch-1"),
    ConnectedAccountId("personal-account"),
    WatchScope.calendar(CalendarId("personal-calendar")),
    coverage=frozenset({CalendarId("personal-calendar")}),
)
DELIVERING = WatchRegistration(
    id=WatchRegistrationId("registration-1"),
    watch_id=WATCH.id,
    state=RegistrationState.LIVE,
    address=f"{ADDRESS}/api/v1/watch-notices/example/registration-1",
    token_hash=token_hash("synthetic-token"),
    created_at=NOW,
    requested_until=NOW + LONGEST_REGISTRATION,
    handle="synthetic-handle",
    expires_at=NOW + timedelta(days=6),
    confirmed_at=NOW,
    renew_at=NOW + timedelta(days=4),
)


@pytest.mark.parametrize(
    ("success", "failure", "state"),
    [
        (None, None, DeliveryState.UNKNOWN),
        (NOW, None, DeliveryState.WORKING),
        (None, NOW, DeliveryState.FAILING),
        (NOW, NOW - timedelta(minutes=1), DeliveryState.WORKING),
        (NOW - timedelta(minutes=1), NOW, DeliveryState.FAILING),
        (NOW, NOW, DeliveryState.WORKING),
    ],
)
def test_delivery_fails_only_while_the_latest_failure_is_newer_than_the_latest_success(
    success: datetime | None, failure: datetime | None, state: DeliveryState
) -> None:
    evidence = DeliveryEvidence(ProviderKind.GOOGLE, ADDRESS, success, failure)

    assert evidence.state is state


@pytest.mark.parametrize(
    ("https", "cadence", "wanted", "delivery", "availability"),
    [
        (True, DEFAULT_CADENCE, True, (), Availability.ON),
        (True, DEFAULT_CADENCE, True, (WORKING, UNKNOWN), Availability.ON),
        (True, DEFAULT_CADENCE, True, (FAILING, WORKING), Availability.ON),
        (True, DEFAULT_CADENCE, True, (FAILING, UNKNOWN), Availability.ON),
        (True, DEFAULT_CADENCE, True, (FAILING,), Availability.NOT_REACHING),
        (True, DEFAULT_CADENCE, True, (FAILING, FAILING), Availability.NOT_REACHING),
        (True, DEFAULT_CADENCE, False, (FAILING,), Availability.OFF_BY_USER),
        (True, NO_INSTANT, False, (FAILING,), Availability.NOT_IN_PLAN),
        (False, NO_INSTANT, False, (FAILING,), Availability.NO_PUBLIC_ADDRESS),
        (False, DEFAULT_CADENCE, True, (), Availability.NO_PUBLIC_ADDRESS),
    ],
)
def test_availability_names_the_first_reason_that_stops_instant_sync(
    https: bool,
    cadence: SyncCadence,
    wanted: bool,
    delivery: tuple[DeliveryState, ...],
    availability: Availability,
) -> None:
    decided = instant_sync_availability(
        address_is_https=https, cadence=cadence, wanted=wanted, delivery=delivery
    )

    assert decided is availability


def test_every_reason_but_on_and_off_by_user_names_its_docs_section() -> None:
    assert set(AVAILABILITY_ANCHORS) == set(Availability) - {
        Availability.ON,
        Availability.OFF_BY_USER,
    }
    assert AVAILABILITY_ANCHORS[Availability.NO_PUBLIC_ADDRESS] == "no-public-https-address"
    assert AVAILABILITY_ANCHORS[Availability.NOT_IN_PLAN] == "not-in-your-plan"
    assert (
        AVAILABILITY_ANCHORS[Availability.NOT_REACHING] == "providers-cannot-reach-the-installation"
    )


@pytest.mark.parametrize(
    ("availability", "reason"),
    [
        (Availability.OFF_BY_USER, CadenceReason.OFF_BY_USER),
        (Availability.NOT_IN_PLAN, CadenceReason.NOT_IN_PLAN),
        (Availability.NO_PUBLIC_ADDRESS, CadenceReason.NO_PUBLIC_ADDRESS),
        (Availability.NOT_REACHING, CadenceReason.NOT_REACHING),
    ],
)
def test_a_rule_syncs_on_schedule_for_its_owners_reason_even_with_a_delivering_watch(
    availability: Availability, reason: CadenceReason
) -> None:
    assert effective_cadence(availability, WATCH, (DELIVERING,), NOW) is reason


def test_a_rule_whose_source_its_provider_cannot_watch_is_not_watchable() -> None:
    reason = effective_cadence(Availability.ON, None, (), NOW, unwatchable=True)

    assert reason is CadenceReason.NOT_WATCHABLE


def test_a_rule_whose_source_no_watch_covers_yet_waits_for_the_provider() -> None:
    # A new or resumed rule, until upkeep reaches it, or while its account's lookup backs off.
    assert effective_cadence(Availability.ON, None, (), NOW) is CadenceReason.WAITING_FOR_PROVIDER


def test_an_availability_reason_comes_before_an_unwatchable_source() -> None:
    reason = effective_cadence(Availability.OFF_BY_USER, None, (), NOW, unwatchable=True)

    assert reason is CadenceReason.OFF_BY_USER


def test_a_rule_syncs_instantly_while_its_watch_has_a_delivering_registration() -> None:
    assert effective_cadence(Availability.ON, WATCH, (DELIVERING,), NOW) is CadenceReason.INSTANT


@pytest.mark.parametrize(
    "registrations",
    [
        (),
        (replace(DELIVERING, confirmed_at=None),),
        (replace(DELIVERING, state=RegistrationState.CREATING),),
        (replace(DELIVERING, state=RegistrationState.RETIRING),),
        (replace(DELIVERING, expires_at=NOW),),
        (replace(DELIVERING, watch_id=CalendarWatchId("another-watch")),),
    ],
)
def test_a_watch_without_a_delivering_registration_waits_for_its_provider(
    registrations: tuple[WatchRegistration, ...],
) -> None:
    reason = effective_cadence(Availability.ON, WATCH, registrations, NOW)

    assert reason is CadenceReason.WAITING_FOR_PROVIDER
