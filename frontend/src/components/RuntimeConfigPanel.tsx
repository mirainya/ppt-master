import {
  AlertCircle,
  Check,
  Eye,
  EyeOff,
  LoaderCircle,
  Save,
  Users,
} from "lucide-react";
import { useState } from "react";

import type { useRuntimeConfig } from "../hooks/useRuntimeConfig";

type RuntimeConfigHook = ReturnType<typeof useRuntimeConfig>;

interface SecretFieldProps {
  label: string;
  configured: boolean;
  draft: string;
  onDraft: (value: string) => void;
  cleared: boolean;
  onClear: (value: boolean) => void;
}

function SecretField({
  label,
  configured,
  draft,
  onDraft,
  cleared,
  onClear,
}: SecretFieldProps) {
  const [shown, setShown] = useState(false);
  return (
    <label className="settings-secret-field">
      <span>{label}</span>
      <div>
        <input
          type={shown ? "text" : "password"}
          value={draft}
          disabled={cleared}
          placeholder={configured ? "留空保持当前密钥" : "输入 API 密钥"}
          autoComplete="new-password"
          onChange={(event) => onDraft(event.target.value)}
        />
        <button
          type="button"
          className="icon-button"
          onClick={() => setShown((value) => !value)}
          aria-label={shown ? "隐藏密钥" : "显示密钥"}
          title={shown ? "隐藏密钥" : "显示密钥"}
        >
          {shown ? <EyeOff size={16} /> : <Eye size={16} />}
        </button>
      </div>
      {configured && (
        <label className="settings-checkbox">
          <input
            type="checkbox"
            checked={cleared}
            onChange={(event) => onClear(event.target.checked)}
          />
          <span>清除当前密钥</span>
        </label>
      )}
    </label>
  );
}

/** Service-wide runtime config panel: Codex + image provider endpoints/keys. */
export function RuntimeConfigPanel({ rc }: { rc: RuntimeConfigHook }) {
  if (rc.busy && !rc.config) {
    return (
      <div className="settings-loading">
        <LoaderCircle className="spin" size={24} />
      </div>
    );
  }
  if (!rc.config) {
    return (
      <div className="admin-panel-body">
        <span className="settings-error">
          <AlertCircle size={15} />
          {rc.error || "配置不可用"}
        </span>
      </div>
    );
  }

  const config = rc.config;

  return (
    <form className="settings-form admin-panel-body" onSubmit={rc.save}>
      <div className="settings-scope-note">
        <Users size={18} />
        <span>服务端统一使用此配置，普通账号不可查看渠道或密钥。</span>
      </div>

      <section className="settings-section">
        <div className="settings-section-title">
          <h2>Codex</h2>
          <span>
            {config.codex_api_key_configured ? "密钥已配置" : "密钥未配置"}
          </span>
        </div>
        <div className="settings-fields">
          <label>
            <span>中转地址</span>
            <input
              type="url"
              value={config.codex_base_url}
              placeholder="https://example.com/v1"
              onChange={(event) =>
                rc.setConfig({ ...config, codex_base_url: event.target.value })
              }
            />
          </label>
          <label>
            <span>模型</span>
            <input
              value={config.codex_model}
              placeholder="gpt-5"
              onChange={(event) =>
                rc.setConfig({ ...config, codex_model: event.target.value })
              }
            />
          </label>
          <SecretField
            label="API 密钥"
            configured={config.codex_api_key_configured}
            draft={rc.codexKeyDraft}
            onDraft={rc.setCodexKeyDraft}
            cleared={rc.clearCodexKey}
            onClear={rc.setClearCodexKey}
          />
        </div>
      </section>

      <section className="settings-section">
        <div className="settings-section-title">
          <h2>生图渠道</h2>
          <span>
            {config.image_api_key_configured ? "密钥已配置" : "密钥未配置"}
          </span>
        </div>
        <div className="settings-fields">
          <label>
            <span>中转地址</span>
            <input
              type="url"
              value={config.image_base_url}
              placeholder="https://example.com/v1"
              onChange={(event) =>
                rc.setConfig({ ...config, image_base_url: event.target.value })
              }
            />
          </label>
          <label>
            <span>模型</span>
            <input
              value={config.image_model}
              placeholder="gpt-image-2"
              onChange={(event) =>
                rc.setConfig({ ...config, image_model: event.target.value })
              }
            />
          </label>
          <label>
            <span>尺寸</span>
            <input
              value={config.image_size}
              placeholder="2048x1536"
              onChange={(event) =>
                rc.setConfig({ ...config, image_size: event.target.value })
              }
            />
          </label>
          <SecretField
            label="API 密钥"
            configured={config.image_api_key_configured}
            draft={rc.imageKeyDraft}
            onDraft={rc.setImageKeyDraft}
            cleared={rc.clearImageKey}
            onClear={rc.setClearImageKey}
          />
        </div>
      </section>

      <footer className="settings-actions">
        {rc.error && (
          <span className="settings-error">
            <AlertCircle size={15} />
            {rc.error}
          </span>
        )}
        {rc.saved && (
          <span className="settings-success">
            <Check size={15} />
            配置已保存
          </span>
        )}
        <button className="primary-command" type="submit" disabled={rc.busy}>
          {rc.busy ? (
            <LoaderCircle className="spin" size={17} />
          ) : (
            <Save size={17} />
          )}
          <span>保存配置</span>
        </button>
      </footer>
    </form>
  );
}
