"""Installation Health: the one verdict on the whole installation (ADR 0030).

Installation Administrators and their monitors read it: incidents about the installation itself,
and how many Users are in each Installation Status verdict. It names no rule, calendar, or User.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from calendar_sync.application.ports import (
    Clock,
    SchedulerHeartbeat,
    SchedulerProgress,
    UserDirectory,
)
from calendar_sync.application.status import NEEDS_ATTENTION, StatusVerdict, stalled_since
from calendar_sync.domain.access import UserId, UserState

# Most urgent first. Nothing needing attention reads healthy before paused, and paused before
# setup, so one User's working rules are not hidden by another who has not set up yet.
_PRECEDENCE = (
    StatusVerdict.STALLED,
    StatusVerdict.STOPPED,
    StatusVerdict.REVIEW,
    StatusVerdict.WAITING,
    StatusVerdict.HEALTHY,
    StatusVerdict.PAUSED,
    StatusVerdict.SETUP,
)


class InstallationIncidentKind(StrEnum):
    SCHEDULER_STALLED = "scheduler_stalled"


@dataclass(frozen=True, slots=True)
class InstallationIncident:
    """An incident about the installation itself, which affects every User."""

    kind: InstallationIncidentKind
    since: datetime


def installation_incidents(
    scheduler: SchedulerProgress | None, now: datetime
) -> tuple[InstallationIncident, ...]:
    """What is wrong with the installation itself: today, a scheduler that stopped completing
    passes. Without a scheduler, as without a master key, nothing can synchronize or stall."""
    since = stalled_since(scheduler, now) if scheduler is not None else None
    if since is None:
        return ()
    return (InstallationIncident(InstallationIncidentKind.SCHEDULER_STALLED, since),)


class InstallationNotifications(Protocol):
    """The installation's own channels: its SMTP recipient and webhook (ADR 0030)."""

    def installation_incident_opened(self, incident: InstallationIncident) -> None:
        """Deliver the notice; best-effort, so it never raises."""
        ...


@dataclass(frozen=True, slots=True)
class InstallationHealth:
    status: StatusVerdict
    incidents: tuple[InstallationIncident, ...]
    users: Mapping[StatusVerdict, int]
    """How many Users who may sign in are in each verdict."""
    disabled_users: int
    checked_at: datetime

    @property
    def needs_attention(self) -> bool:
        return self.status in NEEDS_ATTENTION


@dataclass(slots=True)
class GetInstallationHealth:
    users: UserDirectory
    verdict_of: Callable[[UserId], StatusVerdict]
    """Each User's Installation Status verdict, as their own Overview shows it."""
    scheduler: SchedulerHeartbeat | None
    clock: Clock

    def execute(self) -> InstallationHealth:
        now = self.clock.now()
        everyone = self.users.list()
        active = [user for user in everyone if user.state is UserState.ACTIVE]
        counts = Counter(self.verdict_of(user.id) for user in active)
        incidents = installation_incidents(
            self.scheduler.progress() if self.scheduler is not None else None, now
        )
        present = {*counts, *(StatusVerdict.STALLED for _ in incidents)}
        status = next(
            (verdict for verdict in _PRECEDENCE if verdict in present), StatusVerdict.SETUP
        )
        return InstallationHealth(
            status=status,
            incidents=incidents,
            users=dict(counts),
            disabled_users=len(everyone) - len(active),
            checked_at=now,
        )
