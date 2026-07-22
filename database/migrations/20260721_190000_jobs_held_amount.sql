-- Reason: settle the creation-time hold against the actually-held amount, and release
--         it when a job reaches a terminal state without ever settling a turn.
-- Requirement: no credit leak on cancel/fail/never-run; refund must match what was held.
-- Scope: add jobs.held_amount as the outstanding, unreconciled hold for each job.

ALTER TABLE jobs ADD COLUMN held_amount NUMERIC(14, 4) NOT NULL DEFAULT 0;
