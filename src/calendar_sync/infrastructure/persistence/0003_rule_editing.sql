ALTER TABLE sync_rules ADD COLUMN reprojection_required INTEGER NOT NULL DEFAULT 0;

CREATE TABLE rule_run_outcomes (
    rule_id TEXT NOT NULL REFERENCES sync_rules(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('sync', 'reconciliation')),
    completed_at TEXT NOT NULL,
    succeeded INTEGER NOT NULL,
    full_run INTEGER NOT NULL DEFAULT 0,
    created INTEGER NOT NULL DEFAULT 0,
    updated INTEGER NOT NULL DEFAULT 0,
    deleted INTEGER NOT NULL DEFAULT 0,
    conflicts INTEGER NOT NULL DEFAULT 0,
    checked_mappings INTEGER NOT NULL DEFAULT 0,
    drift INTEGER NOT NULL DEFAULT 0,
    failure_kind TEXT,
    PRIMARY KEY (rule_id, kind)
);
