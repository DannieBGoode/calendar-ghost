-- Owned issuance counters are separate from anonymous network admission (ADR 0029).
CREATE TABLE email_change_proofs (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    proposed_email TEXT NOT NULL,
    credential_revision INTEGER NOT NULL CHECK (credential_revision >= 0),
    token_hash TEXT UNIQUE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    revoked_at TEXT
);
CREATE INDEX email_changes_owner ON email_change_proofs(user_id, credential_revision);
CREATE INDEX email_changes_expiry ON email_change_proofs(expires_at);
CREATE TABLE email_change_attempts (
    id INTEGER PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    admitted_at REAL NOT NULL,
    target_digest TEXT NOT NULL
);
CREATE INDEX email_change_user_window ON email_change_attempts(user_id, admitted_at);
CREATE INDEX email_change_target_window ON email_change_attempts(target_digest, admitted_at);
CREATE TABLE email_change_network_attempts (
    id INTEGER PRIMARY KEY,
    boundary TEXT NOT NULL CHECK (boundary IN ('request', 'invalid-token', 'completion')),
    network_digest TEXT NOT NULL,
    admitted_at REAL NOT NULL
);
CREATE INDEX email_change_network_window
    ON email_change_network_attempts(boundary, network_digest, admitted_at);
CREATE INDEX email_change_network_expiry ON email_change_network_attempts(admitted_at);
