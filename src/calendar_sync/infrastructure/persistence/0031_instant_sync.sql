-- Instant Sync (ADR 0036): a rule runs soon after its provider reports a change that may concern
-- its Source Calendar. A User's Calendar Watches, the calendars each one covers, the provider
-- channels or subscriptions that deliver its Watch Notices, and each rule's Instant Sync Request
-- belong to that User. Each refers to its account, watch, or rule by identifier and User together,
-- so the database refuses one whose User differs from its parent's, and it goes with its parent.
-- Only a hash of each registration's secret token is kept.
-- Delivery Evidence belongs to the installation: whether each provider reached its public address.
-- Nothing is rewritten: every existing User wants Instant Sync, and watches appear at the first
-- upkeep after start. Earlier releases ignore these tables and the column, so rolling back is safe;
-- providers then receive 404 until their registrations expire, and polling runs as before.
ALTER TABLE users ADD COLUMN instant_sync INTEGER NOT NULL DEFAULT 1;

CREATE TABLE calendar_watches (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    scope_key TEXT NOT NULL,
    retry_at TEXT,
    failures INTEGER NOT NULL DEFAULT 0 CHECK (failures >= 0),
    UNIQUE (id, user_id),
    UNIQUE (user_id, account_id, scope_key),
    FOREIGN KEY (account_id, user_id)
        REFERENCES connected_accounts(id, user_id) ON DELETE CASCADE
);
CREATE INDEX calendar_watches_account ON calendar_watches(account_id, user_id);

CREATE TABLE watch_coverage (
    watch_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    calendar_id TEXT NOT NULL,
    PRIMARY KEY (watch_id, calendar_id),
    FOREIGN KEY (watch_id, user_id)
        REFERENCES calendar_watches(id, user_id) ON DELETE CASCADE
);

CREATE TABLE watch_registrations (
    id TEXT PRIMARY KEY,
    watch_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('creating', 'live', 'retiring', 'abandoned')),
    address TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    requested_until TEXT NOT NULL,
    handle TEXT,
    expires_at TEXT,
    confirmed_at TEXT,
    renew_at TEXT,
    renew_requested_at TEXT,
    FOREIGN KEY (watch_id, user_id)
        REFERENCES calendar_watches(id, user_id) ON DELETE CASCADE
);
CREATE INDEX watch_registrations_watch ON watch_registrations(watch_id, user_id);
CREATE INDEX watch_registrations_user ON watch_registrations(user_id);

CREATE TABLE instant_sync_requests (
    rule_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    requested_seq INTEGER NOT NULL CHECK (requested_seq >= 0),
    handled_seq INTEGER NOT NULL DEFAULT 0 CHECK (handled_seq >= 0),
    first_requested_at TEXT NOT NULL,
    last_requested_at TEXT NOT NULL,
    last_run_at TEXT,
    FOREIGN KEY (rule_id, user_id) REFERENCES sync_rules(id, user_id) ON DELETE CASCADE
);
CREATE INDEX instant_sync_requests_pending
ON instant_sync_requests(user_id) WHERE requested_seq > handled_seq;

-- One row per provider and public address; no User's records.
CREATE TABLE delivery_evidence (
    provider TEXT NOT NULL,
    address TEXT NOT NULL,
    last_success_at TEXT,
    last_failure_at TEXT,
    PRIMARY KEY (provider, address)
);
