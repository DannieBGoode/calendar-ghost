-- What each Incident says, as a stable code and JSON parameters the Web UI translates (ADR 0026).
-- Incidents recorded earlier keep NULL, and the Web UI shows their stored English summary.
ALTER TABLE incidents ADD COLUMN message_code TEXT;
ALTER TABLE incidents ADD COLUMN message_params TEXT;
