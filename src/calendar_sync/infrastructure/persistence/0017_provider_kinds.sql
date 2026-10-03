-- Connected Accounts may belong to any calendar provider (ADR 0022). Code validates the provider,
-- so adding one needs no schema change. SQLite cannot drop a CHECK constraint, so the table is
-- rebuilt. Foreign keys are on while migrations run, and dropping the old table would delete
-- every calendar name through ON DELETE CASCADE, so calendar names are set aside first and
-- restored afterwards.
CREATE TEMP TABLE calendar_names_kept AS SELECT * FROM calendar_names;
DROP TABLE calendar_names;

CREATE TABLE connected_accounts_rebuilt (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    display_name TEXT NOT NULL,
    email TEXT NOT NULL,
    encrypted_credentials BLOB NOT NULL,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    avatar_url TEXT,
    UNIQUE (provider, email)
);
INSERT INTO connected_accounts_rebuilt (
    id, provider, display_name, email, encrypted_credentials, state, created_at, updated_at,
    avatar_url
)
SELECT
    id, provider, display_name, email, encrypted_credentials, state, created_at, updated_at,
    avatar_url
FROM connected_accounts;
DROP TABLE connected_accounts;
ALTER TABLE connected_accounts_rebuilt RENAME TO connected_accounts;

CREATE TABLE calendar_names (
    connected_account_id TEXT NOT NULL REFERENCES connected_accounts(id) ON DELETE CASCADE,
    calendar_id TEXT NOT NULL,
    name TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (connected_account_id, calendar_id)
);
INSERT INTO calendar_names (connected_account_id, calendar_id, name, updated_at)
SELECT connected_account_id, calendar_id, name, updated_at FROM calendar_names_kept;
DROP TABLE calendar_names_kept;
