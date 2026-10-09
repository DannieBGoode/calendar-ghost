-- Who may join, and the single-use links that let them (ADR 0030). New and upgraded
-- installations start with Only Me. Only each link's hash is kept, so a database backup holds
-- nothing that opens an Invitation or resets a password.
CREATE TABLE installation_settings (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    registration_policy TEXT NOT NULL CHECK (registration_policy IN ('only_me', 'invitation_only'))
);
INSERT INTO installation_settings (singleton, registration_policy) VALUES (1, 'only_me');

-- An Invitation belongs to nobody until it is used, so it carries no User of its own.
CREATE TABLE invitations (
    id TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
    created_by TEXT REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    accepted_at TEXT,
    accepted_by TEXT REFERENCES users(id) ON DELETE SET NULL,
    revoked_at TEXT
);

CREATE TABLE password_reset_links (
    id TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_by TEXT REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    revoked_at TEXT
);
CREATE INDEX password_reset_links_user ON password_reset_links(user_id);
