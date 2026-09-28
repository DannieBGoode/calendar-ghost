-- Activity reads one run's decisions and counts runs' no-change checks by run identifier.
CREATE INDEX IF NOT EXISTS audit_entries_run_id ON audit_entries(run_id, id);
