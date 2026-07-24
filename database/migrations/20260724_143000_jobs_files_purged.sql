-- Reason: 支持清理任务磁盘文件后保留任务记录，标记清理时间。
-- Requirement: 管理员手动清理 + worker 自动到期清理，保留 jobs 记录与计费流水。
-- Scope: 给 jobs 加 files_purged_at；NULL=文件在，有值=已清理及时间。

ALTER TABLE jobs ADD COLUMN files_purged_at TIMESTAMPTZ NULL;
