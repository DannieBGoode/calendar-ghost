"""What the ports of Instant Sync decide on their own: notice addresses and the default cadence."""

from calendar_sync.application.sync.errors import ProviderFailure
from calendar_sync.application.sync.watch_ports import (
    EveryUserInstant,
    WatchFailure,
    WatchFailureKind,
    notice_address,
)
from calendar_sync.domain.cadence import DEFAULT_CADENCE
from calendar_sync.domain.providers import ProviderFailureKind
from calendar_sync.domain.watches import WatchRegistrationId
from tests.users import OTHER_USER, USER


def test_a_notice_address_names_the_provider_and_the_registration() -> None:
    address = notice_address(
        "https://ghost.example.test", "example", WatchRegistrationId("0123456789abcdef" * 2)
    )

    assert address == (
        "https://ghost.example.test/api/v1/watch-notices/example/0123456789abcdef0123456789abcdef"
    )


def test_with_plans_off_every_user_may_sync_instantly() -> None:
    policy = EveryUserInstant()

    assert policy.cadence(USER) == DEFAULT_CADENCE
    assert policy.cadence(OTHER_USER) == DEFAULT_CADENCE
    assert policy.cadences([USER, OTHER_USER]) == {
        USER: DEFAULT_CADENCE,
        OTHER_USER: DEFAULT_CADENCE,
    }
    assert policy.cadences([]) == {}


def test_a_watch_failure_reads_as_its_detail_and_carries_the_refusal() -> None:
    refusal = ProviderFailure(ProviderFailureKind.AUTHENTICATION, "expired")
    failure = WatchFailure(WatchFailureKind.UNAUTHORIZED, "refused", failure=refusal)

    assert str(failure) == "refused"
    assert failure.failure is refusal
    assert failure.retry_after_seconds is None
