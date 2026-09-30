-- The tracked details of each source event a rule last observed, so the next revision's changes
-- can be described (ADR 0016). Titles are plain text; every other detail is sealed.
CREATE TABLE IF NOT EXISTS source_observations (
    rule_id TEXT NOT NULL REFERENCES sync_rules(id) ON DELETE CASCADE,
    source_account_id TEXT NOT NULL,
    source_calendar_id TEXT NOT NULL,
    source_event_id TEXT NOT NULL,
    revision TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    title TEXT NOT NULL,
    recurring INTEGER NOT NULL,
    -- When a single event ended, so retention can forget it; ignored for a series.
    ends TEXT NOT NULL,
    sealed BLOB NOT NULL,
    PRIMARY KEY (rule_id, source_account_id, source_calendar_id, source_event_id)
);
-- A Source Change recorded with an entry: its fields and previous title in plain text, and the
-- other values before and after sealed until retention clears them. Null when none was recorded.
ALTER TABLE audit_entries ADD COLUMN change_fields TEXT;
ALTER TABLE audit_entries ADD COLUMN change_title_before TEXT;
ALTER TABLE audit_entries ADD COLUMN change_sealed BLOB;
CREATE INDEX IF NOT EXISTS audit_entries_change_values
ON audit_entries(rule_id, occurred_at) WHERE change_sealed IS NOT NULL;
