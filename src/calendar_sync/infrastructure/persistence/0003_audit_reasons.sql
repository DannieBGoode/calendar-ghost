ALTER TABLE audit_entries ADD COLUMN reason TEXT;
ALTER TABLE audit_entries ADD COLUMN run_id TEXT;

UPDATE audit_entries SET reason = CASE detail
    WHEN 'event is outside the rule source calendar' THEN 'outside_source_calendar'
    WHEN 'managed projections cannot become sources' THEN 'managed_projection_source'
    WHEN 'recurring series and occurrence exceptions are not supported yet'
        THEN 'recurring_unsupported'
    WHEN 'mapping identity is inconsistent' THEN 'mapping_inconsistent'
    WHEN 'destination identity is inconsistent' THEN 'destination_identity_inconsistent'
    WHEN 'destination ownership metadata is inconsistent'
        THEN 'destination_ownership_inconsistent'
    WHEN 'mapped source event was cancelled' THEN 'source_cancelled'
    WHEN 'rule excludes mapped all-day event' THEN 'all_day_excluded_removed'
    WHEN 'source has no managed projection' THEN 'source_created'
    WHEN 'managed projection is missing' THEN 'projection_missing'
    WHEN 'projection is current' THEN 'projection_current'
    WHEN 'source could not be verified while repairing a destination change'
        THEN 'source_unverifiable'
    ELSE NULL
END
WHERE reason IS NULL;

CREATE INDEX IF NOT EXISTS audit_entries_rule_id ON audit_entries(rule_id, id);
