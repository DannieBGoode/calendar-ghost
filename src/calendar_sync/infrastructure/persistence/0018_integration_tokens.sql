-- Integration Tokens let monitors and agents read Installation Status (ADR 0024).
-- Only a SHA-256 hash of each token is kept; UNIQUE indexes it for lookup.
CREATE TABLE integration_tokens (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    scope TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_used_at TEXT,
    revoked_at TEXT
);
