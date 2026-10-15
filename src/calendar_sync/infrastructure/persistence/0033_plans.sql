-- Plans (ADR 0028, ADR 0038): named limits an Installation Administrator defines and assigns.
-- Installation data, no User's records: a User names their own Plan through users.plan_key, and
-- NULL there means the Default Plan. Nothing is backfilled: Plans start off and limit nobody. A
-- Rule Replacement draft may keep the place of the rule it replaced under its User's rule limit.
-- The foreign keys keep NO ACTION, so the database refuses to delete a Plan that a User or the
-- default still names. Earlier releases ignore the table and the columns and limit nobody, so
-- rolling back works with the same database; after upgrading again, Plans are as the
-- administrator left them. Phase 4 rebuilds installation_settings and must carry plans_enabled
-- and default_plan_key.
CREATE TABLE plans (
    key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    rule_limit INTEGER,
    account_limit INTEGER,
    token_limit INTEGER,
    sync_interval TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
ALTER TABLE installation_settings ADD COLUMN plans_enabled INTEGER NOT NULL DEFAULT 0;
ALTER TABLE installation_settings ADD COLUMN default_plan_key TEXT REFERENCES plans(key);
ALTER TABLE users ADD COLUMN plan_key TEXT REFERENCES plans(key);
ALTER TABLE users ADD COLUMN plan_assigned_by TEXT;
ALTER TABLE users ADD COLUMN plan_assigner_id TEXT REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE users ADD COLUMN plan_assigned_at TEXT;
ALTER TABLE sync_rules ADD COLUMN keeps_place INTEGER NOT NULL DEFAULT 0;
