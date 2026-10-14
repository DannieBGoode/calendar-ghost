"""Watch Registrations and Calendar Watches decide their own lifecycle from time alone."""

import hashlib
from dataclasses import replace
from datetime import timedelta

import pytest

from calendar_sync.domain.errors import DomainValidationError
from calendar_sync.domain.model import CalendarId, ConnectedAccountId
from calendar_sync.domain.watches import (
    CONFIRMATION_DEADLINE,
    CREATION_DEADLINE,
    LONGEST_REGISTRATION,
    MAX_BACKOFF,
    CalendarWatch,
    CalendarWatchId,
    RegistrationState,
    WatchRegistration,
    WatchRegistrationId,
    WatchScope,
    backoff,
    renewal_time,
    token_hash,
)
from tests.helpers import NOW, endpoint

ADDRESS = "https://ghost.example.test/api/v1/watch-notices/example/registration-1"
LIVE = WatchRegistration(
    id=WatchRegistrationId("registration-1"),
    watch_id=CalendarWatchId("watch-1"),
    state=RegistrationState.LIVE,
    address=ADDRESS,
    token_hash=token_hash("synthetic-token"),
    created_at=NOW,
    requested_until=NOW + LONGEST_REGISTRATION,
    handle="synthetic-handle",
    expires_at=NOW + timedelta(days=6),
    confirmed_at=NOW,
    renew_at=NOW + timedelta(days=4),
)
CREATING = replace(
    LIVE,
    state=RegistrationState.CREATING,
    handle=None,
    expires_at=None,
    confirmed_at=None,
    renew_at=None,
)


@pytest.mark.parametrize("value", ["", "   "])
def test_identifiers_must_not_be_empty(value: str) -> None:
    with pytest.raises(DomainValidationError):
        CalendarWatchId(value)
    with pytest.raises(DomainValidationError):
        WatchRegistrationId(value)


def test_a_scope_covers_an_account_or_one_calendar() -> None:
    assert WatchScope.account().key == "account"
    assert WatchScope.account().calendar_id is None
    assert WatchScope.calendar(CalendarId("team@example.test")).key == "calendar:team@example.test"
    assert WatchScope.calendar(CalendarId("team")).calendar_id == CalendarId("team")


@pytest.mark.parametrize("key", ["", "calendar", "calendar:", "calendar: ", "mailbox"])
def test_a_scope_refuses_any_other_key(key: str) -> None:
    with pytest.raises(DomainValidationError):
        WatchScope(key)


def test_a_live_registration_is_usable_only_at_its_own_address_until_it_expires() -> None:
    assert LIVE.usable(NOW, ADDRESS)
    assert not LIVE.usable(NOW, ADDRESS.replace("ghost", "moved"))
    assert not LIVE.usable(NOW + timedelta(days=6), ADDRESS)
    for state in (RegistrationState.RETIRING, RegistrationState.ABANDONED):
        assert not replace(LIVE, state=state).usable(NOW, ADDRESS)
    assert not CREATING.usable(NOW, ADDRESS)


def test_only_a_confirmed_live_unexpired_registration_is_delivering() -> None:
    assert LIVE.delivering(NOW)
    assert not replace(LIVE, confirmed_at=None).delivering(NOW)
    assert not LIVE.delivering(NOW + timedelta(days=6))
    assert not replace(LIVE, state=RegistrationState.RETIRING).delivering(NOW)


def test_a_creation_is_stale_once_its_deadline_passes() -> None:
    assert not CREATING.creation_stale(NOW + CREATION_DEADLINE - timedelta(seconds=1))
    assert CREATING.creation_stale(NOW + CREATION_DEADLINE)
    assert not LIVE.creation_stale(NOW + CREATION_DEADLINE)


def test_an_unconfirmed_live_registration_is_overdue_after_the_confirmation_deadline() -> None:
    unconfirmed = replace(LIVE, confirmed_at=None)

    assert not unconfirmed.confirmation_overdue(NOW + CONFIRMATION_DEADLINE - timedelta(seconds=1))
    assert unconfirmed.confirmation_overdue(NOW + CONFIRMATION_DEADLINE)
    assert not LIVE.confirmation_overdue(NOW + CONFIRMATION_DEADLINE)
    assert not CREATING.confirmation_overdue(NOW + CONFIRMATION_DEADLINE)


def test_renewal_is_due_at_its_time_or_when_the_provider_asks() -> None:
    assert not LIVE.renewal_due(NOW + timedelta(days=4) - timedelta(seconds=1))
    assert LIVE.renewal_due(NOW + timedelta(days=4))
    assert replace(LIVE, renew_requested_at=NOW).renewal_due(NOW)
    assert not replace(LIVE, state=RegistrationState.RETIRING, renew_requested_at=NOW).renewal_due(
        NOW
    )


def test_a_registration_is_gone_once_it_would_have_expired() -> None:
    retiring = replace(LIVE, state=RegistrationState.RETIRING)
    lost = replace(CREATING, state=RegistrationState.ABANDONED)

    assert not retiring.gone(NOW + timedelta(days=6) - timedelta(seconds=1))
    assert retiring.gone(NOW + timedelta(days=6))
    assert LIVE.gone(NOW + timedelta(days=6))
    # Without an answer, it is kept as long as upkeep asked the provider to keep it.
    assert not lost.gone(NOW + timedelta(days=6))
    assert lost.gone(NOW + LONGEST_REGISTRATION)
    assert not CREATING.gone(NOW + timedelta(days=30))


def test_a_watch_covers_only_its_own_accounts_calendars_in_its_coverage() -> None:
    watch = CalendarWatch(
        CalendarWatchId("watch-1"),
        ConnectedAccountId("personal-account"),
        WatchScope.account(),
        coverage=frozenset({CalendarId("personal-calendar")}),
    )

    assert watch.covers(endpoint("personal-account", "personal-calendar"))
    assert not watch.covers(endpoint("personal-account", "other-calendar"))
    assert not watch.covers(endpoint("work-account", "personal-calendar"))


def test_a_watch_waits_until_its_retry_time() -> None:
    watch = CalendarWatch(
        CalendarWatchId("watch-1"), ConnectedAccountId("personal-account"), WatchScope.account()
    )

    assert not watch.waiting(NOW)
    assert replace(watch, retry_at=NOW + timedelta(minutes=1)).waiting(NOW)
    assert not replace(watch, retry_at=NOW).waiting(NOW)


@pytest.mark.parametrize(
    ("jitter", "after"),
    [(0.0, timedelta(days=4)), (0.5, timedelta(days=4, hours=12)), (0.999, timedelta(days=5))],
)
def test_renewal_falls_in_the_last_third_of_the_lifetime(jitter: float, after: timedelta) -> None:
    renew_at = renewal_time(NOW, NOW + timedelta(days=6), jitter)

    assert abs(renew_at - (NOW + after)) < timedelta(minutes=10)
    assert NOW + timedelta(days=4) <= renew_at < NOW + timedelta(days=5)


@pytest.mark.parametrize("jitter", [-0.1, 1.0])
def test_renewal_jitter_lies_between_zero_and_one(jitter: float) -> None:
    with pytest.raises(DomainValidationError):
        renewal_time(NOW, NOW + timedelta(days=6), jitter)


@pytest.mark.parametrize(
    ("failures", "delay"),
    [
        (1, timedelta(minutes=1)),
        (2, timedelta(minutes=2)),
        (5, timedelta(minutes=16)),
        (11, timedelta(minutes=1024)),
        (12, MAX_BACKOFF),
        (500, MAX_BACKOFF),
    ],
)
def test_backoff_doubles_from_a_minute_up_to_a_day(failures: int, delay: timedelta) -> None:
    assert backoff(failures) == delay


def test_backoff_honors_a_longer_retry_after() -> None:
    assert backoff(1, timedelta(minutes=10)) == timedelta(minutes=10)
    assert backoff(3, timedelta(seconds=30)) == timedelta(minutes=4)


def test_backoff_follows_at_least_one_failure() -> None:
    with pytest.raises(DomainValidationError):
        backoff(0)


def test_a_token_is_kept_only_as_its_sha256_hex_digest() -> None:
    digest = token_hash("synthetic-token")

    assert digest == hashlib.sha256(b"synthetic-token").hexdigest()
    assert "synthetic-token" not in digest
