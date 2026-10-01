-- What each rule does with events its Source Calendar answered Maybe to or has not answered
-- (ADR 0018). Existing rules take the new defaults; their projections were written without
-- regard to responses, so the next run reprojects every mapping under the new policy.
ALTER TABLE sync_rules ADD COLUMN tentative_policy TEXT NOT NULL DEFAULT 'mark';
ALTER TABLE sync_rules ADD COLUMN unanswered_policy TEXT NOT NULL DEFAULT 'as_tentative';
UPDATE sync_rules SET reprojection_required = 1 WHERE state != 'disabled';
