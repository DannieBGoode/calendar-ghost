-- How many calls each User's runs made to each calendar provider, per UTC day, so the Operator
-- Overview can show a User's resource use (ADR 0030). Only counts are kept; no request, calendar,
-- or event. The scheduler discards days older than 30.
CREATE TABLE provider_calls (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    day TEXT NOT NULL,
    calls INTEGER NOT NULL CHECK (calls >= 0),
    rate_limited INTEGER NOT NULL CHECK (rate_limited >= 0),
    failed INTEGER NOT NULL CHECK (failed >= 0),
    PRIMARY KEY (user_id, provider, day)
);
CREATE INDEX provider_calls_day ON provider_calls(day);
