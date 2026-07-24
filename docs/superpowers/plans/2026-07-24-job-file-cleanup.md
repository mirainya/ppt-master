# 任务文件清理（手动 + 自动到期）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让管理员能查看/清理全部任务的磁盘文件，并让 worker 按可配置保留期自动清理到期任务文件，保留任务记录与计费流水。

**Architecture:** 共享一个「清理文件」底层操作（`JobStorage.purge_job_files` + `repository.mark_job_purged`）。手动路径经管理员接口触发，自动路径经 worker 每 24 小时的后台 asyncio 任务触发。`jobs.files_purged_at` 列标记清理态，前端据此禁用下载。

**Tech Stack:** Python 3.11 / FastAPI / asyncpg / PostgreSQL / Redis；前端 React + TypeScript + Vite；pytest（新引入，仅纯文件逻辑单测）。

---

## 文件结构

- Create `database/migrations/20260724_HHMMSS_jobs_files_purged.sql` — 加 `files_purged_at` 列。
- Modify `service/storage.py` — 加 `purge_job_files`（纯文件逻辑，可单测）。
- Create `service/tests/__init__.py`、`service/tests/test_storage_purge.py` — 最小 pytest。
- Modify `service/repository.py` — 加 `mark_job_purged`、`list_purgeable_jobs`、`list_all_jobs`。
- Modify `service/schemas.py` — `JobRead` 加 `files_purged_at`；新增 `AdminJobRead`。
- Modify `service/app.py` — 加 `GET /v1/admin/jobs`、`POST /v1/admin/jobs/{job_id}/purge`；下载/预览接口清理态返回 410。
- Modify `service/config.py` — 加 `job_retention_days`。
- Modify `service/worker.py` — 加后台周期清理任务。
- Modify `compose.yaml`、`compose.linux-4g.yaml` — `environment:` 加 `PPT_JOB_RETENTION_DAYS`。
- Modify `.env.example` — 文档说明。
- Modify `frontend/src/api.ts` — 加 `listAllJobs`、`purgeJob`。
- Modify `frontend/src/types.ts` — `Job` 加 `files_purged_at`；新增 `AdminJob`。
- Create `frontend/src/hooks/useAdminJobs.ts` — 全部任务读取 + 清理。
- Create `frontend/src/components/JobsPanel.tsx` — 任务面板。
- Modify `frontend/src/pages/AdminPage.tsx` — 接入「任务」tab。

---

### Task 1: 数据库迁移 — files_purged_at 列

**Files:**
- Create: `database/migrations/20260724_HHMMSS_jobs_files_purged.sql`（`HHMMSS` 用创建时的真实时间，如 `20260724_143000`）

- [ ] **Step 1: 写迁移文件**

```sql
-- Reason: 支持清理任务磁盘文件后保留任务记录，标记清理时间。
-- Requirement: 管理员手动清理 + worker 自动到期清理，保留 jobs 记录与计费流水。
-- Scope: 给 jobs 加 files_purged_at；NULL=文件在，有值=已清理及时间。

ALTER TABLE jobs ADD COLUMN files_purged_at TIMESTAMPTZ NULL;
```

- [ ] **Step 2: 提交**

```bash
git add database/migrations/20260724_*_jobs_files_purged.sql
git commit -m "feat(db): add jobs.files_purged_at for file cleanup tracking"
```

（迁移在部署阶段 apply，不在本地跑；本地无 PG 实例。）

---

### Task 2: JobStorage.purge_job_files + 单元测试（纯文件逻辑，TDD）

**Files:**
- Create: `service/tests/__init__.py`
- Create: `service/tests/test_storage_purge.py`
- Modify: `service/storage.py`（在 `JobStorage` 类内，`_require_child` 之后加方法）

- [ ] **Step 1: 建测试包占位文件**

`service/tests/__init__.py` 内容为空（仅使目录成为包）。

- [ ] **Step 2: 写失败测试**

`service/tests/test_storage_purge.py`：

```python
"""Unit tests for JobStorage.purge_job_files (pure filesystem logic)."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from service.storage import JobStorage


def _storage(tmp_path: Path) -> JobStorage:
    return JobStorage(tmp_path / "jobs", max_upload_bytes=1024)


def test_purge_removes_job_directory(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    job_id = uuid4()
    storage.prepare_job(job_id)
    assert storage.job_dir(job_id).exists()

    removed = storage.purge_job_files(job_id)

    assert removed is True
    assert not storage.job_dir(job_id).exists()


def test_purge_is_idempotent_when_missing(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    job_id = uuid4()

    removed = storage.purge_job_files(job_id)

    assert removed is False


def test_purge_keeps_sibling_jobs(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    keep_id = uuid4()
    drop_id = uuid4()
    storage.prepare_job(keep_id)
    storage.prepare_job(drop_id)

    storage.purge_job_files(drop_id)

    assert storage.job_dir(keep_id).exists()
    assert not storage.job_dir(drop_id).exists()
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd F:/free/PythonProject/ppt-master && python -m pytest service/tests/test_storage_purge.py -v`
Expected: FAIL — `AttributeError: 'JobStorage' object has no attribute 'purge_job_files'`
（若 pytest 未装：`pip install pytest` 后再跑。）

- [ ] **Step 4: 实现 purge_job_files**

在 `service/storage.py` 的 `JobStorage` 类内、`_require_child` 静态方法之前插入：

```python
    def purge_job_files(self, job_id: UUID) -> bool:
        """Delete one task's whole on-disk directory. Idempotent.

        Returns True if a directory was removed, False if it did not exist.
        The job_dir() call re-validates the path stays under root.
        """
        job_dir = self.job_dir(job_id)
        if not job_dir.exists():
            return False
        shutil.rmtree(job_dir)
        return True
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd F:/free/PythonProject/ppt-master && python -m pytest service/tests/test_storage_purge.py -v`
Expected: PASS（3 passed）

- [ ] **Step 6: 提交**

```bash
git add service/tests/__init__.py service/tests/test_storage_purge.py service/storage.py
git commit -m "feat(storage): add purge_job_files with unit tests"
```

---

### Task 3: repository 层 — mark_job_purged / list_purgeable_jobs / list_all_jobs

**Files:**
- Modify: `service/repository.py`（在 `list_jobs_for_user` 之后，`record_turn_usage` 之前插入三个方法）

无纯逻辑单测（依赖 asyncpg + PostgreSQL 语法，SQLite 不兼容）；靠 Task 5/8 接口跑起来验证。

- [ ] **Step 1: 加三个方法**

在 `service/repository.py` 的 `list_jobs_for_user` 方法之后插入：

```python
    async def list_all_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        """List every task across all owners, newest first, with owner username."""
        records = await self.database.require_pool().fetch(
            """
            SELECT job.*, account.username AS owner_username
            FROM jobs AS job
            LEFT JOIN users AS account ON account.id = job.owner_id
            ORDER BY job.updated_at DESC
            LIMIT $1
            """,
            max(1, min(limit, 200)),
        )
        return [dict(record) for record in records]

    async def mark_job_purged(self, job_id: UUID) -> dict[str, Any] | None:
        """Stamp files_purged_at once the on-disk files are gone."""
        record = await self.database.require_pool().fetchrow(
            """
            UPDATE jobs
            SET files_purged_at = CURRENT_TIMESTAMP
            WHERE id = $1
            RETURNING *
            """,
            job_id,
        )
        return dict(record) if record else None

    async def list_purgeable_jobs(self, cutoff: datetime) -> list[dict[str, Any]]:
        """Terminal tasks last updated before cutoff that still hold files."""
        records = await self.database.require_pool().fetch(
            """
            SELECT * FROM jobs
            WHERE status IN ('succeeded', 'failed', 'cancelled')
              AND updated_at < $1
              AND files_purged_at IS NULL
            ORDER BY updated_at ASC
            """,
            cutoff,
        )
        return [dict(record) for record in records]
```

- [ ] **Step 2: 确认 datetime 已导入**

Run: `grep -n "from datetime" service/repository.py`
Expected: 已有 `datetime` 导入（如 `from datetime import ...`）。若缺 `datetime`，在文件顶部导入区补 `from datetime import datetime`。

- [ ] **Step 3: 语法检查**

Run: `cd F:/free/PythonProject/ppt-master && python -c "import ast; ast.parse(open('service/repository.py',encoding='utf-8').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 4: 提交**

```bash
git add service/repository.py
git commit -m "feat(repository): add all-jobs listing, purge marker, purgeable query"
```

---

### Task 4: schemas — files_purged_at 字段 + AdminJobRead

**Files:**
- Modify: `service/schemas.py`（`JobRead` 加字段；其后新增 `AdminJobRead`）

- [ ] **Step 1: JobRead 加字段**

在 `service/schemas.py` 的 `JobRead` 类内，`updated_at: datetime` 之后加一行：

```python
    files_purged_at: datetime | None = None
```

- [ ] **Step 2: 新增 AdminJobRead**

紧跟 `JobRead` 类之后插入：

```python
class AdminJobRead(JobRead):
    """Task row for the admin console: adds the owner's username."""

    owner_username: str | None = None
```

- [ ] **Step 3: 语法检查**

Run: `cd F:/free/PythonProject/ppt-master && python -c "import ast; ast.parse(open('service/schemas.py',encoding='utf-8').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 4: 提交**

```bash
git add service/schemas.py
git commit -m "feat(schemas): expose files_purged_at and add AdminJobRead"
```

---

### Task 5: A — 管理员接口（全部任务视图 + 手动清理）

**Files:**
- Modify: `service/app.py`（`admin_list_users` 之前或之后加两个路由；确保 `AdminJobRead` 已导入）

- [ ] **Step 1: 导入 AdminJobRead**

在 `service/app.py` 顶部从 `service.schemas` 导入的清单里加 `AdminJobRead`（与现有 `JobRead` 等并列）。

- [ ] **Step 2: 加「全部任务」接口**

在 `service/app.py` 的 `@app.get("/v1/admin/users"...)` 定义之前插入：

```python
@app.get("/v1/admin/jobs", response_model=list[AdminJobRead])
async def admin_list_jobs(
    request: Request,
    admin: AdminUser,
    limit: int = 50,
) -> list[dict]:
    """List every task across all users for the admin console."""
    return await _repository(request).list_all_jobs(limit)
```

- [ ] **Step 3: 加「手动清理」接口**

紧跟其后插入：

```python
@app.post("/v1/admin/jobs/{job_id}/purge", response_model=AdminJobRead)
async def admin_purge_job(
    request: Request,
    job_id: UUID,
    admin: AdminUser,
) -> dict:
    """Delete one task's on-disk files while keeping its record and billing."""
    job = await _repository(request).get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job["status"] not in {s.value for s in TERMINAL_STATUSES}:
        raise HTTPException(
            status_code=409,
            detail="task is still active; cancel it before purging files",
        )
    request.app.state.storage.purge_job_files(job_id)
    updated = await _repository(request).mark_job_purged(job_id)
    return updated if updated is not None else job
```

- [ ] **Step 4: 确认 TERMINAL_STATUSES 已导入**

Run: `grep -n "TERMINAL_STATUSES" service/app.py`
Expected: 已在从 `service.schemas` 的导入里。若无，补进导入清单。

- [ ] **Step 5: 语法检查**

Run: `cd F:/free/PythonProject/ppt-master && python -c "import ast; ast.parse(open('service/app.py',encoding='utf-8').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 6: 提交**

```bash
git add service/app.py
git commit -m "feat(api): admin all-jobs listing and manual file purge"
```

---

### Task 6: 下载/预览接口 — 清理态返回 410

**Files:**
- Modify: `service/app.py`（`download_artifact` 与 `view_artifact` 两处）

现状：文件缺失时返回 404「artifact file is missing」。改造：先查任务 `files_purged_at`，已清理则返回明确的 410。

- [ ] **Step 1: 加共享校验辅助**

在 `service/app.py` 的 `_require_job` 函数之后插入：

```python
async def _reject_if_purged(request: Request, job_id: UUID) -> None:
    """Return 410 when a task's files were intentionally cleaned up."""
    job = await _repository(request).get_job(job_id)
    if job is not None and job.get("files_purged_at") is not None:
        raise HTTPException(status_code=410, detail="task files have been cleaned up")
```

- [ ] **Step 2: download_artifact 加校验**

在 `download_artifact` 里，`await _require_job(...)` 之后、取 artifact 之前插入一行：

```python
    await _reject_if_purged(request, job_id)
```

- [ ] **Step 3: view_artifact 加校验**

在 `view_artifact` 里同样位置插入相同一行 `await _reject_if_purged(request, job_id)`。

- [ ] **Step 4: 语法检查**

Run: `cd F:/free/PythonProject/ppt-master && python -c "import ast; ast.parse(open('service/app.py',encoding='utf-8').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 5: 提交**

```bash
git add service/app.py
git commit -m "feat(api): return 410 for downloads of purged task files"
```

---

### Task 7: config — PPT_JOB_RETENTION_DAYS + compose + .env

**Files:**
- Modify: `service/config.py`（Settings 加字段 + from_env 读取）
- Modify: `compose.yaml`、`compose.linux-4g.yaml`（environment 白名单）
- Modify: `.env.example`（文档）

- [ ] **Step 1: Settings 加字段**

在 `service/config.py` 的 `Settings` dataclass 里，`session_days: int` 之后加：

```python
    job_retention_days: int
```

- [ ] **Step 2: from_env 读取**

在 `from_env` 的返回体里，`session_days=...` 之后加（默认 30；0 = 关闭自动清理，故用容许 0 的独立读取）：

```python
            job_retention_days=_non_negative_int("PPT_JOB_RETENTION_DAYS", 30),
```

- [ ] **Step 3: 加 _non_negative_int 辅助**

在 `service/config.py` 的 `_positive_int` 函数之后插入（0 表示关闭，故不能复用 _positive_int）：

```python
def _non_negative_int(name: str, default: int) -> int:
    raw_value = os.environ.get(name, str(default))
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < 0:
        raise ValueError(f"{name} must be zero or greater")
    return value
```

- [ ] **Step 4: 两个 compose 文件 environment 各加一行**

`compose.linux-4g.yaml` 与 `compose.yaml` 的 `environment:`（`&service-environment` 锚点段）里，`PPT_SESSION_DAYS` 那一行之后各加：

```yaml
      PPT_JOB_RETENTION_DAYS: ${PPT_JOB_RETENTION_DAYS:-30}
```

- [ ] **Step 5: .env.example 文档**

在 `.env.example` 的 `PPT_SESSION_DAYS=30` 之后加：

```bash
# 任务文件保留天数：终态任务最后更新超过该天数后，worker 自动清理其磁盘文件
# （保留任务记录与计费流水）。设 0 关闭自动清理。默认 30。
PPT_JOB_RETENTION_DAYS=30
```

- [ ] **Step 6: 校验配置加载**

Run: `cd F:/free/PythonProject/ppt-master && PPT_JOB_RETENTION_DAYS=0 python -c "from service.config import Settings; print('retention=', Settings.from_env().job_retention_days)"`
Expected: `retention= 0`（不报错，证明 0 被接受）

- [ ] **Step 7: 提交**

```bash
git add service/config.py compose.yaml compose.linux-4g.yaml .env.example
git commit -m "feat(config): add PPT_JOB_RETENTION_DAYS for auto file cleanup"
```

---

### Task 8: B — worker 后台周期清理任务

**Files:**
- Modify: `service/worker.py`（顶部加 datetime 导入；加清理协程；run_worker 里启动/停止）

- [ ] **Step 1: 加 datetime 导入**

在 `service/worker.py` 顶部 `from time import time` 之后加：

```python
from datetime import UTC, datetime, timedelta
```

- [ ] **Step 2: 加清理协程**

在 `service/worker.py` 的 `async def run_worker()` 定义之前插入：

```python
_CLEANUP_INTERVAL_SECONDS = 24 * 60 * 60


async def _maintain_file_retention(
    repository: JobRepository,
    storage: JobStorage,
    settings: Settings,
    stop: asyncio.Event,
) -> None:
    """Purge on-disk files of terminal tasks older than the retention window."""
    retention_days = settings.job_retention_days
    if retention_days <= 0:
        return
    while not stop.is_set():
        try:
            cutoff = datetime.now(UTC) - timedelta(days=retention_days)
            for job in await repository.list_purgeable_jobs(cutoff):
                if job["status"] not in {s.value for s in TERMINAL_STATUSES}:
                    continue
                if storage.purge_job_files(job["id"]):
                    await repository.mark_job_purged(job["id"])
                    logger.info("Purged files for expired task %s", job["id"])
        except Exception:
            logger.exception("File retention sweep failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=_CLEANUP_INTERVAL_SECONDS)
        except TimeoutError:
            continue
```

- [ ] **Step 3: run_worker 启动清理任务**

在 `run_worker` 里，`presence_task = asyncio.create_task(...)` 之后加：

```python
    stop_retention = asyncio.Event()
    retention_task = asyncio.create_task(
        _maintain_file_retention(repository, storage, settings, stop_retention)
    )
```

- [ ] **Step 4: run_worker 停止清理任务**

在 `run_worker` 末尾的 `finally:` 块里，`stop_presence.set()` / `await presence_task` 旁边加：

```python
        stop_retention.set()
        await retention_task
```

- [ ] **Step 5: 语法检查**

Run: `cd F:/free/PythonProject/ppt-master && python -c "import ast; ast.parse(open('service/worker.py',encoding='utf-8').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 6: 提交**

```bash
git add service/worker.py
git commit -m "feat(worker): auto-purge expired task files on a daily sweep"
```

---

### Task 9: 前端 — api.ts + types.ts

**Files:**
- Modify: `frontend/src/types.ts`（Job 加字段 + 新增 AdminJob）
- Modify: `frontend/src/api.ts`（加 listAllJobs、purgeJob）

- [ ] **Step 1: types.ts — Job 加字段**

在 `frontend/src/types.ts` 的 `Job` 接口里，`updated_at: string;` 之后加：

```typescript
  files_purged_at: string | null;
```

- [ ] **Step 2: types.ts — 新增 AdminJob**

紧跟 `Job` 接口之后插入：

```typescript
export interface AdminJob extends Job {
  owner_username: string | null;
}
```

- [ ] **Step 3: api.ts — 加两个方法**

在 `frontend/src/api.ts` 的 `listJobs()` 方法之后插入（注意 `AdminJob` 需在文件顶部 type 导入里补上）：

```typescript
  listAllJobs(limit = 50): Promise<AdminJob[]> {
    return this.request<AdminJob[]>(`/v1/admin/jobs?limit=${limit}`);
  }

  purgeJob(jobId: string): Promise<AdminJob> {
    return this.request<AdminJob>(`/v1/admin/jobs/${jobId}/purge`, {
      method: "POST",
    });
  }
```

- [ ] **Step 4: 类型检查**

Run: `cd F:/free/PythonProject/ppt-master/frontend && npx tsc --noEmit`
Expected: 无错误（若报 AdminJob 未导入，在 api.ts 顶部 `import type { ... }` 里补 `AdminJob`）

- [ ] **Step 5: 提交**

```bash
git add frontend/src/types.ts frontend/src/api.ts
git commit -m "feat(frontend): add admin all-jobs and purge API client methods"
```

---

### Task 10: 前端 — useAdminJobs hook + JobsPanel + AdminPage 接线

**Files:**
- Create: `frontend/src/hooks/useAdminJobs.ts`
- Create: `frontend/src/components/JobsPanel.tsx`
- Modify: `frontend/src/pages/AdminPage.tsx`

- [ ] **Step 1: 建 useAdminJobs hook**

`frontend/src/hooks/useAdminJobs.ts`：

```typescript
import { useCallback, useEffect, useState } from "react";

import type { ApiClient } from "../api";
import type { AdminJob } from "../types";

/** Admin task console: list every task and purge one task's files. */
export function useAdminJobs(apiClient: ApiClient) {
  const [jobs, setJobs] = useState<AdminJob[]>([]);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      setJobs(await apiClient.listAllJobs(100));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "任务读取失败");
    } finally {
      setBusy(false);
    }
  }, [apiClient]);

  useEffect(() => {
    void load();
  }, [load]);

  const purge = useCallback(
    async (jobId: string) => {
      setError("");
      try {
        const updated = await apiClient.purgeJob(jobId);
        setJobs((current) =>
          current.map((job) => (job.id === jobId ? updated : job)),
        );
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "清理失败");
      }
    },
    [apiClient],
  );

  return { jobs, busy, error, load, purge };
}
```

- [ ] **Step 2: 建 JobsPanel 组件**

`frontend/src/components/JobsPanel.tsx`：

```typescript
import { RefreshCw, Trash2 } from "lucide-react";

import { formatDate } from "../lib/jobDisplay";
import type { useAdminJobs } from "../hooks/useAdminJobs";

type JobsHook = ReturnType<typeof useAdminJobs>;

/** Admin task console: view every task and clean up one task's files. */
export function JobsPanel({ jobs }: { jobs: JobsHook }) {
  const confirmPurge = (id: string, title: string | null) => {
    if (window.confirm(`确定清理任务「${title || id}」的文件吗？此操作不可恢复。`)) {
      void jobs.purge(id);
    }
  };

  return (
    <div className="admin-panel-body">
      <div className="user-section-heading">
        <h2>全部任务</h2>
        <button className="secondary-command" onClick={() => void jobs.load()}>
          <RefreshCw size={15} />
          <span>刷新</span>
        </button>
      </div>
      {jobs.error && <p className="field-error">{jobs.error}</p>}
      <table className="user-table">
        <thead>
          <tr>
            <th>标题</th>
            <th>归属</th>
            <th>状态</th>
            <th>更新时间</th>
            <th>文件</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {jobs.jobs.map((job) => (
            <tr key={job.id}>
              <td>{job.title || job.prompt.slice(0, 30)}</td>
              <td>{job.owner_username ?? "—"}</td>
              <td>{job.status}</td>
              <td>{formatDate(job.updated_at)}</td>
              <td>{job.files_purged_at ? "已清理" : "在库"}</td>
              <td>
                {!job.files_purged_at && (
                  <button
                    className="secondary-command"
                    onClick={() => confirmPurge(job.id, job.title)}
                  >
                    <Trash2 size={15} />
                    <span>清理文件</span>
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 3: AdminPage 接线**

在 `frontend/src/pages/AdminPage.tsx` 做四处改动：

1. 顶部 import 加：`import { JobsPanel } from "../components/JobsPanel";` 和 `import { useAdminJobs } from "../hooks/useAdminJobs";`，并在 lucide 图标导入里加 `ListChecks`。
2. `AdminTab` 类型改为：`type AdminTab = "accounts" | "orgs" | "billing" | "runtime" | "jobs";`
3. `TABS` 数组末尾加：`{ key: "jobs", label: "任务管理", icon: ListChecks },`
4. 组件体内 `const orgs = useOrgs(apiClient);` 之后加 `const adminJobs = useAdminJobs(apiClient);`；`admin-content` 里 `{tab === "runtime" && ...}` 之后加 `{tab === "jobs" && <JobsPanel jobs={adminJobs} />}`。

- [ ] **Step 4: 类型检查**

Run: `cd F:/free/PythonProject/ppt-master/frontend && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 5: 提交**

```bash
git add frontend/src/hooks/useAdminJobs.ts frontend/src/components/JobsPanel.tsx frontend/src/pages/AdminPage.tsx
git commit -m "feat(frontend): admin task panel with all-jobs view and file purge"
```

---

### Task 11: 部署与线上验证

**Files:** 无代码改动，纯部署操作（参考 [[ppt-master-deploy-reality]] 记忆）。

- [ ] **Step 1: apply 迁移**

scp 迁移文件到服务器后，用 psql apply（在服务器上，从容器或宿主机连 PG）：
`ALTER TABLE jobs ADD COLUMN files_purged_at TIMESTAMPTZ NULL;`
先展示 SQL 等主人确认再执行（数据库操作规范）。

- [ ] **Step 2: 传 service 改动 + compose**

scp 传 `service/`（storage.py app.py repository.py schemas.py config.py worker.py）+ 两个 compose 文件 + .env 加 `PPT_JOB_RETENTION_DAYS=30`（可选，默认已 30）。

- [ ] **Step 3: 前端构建 + 传 dist**

本地 `cd frontend && npm run build`（不带 VITE_MOCK）→ 传 dist 到 `/www/wwwroot/ppt.mirainya.icu`（排除 .user.ini）。

- [ ] **Step 4: 重建容器**

`docker compose -f compose.linux-4g.yaml up -d --build api worker`

- [ ] **Step 5: 线上验证（端到端，非只看日志）**

- 管理后台 → 任务管理 tab：能看到全部用户任务、带归属。
- 对一个终态任务点「清理文件」→ 确认 → 该任务标记「已清理」、服务器上 `runtime/jobs/<id>` 目录消失、jobs 记录仍在。
- 已清理任务调下载接口返回 410。
- 对运行中任务清理返回 409。
- worker 日志确认 retention 任务已启动（retention_days>0 时）。

- [ ] **Step 6: 更新记忆**

在 `ppt-master-deploy-reality` 或新建记忆里记录：任务文件清理功能上线、`PPT_JOB_RETENTION_DAYS` 默认 30、管理后台「任务管理」tab 是全部任务入口。

---

## 自检

- **spec 覆盖**：数据模型(T1,T4)、清理核心(T2,T3)、A 手动+全部任务视图(T3,T5,T10)、B 自动清理(T7,T8)、下载失效 410(T6)、部署验证(T11) — 全覆盖。
- **类型一致**：`purge_job_files`(bool)、`mark_job_purged`、`list_purgeable_jobs`、`list_all_jobs`、`AdminJobRead`/`AdminJob`、`files_purged_at`、`job_retention_days`/`PPT_JOB_RETENTION_DAYS` — 前后一致。
- **占位符**：仅迁移文件名 `HHMMSS`（有意，需填真实时间戳）。
