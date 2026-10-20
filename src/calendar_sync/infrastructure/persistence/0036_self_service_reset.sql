-- Bind reset proofs to a monotonic credential revision. Legacy proofs have no trustworthy
-- binding: administrators must issue replacements after upgrading. Passwords and sessions stay.
ALTER TABLE users ADD COLUMN credential_revision INTEGER NOT NULL DEFAULT 0;
ALTER TABLE password_reset_links ADD COLUMN credential_revision INTEGER;
UPDATE password_reset_links SET revoked_at = CURRENT_TIMESTAMP
WHERE used_at IS NULL AND revoked_at IS NULL;
