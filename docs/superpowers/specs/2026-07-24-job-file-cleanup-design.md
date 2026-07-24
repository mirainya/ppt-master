# 任务文件清理（手动 + 自动到期）设计

- 日期：2026-07-24
- 状态：已确认，待拆实现计划
- 相关：`service/storage.py`、`service/repository.py`、`service/app.py`、`service/worker.py`、`frontend/src/pages/AdminPage.tsx`

## 背景与目标

叙卷（PPT Master）当前**无任何任务文件清理机制**：每个任务的 SVG/图片/PPTX 堆在 `runtime/jobs/<job_id>/`，只增不减。短期磁盘充裕（实测 7 任务仅 140K），但用户量上来后长期堆积是隐患。

此外发现一个可见性缺口：管理员调 `GET /v1/jobs` 时 SQL 为 `owner_id = $1 OR ($2 AND owner_id IS NULL)`，只看得到自己的任务 + 无主任务，**看不到其他用户名下的任务**，系统里没有「查看全部任务」的入口。

两个目标：
- **A（手动）**：管理员能看到全部任务，并清理任意任务的磁盘文件。
- **B（自动）**：到期任务自动清理磁盘文件，防长期堆积。

核心洞察：**A 和 B 共用同一个「清理文件」底层操作**，只是触发方式不同（人工 vs 定时）。

## 语义定义

「清理任务文件」而非「删除任务」：
- **保留** `jobs` 数据库记录（列表仍可见，标记为「已清理」态，历史/审计可查）
- **保留** 计费流水（`usage` / `credit_transactions` 等表完全不动）
- **删除** 磁盘目录 `runtime/jobs/<job_id>/`（inbox + workspace + artifacts 全清）
- 不可恢复；文件清理后产物下载失效

## 硬约束

- 只清理终态任务：`status ∈ {succeeded, failed, cancelled}`（复用 `schemas.TERMINAL_STATUSES`）。
- **运行中的任务绝不清理**（防止清掉 worker 正在写的数据）。
- 权限：仅管理员（`is_admin`）能手动清理；普通用户无清理能力。

## 数据模型

新增迁移文件 `database/migrations/20260724_HHMMSS_jobs_files_purged.sql`：

```sql
ALTER TABLE jobs ADD COLUMN files_purged_at TIMESTAMPTZ NULL;
```

- `NULL` = 文件在；有值 = 已清理及清理时间。
- `JobRead` schema 增 `files_purged_at: datetime | None`，前端据此渲染「已清理」态、禁用下载。管理员面板用的 `AdminJobRead` 继承同字段并额外带 `owner_username`。

## 组件设计

### 1. 共享清理核心（storage + repository）

- `JobStorage.purge_job_files(job_id) -> bool`：`shutil.rmtree` 掉 `runtime/jobs/<job_id>/`，复用 `_require_child` 做路径安全校验；目录不存在时幂等返回。
- `JobRepository.mark_job_purged(job_id)`：置 `files_purged_at = CURRENT_TIMESTAMP`。
- `JobRepository.list_purgeable_jobs(cutoff)`：查 `status ∈ 终态 AND updated_at < cutoff AND files_purged_at IS NULL`。

### 2. A — 管理员手动清理 + 全部任务视图

- `GET /v1/admin/jobs?limit=`（管理员专属）：列全部用户任务，带 owner 用户名。复用已存在但未暴露的 `repository.list_jobs()`；新增 owner 用户名 JOIN。响应模型 `AdminJobRead`（JobRead + owner_username + files_purged_at）。
- `POST /v1/admin/jobs/{job_id}/purge`（管理员专属）：清理指定任务文件。任务非终态 → 返回 409 提示先取消。调用共享核心 + `mark_job_purged`。
- 前端：`AdminPage` 新增第 5 个「任务」面板 `JobsPanel.tsx`——表格（标题/owner/状态/更新时间/已清理），每行「清理文件」按钮 + 二次确认。这是「查看所有任务列表」的入口。

### 3. B — 自动到期清理（worker）

- 配置 `PPT_JOB_RETENTION_DAYS`（`config.py`，默认 30；`0` = 关闭）。compose 两文件 `environment:` 白名单各加一行 `PPT_JOB_RETENTION_DAYS: ${PPT_JOB_RETENTION_DAYS:-30}`（避免 .env 变量不注入容器的坑）。
- worker 新增后台周期任务：每 **24 小时** 跑一次，`list_purgeable_jobs(now - retention)` → 逐个清理 + 标记。
- 与 worker 主循环（dequeue）并行独立跑（asyncio task），互不干扰。retention=0 时不启动该任务。

## 边界与错误处理

- **下载失效**：任务已清理后调产物下载/预览/artifacts 列表接口 → 返回 `410 Gone`「文件已清理」。前端「已清理」态禁用下载按钮。
- **并发**：自动清理前二次校验任务仍为终态（避免扫描后、清理前任务被重新 resume）。
- **幂等**：`files_purged_at` 已有值的任务跳过；`rmtree` 目录不存在不报错。

## 测试

- 单元：`purge_job_files`（正常清理、目录不存在幂等、路径逃逸拒绝）；运行中任务拒清；`list_purgeable_jobs` 筛选（终态+过期+未清理，排除运行中/未过期/已清理）。
- 接口：`GET /v1/admin/jobs` 非管理员 403；`POST .../purge` 非管理员 403、非终态 409、成功后 `files_purged_at` 落库；下载已清理任务返回 410。

## 部署

- `service/` 改动：scp 传文件。
- 前端：本地 `npm run build`（不带 VITE_MOCK）→ 传 dist 到 `/www/wwwroot/ppt.mirainya.icu`。
- 迁移：`database/migrations/` 新文件在服务器手动 apply（psql）。
- compose：两文件 `environment:` 加 `PPT_JOB_RETENTION_DAYS`；重建 api+worker。
- 验证：管理后台任务面板可见全部任务；手动清理后目录消失、记录仍在、下载 410；worker 日志确认周期清理任务启动。
