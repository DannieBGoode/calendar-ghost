"""Installation Hints: likely causes from patterns across Users, never one User's content."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from calendar_sync.application.operations.installation_hints import (
    ADMINISTRATOR_CAUSE_USERS,
    HINT_WINDOW,
    HINTED_USERS,
    NOT_ARRIVING_ANCHOR,
    PLAIN_HTTP_ANCHOR,
    UNRECOGNIZED_ANCHOR,
    HintKind,
    InstallationHint,
    InstantSyncSignals,
    installation_hints,
    instant_sync_hints,
    instant_sync_signals,
)
from calendar_sync.application.operations.ports import CauseSighting, InstantSyncOwner
from calendar_sync.application.sync.provider_descriptors import GrantLifetime, ProviderGuide
from calendar_sync.application.sync.watch_ports import EveryUserInstant
from calendar_sync.domain.access import UserId
from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.cadence import SCHEDULED_EVERY, SyncCadence
from calendar_sync.domain.causes import Cause
from calendar_sync.domain.watches import DeliveryEvidence

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


HTTPS = "https://calendar.example.test"
KIM = UserId("kim")


@dataclass(frozen=True)
class Cadences:
    """A Sync Cadence Policy that gives Instant Sync to everyone but some Users."""

    without_instant: frozenset[UserId] = frozenset()

    def cadence(self, user: UserId) -> SyncCadence:
        return SyncCadence(instant=user not in self.without_instant, poll_every=SCHEDULED_EVERY)


def owner(user: UserId, *, wanted: bool = True, disabled: bool = False) -> InstantSyncOwner:
    return InstantSyncOwner(user, wanted, disabled, None)


EVERYONE = (owner(ROBIN), owner(SAM))


def evidence(provider: ProviderKind, *, failing: bool) -> DeliveryEvidence:
    earlier, later = NOW - timedelta(hours=2), NOW - timedelta(hours=1)
    return DeliveryEvidence(
        provider,
        HTTPS,
        last_success_at=earlier if failing else later,
        last_failure_at=later if failing else earlier,
    )


def test_only_users_who_may_sign_in_want_it_and_may_use_it_count() -> None:
    owners = [owner(ROBIN), owner(SAM, disabled=True), owner(ALEX, wanted=False), owner(KIM)]

    signals = instant_sync_signals(owners, Cadences(frozenset({KIM})), HTTPS, {})

    assert signals == InstantSyncSignals(wanting=1)


@pytest.mark.parametrize(
    "address", ["http://calendar.example.test", "http://calendar.example.test:8000"]
)
def test_a_plain_http_address_the_internet_reaches_is_a_hint(address: str) -> None:
    signals = instant_sync_signals(EVERYONE, EveryUserInstant(), address, {})

    assert signals == InstantSyncSignals(wanting=2, plain_http=True)
    assert instant_sync_hints(signals, GUIDES) == (
        InstallationHint(HintKind.PLAIN_HTTP_ADDRESS, None, 2, PLAIN_HTTP_ANCHOR),
    )
    assert PLAIN_HTTP_ANCHOR == "instant-sync-needs-an-https-public-address"


@pytest.mark.parametrize(
    "address",
    [
        "http://localhost:8000",
        "http://192.168.1.50:8000",
        "http://10.0.0.2",
        "http://100.100.1.1",
        "http://calendar.local",
        "http://pi.home.arpa",
        "http://raspberrypi:8000",
        "http://[::1]:8000",
        "http://[fd00::1]",
    ],
)
def test_plain_http_on_this_machine_or_a_home_network_says_nothing(address: str) -> None:
    # The homelab norm; each person's switch already says Instant Sync needs a public address.
    signals = instant_sync_signals(EVERYONE, EveryUserInstant(), address, {})

    assert instant_sync_hints(signals, GUIDES) == ()


def test_each_provider_whose_delivery_is_failing_is_a_hint_in_the_guides_order() -> None:
    other = ProviderGuide(ProviderKind.OUTLOOK, "other", "Other", "Other Calendar", {})
    seen = {
        ProviderKind.OUTLOOK: evidence(ProviderKind.OUTLOOK, failing=True),
        PROVIDER: evidence(PROVIDER, failing=True),
    }

    signals = instant_sync_signals(EVERYONE, EveryUserInstant(), HTTPS, seen)

    assert instant_sync_hints(signals, (GUIDE, other)) == (
        InstallationHint(
            HintKind.NOTICES_NOT_ARRIVING, None, 2, NOT_ARRIVING_ANCHOR, provider=PROVIDER
        ),
        InstallationHint(
            HintKind.NOTICES_NOT_ARRIVING,
            None,
            2,
            NOT_ARRIVING_ANCHOR,
            provider=ProviderKind.OUTLOOK,
        ),
    )
    assert NOT_ARRIVING_ANCHOR == "calendar-providers-cannot-reach-the-installation"


def test_working_or_unknown_delivery_is_no_hint() -> None:
    seen = {
        PROVIDER: evidence(PROVIDER, failing=False),
        ProviderKind.OUTLOOK: DeliveryEvidence(ProviderKind.OUTLOOK, HTTPS),
    }

    signals = instant_sync_signals(EVERYONE, EveryUserInstant(), HTTPS, seen)

    assert signals == InstantSyncSignals(wanting=2)
    assert instant_sync_hints(signals, GUIDES) == ()


def test_nobody_wanting_instant_sync_is_no_hint_whatever_the_address_or_evidence() -> None:
    nobody = [owner(ROBIN, wanted=False), owner(SAM, disabled=True)]
    seen = {PROVIDER: evidence(PROVIDER, failing=True)}

    for address in ("http://calendar.example.test", HTTPS):
        signals = instant_sync_signals(nobody, EveryUserInstant(), address, seen)
        assert instant_sync_hints(signals, GUIDES) == ()


def test_without_a_public_address_there_is_no_hint() -> None:
    signals = instant_sync_signals(EVERYONE, EveryUserInstant(), None, {})

    assert signals == InstantSyncSignals(wanting=2)
    assert instant_sync_hints(signals, GUIDES) == ()


def test_a_failing_provider_without_a_guide_is_no_hint() -> None:
    signals = InstantSyncSignals(wanting=2, failing=frozenset({ProviderKind.OUTLOOK}))

    assert instant_sync_hints(signals, GUIDES) == ()
