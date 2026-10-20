-- Bind reset proofs to a monotonic credential revision. Legacy proofs have no trustworthy
-- binding: administrators must issue replacements after upgrading. Passwords and sessions stay.
ALTER TABLE users ADD COLUMN credential_revision INTEGER NOT NULL DEFAULT 0;
ALTER TABLE password_reset_links ADD COLUMN credential_revision INTEGER;
UPDATE password_reset_links SET revoked_at = CURRENT_TIMESTAMP
WHERE used_at IS NULL AND revoked_at IS NULL;

-- Anonymous reset admission has no User ownership or account eligibility outcome. Only HMAC
-- digests survive a request. Reset requests, invalid tokens, and completions share no allowance.
CREATE TABLE reset_request_attempts (
    id INTEGER PRIMARY KEY,
    boundary TEXT NOT NULL CHECK (boundary IN ('request', 'invalid-token', 'completion')),
    admitted_at REAL NOT NULL,
    email_digest TEXT,
    network_digest TEXT NOT NULL,
    pair_digest TEXT,
    CHECK ((boundary = 'request' AND email_digest IS NOT NULL AND pair_digest IS NOT NULL)
        OR (boundary != 'request' AND email_digest IS NULL AND pair_digest IS NULL))
);
CREATE INDEX reset_attempt_expiry ON reset_request_attempts(admitted_at);
CREATE INDEX reset_attempt_time ON reset_request_attempts(boundary, admitted_at);
CREATE INDEX reset_attempt_network ON reset_request_attempts(boundary, network_digest, admitted_at);
CREATE INDEX reset_attempt_email ON reset_request_attempts(email_digest, admitted_at)
    WHERE boundary = 'request';
CREATE INDEX reset_attempt_pair ON reset_request_attempts(pair_digest, admitted_at)
    WHERE boundary = 'request';
