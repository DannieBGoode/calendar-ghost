from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from calendar_sync.application.shared.ports import Clock
from calendar_sync.application.sync.locking import RuleLocks, RuleWork
from calendar_sync.application.sync.ports import (
    CalendarReader,
    ProviderChangeSet,
    RunIdGenerator,
    UnitOfWork,
)
from calendar_sync.application.sync.sync_run import (
    SOURCE_CHANGE_RETENTION,
    SyncRunContext,
    SyncRunLog,
)
from calendar_sync.domain.audit import RunReason
from calendar_sync.domain.model import SyncAction, SyncRule
from calendar_sync.domain.runs import RuleRunOutcome, RunKind, RunOrigin


def _run_mode(*, reproject: bool, full: bool, first: bool) -> tuple[str, str]:
    """How a run reads its calendars, and why: the mode and reason its first log line names."""
    if reproject:
        return "reprojection", "reprojection"
    if first:
        return "full", "first-run"
    if full:
        return "full", "daily-pass"
    return "incremental", "changes"


@dataclass(frozen=True, slots=True)
class ChangeFeeds:
    """Both calendars' changes for one Sync Run, and whether each feed listed in full."""

    source: ProviderChangeSet
    destination: ProviderChangeSet
    source_listed: bool
    destination_listed: bool

    @property
    def listed_in_full(self) -> bool:
        return self.source_listed and self.destination_listed


def run_reason(
    *,
    reproject: bool,
    origin: RunOrigin,
    full: bool,
    saved_source: bool,
    saved_destination: bool,
    feeds: ChangeFeeds,
) -> RunReason:
    """Why the run read the calendars as it did: the first reason that applies (ADR 0037)."""
    if reproject:
        return RunReason.REPROJECTION
    if origin is RunOrigin.RECONCILE_NOW:
        return RunReason.RECONCILE_NOW
    if full:
        return RunReason.DAILY_PASS
    if not saved_source and not saved_destination:
        return RunReason.FIRST_RUN
    if feeds.source_listed or feeds.destination_listed:
        return RunReason.RELISTED
    return RunReason.CHANGES


@dataclass(slots=True)
class ChangeFeedCursors:
    """Reads both calendars' change feeds from a rule's saved cursors, and saves the next ones."""

    provider: CalendarReader
    clock: Clock
    run_ids: RunIdGenerator
    locks: RuleLocks

    def begin(
        self,
        uow: UnitOfWork,
        rule: SyncRule,
        *,
        full: bool,
        origin: RunOrigin,
        log: SyncRunLog,
        work: RuleWork,
    ) -> tuple[SyncRunContext, ChangeFeeds]:
        """Read both change feeds from the saved cursors, or in full when a full run is due."""
        run_id = self.run_ids.new_run_id()
        reproject = rule.reprojection_required
        full_run = full or reproject
        previous_cursor = uow.cursors.get(rule.id)
        cursor = None if full_run else previous_cursor
        saved_destination = uow.destination_cursors.get(rule.id)
        destination_cursor = None if full_run else saved_destination
        log.begin(run_id, *_run_mode(reproject=reproject, full=full, first=previous_cursor is None))
        cutoff = self.clock.now() - timedelta(days=rule.initial_lookback_days)
        changes = self.provider.changes(rule.source, cursor, cutoff)
        destination_changes = self.provider.changes(rule.destination, destination_cursor, cutoff)
        log.listed(len(changes.events), len(destination_changes.events))
        # A missing or rejected cursor also yields a full listing instead of changes.
        for feed, sent, received in (
            ("source", cursor, changes),
            ("destination", destination_cursor, destination_changes),
        ):
            if sent is not None and received.complete:
                log.cursor_rejected(feed)
        feeds = ChangeFeeds(
            changes,
            destination_changes,
            source_listed=cursor is None or changes.complete,
            destination_listed=destination_cursor is None or destination_changes.complete,
        )
        run = SyncRunContext(
            uow,
            rule,
            run_id,
            {action: 0 for action in SyncAction},
            cutoff,
            reproject,
            incremental=not feeds.source_listed and not feeds.destination_listed,
            daily_pass=feeds.source_listed and previous_cursor is not None,
            source_listed=feeds.source_listed,
            log=log,
            work=work,
            run_reason=run_reason(
                reproject=reproject,
                origin=origin,
                full=full,
                saved_source=previous_cursor is not None,
                saved_destination=saved_destination is not None,
                feeds=feeds,
            ),
        )
        run.expect(len(changes.events) + len(destination_changes.events))
        if feeds.destination_listed:
            # A full listing already holds each projection, so decisions need not re-read it.
            run.listed_destinations = {
                event.reference: event
                for event in destination_changes.events
                if event.occurrence is None
            }
        return run, feeds

    def advance(self, run: SyncRunContext, feeds: ChangeFeeds) -> None:
        """Save both cursors, reached only after every change in both batches succeeded."""
        uow, rule = run.uow, run.rule
        uow.cursors.save(rule.id, feeds.source.next_cursor)
        uow.destination_cursors.save(rule.id, feeds.destination.next_cursor)
        if feeds.listed_in_full:
            # Retention runs with the daily pass, which lists every event still observed.
            cutoff = self.clock.now() - SOURCE_CHANGE_RETENTION
            uow.audit.forget_change_values(cutoff)
            uow.observations.forget_stale(rule.id, rule.source, cutoff)
        with self.locks.for_writes(rule.id):
            if run.reproject:
                current = uow.rules.get(rule.id)
                # An edit made while this run was in flight keeps reprojection pending.
                if (
                    current is not None
                    and current.reprojection_required
                    and current.material_signature == rule.material_signature
                ):
                    uow.rules.save(current.complete_reprojection())
            uow.commit()
        uow.run_outcomes.record(
            RuleRunOutcome(
                rule.id,
                RunKind.SYNC,
                self.clock.now(),
                True,
                # Listing both calendars in full, as a first run does, completes the daily pass.
                feeds.listed_in_full,
                created=run.counts[SyncAction.CREATE],
                updated=run.counts[SyncAction.UPDATE],
                deleted=run.counts[SyncAction.DELETE],
                conflicts=run.counts[SyncAction.CONFLICT],
            )
        )
        uow.commit()
