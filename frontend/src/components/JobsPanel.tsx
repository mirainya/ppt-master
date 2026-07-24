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
