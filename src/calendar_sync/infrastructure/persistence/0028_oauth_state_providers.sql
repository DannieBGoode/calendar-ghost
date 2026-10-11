-- Each OAuth state belongs to the provider whose flow began it, so a state returned to another
-- provider's callback is unknown there (ADR 0022). Every flow begun before this migration was
-- Google's. Earlier releases ignore the column, so rolling back is safe.
ALTER TABLE oauth_states ADD COLUMN provider TEXT NOT NULL DEFAULT 'google';
