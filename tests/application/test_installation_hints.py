"""Installation Hints: likely causes from patterns across Users, never one User's content."""

from datetime import UTC, datetime, timedelta

import pytest

from calendar_sync.application.causes import Cause
from calendar_sync.application.installation_hints import (
    HINT_WINDOW,
    HINTED_USERS,
    TESTING_MODE_GRANT_LIFETIME,
    TESTING_MODE_TOLERANCE,
    HintKind,
    InstallationHint,
    installation_hints,
)
from calendar_sync.application.ports import CauseSighting
from calendar_sync.domain.access import UserId

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
ROBIN, SAM, ALEX = UserId("robin"), UserId("sam"), UserId("alex")


def seen(
    user: UserId,
    cause: Cause,
    *,
    ago: timedelta = timedelta(hours=1),
    open_: bool = False,
    authorized_for: timedelta | None = None,
) -> CauseSighting:
    return CauseSighting(user, cause, NOW - ago, open_, authorized_for)


def test_the_thresholds_are_two_users_a_day_and_about_seven_days() -> None:
    assert HINTED_USERS == 2
    assert timedelta(hours=24) == HINT_WINDOW
    assert timedelta(days=7) == TESTING_MODE_GRANT_LIFETIME
    assert timedelta(days=1) == TESTING_MODE_TOLERANCE


@pytest.mark.parametrize("cause", [Cause.API_DISABLED, Cause.QUOTA_EXCEEDED])
def test_an_administrators_cause_two_users_share_is_a_hint(cause: Cause) -> None:
    hints = installation_hints([seen(ROBIN, cause), seen(SAM, cause)], NOW)

    assert hints == (
        InstallationHint(
            HintKind.SHARED_CAUSE,
            cause,
            2,
            "the-google-calendar-api-is-turned-off"
            if cause is Cause.API_DISABLED
            else "the-google-cloud-projects-daily-quota-is-used-up",
        ),
    )


def test_an_administrators_cause_of_one_user_is_no_hint() -> None:
    # Below the threshold, however often that one User failed.
    sightings = [seen(ROBIN, Cause.API_DISABLED), seen(ROBIN, Cause.API_DISABLED, ago=timedelta())]

    assert installation_hints(sightings, NOW) == ()


def test_a_hint_counts_everyone_who_shares_the_cause() -> None:
    sightings = [seen(user, Cause.OAUTH_CLIENT_INVALID) for user in (ROBIN, SAM, ALEX)]

    (hint,) = installation_hints(sightings, NOW)

    assert (hint.cause, hint.users, hint.anchor) == (
        Cause.OAUTH_CLIENT_INVALID,
        3,
        "google-no-longer-accepts-the-oauth-client",
    )


def test_a_failure_exactly_a_day_old_counts_and_an_older_one_does_not() -> None:
    at_edge = [seen(ROBIN, Cause.API_DISABLED), seen(SAM, Cause.API_DISABLED, ago=HINT_WINDOW)]
    beyond = [
        seen(ROBIN, Cause.API_DISABLED),
        seen(SAM, Cause.API_DISABLED, ago=HINT_WINDOW + timedelta(seconds=1)),
    ]

    assert len(installation_hints(at_edge, NOW)) == 1
    assert installation_hints(beyond, NOW) == ()


def test_an_incident_still_open_counts_however_long_ago_it_failed() -> None:
    # A rule the Cause stopped tries no more, so its last failure ages while it stays stopped.
    sightings = [
        seen(ROBIN, Cause.API_DISABLED),
        seen(SAM, Cause.API_DISABLED, ago=timedelta(days=3), open_=True),
    ]

    assert len(installation_hints(sightings, NOW)) == 1


@pytest.mark.parametrize(
    "cause",
    [
        Cause.ACCESS_REVOKED,
        Cause.CALENDAR_FORBIDDEN,
        Cause.CALENDAR_NOT_FOUND,
        Cause.RATE_LIMITED,
        Cause.TEMPORARY,
    ],
)
def test_a_users_own_cause_is_never_a_hint_however_many_share_it(cause: Cause) -> None:
    sightings = [seen(user, cause) for user in (ROBIN, SAM, ALEX)]

    assert installation_hints(sightings, NOW) == ()


def test_many_users_failing_for_an_unrecognized_reason_points_to_the_logs() -> None:
    two = [seen(ROBIN, Cause.UNKNOWN), seen(SAM, Cause.UNKNOWN)]
    one = [seen(ROBIN, Cause.UNKNOWN)]

    assert installation_hints(two, NOW) == (
        InstallationHint(HintKind.UNRECOGNIZED, Cause.UNKNOWN, 2, "reading-the-logs"),
    )
    assert installation_hints(one, NOW) == ()


def lapse(user: UserId, authorized_for: timedelta, *, open_: bool = True) -> CauseSighting:
    return seen(
        user,
        Cause.ACCESS_REVOKED,
        ago=timedelta(days=2),
        open_=open_,
        authorized_for=authorized_for,
    )


TESTING_MODE = InstallationHint(
    HintKind.TESTING_MODE,
    Cause.ACCESS_REVOKED,
    2,
    "google-accounts-stop-working-7-days-after-connecting",
)


@pytest.mark.parametrize(
    "authorized_for",
    [
        TESTING_MODE_GRANT_LIFETIME,
        TESTING_MODE_GRANT_LIFETIME - TESTING_MODE_TOLERANCE,
        TESTING_MODE_GRANT_LIFETIME + TESTING_MODE_TOLERANCE,
    ],
)
def test_grants_refused_about_seven_days_after_authorizing_suggest_testing_mode(
    authorized_for: timedelta,
) -> None:
    sightings = [lapse(ROBIN, authorized_for), lapse(SAM, TESTING_MODE_GRANT_LIFETIME)]

    assert installation_hints(sightings, NOW) == (TESTING_MODE,)


@pytest.mark.parametrize(
    "authorized_for",
    [
        TESTING_MODE_GRANT_LIFETIME - TESTING_MODE_TOLERANCE - timedelta(seconds=1),
        TESTING_MODE_GRANT_LIFETIME + TESTING_MODE_TOLERANCE + timedelta(seconds=1),
        timedelta(days=60),
    ],
)
def test_grants_refused_at_another_age_do_not(authorized_for: timedelta) -> None:
    sightings = [lapse(ROBIN, authorized_for), lapse(SAM, TESTING_MODE_GRANT_LIFETIME)]

    assert installation_hints(sightings, NOW) == ()


def test_testing_mode_needs_two_users_whose_lapse_is_still_open() -> None:
    one = [lapse(ROBIN, TESTING_MODE_GRANT_LIFETIME)]
    reauthorized = [
        lapse(ROBIN, TESTING_MODE_GRANT_LIFETIME),
        lapse(SAM, TESTING_MODE_GRANT_LIFETIME, open_=False),
    ]

    assert installation_hints(one, NOW) == ()
    assert installation_hints(reauthorized, NOW) == ()


def test_hints_come_in_a_stable_order() -> None:
    sightings = [
        *(seen(user, Cause.QUOTA_EXCEEDED) for user in (ROBIN, SAM)),
        *(seen(user, Cause.UNKNOWN) for user in (ROBIN, SAM)),
        *(seen(user, Cause.API_DISABLED) for user in (ROBIN, SAM)),
        *(lapse(user, TESTING_MODE_GRANT_LIFETIME) for user in (ROBIN, SAM)),
    ]

    assert [(hint.kind, hint.cause) for hint in installation_hints(sightings, NOW)] == [
        (HintKind.SHARED_CAUSE, Cause.API_DISABLED),
        (HintKind.SHARED_CAUSE, Cause.QUOTA_EXCEEDED),
        (HintKind.TESTING_MODE, Cause.ACCESS_REVOKED),
        (HintKind.UNRECOGNIZED, Cause.UNKNOWN),
    ]
