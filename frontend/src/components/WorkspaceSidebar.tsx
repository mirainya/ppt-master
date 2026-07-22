import {
  KeyRound,
  LogOut,
  Plus,
  Presentation,
  Settings,
  X,
} from "lucide-react";
import { useNavigate } from "react-router-dom";

import { ThemeSwitcher } from "./ThemeSwitcher";
import { jobTitle, statusLabels, statusTone } from "../lib/jobDisplay";
import type { AppTheme, Job, User } from "../types";

interface WorkspaceSidebarProps {
  open: boolean;
  onClose: () => void;
  jobs: Job[];
  selectedId: string | null;
  onSelect: (jobId: string) => void;
  onNewJob: () => void;
  user: User | null;
  theme: AppTheme;
  onTheme: (theme: AppTheme) => void;
  onOpenApiKeys: () => void;
  onLogout: () => void;
}

/** Left rail: brand, new-job button, recent job list, theme + account controls. */
export function WorkspaceSidebar({
  open,
  onClose,
  jobs,
  selectedId,
  onSelect,
  onNewJob,
  user,
  theme,
  onTheme,
  onOpenApiKeys,
  onLogout,
}: WorkspaceSidebarProps) {
  const navigate = useNavigate();

  return (
    <aside className={`sidebar ${open ? "sidebar-open" : ""}`}>
      <div className="brand-row">
        <div className="brand-mark">
          <Presentation size={18} />
        </div>
        <strong>PPT Master</strong>
        <button
          className="icon-button sidebar-close"
          onClick={onClose}
          aria-label="关闭任务栏"
          title="关闭任务栏"
        >
          <X size={18} />
        </button>
      </div>

      <button className="new-job-button" onClick={onNewJob}>
        <Plus size={17} />
        <span>新建演示</span>
      </button>

      <div className="sidebar-label">最近任务</div>
      <nav className="job-list" aria-label="最近任务">
        {jobs.map((job) => (
          <button
            key={job.id}
            className={`job-item ${selectedId === job.id ? "selected" : ""}`}
            onClick={() => onSelect(job.id)}
          >
            <span className={`status-dot ${statusTone(job.status)}`} />
            <span className="job-copy">
              <strong>{jobTitle(job)}</strong>
              <small>{statusLabels[job.status]}</small>
            </span>
          </button>
        ))}
        {jobs.length === 0 && <div className="empty-list">暂无任务</div>}
      </nav>

      <div className="sidebar-footer">
        <ThemeSwitcher theme={theme} onChange={onTheme} />
        <div className="account-row">
          <span className="account-name" title={user?.username || "账户"}>
            {user?.username || "账户"}
          </span>
          {user?.is_admin && (
            <button
              type="button"
              onClick={() => navigate("/admin")}
              aria-label="管理控制台"
              title="管理控制台"
            >
              <Settings size={15} />
            </button>
          )}
          {!user?.org_id && (
            <button
              type="button"
              onClick={onOpenApiKeys}
              aria-label="管理 API 密钥"
              title="管理 API 密钥"
            >
              <KeyRound size={15} />
            </button>
          )}
          <button
            type="button"
            onClick={onLogout}
            aria-label="退出登录"
            title="退出登录"
          >
            <LogOut size={15} />
          </button>
        </div>
      </div>
    </aside>
  );
}
