-- A series projection created from an incremental feed must still receive its source exceptions.
-- Recording the obligation with the mapping lets a retry finish a replay that a failed run began.
CREATE TABLE pending_exception_replays (
    series_mapping_id TEXT PRIMARY KEY REFERENCES event_mappings(id) ON DELETE CASCADE
);
