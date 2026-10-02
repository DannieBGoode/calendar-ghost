-- The name each calendar last had in Google, recorded whenever an account's calendars are
-- listed, so a rule shows its calendars' names before Google answers again. Calendar names are
-- account metadata, not event content. Deleting the account deletes its names.
CREATE TABLE calendar_names (
    connected_account_id TEXT NOT NULL REFERENCES connected_accounts(id) ON DELETE CASCADE,
    calendar_id TEXT NOT NULL,
    name TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (connected_account_id, calendar_id)
);
