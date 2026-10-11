"""Installation Health: installation incidents and how many Users are in each verdict."""

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from calendar_sync.application.causes import Cause
from calendar_sync.application.installation_health import (
    GetInstallationHealth,
    InstallationHealth,
    InstallationIncident,
    InstallationIncidentKind,
    installation_incidents,
)
from calendar_sync.application.installation_hints import HINT_WINDOW
from calendar_sync.application.ports import CauseSighting, SchedulerProgress
from calendar_sync.application.provider_descriptors import ProviderGuide
from calendar_sync.application.providers import ProviderKind
from calendar_sync.application.status import StatusVerdict
from calendar_sync.domain.access import Role, User, UserId, UserState
from tests.identity_fakes import MemoryUsers

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
TICKING = SchedulerProgress(NOW - timedelta(days=1), None, NOW - timedelta(minutes=2))
STOPPED_SINCE = NOW - timedelta(minutes=40)
STALLED = SchedulerProgress(NOW - timedelta(days=1), None, STOPPED_SINCE)
PROVIDER = ProviderKind.GOOGLE
GUIDES = (
    ProviderGuide(
        PROVIDER,
        "example",
        "Example",
        "Example Calendar",
        {Cause.API_DISABLED: "the-api-is-off", Cause.QUOTA_EXCEEDED: "the-quota-is-used-up"},
    ),
)


def failure(user: str, cause: Cause) -> CauseSighting:
    return CauseSighting(UserId(user), cause, NOW, False, provider=PROVIDER)


class Heartbeat:
    def __init__(self, progress: SchedulerProgress) -> None:
        self.current = progress

    def progress(self) -> SchedulerProgress:
        return self.current


class Clock:
    def now(self) -> datetime:
        return NOW


def _users(*verdicts: tuple[str, UserState]) -> MemoryUsers:
    users = MemoryUsers()
    for number, (_, state) in enumerate(verdicts):
        users.add(
            User(UserId(f"user-{number}"), f"u{number}@example.test", Role.USER, state, NOW),
            "hash",
        )
    return users


def _health(
    verdicts: dict[str, StatusVerdict], users: MemoryUsers, progress: SchedulerProgress
) -> InstallationHealth:
    return GetInstallationHealth(
        users,
        lambda ids: {user: verdicts[user.value] for user in ids},
        Heartbeat(progress),
        Clock(),
    ).execute()


def test_every_active_users_verdict_is_read_at_once() -> None:
    users = _users(("a", UserState.ACTIVE), ("b", UserState.DISABLED), ("c", UserState.ACTIVE))
    asked: list[list[UserId]] = []

    def verdicts(ids: Sequence[UserId]) -> dict[UserId, StatusVerdict]:
        asked.append(list(ids))
        return dict.fromkeys(ids, StatusVerdict.HEALTHY)

    GetInstallationHealth(users, verdicts, Heartbeat(TICKING), Clock()).execute()

    assert asked == [[UserId("user-0"), UserId("user-2")]]


def test_users_are_counted_by_verdict_and_the_most_urgent_one_leads() -> None:
    users = _users(
        ("healthy", UserState.ACTIVE), ("stopped", UserState.ACTIVE), ("x", UserState.ACTIVE)
    )
    verdicts = {
        "user-0": StatusVerdict.HEALTHY,
        "user-1": StatusVerdict.STOPPED,
        "user-2": StatusVerdict.HEALTHY,
    }

    health = _health(verdicts, users, TICKING)

    assert health == InstallationHealth(
        status=StatusVerdict.STOPPED,
        incidents=(),
        users={StatusVerdict.HEALTHY: 2, StatusVerdict.STOPPED: 1},
        disabled_users=0,
        checked_at=NOW,
    )
    assert health.needs_attention


def test_disabled_users_are_counted_apart_and_their_rules_do_not_count() -> None:
    users = _users(("healthy", UserState.ACTIVE), ("disabled", UserState.DISABLED))

    health = _health({"user-0": StatusVerdict.HEALTHY}, users, TICKING)

    assert (health.status, health.users, health.disabled_users) == (
        StatusVerdict.HEALTHY,
        {StatusVerdict.HEALTHY: 1},
        1,
    )
    assert not health.needs_attention


def test_a_stalled_scheduler_is_an_installation_incident_that_leads() -> None:
    users = _users(("healthy", UserState.ACTIVE))

    health = _health({"user-0": StatusVerdict.HEALTHY}, users, STALLED)

    assert health.status is StatusVerdict.STALLED
    assert health.incidents == (
        InstallationIncident(InstallationIncidentKind.SCHEDULER_STALLED, STOPPED_SINCE),
    )


def test_a_scheduler_stalls_once_no_pass_completed_for_fifteen_minutes() -> None:
    fresh = SchedulerProgress(NOW - timedelta(minutes=14), None, None)
    stuck = replace(TICKING, pass_started_at=NOW - timedelta(hours=4))

    assert installation_incidents(fresh, NOW) == ()
    assert installation_incidents(replace(fresh, running_since=NOW - timedelta(minutes=16)), NOW)
    assert installation_incidents(stuck, NOW) == (
        InstallationIncident(InstallationIncidentKind.SCHEDULER_STALLED, NOW - timedelta(hours=4)),
    )
    # Without a master key nothing can synchronize, so nothing has stalled.
    assert installation_incidents(None, NOW) == ()


def test_nothing_needing_attention_reads_healthy_before_paused_and_setup() -> None:
    users = _users(("a", UserState.ACTIVE), ("b", UserState.ACTIVE), ("c", UserState.ACTIVE))
    verdicts = {
        "user-0": StatusVerdict.SETUP,
        "user-1": StatusVerdict.PAUSED,
        "user-2": StatusVerdict.WAITING,
    }

    assert _health(verdicts, users, TICKING).status is StatusVerdict.WAITING
    assert _health({**verdicts, "user-2": StatusVerdict.HEALTHY}, users, TICKING).status is (
        StatusVerdict.HEALTHY
    )
    assert _health({**verdicts, "user-2": StatusVerdict.SETUP}, users, TICKING).status is (
        StatusVerdict.PAUSED
    )


def test_hints_come_from_failures_of_users_who_may_sign_in() -> None:
    users = _users(("a", UserState.ACTIVE), ("b", UserState.ACTIVE), ("c", UserState.DISABLED))
    asked: list[datetime] = []

    def sightings(since: datetime) -> list[CauseSighting]:
        asked.append(since)
        return [failure(f"user-{n}", Cause.API_DISABLED) for n in (0, 2)]

    lone = GetInstallationHealth(
        users,
        lambda ids: dict.fromkeys(ids, StatusVerdict.STOPPED),
        Heartbeat(TICKING),
        Clock(),
        sightings,
        GUIDES,
    ).execute()
    users.add(User(UserId("user-3"), "u3@example.test", Role.USER, UserState.ACTIVE, NOW), "hash")

    def shared(since: datetime) -> list[CauseSighting]:
        return [*sightings(since), failure("user-3", Cause.API_DISABLED)]

    health = GetInstallationHealth(
        users,
        lambda ids: dict.fromkeys(ids, StatusVerdict.STOPPED),
        Heartbeat(TICKING),
        Clock(),
        shared,
        GUIDES,
    ).execute()

    # A disabled User's rules do not run, so only the active User's failure counts.
    assert [(hint.cause, hint.users) for hint in lone.hints] == [(Cause.API_DISABLED, 1)]
    assert [(hint.cause, hint.users) for hint in health.hints] == [(Cause.API_DISABLED, 2)]
    assert asked[0] == NOW - HINT_WINDOW


def test_without_failures_there_are_no_hints() -> None:
    users = _users(("a", UserState.ACTIVE))

    assert _health({"user-0": StatusVerdict.HEALTHY}, users, TICKING).hints == ()


def test_a_hint_needs_attention_whatever_the_verdicts() -> None:
    # A used-up daily quota leaves rules waiting, which alone needs no one; only its administrator
    # can raise the quota, so monitors must hear of it.
    users = _users(("a", UserState.ACTIVE))

    def quota(_since: datetime) -> list[CauseSighting]:
        return [failure("user-0", Cause.QUOTA_EXCEEDED)]

    health = GetInstallationHealth(
        users,
        lambda ids: dict.fromkeys(ids, StatusVerdict.WAITING),
        Heartbeat(TICKING),
        Clock(),
        quota,
        GUIDES,
    ).execute()

    assert health.status is StatusVerdict.WAITING
    assert health.needs_attention
