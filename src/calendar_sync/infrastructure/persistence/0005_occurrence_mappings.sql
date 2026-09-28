CREATE TABLE occurrence_mappings (
    id TEXT PRIMARY KEY,
    series_mapping_id TEXT NOT NULL REFERENCES event_mappings(id) ON DELETE CASCADE,
    original_start TEXT NOT NULL,
    source_account_id TEXT NOT NULL,
    source_calendar_id TEXT NOT NULL,
    source_event_id TEXT NOT NULL,
    destination_account_id TEXT NOT NULL,
    destination_calendar_id TEXT NOT NULL,
    destination_event_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('modified', 'cancelled')),
    source_revision TEXT NOT NULL,
    projection_fingerprint TEXT,
    CHECK ((state = 'modified') = (projection_fingerprint IS NOT NULL)),
    UNIQUE (series_mapping_id, original_start)
);

-- Recurring events were skipped before this release; re-read every source window to backfill them.
DELETE FROM sync_cursors;
DELETE FROM destination_sync_cursors;
