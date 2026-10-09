"""The Operator Overview: each User's Installation Status as their own Overview computes it, with
every calendar shown by a neutral label instead of its name (ADR 0030).

It reads across Users through the installation-wide unit of work, which holds no calendar or
account name, so neither can reach what an Installation Administrator sees.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime

from calendar_sync.application.administration import (
    AdministratorRequired,
    UserNotFound,
    require_administrator,
)
from calendar_sync.application.locking import RuleLocks
from calendar_sync.application.ports import (
    Clock,
    InstallationUnitOfWorkFactory,
    ResourceUse,
    SchedulerHeartbeat,
    SchedulerProgress,
    StatusRecords,
    UserDirectory,
    UserQuery,
)
from calendar_sync.application.resource_use import first_counted_day
from calendar_sync.application.rules import SyncRuleSummary
from calendar_sync.application.status import (
    InstallationStatus,
    StatusVerdict,
    assess_installation,
)
from calendar_sync.domain.access import User, UserId
from calendar_sync.domain.model import CalendarEndpoint, SyncRule

CALENDAR_LABEL = "Calendar {number}"


def calendar_labels(rules: Iterable[SyncRule]) -> dict[CalendarEndpoint, str]:
    """A neutral label for each calendar the rules use, numbered in the order the rules were
    created, each rule's source before its destination, so a User's calendars keep their numbers
    from one visit to the next."""
    labels: dict[CalendarEndpoint, str] = {}
    for rule in rules:
        for endpoint in (rule.source, rule.destination):
            labels.setdefault(endpoint, CALENDAR_LABEL.format(number=len(labels) + 1))
    return labels


@dataclass(slots=True)
class UserStatuses:
    """Each User's Installation Status, as `GetInstallationStatus` computes it for them, with
    calendars by their labels. A page of Users is read at once, never one rule at a time."""

    installation: InstallationUnitOfWorkFactory
    locks: RuleLocks
    clock: Clock
    scheduler: SchedulerHeartbeat | None

    def of(self, users: Collection[UserId]) -> dict[UserId, InstallationStatus]:
        with self.installation() as installation:
            records = installation.status_records(users)
        scheduler = self.scheduler.progress() if self.scheduler is not None else None
        now = self.clock.now()
        return {user: self._assess(records[user], scheduler, now) for user in records}

    def _assess(
        self, records: StatusRecords, scheduler: SchedulerProgress | None, now: datetime
    ) -> InstallationStatus:
        labels = calendar_labels(recorded.rule for recorded in records.rules)
        # In identifier order, as ListSyncRules lists them, so problems of equal urgency come
        # in the order the User's own Overview shows them.
        summaries = [
            SyncRuleSummary(
                recorded.rule,
                recorded.last_sync,
                recorded.latest_preview,
                self.locks.current_work(recorded.rule.id),
                labels,
            )
            for recorded in sorted(records.rules, key=lambda recorded: recorded.rule.id.value)
        ]
        return assess_installation(summaries, records.overview, records.incidents, scheduler, now)


@dataclass(frozen=True, slots=True)
class UserOverview:
    """What the Operator Overview shows about one User, to an administrator and to that User."""

    user: User
    status: InstallationStatus
    resources: ResourceUse
    calls_since: date
    """The first UTC day the provider calls in `resources` count."""


@dataclass(frozen=True, slots=True)
class OverviewQuery:
    users: UserQuery = field(default_factory=UserQuery)
    verdict: StatusVerdict | None = None
    """Only Users whose Installation Status has this verdict."""
    by_verdict: bool = False
    """Most urgent verdict first, or last when the query is descending; then by `users.sort`."""


@dataclass(frozen=True, slots=True)
class OverviewPage:
    users: tuple[UserOverview, ...]
    total: int
    """How many Users match, across every page."""


# Most urgent first, in the order CONTEXT.md lists the verdicts.
_URGENCY = {verdict: rank for rank, verdict in enumerate(StatusVerdict)}


@dataclass(slots=True)
class OperatorOverview:
    """The Installation Administrator's view of every User's health, and each User's view of
    what it shows about them. Both come from `_overviews`, so they cannot differ."""

    users: UserDirectory
    statuses: UserStatuses
    installation: InstallationUnitOfWorkFactory
    clock: Clock

    def page(self, actor: UserId, query: OverviewQuery) -> OverviewPage:
        require_administrator(self.users, actor)
        if query.verdict is None and not query.by_verdict:
            found = self.users.find(query.users)
            return OverviewPage(self._overviews(found.users), found.total)
        # A verdict is computed, not stored, so filtering or sorting by it reads everyone who
        # matches the rest of the query, then pages.
        everyone = self.users.find(
            replace(query.users, offset=0, limit=max(self.users.count(), 1))
        ).users
        matching = [
            overview
            for overview in self._overviews(everyone)
            if query.verdict in (None, overview.status.health)
        ]
        if query.by_verdict:
            matching.sort(
                key=lambda overview: _URGENCY[overview.status.health],
                reverse=query.users.descending,
            )
        start = query.users.offset
        return OverviewPage(tuple(matching[start : start + query.users.limit]), len(matching))

    def of(self, actor: UserId, subject: UserId) -> UserOverview:
        """One User's overview, for an Installation Administrator. Anyone else is told, as for
        a User who does not exist, that there is no such User, so nothing is revealed."""
        try:
            require_administrator(self.users, actor)
        except AdministratorRequired as refused:
            raise UserNotFound(f"user {subject.value} does not exist") from refused
        return self._overview(subject)

    def own(self, actor: UserId) -> UserOverview:
        """What the Operator Overview shows about `actor`, exactly as an administrator sees it."""
        return self._overview(actor)

    def _overview(self, subject: UserId) -> UserOverview:
        user = self.users.get(subject)
        if user is None:
            raise UserNotFound(f"user {subject.value} does not exist")
        return self._overviews([user])[0]

    def _overviews(self, users: Sequence[User]) -> tuple[UserOverview, ...]:
        ids = [user.id for user in users]
        since = first_counted_day(self.clock.now().astimezone(UTC).date())
        statuses = self.statuses.of(ids)
        with self.installation() as installation:
            resources = installation.resource_use(ids, since)
        return tuple(
            UserOverview(user, statuses[user.id], resources[user.id], since) for user in users
        )
