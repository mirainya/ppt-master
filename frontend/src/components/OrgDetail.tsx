import { BarChart3, Copy, KeyRound, Plus, Trash2, Wallet } from "lucide-react";

import { copyText } from "../lib/clipboard";
import type { useOrgs } from "../hooks/useOrgs";

type OrgsHook = ReturnType<typeof useOrgs>;

/** Drill-down for one selected org: credit top-up, org keys, usage report. */
export function OrgDetail({ orgs }: { orgs: OrgsHook }) {
  const org = orgs.selected;
  if (!org) return null;

  return (
    <section className="org-detail">
      <header className="org-detail-head">
        <div>
          <strong>{org.name}</strong>
          <small>{org.slug}</small>
        </div>
        <div className="org-detail-balance">
          <Wallet size={16} />
          <span>余额 {org.credit_balance}</span>
        </div>
      </header>

      <div className="org-detail-grid">
        {/* Top-up */}
        <div className="org-detail-card">
          <div className="user-section-heading">
            <Wallet size={17} />
            <h3>充值积分</h3>
          </div>
          <form className="org-topup-form" onSubmit={orgs.topup}>
            <input
              type="number"
              min="0"
              step="0.01"
              value={orgs.topupAmount}
              placeholder="充值金额"
              onChange={(event) => orgs.setTopupAmount(event.target.value)}
            />
            <button
              className="primary-command"
              type="submit"
              disabled={orgs.busy || !(Number(orgs.topupAmount) > 0)}
            >
              <Plus size={16} />
              充值
            </button>
          </form>
        </div>

        {/* Org keys */}
        <div className="org-detail-card">
          <div className="user-section-heading">
            <KeyRound size={17} />
            <h3>组织密钥</h3>
            <button
              className="primary-command"
              type="button"
              onClick={orgs.createKey}
              disabled={orgs.busy}
            >
              <Plus size={16} />
              生成
            </button>
          </div>
          {orgs.createdKey && (
            <div className="created-api-key">
              <span>仅显示一次，请立即保存</span>
              <div>
                <code>{orgs.createdKey.key}</code>
                <button
                  className="icon-button"
                  type="button"
                  onClick={() => void copyText(orgs.createdKey!.key)}
                  aria-label="复制组织密钥"
                  title="复制"
                >
                  <Copy size={16} />
                </button>
              </div>
            </div>
          )}
          <div className="user-key-list">
            {orgs.keys.map((key) => (
              <div key={key.id}>
                <span>
                  <strong>{key.name}</strong>
                  <small>{key.key_prefix}...</small>
                </span>
                <small>{key.revoked_at ? "已撤销" : "可用"}</small>
                <button
                  className="icon-button"
                  type="button"
                  onClick={() => orgs.revokeKey(key.id)}
                  disabled={orgs.busy || Boolean(key.revoked_at)}
                  aria-label={`撤销 ${key.name}`}
                  title="撤销"
                >
                  <Trash2 size={16} />
                </button>
              </div>
            ))}
            {orgs.keys.length === 0 && <p>暂无组织密钥</p>}
          </div>
        </div>
      </div>

      {/* Usage report */}
      <div className="org-detail-card org-usage-card">
        <div className="user-section-heading">
          <BarChart3 size={17} />
          <h3>用量报表（按终端用户）</h3>
        </div>
        <div className="user-table-wrap">
          <table className="user-table usage-table">
            <thead>
              <tr>
                <th>终端用户</th>
                <th>任务</th>
                <th>输入 Token</th>
                <th>输出 Token</th>
                <th>图片</th>
                <th>页数</th>
                <th>计费积分</th>
              </tr>
            </thead>
            <tbody>
              {orgs.usage.map((row) => (
                <tr key={row.end_user_id ?? "service"}>
                  <td>
                    <strong>{row.end_user_id || "（服务账号）"}</strong>
                  </td>
                  <td>{row.jobs}</td>
                  <td>{row.input_tokens.toLocaleString()}</td>
                  <td>{row.output_tokens.toLocaleString()}</td>
                  <td>{row.images}</td>
                  <td>{row.pages}</td>
                  <td>
                    <span className="org-balance">{row.our_charge}</span>
                  </td>
                </tr>
              ))}
              {orgs.usage.length === 0 && (
                <tr>
                  <td colSpan={7} className="table-empty">
                    暂无用量数据
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}
