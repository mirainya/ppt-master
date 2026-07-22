-- Reason: enable B2B enterprise integration with per-end-user metering and prepaid billing.
-- Requirement: seamless org API access, per-end-user usage accounting, logical data isolation.
-- Scope: adds organizations/org_api_keys/usage_records/credit_transactions; extends users and jobs.
--         Existing personal users and admins keep org_id = NULL and are unaffected.

-- Tenant organizations. Never hard-deleted (jobs.org_id has no cascade); disable via status.
CREATE TABLE organizations (
    id UUID PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    slug VARCHAR(100) NOT NULL UNIQUE,
    status VARCHAR(20) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'suspended')),
    credit_balance NUMERIC(14, 4) NOT NULL DEFAULT 0,
    daily_job_limit INT NOT NULL DEFAULT 100,
    max_active_jobs INT NOT NULL DEFAULT 5,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Organization-scoped API keys, kept separate from personal user_api_keys.
CREATE TABLE org_api_keys (
    id UUID PRIMARY KEY,
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    key_prefix VARCHAR(20) NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    last_used_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX org_api_keys_org_id_idx ON org_api_keys(org_id);

-- Full-dimension metering ledger; source for the layer-2 usage receipt.
CREATE TABLE usage_records (
    id UUID PRIMARY KEY,
    org_id UUID NOT NULL REFERENCES organizations(id),
    end_user_id UUID REFERENCES users(id),
    job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    turn INT NOT NULL DEFAULT 0,
    input_tokens INT NOT NULL DEFAULT 0,
    output_tokens INT NOT NULL DEFAULT 0,
    images INT NOT NULL DEFAULT 0,
    pages INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (job_id, turn)
);

CREATE INDEX usage_records_org_user_idx
    ON usage_records(org_id, end_user_id, created_at);

-- Credit top-ups and charges for reconciliation.
CREATE TABLE credit_transactions (
    id UUID PRIMARY KEY,
    org_id UUID NOT NULL REFERENCES organizations(id),
    amount NUMERIC(14, 4) NOT NULL,
    reason VARCHAR(40) NOT NULL
        CHECK (reason IN ('topup', 'hold', 'settle_refund', 'settle_extra', 'adjust')),
    job_id UUID REFERENCES jobs(id),
    balance_after NUMERIC(14, 4) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX credit_transactions_org_idx ON credit_transactions(org_id, created_at);

-- Extend users to represent enterprise end-users provisioned just-in-time.
ALTER TABLE users ADD COLUMN org_id UUID REFERENCES organizations(id) ON DELETE CASCADE;
ALTER TABLE users ADD COLUMN external_id VARCHAR(200);
ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL;
ALTER TABLE users ADD CONSTRAINT uq_org_external UNIQUE (org_id, external_id);

-- Extend jobs with organization ownership and a billed-turn counter for idempotent settlement.
ALTER TABLE jobs ADD COLUMN org_id UUID REFERENCES organizations(id);
ALTER TABLE jobs ADD COLUMN billed_turns INT NOT NULL DEFAULT 0;

CREATE INDEX jobs_org_id_idx ON jobs(org_id);
