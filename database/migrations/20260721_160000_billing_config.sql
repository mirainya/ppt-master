-- Reason: make layer-1 pricing runtime-configurable from the admin backend instead of env vars.
-- Requirement: change unit prices and per-job hold without restarting the service.
-- Scope: single-row global billing_config table, seeded with default prices.

CREATE TABLE billing_config (
    id INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),   -- single global row
    price_input_token NUMERIC(16, 10) NOT NULL DEFAULT 0.000002,
    price_output_token NUMERIC(16, 10) NOT NULL DEFAULT 0.000008,
    price_image NUMERIC(12, 4) NOT NULL DEFAULT 0.05,
    hold_amount NUMERIC(14, 4) NOT NULL DEFAULT 5.0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO billing_config (id) VALUES (1);
