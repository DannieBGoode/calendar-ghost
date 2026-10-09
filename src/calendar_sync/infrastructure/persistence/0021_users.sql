-- Users own every record (ADR 0029, ADR 0030). The single administrator becomes User #1, an
-- Installation Administrator with no email, and receives every existing record. Every owned table
-- carries its User; a child references its parent by the parent's identifier and User together, so
-- the database refuses a record whose User differs from its parent's. SQLite cannot add these
-- references to a table, so each table is rebuilt. The migration runs with foreign keys off, as
-- SQLite's table rebuild requires, and the runner checks every reference before it commits.
-- Children are copied only with a parent that exists: a row an earlier release left without its
-- rule could never be read.

CREATE TABLE users (
    id TEXT PRIMARY KEY,
    email TEXT COLLATE NOCASE UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('installation_administrator', 'user')),
    state TEXT NOT NULL CHECK (state IN ('active', 'disabled')),
    language TEXT,
    notify_by_email INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    last_sign_in_at TEXT
);
-- Only the upgraded first User lacks an email, and only until they add one.
CREATE UNIQUE INDEX users_without_email ON users ((email IS NULL)) WHERE email IS NULL;
CREATE TRIGGER users_keep_their_email BEFORE UPDATE OF email ON users
WHEN OLD.email IS NOT NULL AND NEW.email IS NULL
BEGIN
    SELECT RAISE(ABORT, 'a User keeps an email once they have one');
END;

INSERT INTO users (id, email, password_hash, role, state, created_at)
SELECT
    lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4'
        || substr(lower(hex(randomblob(2))), 2) || '-'
        || substr('89ab', 1 + abs(random()) % 4, 1) || substr(lower(hex(randomblob(2))), 2)
        || '-' || lower(hex(randomblob(6))),
    NULL, password_hash, 'installation_administrator', 'active', created_at
FROM installation_admin;

CREATE TEMP TABLE first_user AS SELECT id FROM users;

CREATE TABLE user_sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE INDEX user_sessions_user ON user_sessions(user_id);
INSERT INTO user_sessions (token_hash, user_id, created_at, expires_at)
SELECT token_hash, (SELECT id FROM temp.first_user), created_at, expires_at FROM admin_sessions;
DROP TABLE admin_sessions;
DROP TABLE installation_admin;

-- A state lives ten minutes; one in flight during the upgrade is simply started again.
DROP TABLE oauth_states;
CREATE TABLE oauth_states (
    state_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    consumed_at TEXT
);

CREATE TABLE connected_accounts_owned (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    display_name TEXT NOT NULL,
    email TEXT NOT NULL,
    encrypted_credentials BLOB NOT NULL,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    avatar_url TEXT,
    authorization_lapsed_at TEXT,
    UNIQUE (id, user_id),
    -- Two Users may connect the same identity; neither learns of the other's (ADR 0030).
    UNIQUE (user_id, provider, email)
);
INSERT INTO connected_accounts_owned (
    id, user_id, provider, display_name, email, encrypted_credentials, state, created_at,
    updated_at, avatar_url, authorization_lapsed_at
)
SELECT
    id, (SELECT id FROM temp.first_user), provider, display_name, email, encrypted_credentials,
    state, created_at, updated_at, avatar_url, authorization_lapsed_at
FROM connected_accounts;

CREATE TABLE calendar_names_owned (
    connected_account_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    calendar_id TEXT NOT NULL,
    name TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (connected_account_id, calendar_id),
    FOREIGN KEY (connected_account_id, user_id)
        REFERENCES connected_accounts(id, user_id) ON DELETE CASCADE
);
INSERT INTO calendar_names_owned (connected_account_id, user_id, calendar_id, name, updated_at)
SELECT n.connected_account_id, a.user_id, n.calendar_id, n.name, n.updated_at
FROM calendar_names n JOIN connected_accounts_owned a ON a.id = n.connected_account_id;

CREATE TABLE sync_rules_owned (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source_account_id TEXT NOT NULL,
    source_calendar_id TEXT NOT NULL,
    destination_account_id TEXT NOT NULL,
    destination_calendar_id TEXT NOT NULL,
    privacy_policy TEXT NOT NULL,
    all_day_policy TEXT NOT NULL,
    busy_title TEXT NOT NULL,
    initial_lookback_days INTEGER NOT NULL CHECK (initial_lookback_days >= 0),
    state TEXT NOT NULL,
    reprojection_required INTEGER NOT NULL DEFAULT 0,
    tentative_policy TEXT NOT NULL DEFAULT 'mark',
    unanswered_policy TEXT NOT NULL DEFAULT 'as_tentative',
    awaiting_reauthorization INTEGER NOT NULL DEFAULT 0,
    UNIQUE (id, user_id),
    -- Per User, so a rule never reveals that another User's rule joins the same calendars.
    UNIQUE (
        user_id, source_account_id, source_calendar_id, destination_account_id,
        destination_calendar_id
    ),
    -- A rule and both of its accounts belong to one User (ADR 0030). Checked at commit, so
    -- deleting an account and the rules that use it can happen in either order.
    FOREIGN KEY (source_account_id, user_id) REFERENCES connected_accounts(id, user_id)
        DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (destination_account_id, user_id) REFERENCES connected_accounts(id, user_id)
        DEFERRABLE INITIALLY DEFERRED
);
INSERT INTO sync_rules_owned (
    id, user_id, source_account_id, source_calendar_id, destination_account_id,
    destination_calendar_id, privacy_policy, all_day_policy, busy_title, initial_lookback_days,
    state, reprojection_required, tentative_policy, unanswered_policy, awaiting_reauthorization
)
SELECT
    id, (SELECT id FROM temp.first_user), source_account_id, source_calendar_id,
    destination_account_id, destination_calendar_id, privacy_policy, all_day_policy, busy_title,
    initial_lookback_days, state, reprojection_required, tentative_policy, unanswered_policy,
    awaiting_reauthorization
FROM sync_rules;
CREATE INDEX sync_rules_user ON sync_rules_owned(user_id);

CREATE TABLE event_mappings_owned (
    id TEXT PRIMARY KEY,
    rule_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    source_account_id TEXT NOT NULL,
    source_calendar_id TEXT NOT NULL,
    source_event_id TEXT NOT NULL,
    destination_account_id TEXT NOT NULL,
    destination_calendar_id TEXT NOT NULL,
    destination_event_id TEXT NOT NULL,
    source_revision TEXT NOT NULL,
    projection_fingerprint TEXT NOT NULL,
    UNIQUE (id, user_id),
    UNIQUE (rule_id, source_account_id, source_calendar_id, source_event_id),
    UNIQUE (rule_id, destination_account_id, destination_calendar_id, destination_event_id),
    FOREIGN KEY (rule_id, user_id) REFERENCES sync_rules(id, user_id) ON DELETE CASCADE
);
INSERT INTO event_mappings_owned
SELECT
    m.id, m.rule_id, r.user_id, m.source_account_id, m.source_calendar_id, m.source_event_id,
    m.destination_account_id, m.destination_calendar_id, m.destination_event_id,
    m.source_revision, m.projection_fingerprint
FROM event_mappings m JOIN sync_rules_owned r ON r.id = m.rule_id;

CREATE TABLE occurrence_mappings_owned (
    id TEXT PRIMARY KEY,
    series_mapping_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    original_start TEXT NOT NULL,
    source_account_id TEXT NOT NULL,
    source_calendar_id TEXT NOT NULL,
    source_event_id TEXT NOT NULL,
    destination_account_id TEXT NOT NULL,
    destination_calendar_id TEXT NOT NULL,
    destination_event_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('modified', 'cancelled')),
    source_revision TEXT NOT NULL,
    projection_fingerprint TEXT,
    CHECK ((state = 'modified') = (projection_fingerprint IS NOT NULL)),
    UNIQUE (series_mapping_id, original_start),
    FOREIGN KEY (series_mapping_id, user_id)
        REFERENCES event_mappings(id, user_id) ON DELETE CASCADE
);
INSERT INTO occurrence_mappings_owned
SELECT
    o.id, o.series_mapping_id, m.user_id, o.original_start, o.source_account_id,
    o.source_calendar_id, o.source_event_id, o.destination_account_id, o.destination_calendar_id,
    o.destination_event_id, o.state, o.source_revision, o.projection_fingerprint
FROM occurrence_mappings o JOIN event_mappings_owned m ON m.id = o.series_mapping_id;

CREATE TABLE pending_exception_replays_owned (
    series_mapping_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    FOREIGN KEY (series_mapping_id, user_id)
        REFERENCES event_mappings(id, user_id) ON DELETE CASCADE
);
INSERT INTO pending_exception_replays_owned
SELECT p.series_mapping_id, m.user_id
FROM pending_exception_replays p JOIN event_mappings_owned m ON m.id = p.series_mapping_id;

CREATE TABLE sync_cursors_owned (
    rule_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    cursor TEXT NOT NULL,
    FOREIGN KEY (rule_id, user_id) REFERENCES sync_rules(id, user_id) ON DELETE CASCADE
);
INSERT INTO sync_cursors_owned
SELECT c.rule_id, r.user_id, c.cursor FROM sync_cursors c JOIN sync_rules_owned r ON r.id = c.rule_id;

CREATE TABLE destination_sync_cursors_owned (
    rule_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    cursor TEXT NOT NULL,
    FOREIGN KEY (rule_id, user_id) REFERENCES sync_rules(id, user_id) ON DELETE CASCADE
);
INSERT INTO destination_sync_cursors_owned
SELECT c.rule_id, r.user_id, c.cursor
FROM destination_sync_cursors c JOIN sync_rules_owned r ON r.id = c.rule_id;

CREATE TABLE rule_run_outcomes_owned (
    rule_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
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
    last_succeeded_at TEXT,
    last_full_succeeded_at TEXT,
    PRIMARY KEY (rule_id, kind),
    FOREIGN KEY (rule_id, user_id) REFERENCES sync_rules(id, user_id) ON DELETE CASCADE
);
INSERT INTO rule_run_outcomes_owned
SELECT
    o.rule_id, r.user_id, o.kind, o.completed_at, o.succeeded, o.full_run, o.created, o.updated,
    o.deleted, o.conflicts, o.checked_mappings, o.drift, o.failure_kind, o.last_succeeded_at,
    o.last_full_succeeded_at
FROM rule_run_outcomes o JOIN sync_rules_owned r ON r.id = o.rule_id;

CREATE TABLE rule_previews_owned (
    rule_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    eligible_events INTEGER NOT NULL,
    excluded_events INTEGER NOT NULL,
    recurring_series INTEGER NOT NULL DEFAULT 0,
    occurrence_changes INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (rule_id, user_id) REFERENCES sync_rules(id, user_id) ON DELETE CASCADE
);
INSERT INTO rule_previews_owned
SELECT
    p.rule_id, r.user_id, p.completed_at, p.eligible_events, p.excluded_events,
    p.recurring_series, p.occurrence_changes
FROM rule_previews p JOIN sync_rules_owned r ON r.id = p.rule_id;

CREATE TABLE rule_block_checks_owned (
    rule_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    audit_floor INTEGER NOT NULL,
    checked_at TEXT NOT NULL,
    FOREIGN KEY (rule_id, user_id) REFERENCES sync_rules(id, user_id) ON DELETE CASCADE
);
INSERT INTO rule_block_checks_owned
SELECT b.rule_id, r.user_id, b.audit_floor, b.checked_at
FROM rule_block_checks b JOIN sync_rules_owned r ON r.id = b.rule_id;

CREATE TABLE rule_failures_owned (
    rule_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    consecutive_failures INTEGER NOT NULL,
    last_category TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (rule_id, user_id) REFERENCES sync_rules(id, user_id) ON DELETE CASCADE
);
INSERT INTO rule_failures_owned
SELECT f.rule_id, r.user_id, f.consecutive_failures, f.last_category, f.updated_at
FROM rule_failures f JOIN sync_rules_owned r ON r.id = f.rule_id;

CREATE TABLE source_observations_owned (
    rule_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    source_account_id TEXT NOT NULL,
    source_calendar_id TEXT NOT NULL,
    source_event_id TEXT NOT NULL,
    revision TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    title TEXT NOT NULL,
    recurring INTEGER NOT NULL,
    -- When a single event ended, so retention can forget it; ignored for a series.
    ends TEXT NOT NULL,
    sealed BLOB NOT NULL,
    PRIMARY KEY (rule_id, source_account_id, source_calendar_id, source_event_id),
    FOREIGN KEY (rule_id, user_id) REFERENCES sync_rules(id, user_id) ON DELETE CASCADE
);
INSERT INTO source_observations_owned
SELECT
    o.rule_id, r.user_id, o.source_account_id, o.source_calendar_id, o.source_event_id,
    o.revision, o.observed_at, o.title, o.recurring, o.ends, o.sealed
FROM source_observations o JOIN sync_rules_owned r ON r.id = o.rule_id;

-- Audit Entries and Incidents outlive their rules, so they reference their User only.
CREATE TABLE audit_entries_owned (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    occurred_at TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    action TEXT NOT NULL,
    outcome TEXT NOT NULL,
    source_event_id TEXT,
    destination_event_id TEXT,
    detail TEXT NOT NULL,
    reason TEXT,
    run_id TEXT,
    event_title TEXT,
    event_starts TEXT,
    event_ends TEXT,
    event_all_day INTEGER NOT NULL DEFAULT 0,
    event_recurring INTEGER NOT NULL DEFAULT 0,
    event_cancelled INTEGER NOT NULL DEFAULT 0,
    change_fields TEXT,
    change_title_before TEXT,
    change_sealed BLOB
);
INSERT INTO audit_entries_owned (
    id, user_id, occurred_at, rule_id, action, outcome, source_event_id, destination_event_id,
    detail, reason, run_id, event_title, event_starts, event_ends, event_all_day,
    event_recurring, event_cancelled, change_fields, change_title_before, change_sealed
)
SELECT
    id, (SELECT id FROM temp.first_user), occurred_at, rule_id, action, outcome,
    source_event_id, destination_event_id, detail, reason, run_id, event_title, event_starts,
    event_ends, event_all_day, event_recurring, event_cancelled, change_fields,
    change_title_before, change_sealed
FROM audit_entries;
-- Identifiers of cleared entries stay retired, so a later entry never reuses one.
CREATE TEMP TABLE audit_sequence AS
SELECT seq FROM sqlite_sequence WHERE name = 'audit_entries';

CREATE TABLE incidents_owned (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    deduplication_key TEXT NOT NULL,
    rule_id TEXT,
    account_id TEXT,
    category TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('open', 'resolved')),
    summary TEXT NOT NULL,
    opened_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    resolved_at TEXT,
    resolution TEXT CHECK (
        resolution IN ('sync_succeeded', 'blocks_cleared', 'rule_removed', 'access_restored')
    ),
    message_code TEXT,
    message_params TEXT,
    UNIQUE (user_id, deduplication_key)
);
INSERT INTO incidents_owned (
    id, user_id, deduplication_key, rule_id, account_id, category, state, summary, opened_at,
    updated_at, resolved_at, resolution, message_code, message_params
)
SELECT
    id, (SELECT id FROM temp.first_user), deduplication_key, rule_id, account_id, category,
    state, summary, opened_at, updated_at, resolved_at, resolution, message_code, message_params
FROM incidents;

CREATE TABLE integration_tokens_owned (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    scope TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_used_at TEXT,
    revoked_at TEXT
);
INSERT INTO integration_tokens_owned (
    id, user_id, name, token_hash, scope, created_at, last_used_at, revoked_at
)
SELECT
    id, (SELECT id FROM temp.first_user), name, token_hash, scope, created_at, last_used_at,
    revoked_at
FROM integration_tokens;

DROP TABLE integration_tokens;
DROP TABLE incidents;
DROP TABLE audit_entries;
DROP TABLE source_observations;
DROP TABLE rule_failures;
DROP TABLE rule_block_checks;
DROP TABLE rule_previews;
DROP TABLE rule_run_outcomes;
DROP TABLE destination_sync_cursors;
DROP TABLE sync_cursors;
DROP TABLE pending_exception_replays;
DROP TABLE occurrence_mappings;
DROP TABLE event_mappings;
DROP TABLE sync_rules;
DROP TABLE calendar_names;
DROP TABLE connected_accounts;

ALTER TABLE connected_accounts_owned RENAME TO connected_accounts;
ALTER TABLE calendar_names_owned RENAME TO calendar_names;
ALTER TABLE sync_rules_owned RENAME TO sync_rules;
ALTER TABLE event_mappings_owned RENAME TO event_mappings;
ALTER TABLE occurrence_mappings_owned RENAME TO occurrence_mappings;
ALTER TABLE pending_exception_replays_owned RENAME TO pending_exception_replays;
ALTER TABLE sync_cursors_owned RENAME TO sync_cursors;
ALTER TABLE destination_sync_cursors_owned RENAME TO destination_sync_cursors;
ALTER TABLE rule_run_outcomes_owned RENAME TO rule_run_outcomes;
ALTER TABLE rule_previews_owned RENAME TO rule_previews;
ALTER TABLE rule_block_checks_owned RENAME TO rule_block_checks;
ALTER TABLE rule_failures_owned RENAME TO rule_failures;
ALTER TABLE source_observations_owned RENAME TO source_observations;
ALTER TABLE audit_entries_owned RENAME TO audit_entries;
ALTER TABLE incidents_owned RENAME TO incidents;
ALTER TABLE integration_tokens_owned RENAME TO integration_tokens;

UPDATE sqlite_sequence SET seq = MAX(seq, (SELECT seq FROM temp.audit_sequence))
WHERE name = 'audit_entries' AND EXISTS (SELECT 1 FROM temp.audit_sequence);
INSERT INTO sqlite_sequence (name, seq)
SELECT 'audit_entries', seq FROM temp.audit_sequence
WHERE NOT EXISTS (SELECT 1 FROM sqlite_sequence WHERE name = 'audit_entries');

CREATE INDEX audit_entries_user ON audit_entries(user_id, id);
CREATE INDEX audit_entries_rule_id ON audit_entries(rule_id, id);
CREATE INDEX audit_entries_run_id ON audit_entries(run_id, id);
CREATE INDEX audit_entries_source_event ON audit_entries(rule_id, source_event_id, id);
CREATE INDEX audit_entries_change_values
ON audit_entries(occurred_at) WHERE change_sealed IS NOT NULL;
CREATE INDEX incidents_user ON incidents(user_id, state);

DROP TABLE temp.audit_sequence;
DROP TABLE temp.first_user;
