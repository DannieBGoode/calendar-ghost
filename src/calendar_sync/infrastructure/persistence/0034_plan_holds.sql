-- Additive Plan Hold engine fields; no existing rule becomes held on upgrade.
-- PR 2 production composition passes plan_holds=None: no grace, hold, or Plan notice.
-- PR 3 activates settlement with visible state, status, and the keep form (ADR 0039).
-- Before migration 34, code 2 reads as an authorization lapse and Start still counts it.
-- Old raw plan_use counts and unfinished-lapse discovery select exact code 1, so a User
-- with only code-2 rules can remain stopped; restore account access or preview and Start.
-- Every old save erases 2 with 0 or 1. Re-upgrade may auto-resume code 1 without a fresh
-- limit check; an activated engine then starts a new grace if over the limit.
-- This inert PR 2 build recognizes 2 as a hold but never releases it in production.
-- For future code-2 data here, upgrade to an active release or pause to clear the hold,
-- then preview and Start within the limit. Reauthorization does not release a hold here.
ALTER TABLE sync_rules ADD COLUMN plan_kept INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN plan_holds_at TEXT;
ALTER TABLE users ADD COLUMN plan_grace_limit INTEGER;
ALTER TABLE users ADD COLUMN plan_grace_admissions INTEGER;
ALTER TABLE users ADD COLUMN plan_admissions INTEGER NOT NULL DEFAULT 0;
