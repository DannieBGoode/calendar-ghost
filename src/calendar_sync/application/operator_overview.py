"""The Operator Overview: each User's Installation Status as their own Overview computes it, with
every calendar shown by a neutral label instead of its name (ADR 0030).

It reads across Users through the installation-wide unit of work, which holds no calendar or
account name, so neither can reach what an Installation Administrator sees.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import datetime

from calendar_sync.application.locking import RuleLocks
from calendar_sync.application.ports import (
    Clock,
    InstallationUnitOfWorkFactory,
    SchedulerHeartbeat,
    SchedulerProgress,
    StatusRecords,
)
from calendar_sync.application.rules import SyncRuleSummary
from calendar_sync.application.status import InstallationStatus, assess_installation
from calendar_sync.domain.access import UserId
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
