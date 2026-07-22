import {
  AlertCircle,
  Building2,
  Check,
  LoaderCircle,
  Plus,
  RefreshCw,
} from "lucide-react";

import { OrgDetail } from "./OrgDetail";
import { formatDate } from "../lib/jobDisplay";
import type { useOrgs } from "../hooks/useOrgs";

type OrgsHook = ReturnType<typeof useOrgs>;

// Mirror the backend OrgCreate.slug constraint so an invalid slug is caught
// client-side instead of surfacing as an opaque 422.
const SLUG_RE = /^[a-z0-9][a-z0-9-]*$/;

/** Admin organization management: create, list, and drill into one org. */
export function OrgsPanel({ orgs }: { orgs: OrgsHook }) {
  const slugValue = orgs.slug.trim();
  const slugInvalid = slugValue.length > 0 && !SLUG_RE.test(slugValue);
  const canCreate =
    !orgs.busy && orgs.name.trim().length > 0 && SLUG_RE.test(slugValue);

  return (
    <div className="admin-panel-body">
      <form
        className="user-create-form org-create-form"
        onSubmit={orgs.createOrg}
      >
        <div className="user-section-heading">
          <Building2 size={19} />
          <h2>创建组织</h2>
        </div>
        <label>
          <span>组织名称</span>
          <input
            value={orgs.name}
            maxLength={200}
            onChange={(event) => orgs.setName(event.target.value)}
          />
        </label>
        <label>
          <span>标识 (slug)</span>
          <input
            value={orgs.slug}
            maxLength={100}
            placeholder="a-z 0-9 -"
            aria-invalid={slugInvalid}
            onChange={(event) => orgs.setSlug(event.target.value)}
          />
          {slugInvalid && (
            <small className="field-error">
              只能用小写字母、数字和连字符，且以字母或数字开头
            </small>
          )}
        </label>
        <button className="primary-command" type="submit" disabled={!canCreate}>
          <Plus size={17} />
          创建
        </button>
      </form>

      <section className="user-list-section">
        <div className="user-section-heading">
          <Building2 size={19} />
          <h2>组织列表</h2>
          <button
            className="icon-button"
            type="button"
            onClick={orgs.load}
            disabled={orgs.busy}
            aria-label="刷新组织"
            title="刷新组织"
          >
            <RefreshCw className={orgs.busy ? "spin" : ""} size={17} />
          </button>
        </div>

        <div className="user-table-wrap">
          <table className="user-table">
            <thead>
              <tr>
                <th>组织</th>
                <th>标识</th>
                <th>余额</th>
                <th>日限额</th>
                <th>并发</th>
                <th>创建日期</th>
              </tr>
            </thead>
            <tbody>
              {orgs.orgs.map((org) => (
                <tr
                  key={org.id}
                  className={`org-row ${orgs.selected?.id === org.id ? "selected" : ""}`}
                  onClick={() => orgs.openOrg(org)}
                >
                  <td>
                    <strong>{org.name}</strong>
                  </td>
                  <td>{org.slug}</td>
                  <td>
                    <span className="org-balance">{org.credit_balance}</span>
                  </td>
                  <td>{org.daily_job_limit}</td>
                  <td>{org.max_active_jobs}</td>
                  <td>{formatDate(org.created_at)}</td>
                </tr>
              ))}
              {orgs.orgs.length === 0 && !orgs.busy && (
                <tr>
                  <td colSpan={6} className="table-empty">
                    暂无组织
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {orgs.selected && <OrgDetail orgs={orgs} />}

      <footer className="user-management-feedback">
        {orgs.busy && <LoaderCircle className="spin" size={17} />}
        {orgs.error && (
          <span className="settings-error">
            <AlertCircle size={15} />
            {orgs.error}
          </span>
        )}
        {orgs.success && (
          <span className="settings-success">
            <Check size={15} />
            {orgs.success}
          </span>
        )}
      </footer>
    </div>
  );
}
