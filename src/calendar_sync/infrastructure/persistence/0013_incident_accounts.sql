-- The Connected Account whose failure opened or last refreshed each Incident, so Activity offers
-- rule recovery only once that account, not merely another account of the rule, is reauthorized.
-- Incidents recorded earlier keep NULL, because the account was not recorded.
ALTER TABLE incidents ADD COLUMN account_id TEXT;
