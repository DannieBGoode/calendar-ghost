-- The daily full pass is due per rule from its last successful full run. Keeping it with the run
-- outcome means a restart, or another rule's failure, does not re-list every calendar again.
ALTER TABLE rule_run_outcomes ADD COLUMN last_full_succeeded_at TEXT;
UPDATE rule_run_outcomes SET last_full_succeeded_at = completed_at
WHERE succeeded = 1 AND full_run = 1;
