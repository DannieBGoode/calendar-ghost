"""What a rule decides for one source event, from provider reads alone.

A Sync Run and a Rule Preview decide through the same planner, so a preview shows exactly what
the next run does; only the run then writes.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from calendar_sync.application.sync.ports import CalendarReader
from calendar_sync.domain.model import (
    CalendarEvent,
    EventMapping,
    EventMappingId,
    EventRef,
    EventStatus,
    SyncAction,
    SyncDecision,
    SyncReason,
    SyncRule,
    SyncRuleId,
)
from calendar_sync.domain.services import ProjectionFingerprinter, SyncDecisionService

LiveOccurrences = Callable[[EventRef], bool]
"""Whether a source series still has an occurrence the rule projects, asked once per series."""


@dataclass(frozen=True, slots=True)
class EventPlanner:
    """Decides a single event or series against its projection, completing what an interrupted
    run left: a projection the provider created before the run could record its mapping."""

    provider: CalendarReader
    decisions: SyncDecisionService
    fingerprinter: ProjectionFingerprinter

    def decide(
        self,
        rule: SyncRule,
        source_event: CalendarEvent,
        mapping: EventMapping | None,
        actual: CalendarEvent | None,
        *,
        window_start: datetime,
        live: LiveOccurrences,
    ) -> tuple[EventMapping | None, SyncDecision]:
        """The decision, and the mapping it holds for: one found for an interrupted create."""
        decision = self.decisions.decide(
            rule, source_event, mapping, actual, window_start=window_start
        )
        if decision.reason is SyncReason.BEFORE_SYNC_WINDOW and self.provider.find_projection(
            rule.destination,
            event_operation_key(
                rule.id, source_event.reference, source_event.revision, SyncAction.CREATE
            ),
        ):
            # The provider acknowledged this create before an interrupted run could record its
            # mapping; complete it idempotently instead of orphaning the projection.
            decision = self.decisions.decide(rule, source_event, mapping, actual)
        if (
            decision.action is SyncAction.CREATE
            and source_event.recurrence is not None
            and not live(source_event.reference)
        ):
            # Creating it would only be cancelled again by its occurrences, on every run.
            if mapping is None:
                mapping, actual = self._acknowledged_series(rule, source_event)
            decision = self.decisions.decide(
                rule, source_event, mapping, actual, has_live_occurrences=False
            )
        return mapping, decision

    def _acknowledged_series(
        self, rule: SyncRule, source_event: CalendarEvent
    ) -> tuple[EventMapping | None, CalendarEvent | None]:
        """Find a series the provider created before an interrupted run could record its mapping.

        Its ownership is then verified like any mapped projection before it is removed.
        """
        key = event_operation_key(
            rule.id, source_event.reference, source_event.revision, SyncAction.CREATE
        )
        found = self.provider.find_projection(rule.destination, key)
        if found is None or found.status is not EventStatus.CONFIRMED or found.occurrence:
            return None, None
        mapping = EventMapping(
            id=EventMappingId(key),
            rule_id=rule.id,
            source=source_event.reference,
            destination=found.reference,
            source_revision=source_event.revision,
            projection_fingerprint=self.fingerprinter.fingerprint(
                SyncDecisionService.as_projection(found)
            ),
        )
        return mapping, found


def event_operation_key(
    rule_id: SyncRuleId,
    source: EventRef,
    revision: str,
    action: SyncAction,
    *,
    replacing: EventRef | None = None,
) -> str:
    """The write's stable key. A create that replaces a projection its destination lost names
    the lost one, so it is new for each replacement and the same for each retry of it: a
    provider that keeps the key of a create, as Graph's transactionId does, never answers it
    with the projection it replaces."""
    parts = [
        rule_id.value,
        source.calendar.connected_account_id.value,
        source.calendar.calendar_id.value,
        source.event_id.value,
        revision,
        action.value,
    ]
    if replacing is not None:
        parts.append(replacing.event_id.value)
    return hashlib.sha256("|".join(parts).encode()).hexdigest()
