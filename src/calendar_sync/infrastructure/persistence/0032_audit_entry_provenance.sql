-- What brought each event into the run, and how it compared with its Source Observation
-- (ADR 0037). Codes only, never event content; earlier entries keep NULL.
ALTER TABLE audit_entries ADD COLUMN run_reason TEXT;
ALTER TABLE audit_entries ADD COLUMN found_by TEXT;
ALTER TABLE audit_entries ADD COLUMN source_comparison TEXT;
