-- Reason: use the Codex turn id as the metering idempotency key instead of a local counter.
-- Requirement: never double-bill the same agent turn after crash/lease-recovery re-runs.
-- Scope: replace usage_records.turn (INT) with turn_id (TEXT); usage_records is empty in dev.

ALTER TABLE usage_records DROP CONSTRAINT usage_records_job_id_turn_key;
ALTER TABLE usage_records DROP COLUMN turn;
ALTER TABLE usage_records ADD COLUMN turn_id TEXT NOT NULL DEFAULT '';
ALTER TABLE usage_records ADD CONSTRAINT uq_usage_job_turn UNIQUE (job_id, turn_id);

-- jobs.billed_turns stays as a human-readable turn counter; it no longer drives idempotency.
