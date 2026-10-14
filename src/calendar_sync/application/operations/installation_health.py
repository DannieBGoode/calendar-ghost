"""Installation Health: the one verdict on the whole installation (ADR 0030).

Installation Administrators and their monitors read it: incidents about the installation itself,
such as a stalled scheduler or an OAuth client secret about to expire, how many Users are in each
Installation Status verdict, and Installation Hints (ADR 0031). It names no rule, calendar, or User.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from enum import StrEnum
from typing import Protocol

from calendar_sync.application.identity.ports import UserDirectory
from calendar_sync.application.operations.installation_hints import (
    HINT_WINDOW,
    InstallationHint,
    InstantSyncSignals,
    installation_hints,
    instant_sync_hints,
)
from calendar_sync.application.operations.ports import (
    CauseSighting,
    SchedulerHeartbeat,
    SchedulerProgress,
)
from calendar_sync.application.operations.status import (
    NEEDS_ATTENTION,
    StatusVerdict,
    stalled_since,
)
from calendar_sync.application.shared.ports import Clock
from calendar_sync.application.sync.provider_descriptors import ClientSecretExpiry, ProviderGuide
from calendar_sync.domain.access import UserId, UserState
from calendar_sync.domain.accounts import ProviderKind

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


SECRET_WARNING = timedelta(days=30)
"""How long before an OAuth client secret expires Installation Health warns about it."""


class InstallationIncidentKind(StrEnum):
    SCHEDULER_STALLED = "scheduler_stalled"
    CLIENT_SECRET_EXPIRING = "client_secret_expiring"  # noqa: S105
    """An OAuth client secret expires soon, or has expired: every account of its provider then
    stops at once, until the administrator puts a new secret in place."""


@dataclass(frozen=True, slots=True)
class InstallationIncident:
    """An incident about the installation itself, which affects every User."""

    kind: InstallationIncidentKind
    since: datetime
    secret: ClientSecretExpiry | None = None
    """For an expiring client secret, which one and when it expires."""
    expired: bool = False
    """Whether that secret already expired, so every account of its provider has stopped."""


def installation_incidents(
    scheduler: SchedulerProgress | None,
    now: datetime,
    secrets: Sequence[ClientSecretExpiry] = (),
) -> tuple[InstallationIncident, ...]:
    """What is wrong with the installation itself: a scheduler that stopped completing passes,
    and each client secret that expires within SECRET_WARNING or already has. Without a
    scheduler, as without a master key, nothing can synchronize or stall."""
    today = now.astimezone(UTC).date()
    incidents = [
        InstallationIncident(
            InstallationIncidentKind.CLIENT_SECRET_EXPIRING,
            datetime.combine(secret.expires - SECRET_WARNING, time(), UTC),
            secret=secret,
            # A secret still works through the day its expiry date names.
            expired=today > secret.expires,
        )
        for secret in secrets
        if today >= secret.expires - SECRET_WARNING
    ]
    since = stalled_since(scheduler, now) if scheduler is not None else None
    if since is not None:
        incidents.insert(0, InstallationIncident(InstallationIncidentKind.SCHEDULER_STALLED, since))
    return tuple(incidents)


@dataclass(slots=True)
class InstallationIncidentWatch:
    """Which installation incidents opened since the last look, so each is reported once."""

    secrets: Sequence[ClientSecretExpiry] = ()
    _open: frozenset[tuple[InstallationIncidentKind, ProviderKind | None, bool]] = field(
        default_factory=frozenset
    )

    def opened(
        self, scheduler: SchedulerProgress | None, now: datetime
    ) -> tuple[InstallationIncident, ...]:
        incidents = installation_incidents(scheduler, now, self.secrets)
        opened = tuple(incident for incident in incidents if _key(incident) not in self._open)
        self._open = frozenset(_key(incident) for incident in incidents)
        return opened


def _key(
    incident: InstallationIncident,
) -> tuple[InstallationIncidentKind, ProviderKind | None, bool]:
    """One incident per kind, and per provider for a client secret, reported again once that
    secret expires."""
    provider = incident.secret.provider if incident.secret is not None else None
    return incident.kind, provider, incident.expired


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
    hints: tuple[InstallationHint, ...] = ()
    """Likely causes from patterns across Users who may sign in."""

    @property
    def needs_attention(self) -> bool:
        """Whether someone must act: a verdict that needs it, an installation incident, or a hint
        only the administrator can act on, such as a used-up quota while every rule merely waits
        (ADR 0031)."""
        return self.status in NEEDS_ATTENTION or bool(self.incidents) or bool(self.hints)


@dataclass(frozen=True, slots=True)
class HintSources:
    """What Installation Hints read, each at once for every User."""

    sightings: Callable[[datetime], Sequence[CauseSighting]] = lambda _since: ()
    """Every User's failures with a Cause from a time on."""
    guides: Sequence[ProviderGuide] = ()
    """Each provider's troubleshooting sections and patterns, which hints link to."""
    instant_sync: Callable[[], InstantSyncSignals] = InstantSyncSignals
    """Who wants Instant Sync, and what keeps providers from the public address (ADR 0036)."""


@dataclass(slots=True)
class GetInstallationHealth:
    users: UserDirectory
    verdicts: Callable[[Sequence[UserId]], Mapping[UserId, StatusVerdict]]
    """The Users' Installation Status verdicts, as their own Overviews show them, read at once."""
    scheduler: SchedulerHeartbeat | None
    clock: Clock
    hint_sources: HintSources = field(default_factory=HintSources)
    """What Installation Hints read."""
    secrets: Sequence[ClientSecretExpiry] = ()
    """When each configured provider's client secret expires, where the administrator said."""

    def execute(self) -> InstallationHealth:
        now = self.clock.now()
        everyone = self.users.list()
        active = [user for user in everyone if user.state is UserState.ACTIVE]
        counts = Counter(self.verdicts([user.id for user in active]).values())
        incidents = installation_incidents(
            self.scheduler.progress() if self.scheduler is not None else None, now, self.secrets
        )
        stalled = any(i.kind is InstallationIncidentKind.SCHEDULER_STALLED for i in incidents)
        present = {*counts, *((StatusVerdict.STALLED,) if stalled else ())}
        status = next(
            (verdict for verdict in _PRECEDENCE if verdict in present), StatusVerdict.SETUP
        )
        return InstallationHealth(
            status=status,
            incidents=incidents,
            users=dict(counts),
            disabled_users=len(everyone) - len(active),
            checked_at=now,
            hints=self._hints(now, {user.id for user in active}),
        )

    def _hints(self, now: datetime, may_sign_in: set[UserId]) -> tuple[InstallationHint, ...]:
        sources = self.hint_sources
        seen = [seen for seen in sources.sightings(now - HINT_WINDOW) if seen.user in may_sign_in]
        return (
            *installation_hints(seen, now, sources.guides),
            *instant_sync_hints(sources.instant_sync(), sources.guides),
        )
