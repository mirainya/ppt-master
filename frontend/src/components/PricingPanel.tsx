import { AlertCircle, Check, Coins, LoaderCircle, Save } from "lucide-react";

import type { usePricing } from "../hooks/usePricing";
import type { Pricing } from "../types";

type PricingHook = ReturnType<typeof usePricing>;

const FIELDS: {
  key: keyof Pricing;
  label: string;
  hint: string;
  step: string;
}[] = [
  {
    key: "price_input_token",
    label: "输入 Token 单价",
    hint: "每个输入 token 扣除的积分",
    step: "0.000001",
  },
  {
    key: "price_output_token",
    label: "输出 Token 单价",
    hint: "每个输出 token 扣除的积分",
    step: "0.000001",
  },
  {
    key: "price_image",
    label: "图片单价",
    hint: "每张生成图片扣除的积分",
    step: "0.01",
  },
  {
    key: "hold_amount",
    label: "每任务预扣",
    hint: "创建/续轮时冻结的积分额度",
    step: "0.1",
  },
];

/** Layer-1 pricing editor: per-token / per-image rates and the per-job hold. */
export function PricingPanel({ pricing }: { pricing: PricingHook }) {
  if (pricing.busy && !pricing.pricing) {
    return (
      <div className="settings-loading">
        <LoaderCircle className="spin" size={24} />
      </div>
    );
  }
  if (!pricing.pricing) {
    return (
      <div className="admin-panel-body">
        <div className="admin-panel-inner">
          <span className="settings-error">
            <AlertCircle size={15} />
            {pricing.error || "计价配置不可用"}
          </span>
        </div>
      </div>
    );
  }

  const value = pricing.pricing;

  return (
    <form className="admin-panel-body" onSubmit={pricing.save}>
      <div className="settings-scope-note">
        <Coins size={18} />
        <span>
          全局计价对所有组织生效，按 token
          与图片计量，创建任务时先冻结预扣额度。
        </span>
      </div>

      <div className="admin-panel-inner">
        <div className="pricing-grid">
          {FIELDS.map((field) => (
            <label key={field.key} className="pricing-field">
              <span className="pricing-label">{field.label}</span>
              <input
                type="number"
                min="0"
                step={field.step}
                value={value[field.key]}
                onChange={(event) =>
                  pricing.setField(field.key, Number(event.target.value))
                }
              />
              <small>{field.hint}</small>
            </label>
          ))}
        </div>
      </div>

      <footer className="settings-actions">
        {pricing.error && (
          <span className="settings-error">
            <AlertCircle size={15} />
            {pricing.error}
          </span>
        )}
        {pricing.saved && (
          <span className="settings-success">
            <Check size={15} />
            计价已保存
          </span>
        )}
        <button
          className="primary-command"
          type="submit"
          disabled={pricing.busy}
        >
          {pricing.busy ? (
            <LoaderCircle className="spin" size={17} />
          ) : (
            <Save size={17} />
          )}
          <span>保存计价</span>
        </button>
      </footer>
    </form>
  );
}
