-- Counts from each rule's latest Rule Preview, so enabling can restate what will be written after
-- a reload. Counts only: event titles, descriptions, and locations are never stored.
CREATE TABLE rule_previews (
    rule_id TEXT PRIMARY KEY REFERENCES sync_rules(id) ON DELETE CASCADE,
    completed_at TEXT NOT NULL,
    eligible_events INTEGER NOT NULL,
    excluded_events INTEGER NOT NULL,
    recurring_series INTEGER NOT NULL DEFAULT 0,
    occurrence_changes INTEGER NOT NULL DEFAULT 0
);

-- The latest-outcome snapshot is replaced on every run, so keep the last successful completion
-- separately; a later failure must not erase evidence that a rule's calendars were current.
ALTER TABLE rule_run_outcomes ADD COLUMN last_succeeded_at TEXT;
UPDATE rule_run_outcomes SET last_succeeded_at = completed_at WHERE succeeded = 1;
