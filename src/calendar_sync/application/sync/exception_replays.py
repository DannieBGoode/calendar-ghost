from __future__ import annotations

from dataclasses import dataclass

from calendar_sync.application.sync.occurrences import SynchronizeOccurrences
from calendar_sync.application.sync.provider_ports import CalendarReader
from calendar_sync.application.sync.sync_run import SyncRunContext
from calendar_sync.domain.model import CalendarEvent, EventMapping


@dataclass(slots=True)
class ExceptionReplays:
    """Applies a newly created series' Occurrence Exceptions from its source."""

    provider: CalendarReader
    occurrences: SynchronizeOccurrences

    def replay(
        self, run: SyncRunContext, series_mapping: EventMapping, source_series: CalendarEvent
    ) -> None:
        """A new series starts from its recurrence alone; its exceptions come from the source.

        This covers exceptions the incremental feed did not report and cancellations that were
        never recorded. The pending replay is cleared only after every exception was applied.
        """
        for exception in self.provider.occurrence_exceptions(
            source_series.reference, run.window_start
        ):
            if exception.reference in run.handled or exception.occurrence is None:
                continue
            self.occurrences.apply(
                run,
                series_mapping,
                source_series,
                exception.occurrence.original_start,
                exception,
                record_current=True,
            )
        run.uow.replays.remove(series_mapping.id)
        run.uow.commit()

    def finish_pending(self, run: SyncRunContext) -> None:
        """Complete replays an earlier failed run left unfinished."""
        pending = run.uow.replays.pending(run.rule.id)
        if pending and run.log is not None:
            run.log.replaying(len(pending))
        for mapping in pending:
            source_series = None if run.source_listed else self.provider.get_event(mapping.source)
            if source_series is None or source_series.recurrence is None:
                # A full listing already applied every exception in the window, and a series
                # that is gone or no longer recurring is decided by its own change.
                run.uow.replays.remove(mapping.id)
                run.uow.commit()
                continue
            self.replay(run, mapping, source_series)
