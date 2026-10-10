-- Why each failure happened, as a Cause read from the provider's reason code, never its message
-- (ADR 0031). Rows recorded earlier keep NULL and read as unknown; a blocked-event Incident, which
-- no provider call opened, has none.
ALTER TABLE incidents ADD COLUMN cause TEXT;
ALTER TABLE rule_run_outcomes ADD COLUMN failure_cause TEXT;
