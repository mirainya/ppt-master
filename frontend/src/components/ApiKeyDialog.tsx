import { type FormEvent } from "react";
import {
  AlertCircle,
  Copy,
  KeyRound,
  LoaderCircle,
  Plus,
  Trash2,
  X,
} from "lucide-react";

import { copyText } from "../lib/clipboard";
import { formatDate } from "../lib/jobDisplay";
import type { ApiKey, CreatedApiKey } from "../types";

interface ApiKeyDialogProps {
  keys: ApiKey[];
  name: string;
  onName: (value: string) => void;
  created: CreatedApiKey | null;
  busy: boolean;
  error: string;
  onCreate: (event: FormEvent) => void;
  onRevoke: (keyId: string) => void;
  onClose: () => void;
}

/** Modal for the current user's personal API keys (create / copy / revoke). */
export function ApiKeyDialog({
  keys,
  name,
  onName,
  created,
  busy,
  error,
  onCreate,
  onRevoke,
  onClose,
}: ApiKeyDialogProps) {
  return (
    <div className="settings-overlay">
      <section
        className="settings-page"
        role="dialog"
        aria-modal="true"
        aria-labelledby="api-key-title"
      >
        <header className="settings-header">
          <div>
            <div className="auth-mark">
              <KeyRound size={22} />
            </div>
            <h1 id="api-key-title">API 密钥</h1>
          </div>
          <button
            className="icon-button"
            type="button"
            onClick={onClose}
            aria-label="关闭"
            title="关闭"
          >
            <X size={18} />
          </button>
        </header>

        <div className="settings-form">
          <form className="api-key-create" onSubmit={onCreate}>
            <label>
              <span>密钥名称</span>
              <input
                value={name}
                maxLength={100}
                onChange={(event) => onName(event.target.value)}
                aria-label="密钥名称"
              />
            </label>
            <button
              className="primary-command"
              type="submit"
              disabled={busy || !name.trim()}
            >
              <Plus size={16} />
              生成密钥
            </button>
          </form>

          {created && (
            <div className="created-api-key">
              <span>仅显示一次，请立即保存</span>
              <div>
                <code>{created.key}</code>
                <button
                  className="icon-button"
                  type="button"
                  onClick={() => void copyText(created.key)}
                  aria-label="复制 API Key"
                  title="复制"
                >
                  <Copy size={16} />
                </button>
              </div>
            </div>
          )}

          <div className="user-key-list">
            {keys.map((key) => (
              <div key={key.id}>
                <span>
                  <strong>{key.name}</strong>
                  <small>
                    {key.key_prefix}... · {formatDate(key.created_at)}
                  </small>
                </span>
                <small>{key.revoked_at ? "已撤销" : "可用"}</small>
                <button
                  className="icon-button"
                  type="button"
                  onClick={() => onRevoke(key.id)}
                  disabled={busy || Boolean(key.revoked_at)}
                  aria-label={`撤销 ${key.name}`}
                  title="撤销"
                >
                  <Trash2 size={16} />
                </button>
              </div>
            ))}
            {keys.length === 0 && <p>暂无 API Key</p>}
          </div>

          <footer className="user-management-feedback">
            {busy && <LoaderCircle className="spin" size={17} />}
            {error && (
              <span className="settings-error">
                <AlertCircle size={15} />
                {error}
              </span>
            )}
          </footer>
        </div>
      </section>
    </div>
  );
}
