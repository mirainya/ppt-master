-- Reason: 企业无法在自己网关拦额度（员工建任务是浏览器直连服务端），需实时推送用量。
-- Requirement: 每轮计费后回调企业接口，企业自行累计并在超限时调 cancel；失败可靠重试。
-- Scope: 新增 org_webhooks（每组织一条回调配置，密钥加密存）与 webhook_deliveries
--        （投递待办表，入队与计费同事务）；不改动既有表。

-- 每组织一条回调配置。密钥 Fernet 加密存储；enabled=FALSE 时保留配置便于恢复。
CREATE TABLE org_webhooks (
    org_id UUID PRIMARY KEY REFERENCES organizations(id) ON DELETE CASCADE,
    callback_url TEXT NOT NULL,
    secret_encrypted TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 投递待办表：入队与计费在同一事务，保证「计费成功即事件已入队」。
-- payload 入队时快照落库，重试不重算，企业不会因重试收到漂移的数字。
-- event_key 是幂等键的可变部分：turn 事件用 usage_records.turn_id；final 事件用
-- jobs.billed_turns，因为终态任务可被 resume 续做后再次终态（app.py 的 resume 允许
-- succeeded/failed 入口），此时总量已变，必须发出新的 final 而不是被唯一键吞掉。
CREATE TABLE webhook_deliveries (
    id UUID PRIMARY KEY,
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    event_type VARCHAR(20) NOT NULL
        CHECK (event_type IN ('usage.turn', 'usage.final')),
    event_key TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::JSONB,
    attempts INT NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    delivered_at TIMESTAMPTZ,
    dead_at TIMESTAMPTZ,
    response_status INT,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (job_id, event_type, event_key)
);

-- 部分索引：后台领取只扫未投递且未死信的行。
CREATE INDEX webhook_deliveries_pending_idx
    ON webhook_deliveries(next_attempt_at)
    WHERE delivered_at IS NULL AND dead_at IS NULL;

-- 企业查自己的投递记录用于排障。
CREATE INDEX webhook_deliveries_org_idx ON webhook_deliveries(org_id, created_at);
