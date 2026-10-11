-- Which provider's answer gave each failure its Cause, so Installation Hints and the Web UI name
-- the provider and its troubleshooting section (ADR 0022). Before this migration Google was the
-- only calendar provider, so every Cause recorded so far is Google's. A failure without a Cause,
-- such as blocked events or a local failure, names no provider.
ALTER TABLE incidents ADD COLUMN provider TEXT;
ALTER TABLE rule_run_outcomes ADD COLUMN failure_provider TEXT;
UPDATE incidents SET provider = 'google' WHERE cause IS NOT NULL AND cause != 'none';
UPDATE rule_run_outcomes SET failure_provider = 'google'
WHERE failure_cause IS NOT NULL AND failure_cause != 'none';
