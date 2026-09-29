-- Each rule's latest successful daily pass decides every blocked event again. Its audit entries
-- have identifiers above `audit_floor`, so a block recorded earlier and not decided again since is
-- no longer open, and finding open blocks never scans history older than one daily pass.
CREATE TABLE rule_block_checks (
    rule_id TEXT PRIMARY KEY REFERENCES sync_rules(id) ON DELETE CASCADE,
    audit_floor INTEGER NOT NULL,
    checked_at TEXT NOT NULL
);
