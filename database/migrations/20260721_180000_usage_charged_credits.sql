-- Reason: the layer-2 receipt's our_charge must be the real per-turn cost, not derived
--         from hold/settle cash-flow rows (the creation-time hold has no job_id).
-- Requirement: report an accurate charged amount per job to the integrating enterprise.
-- Scope: add usage_records.charged_credits, populated per turn at settlement time.

ALTER TABLE usage_records
    ADD COLUMN charged_credits NUMERIC(14, 4) NOT NULL DEFAULT 0;
