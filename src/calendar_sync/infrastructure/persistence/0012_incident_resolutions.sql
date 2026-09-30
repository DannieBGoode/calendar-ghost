-- Why each Incident resolved: after a successful sync, when a daily pass found nothing still
-- blocked, or because its rule was removed. Incidents resolved before this migration keep NULL,
-- because the reason was not recorded.
ALTER TABLE incidents ADD COLUMN resolution TEXT
    CHECK (resolution IN ('sync_succeeded', 'blocks_cleared', 'rule_removed'));
