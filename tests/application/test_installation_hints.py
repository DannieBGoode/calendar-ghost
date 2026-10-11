"""Installation Hints: likely causes from patterns across Users, never one User's content."""

from datetime import UTC, datetime, timedelta

import pytest

from calendar_sync.application.causes import Cause
from calendar_sync.application.installation_hints import (
    ADMINISTRATOR_CAUSE_USERS,
    HINT_WINDOW,
    HINTED_USERS,
    UNRECOGNIZED_ANCHOR,
    HintKind,
    InstallationHint,
    installation_hints,
)
from calendar_sync.application.ports import CauseSighting
from calendar_sync.application.provider_descriptors import GrantLifetime, ProviderGuide
from calendar_sync.application.providers import ProviderKind
from calendar_sync.domain.access import UserId

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
ROBIN, SAM, ALEX = UserId("robin"), UserId("sam"), UserId("alex")
PROVIDER = ProviderKind.GOOGLE
LIFETIME = GrantLifetime(timedelta(days=7), timedelta(days=1), "grants-expire-after-a-week")
# A synthetic provider's guide: hints read anchors and rules from it, never from the provider.
GUIDE = ProviderGuide(
    PROVIDER,
    slug="example",
    display_name="Example",
    calendar_name="Example Calendar",
    cause_anchors={
        Cause.API_DISABLED: "the-api-is-off",
        Cause.QUOTA_EXCEEDED: "the-quota-is-used-up",
        Cause.OAUTH_CLIENT_INVALID: "the-client-is-refused",
    },
    grant_lifetime=LIFETIME,
)
GUIDES = (GUIDE,)


def seen(
    user: UserId,
    cause: Cause,
    *,
    ago: timedelta = timedelta(hours=1),
    open_: bool = False,
    authorized_for: timedelta | None = None,
    provider: ProviderKind | None = PROVIDER,
) -> CauseSighting:
    return CauseSighting(user, cause, NOW - ago, open_, authorized_for, provider=provider)


def hints_of(sightings: list[CauseSighting]) -> tuple[InstallationHint, ...]:
    return installation_hints(sightings, NOW, GUIDES)


def test_the_thresholds_are_one_user_for_the_administrators_two_for_a_pattern() -> None:
    # Only the administrator can fix their Cause, so one person meeting it is enough to say so.
    assert ADMINISTRATOR_CAUSE_USERS == 1
    assert HINTED_USERS == 2
    assert timedelta(hours=24) == HINT_WINDOW


@pytest.mark.parametrize("cause", [Cause.API_DISABLED, Cause.QUOTA_EXCEEDED])
def test_an_administrators_cause_two_users_share_is_a_hint(cause: Cause) -> None:
    hints = hints_of([seen(ROBIN, cause), seen(SAM, cause)])

    assert hints == (
        InstallationHint(
            HintKind.SHARED_CAUSE, cause, 2, GUIDE.cause_anchors[cause], provider=PROVIDER
        ),
    )


def test_an_administrators_cause_of_one_user_is_a_hint_counting_them_once() -> None:
    sightings = [seen(ROBIN, Cause.API_DISABLED), seen(ROBIN, Cause.API_DISABLED, ago=timedelta())]

    assert hints_of(sightings) == (
        InstallationHint(
            HintKind.SHARED_CAUSE, Cause.API_DISABLED, 1, "the-api-is-off", provider=PROVIDER
        ),
    )


def test_a_cause_the_provider_never_raises_is_no_hint() -> None:
    # The guide names the troubleshooting section for each Cause its provider can raise.
    without_quota = ProviderGuide(
        PROVIDER, "example", "Example", "Example Calendar", {Cause.API_DISABLED: "the-api-is-off"}
    )

    assert installation_hints([seen(ROBIN, Cause.QUOTA_EXCEEDED)], NOW, (without_quota,)) == ()


def test_a_failure_of_a_provider_without_a_guide_is_no_hint() -> None:
    sightings = [seen(user, Cause.UNKNOWN, provider=None) for user in (ROBIN, SAM)]

    assert hints_of([*sightings, seen(ROBIN, Cause.API_DISABLED, provider=None)]) == ()


def test_without_an_administrators_cause_there_is_no_hint_for_it() -> None:
    assert hints_of([seen(ROBIN, Cause.ACCESS_REVOKED)]) == ()


def test_a_hint_counts_everyone_who_shares_the_cause() -> None:
    sightings = [seen(user, Cause.OAUTH_CLIENT_INVALID) for user in (ROBIN, SAM, ALEX)]

    (hint,) = hints_of(sightings)

    assert (hint.cause, hint.users, hint.anchor, hint.provider) == (
        Cause.OAUTH_CLIENT_INVALID,
        3,
        "the-client-is-refused",
        PROVIDER,
    )


def test_a_failure_exactly_a_day_old_counts_and_an_older_one_does_not() -> None:
    at_edge = [seen(SAM, Cause.API_DISABLED, ago=HINT_WINDOW)]
    beyond = [seen(SAM, Cause.API_DISABLED, ago=HINT_WINDOW + timedelta(seconds=1))]

    assert len(hints_of(at_edge)) == 1
    assert hints_of(beyond) == ()


def test_an_incident_still_open_counts_however_long_ago_it_failed() -> None:
    # A rule the Cause stopped tries no more, so its last failure ages while it stays stopped.
    sightings = [seen(SAM, Cause.API_DISABLED, ago=timedelta(days=3), open_=True)]

    assert len(hints_of(sightings)) == 1


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

    assert hints_of(sightings) == ()


def test_many_users_failing_for_an_unrecognized_reason_points_to_the_logs() -> None:
    two = [seen(ROBIN, Cause.UNKNOWN), seen(SAM, Cause.UNKNOWN)]
    one = [seen(ROBIN, Cause.UNKNOWN)]

    assert hints_of(two) == (
        InstallationHint(
            HintKind.UNRECOGNIZED, Cause.UNKNOWN, 2, UNRECOGNIZED_ANCHOR, provider=PROVIDER
        ),
    )
    assert UNRECOGNIZED_ANCHOR == "reading-the-logs"
    assert hints_of(one) == ()


def lapse(user: UserId, authorized_for: timedelta, *, open_: bool = True) -> CauseSighting:
    return seen(
        user,
        Cause.ACCESS_REVOKED,
        ago=timedelta(days=2),
        open_=open_,
        authorized_for=authorized_for,
    )


GRANT_LIFETIME_HINT = InstallationHint(
    HintKind.TESTING_MODE, Cause.ACCESS_REVOKED, 2, LIFETIME.anchor, provider=PROVIDER
)


@pytest.mark.parametrize(
    "authorized_for",
    [
        LIFETIME.lifetime,
        LIFETIME.lifetime - LIFETIME.tolerance,
        LIFETIME.lifetime + LIFETIME.tolerance,
    ],
)
def test_grants_refused_about_the_providers_grant_lifetime_after_authorizing_are_a_hint(
    authorized_for: timedelta,
) -> None:
    sightings = [lapse(ROBIN, authorized_for), lapse(SAM, LIFETIME.lifetime)]

    assert hints_of(sightings) == (GRANT_LIFETIME_HINT,)


@pytest.mark.parametrize(
    "authorized_for",
    [
        LIFETIME.lifetime - LIFETIME.tolerance - timedelta(seconds=1),
        LIFETIME.lifetime + LIFETIME.tolerance + timedelta(seconds=1),
        timedelta(days=60),
    ],
)
def test_grants_refused_at_another_age_do_not(authorized_for: timedelta) -> None:
    sightings = [lapse(ROBIN, authorized_for), lapse(SAM, LIFETIME.lifetime)]

    assert hints_of(sightings) == ()


def test_a_provider_without_a_grant_lifetime_gives_no_such_hint() -> None:
    plain = ProviderGuide(PROVIDER, "example", "Example", "Example Calendar", GUIDE.cause_anchors)
    sightings = [lapse(user, LIFETIME.lifetime) for user in (ROBIN, SAM)]

    assert installation_hints(sightings, NOW, (plain,)) == ()


def test_the_grant_lifetime_hint_needs_two_users_whose_lapse_is_still_open() -> None:
    one = [lapse(ROBIN, LIFETIME.lifetime)]
    reauthorized = [
        lapse(ROBIN, LIFETIME.lifetime),
        lapse(SAM, LIFETIME.lifetime, open_=False),
    ]

    assert hints_of(one) == ()
    assert hints_of(reauthorized) == ()


def test_hints_come_in_a_stable_order() -> None:
    sightings = [
        *(seen(user, Cause.QUOTA_EXCEEDED) for user in (ROBIN, SAM)),
        *(seen(user, Cause.UNKNOWN) for user in (ROBIN, SAM)),
        *(seen(user, Cause.API_DISABLED) for user in (ROBIN, SAM)),
        *(lapse(user, LIFETIME.lifetime) for user in (ROBIN, SAM)),
    ]

    assert [(hint.kind, hint.cause) for hint in hints_of(sightings)] == [
        (HintKind.SHARED_CAUSE, Cause.API_DISABLED),
        (HintKind.SHARED_CAUSE, Cause.QUOTA_EXCEEDED),
        (HintKind.TESTING_MODE, Cause.ACCESS_REVOKED),
        (HintKind.UNRECOGNIZED, Cause.UNKNOWN),
    ]


def test_each_provider_hints_its_own_causes_with_its_own_sections() -> None:
    other = ProviderGuide(
        ProviderKind.OUTLOOK,
        "other",
        "Other",
        "Other Calendar",
        {Cause.OAUTH_CLIENT_INVALID: "the-other-client-is-refused"},
    )
    sightings = [
        seen(ROBIN, Cause.OAUTH_CLIENT_INVALID),
        seen(SAM, Cause.OAUTH_CLIENT_INVALID, provider=ProviderKind.OUTLOOK),
        seen(ALEX, Cause.OAUTH_CLIENT_INVALID, provider=ProviderKind.OUTLOOK),
    ]

    hints = installation_hints(sightings, NOW, (GUIDE, other))

    assert [(hint.provider, hint.users, hint.anchor) for hint in hints] == [
        (PROVIDER, 1, "the-client-is-refused"),
        (ProviderKind.OUTLOOK, 2, "the-other-client-is-refused"),
    ]
