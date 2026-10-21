-- Password absence is explicit. Foreign keys are disabled by the migration runner, which
-- checks every reference before committing this rebuild and its version record together.
CREATE TABLE users_password_optional (
    id TEXT PRIMARY KEY,
    email TEXT COLLATE NOCASE UNIQUE,
    password_hash TEXT,
    role TEXT NOT NULL CHECK (role IN ('installation_administrator', 'user')),
    state TEXT NOT NULL CHECK (state IN ('active', 'disabled')),
    language TEXT,
    notify_by_email INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    last_sign_in_at TEXT,
    instant_sync INTEGER NOT NULL DEFAULT 1,
    plan_key TEXT REFERENCES plans(key),
    plan_assigned_by TEXT,
    plan_assigner_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    plan_assigned_at TEXT,
    plan_holds_at TEXT,
    plan_grace_limit INTEGER,
    plan_grace_admissions INTEGER,
    plan_admissions INTEGER NOT NULL DEFAULT 0,
    credential_revision INTEGER NOT NULL DEFAULT 0
);
INSERT INTO users_password_optional (
    id, email, password_hash, role, state, language, notify_by_email, created_at,
    last_sign_in_at, instant_sync, plan_key, plan_assigned_by, plan_assigner_id,
    plan_assigned_at, plan_holds_at, plan_grace_limit, plan_grace_admissions,
    plan_admissions, credential_revision
)
SELECT id, email, password_hash, role, state, language, notify_by_email, created_at,
    last_sign_in_at, instant_sync, plan_key, plan_assigned_by, plan_assigner_id,
    plan_assigned_at, plan_holds_at, plan_grace_limit, plan_grace_admissions,
    plan_admissions, credential_revision FROM users;
DROP TABLE users;
ALTER TABLE users_password_optional RENAME TO users;
CREATE UNIQUE INDEX users_without_email ON users ((email IS NULL)) WHERE email IS NULL;
CREATE TRIGGER users_keep_their_email BEFORE UPDATE OF email ON users
WHEN OLD.email IS NOT NULL AND NEW.email IS NULL
BEGIN
    SELECT RAISE(ABORT, 'a User keeps an email once they have one');
END;

CREATE TABLE provider_identities (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    issuer TEXT NOT NULL,
    subject TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (issuer, subject),
    UNIQUE (id, user_id)
);
CREATE INDEX provider_identities_user ON provider_identities(user_id);
-- An absent row is disabled. Environment availability is deliberately not persisted.
CREATE TABLE provider_sign_in_settings (
    provider TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1))
);

-- Anonymous flows and pending password proofs name no target User before password proof.
CREATE TABLE provider_flows (
    state_hash TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    browser_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    sealed_context BLOB NOT NULL
);
CREATE INDEX provider_flows_expiry ON provider_flows(expires_at);
CREATE INDEX provider_flows_browser ON provider_flows(browser_hash);
CREATE UNIQUE INDEX user_sessions_hash_user ON user_sessions(token_hash, user_id);
CREATE TABLE provider_link_flows (
    state_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_hash TEXT NOT NULL,
    revision INTEGER NOT NULL,
    provider TEXT NOT NULL,
    browser_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    sealed_context BLOB NOT NULL,
    FOREIGN KEY (session_hash, user_id) REFERENCES user_sessions(token_hash, user_id)
        ON DELETE CASCADE
);
CREATE INDEX provider_link_flows_expiry ON provider_link_flows(expires_at);
CREATE INDEX provider_link_flows_browser ON provider_link_flows(browser_hash);
CREATE TABLE provider_pending_links (
    token_hash TEXT PRIMARY KEY,
    browser_hash TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    sealed_context BLOB NOT NULL
);
CREATE INDEX provider_pending_links_expiry ON provider_pending_links(expires_at);
CREATE TABLE provider_sign_in_attempts (
    id INTEGER PRIMARY KEY,
    boundary TEXT NOT NULL CHECK (boundary IN ('begin', 'callback', 'confirmation')),
    network_digest TEXT NOT NULL,
    admitted_at REAL NOT NULL
);
CREATE INDEX provider_sign_in_attempts_window ON provider_sign_in_attempts(boundary, network_digest, admitted_at);
CREATE INDEX provider_sign_in_attempts_expiry ON provider_sign_in_attempts(admitted_at);
