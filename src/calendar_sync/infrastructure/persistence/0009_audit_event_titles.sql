-- Each entry names its source event as the run saw it (ADR 0014). A null title means the entry
-- recorded no event, as for entries written before this migration.
ALTER TABLE audit_entries ADD COLUMN event_title TEXT;
ALTER TABLE audit_entries ADD COLUMN event_starts TEXT;
ALTER TABLE audit_entries ADD COLUMN event_ends TEXT;
ALTER TABLE audit_entries ADD COLUMN event_all_day INTEGER NOT NULL DEFAULT 0;
ALTER TABLE audit_entries ADD COLUMN event_recurring INTEGER NOT NULL DEFAULT 0;
ALTER TABLE audit_entries ADD COLUMN event_cancelled INTEGER NOT NULL DEFAULT 0;
-- Activity finds an event's previous recorded name to fill gaps and show renames.
CREATE INDEX IF NOT EXISTS audit_entries_source_event
ON audit_entries(rule_id, source_event_id, id);
