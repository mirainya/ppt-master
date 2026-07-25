import {
  BarChart3,
  Copy,
  KeyRound,
  Plus,
  RefreshCw,
  Save,
  Send,
  Trash2,
  Wallet,
  Webhook,
} from "lucide-react";

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

      {/* Usage callback */}
      <div className="org-detail-card org-usage-card">
        <div className="user-section-heading">
          <Webhook size={17} />
          <h3>用量回调</h3>
          <small className="org-webhook-state">
            {orgs.webhook
              ? orgs.webhook.enabled
                ? "已启用"
                : "已停用"
              : "未配置"}
          </small>
        </div>
        <div className="org-webhook-form">
          <input
            type="url"
            value={orgs.webhookUrl}
            placeholder="https://partner.example.com/webhook/usage"
            onChange={(event) => orgs.setWebhookUrl(event.target.value)}
          />
          <label className="org-webhook-toggle">
            <input
              type="checkbox"
              checked={orgs.webhookEnabled}
              onChange={(event) => orgs.setWebhookEnabled(event.target.checked)}
            />
            启用
          </label>
          <button
            className="primary-command"
            type="button"
            onClick={() => void orgs.saveWebhook(false)}
            disabled={orgs.busy || !orgs.webhookUrl.trim()}
          >
            <Save size={16} />
            保存
          </button>
          <button
            type="button"
            onClick={() => void orgs.saveWebhook(true)}
            disabled={orgs.busy || !orgs.webhookUrl.trim()}
            title="生成新的签名密钥，旧密钥立即失效"
          >
            <RefreshCw size={16} />
            轮换密钥
          </button>
          <button
            type="button"
            onClick={() => void orgs.testWebhook()}
            disabled={orgs.busy || !orgs.webhook}
            title="发送一条 webhook.test 事件，不写入投递表"
          >
            <Send size={16} />
            测试
          </button>
        </div>
        <p className="org-webhook-hint">
          必须是公网 HTTPS 地址；解析到环回、私有或链路本地地址会被拒绝，且不跟随重定向。
        </p>
        {orgs.webhookSecret && (
          <div className="created-api-key">
            <span>签名密钥仅显示一次，请立即交付给企业</span>
            <div>
              <code>{orgs.webhookSecret}</code>
              <button
                className="icon-button"
                type="button"
                onClick={() => void copyText(orgs.webhookSecret)}
                aria-label="复制签名密钥"
                title="复制"
              >
                <Copy size={16} />
              </button>
            </div>
          </div>
        )}
        {orgs.webhookTest && (
          <p
            className={
              orgs.webhookTest.delivered
                ? "org-webhook-result ok"
                : "org-webhook-result bad"
            }
          >
            {orgs.webhookTest.delivered
              ? `投递成功（HTTP ${orgs.webhookTest.response_status}）`
              : `投递失败：${orgs.webhookTest.error ?? `HTTP ${orgs.webhookTest.response_status}`}`}
          </p>
        )}
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
