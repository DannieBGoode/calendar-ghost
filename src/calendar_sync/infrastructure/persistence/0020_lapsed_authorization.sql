-- Lapsed Authorization (ADR 0027): when the provider stopped accepting a connected account's
-- credentials. NULL while it accepts them; Reauthorization or a passing access check clears it.
ALTER TABLE connected_accounts ADD COLUMN authorization_lapsed_at TEXT;
-- A Degraded Rule stopped only by Lapsed Authorization, which resumes once its accounts are
-- authorized again instead of needing a recovery preview.
ALTER TABLE sync_rules ADD COLUMN awaiting_reauthorization INTEGER NOT NULL DEFAULT 0;

-- Accounts an open authorization Incident names, and that were not reauthorized after it last
-- failed, lapsed before this release recorded it.
UPDATE connected_accounts SET authorization_lapsed_at = (
    SELECT MAX(incidents.updated_at) FROM incidents
    WHERE incidents.account_id = connected_accounts.id
        AND incidents.state = 'open'
        AND incidents.category IN ('authentication', 'authorization')
)
WHERE state = 'connected' AND EXISTS (
    SELECT 1 FROM incidents
    WHERE incidents.account_id = connected_accounts.id
        AND incidents.state = 'open'
        AND incidents.category IN ('authentication', 'authorization')
        AND incidents.updated_at > connected_accounts.updated_at
);

-- Rules such an Incident stopped resume with their accounts, as rules stopped from now on do.
-- A rule changed materially since, or one with a disconnected account, still needs a preview.
UPDATE sync_rules SET awaiting_reauthorization = 1
WHERE state = 'degraded'
    AND reprojection_required = 0
    AND NOT EXISTS (
        SELECT 1 FROM connected_accounts
        WHERE connected_accounts.id IN (
                sync_rules.source_account_id, sync_rules.destination_account_id
            )
            AND connected_accounts.state != 'connected'
    )
    AND id IN (
        SELECT rule_id FROM incidents
        WHERE state = 'open'
            AND deduplication_key LIKE 'provider:%'
            AND category IN ('authentication', 'authorization')
    );

-- An Incident for Lapsed Authorization resolves when access is restored. SQLite cannot change the
-- CHECK constraint migration 12 put on `resolution`, so the column is replaced with its values.
ALTER TABLE incidents ADD COLUMN resolution_kept TEXT CHECK (
    resolution_kept IN ('sync_succeeded', 'blocks_cleared', 'rule_removed', 'access_restored')
);
UPDATE incidents SET resolution_kept = resolution;
ALTER TABLE incidents DROP COLUMN resolution;
ALTER TABLE incidents RENAME COLUMN resolution_kept TO resolution;
