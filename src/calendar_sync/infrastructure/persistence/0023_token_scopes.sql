-- Integration Tokens carry scopes (ADR 0030): status:read reads their User's Installation Status,
-- and installation:read, for Installation Administrators, reads Installation Health. Every token
-- issued before Users existed read the whole installation, so it keeps both, and an existing
-- monitor keeps receiving the answer it received before. Scopes are kept sorted, space-separated.
ALTER TABLE integration_tokens ADD COLUMN scopes TEXT NOT NULL DEFAULT 'status:read';
UPDATE integration_tokens SET scopes = 'installation:read status:read';
ALTER TABLE integration_tokens DROP COLUMN scope;
