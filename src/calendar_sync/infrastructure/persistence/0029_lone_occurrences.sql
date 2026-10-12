-- The occurrence an Event Mapping projects on its own, while its calendar does not show the
-- occurrence's series (ADR 0011). Once the series is shown, its single projection is found by the
-- series and removed. Every mapping recorded before this migration is of an event, not of one.
ALTER TABLE event_mappings ADD COLUMN occurrence_series_event_id TEXT;
ALTER TABLE event_mappings ADD COLUMN occurrence_original_start TEXT;
CREATE INDEX event_mappings_lone_occurrences
ON event_mappings (rule_id, occurrence_series_event_id)
WHERE occurrence_series_event_id IS NOT NULL;
