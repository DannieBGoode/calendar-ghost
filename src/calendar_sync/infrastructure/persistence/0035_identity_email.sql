-- Installation-wide proof of the current SMTP configuration, invalidated by setup reset.
CREATE TABLE identity_email_readiness (
    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
    fingerprint TEXT,
    tested_at TEXT,
    generation INTEGER NOT NULL DEFAULT 0 CHECK(generation >= 0),
    CHECK((fingerprint IS NULL) = (tested_at IS NULL))
);
INSERT INTO identity_email_readiness(singleton) VALUES (1);

-- Durable admission counters contain no recipient, configuration, or delivery outcome.
CREATE TABLE identity_email_test_attempts (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    admitted_at TEXT NOT NULL
);
CREATE INDEX identity_email_test_attempts_user_time
    ON identity_email_test_attempts(user_id, admitted_at);
