-- Whether each rule projects the birthdays a provider keeps among a calendar's events (ADR 0035).
-- Existing rules take the default and do not. Their projections were written without regard to
-- birthdays, so the next run reprojects every mapping and removes the projections of birthdays.
ALTER TABLE sync_rules ADD COLUMN birthday_policy TEXT NOT NULL DEFAULT 'exclude';
UPDATE sync_rules SET reprojection_required = 1 WHERE state != 'disabled';
