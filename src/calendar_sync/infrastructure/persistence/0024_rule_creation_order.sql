-- The order a User's rules were created in, so the Operator Overview numbers their calendars
-- the same way on every visit ("Calendar 1", "Calendar 2"). Rules created before this release
-- take the order the database holds them in, which is the order they were created unless the
-- database was compacted since.
ALTER TABLE sync_rules ADD COLUMN creation_order INTEGER NOT NULL DEFAULT 0;
UPDATE sync_rules SET creation_order = rowid;
