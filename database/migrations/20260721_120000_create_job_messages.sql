-- Reason: preserve every user and assistant turn instead of overwriting the latest response.
-- Requirement: render complete task conversations in the remote web application and API.
-- Scope: creates job_messages and backfills the recoverable history of existing jobs.

CREATE TABLE job_messages (
    id BIGSERIAL PRIMARY KEY,
    job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX job_messages_job_id_id_idx ON job_messages(job_id, id);

INSERT INTO job_messages (job_id, role, content, created_at)
SELECT job_id, role, content, created_at
FROM (
    SELECT id AS job_id, 'user' AS role, prompt AS content, created_at, 0 AS sort_order
    FROM jobs
    UNION ALL
    SELECT
        job_id,
        'assistant',
        COALESCE(NULLIF(proposal->>'markdown', ''), proposal->>'message'),
        created_at,
        1
    FROM job_confirmations
    WHERE COALESCE(NULLIF(proposal->>'markdown', ''), proposal->>'message') IS NOT NULL
    UNION ALL
    SELECT
        job_id,
        'user',
        COALESCE(
            NULLIF(response->>'message', ''),
            CASE
                WHEN (response->>'approved')::BOOLEAN THEN '确认方案'
                ELSE '请修改方案'
            END
        ),
        updated_at,
        2
    FROM job_confirmations
    WHERE response IS NOT NULL
) AS history
ORDER BY created_at, sort_order;
