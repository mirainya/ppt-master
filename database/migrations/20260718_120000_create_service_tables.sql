-- Reason: add durable storage for the remote PPT Master API.
-- Requirement: chat-style jobs, blocking confirmation, progress, uploads, and artifacts.
-- Scope: creates service-owned tables only; existing PPT Master data is unchanged.

CREATE TABLE schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE jobs (
    id UUID PRIMARY KEY,
    title VARCHAR(200),
    prompt TEXT NOT NULL,
    route VARCHAR(40) NOT NULL CHECK (
        route IN (
            'generate_pptx',
            'create_template',
            'fill_native_pptx',
            'enhance_native_pptx'
        )
    ),
    status VARCHAR(40) NOT NULL CHECK (
        status IN (
            'queued',
            'intake',
            'awaiting_confirmation',
            'planning',
            'acquiring',
            'awaiting_asset',
            'executing',
            'validating',
            'exporting',
            'succeeded',
            'failed',
            'cancelled'
        )
    ),
    stage VARCHAR(40) NOT NULL,
    progress SMALLINT NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
    cancel_requested BOOLEAN NOT NULL DEFAULT FALSE,
    runner_session_id TEXT,
    error JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE job_events (
    id BIGSERIAL PRIMARY KEY,
    job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    event_type VARCHAR(40) NOT NULL,
    stage VARCHAR(40) NOT NULL,
    message TEXT NOT NULL,
    data JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX job_events_job_id_id_idx ON job_events(job_id, id);

CREATE TABLE job_confirmations (
    job_id UUID PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
    proposal JSONB NOT NULL,
    response JSONB,
    status VARCHAR(30) NOT NULL CHECK (
        status IN ('pending', 'approved', 'revision_requested', 'consumed')
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE job_assets (
    id UUID PRIMARY KEY,
    job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    size_bytes BIGINT NOT NULL CHECK (size_bytes >= 0),
    sha256 CHAR(64) NOT NULL,
    media_type TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (job_id, storage_path)
);

CREATE TABLE job_artifacts (
    id UUID PRIMARY KEY,
    job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    kind VARCHAR(40) NOT NULL,
    filename TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    size_bytes BIGINT NOT NULL CHECK (size_bytes >= 0),
    sha256 CHAR(64) NOT NULL,
    media_type TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (job_id, storage_path)
);

CREATE INDEX job_artifacts_job_id_idx ON job_artifacts(job_id);
