-- Preserve selected policy, Plans and their defaults; Open requires an explicit later write.
CREATE TABLE installation_settings_new (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    registration_policy TEXT NOT NULL
        CHECK (registration_policy IN ('only_me', 'invitation_only', 'open')),
    plans_enabled INTEGER NOT NULL DEFAULT 0,
    default_plan_key TEXT REFERENCES plans(key)
);
INSERT INTO installation_settings_new
    (singleton, registration_policy, plans_enabled, default_plan_key)
SELECT singleton, registration_policy, plans_enabled, default_plan_key FROM installation_settings;
DROP TABLE installation_settings;
ALTER TABLE installation_settings_new RENAME TO installation_settings;

-- Proofs reserve no email and belong to no User until atomically consumed.
CREATE TABLE registration_proofs (
    token_hash TEXT PRIMARY KEY NOT NULL
        CHECK (length(token_hash) = 64 AND token_hash NOT GLOB '*[^0-9a-f]*'),
    email TEXT NOT NULL CHECK (email = lower(trim(email)) AND length(email) <= 254),
    invitation_id TEXT REFERENCES invitations(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    revoked_at TEXT
);
CREATE INDEX registration_proof_email ON registration_proofs(email);
CREATE INDEX registration_proof_expiry ON registration_proofs(expires_at);
CREATE INDEX registration_proof_used ON registration_proofs(used_at);
CREATE INDEX registration_proof_revoked ON registration_proofs(revoked_at);

CREATE TABLE registration_request_attempts (
    id INTEGER PRIMARY KEY,
    boundary TEXT NOT NULL CHECK (boundary IN ('request', 'invalid-token', 'completion')),
    admitted_at REAL NOT NULL,
    email_digest TEXT,
    network_digest TEXT NOT NULL,
    pair_digest TEXT,
    CHECK ((boundary = 'request' AND email_digest IS NOT NULL AND pair_digest IS NOT NULL)
        OR (boundary != 'request' AND email_digest IS NULL AND pair_digest IS NULL))
);
CREATE INDEX registration_attempt_expiry ON registration_request_attempts(admitted_at);
CREATE INDEX registration_attempt_time ON registration_request_attempts(boundary, admitted_at);
CREATE INDEX registration_attempt_network ON registration_request_attempts(boundary, network_digest, admitted_at);
CREATE INDEX registration_attempt_email ON registration_request_attempts(email_digest, admitted_at)
    WHERE boundary = 'request';
CREATE INDEX registration_attempt_pair ON registration_request_attempts(pair_digest, admitted_at)
    WHERE boundary = 'request';
