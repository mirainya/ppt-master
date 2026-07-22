import { useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  Check,
  Copy,
  KeyRound,
  LoaderCircle,
  Plus,
  Power,
  PowerOff,
  RefreshCw,
  ShieldCheck,
  Trash2,
  UserPlus,
  Users,
  X,
} from "lucide-react";

import { Pagination } from "./Pagination";
import { copyText } from "../lib/clipboard";
import { formatDate } from "../lib/jobDisplay";
import type { useAdminUsers } from "../hooks/useAdminUsers";

const PAGE_SIZE = 10;

type AdminUsersHook = ReturnType<typeof useAdminUsers>;

interface AccountsPanelProps {
  admin: AdminUsersHook;
  currentUserId: string;
}

/** Admin account management panel (list, create, disable, reset, per-user keys). */
export function AccountsPanel({ admin, currentUserId }: AccountsPanelProps) {
  const [page, setPage] = useState(1);
  const pageCount = Math.max(1, Math.ceil(admin.users.length / PAGE_SIZE));

  // Clamp the page when the list shrinks (e.g. after a filter/refresh).
  useEffect(() => {
    if (page > pageCount) setPage(pageCount);
  }, [page, pageCount]);

  const pageUsers = useMemo(
    () => admin.users.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE),
    [admin.users, page],
  );
  const rangeStart = admin.users.length === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const rangeEnd = Math.min(page * PAGE_SIZE, admin.users.length);

  return (
    <div className="admin-panel-body">
      <form className="user-create-form" onSubmit={admin.createUser}>
        <div className="user-section-heading">
          <UserPlus size={19} />
          <h2>创建账号</h2>
        </div>
        <label>
          <span>用户名</span>
          <input
            value={admin.username}
            maxLength={100}
            autoComplete="off"
            onChange={(event) => admin.setUsername(event.target.value)}
          />
        </label>
        <label>
          <span>初始密码</span>
          <input
            type="password"
            value={admin.password}
            minLength={12}
            maxLength={1024}
            autoComplete="new-password"
            placeholder="至少 12 位"
            onChange={(event) => admin.setPassword(event.target.value)}
          />
        </label>
        <label className="settings-checkbox user-admin-toggle">
          <input
            type="checkbox"
            checked={admin.createAdmin}
            onChange={(event) => admin.setCreateAdmin(event.target.checked)}
          />
          <span>管理员</span>
        </label>
        <button
          className="primary-command"
          type="submit"
          disabled={
            admin.busy || !admin.username.trim() || admin.password.length < 12
          }
        >
          <Plus size={17} />
          创建
        </button>
      </form>

      <div className="settings-scope-note">
        <ShieldCheck size={18} />
        <span>账号只提交任务，无法查看服务端的 Codex、生图渠道或密钥。</span>
      </div>

      <section className="user-list-section">
        <div className="user-section-heading">
          <Users size={19} />
          <h2>本地账号</h2>
          <button
            className="icon-button"
            type="button"
            onClick={admin.loadUsers}
            disabled={admin.busy}
            aria-label="刷新账号"
            title="刷新账号"
          >
            <RefreshCw className={admin.busy ? "spin" : ""} size={17} />
          </button>
        </div>

        <div className="user-table-wrap">
          <table className="user-table">
            <thead>
              <tr>
                <th>账号</th>
                <th>角色</th>
                <th>状态</th>
                <th>API Key</th>
                <th>创建日期</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {pageUsers.map((user) => (
                <tr key={user.id}>
                  <td>
                    <strong>{user.username}</strong>
                    {user.id === currentUserId && <small>当前账号</small>}
                  </td>
                  <td>{user.is_admin ? "管理员" : "用户"}</td>
                  <td>
                    <span
                      className={
                        user.disabled ? "user-disabled" : "user-active"
                      }
                    >
                      {user.disabled ? "已禁用" : "正常"}
                    </span>
                  </td>
                  <td>{user.active_api_key_count}</td>
                  <td>{formatDate(user.created_at)}</td>
                  <td>
                    <div className="user-row-actions">
                      <button
                        className="icon-button"
                        type="button"
                        onClick={() => admin.openKeys(user)}
                        disabled={admin.busy}
                        aria-label={`管理 ${user.username} 的 API Key`}
                        title="管理 API Key"
                      >
                        <KeyRound size={16} />
                      </button>
                      <button
                        className="icon-button"
                        type="button"
                        onClick={() => {
                          admin.setPasswordUser(user);
                          admin.setNewPassword("");
                        }}
                        disabled={admin.busy}
                        aria-label={`重置 ${user.username} 的密码`}
                        title="重置密码"
                      >
                        <RefreshCw size={16} />
                      </button>
                      <button
                        className="icon-button"
                        type="button"
                        onClick={() => admin.toggleDisabled(user)}
                        disabled={admin.busy || user.id === currentUserId}
                        aria-label={`${user.disabled ? "启用" : "禁用"} ${user.username}`}
                        title={user.disabled ? "启用账号" : "禁用账号"}
                      >
                        {user.disabled ? (
                          <Power size={16} />
                        ) : (
                          <PowerOff size={16} />
                        )}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <Pagination
          page={page}
          pageCount={pageCount}
          total={admin.users.length}
          rangeStart={rangeStart}
          rangeEnd={rangeEnd}
          unitLabel="个账号"
          onPage={setPage}
        />
      </section>

      {admin.passwordUser && (
        <form className="user-inline-panel" onSubmit={admin.resetPassword}>
          <div>
            <strong>重置 {admin.passwordUser.username} 的密码</strong>
            <small>保存后该账号的浏览器会话立即失效</small>
          </div>
          <input
            type="password"
            value={admin.newPassword}
            minLength={12}
            maxLength={1024}
            autoComplete="new-password"
            placeholder="至少 12 位"
            onChange={(event) => admin.setNewPassword(event.target.value)}
          />
          <button
            className="primary-command"
            type="submit"
            disabled={admin.busy || admin.newPassword.length < 12}
          >
            <Check size={16} />
            保存
          </button>
          <button
            className="icon-button"
            type="button"
            onClick={() => admin.setPasswordUser(null)}
            aria-label="取消重置"
            title="取消"
          >
            <X size={16} />
          </button>
        </form>
      )}

      {admin.keyUser && (
        <section className="user-key-panel">
          <div className="user-section-heading">
            <KeyRound size={19} />
            <h2>{admin.keyUser.username} 的 API Key</h2>
            <button
              className="primary-command"
              type="button"
              onClick={admin.createKey}
              disabled={admin.busy}
            >
              <Plus size={16} />
              生成独立 Key
            </button>
          </div>
          {admin.createdKey && (
            <div className="created-api-key admin-created-key">
              <span>仅显示一次，请立即保存</span>
              <div>
                <code>{admin.createdKey.key}</code>
                <button
                  className="icon-button"
                  type="button"
                  onClick={() => void copyText(admin.createdKey!.key)}
                  aria-label="复制 API Key"
                  title="复制"
                >
                  <Copy size={16} />
                </button>
              </div>
            </div>
          )}
          <div className="user-key-list">
            {admin.keys.map((key) => (
              <div key={key.id}>
                <span>
                  <strong>{key.name}</strong>
                  <small>{key.key_prefix}...</small>
                </span>
                <small>{key.revoked_at ? "已撤销" : "可用"}</small>
                <button
                  className="icon-button"
                  type="button"
                  onClick={() => admin.revokeKey(key.id)}
                  disabled={admin.busy || Boolean(key.revoked_at)}
                  aria-label={`撤销 ${key.name}`}
                  title="撤销"
                >
                  <Trash2 size={16} />
                </button>
              </div>
            ))}
            {admin.keys.length === 0 && <p>暂无 API Key</p>}
          </div>
        </section>
      )}

      <footer className="user-management-feedback">
        {admin.busy && <LoaderCircle className="spin" size={17} />}
        {admin.error && (
          <span className="settings-error">
            <AlertCircle size={15} />
            {admin.error}
          </span>
        )}
        {admin.success && (
          <span className="settings-success">
            <Check size={15} />
            {admin.success}
          </span>
        )}
      </footer>
    </div>
  );
}
