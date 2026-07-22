-- Reason: let administrators update Codex and image-provider settings at runtime.
-- Requirement: apply provider changes to the next queued task without redeploying.
-- Scope: single-row global service_runtime_config table; API keys are write-only.

CREATE TABLE service_runtime_config (
    id INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    codex_base_url TEXT,
    codex_api_key_encrypted TEXT,
    codex_model TEXT,
    image_base_url TEXT,
    image_api_key_encrypted TEXT,
    image_model TEXT,
    image_size TEXT,
    image_concurrency INT CHECK (
        image_concurrency IS NULL OR image_concurrency BETWEEN 1 AND 20
    ),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO service_runtime_config (id) VALUES (1);
