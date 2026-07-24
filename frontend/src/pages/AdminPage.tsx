import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowLeft,
  Building2,
  Coins,
  KeyRound,
  ListChecks,
  Presentation,
  Settings,
  Users,
} from "lucide-react";

import { AccountsPanel } from "../components/AccountsPanel";
import { JobsPanel } from "../components/JobsPanel";
import { OrgsPanel } from "../components/OrgsPanel";
import { PricingPanel } from "../components/PricingPanel";
import { RuntimeConfigPanel } from "../components/RuntimeConfigPanel";
import { ThemeSwitcher } from "../components/ThemeSwitcher";
import { useAdminJobs } from "../hooks/useAdminJobs";
import { useAdminUsers } from "../hooks/useAdminUsers";
import { useAuth } from "../hooks/authContext";
import { useOrgs } from "../hooks/useOrgs";
import { usePricing } from "../hooks/usePricing";
import { useRuntimeConfig } from "../hooks/useRuntimeConfig";
import type { AppTheme } from "../types";

interface AdminPageProps {
  theme: AppTheme;
  onTheme: (theme: AppTheme) => void;
}

type AdminTab = "accounts" | "orgs" | "billing" | "runtime" | "jobs";

const TABS: { key: AdminTab; label: string; icon: typeof Users }[] = [
  { key: "accounts", label: "账号管理", icon: Users },
  { key: "orgs", label: "组织与计量", icon: Building2 },
  { key: "billing", label: "计价配置", icon: Coins },
  { key: "runtime", label: "运行配置", icon: Settings },
  { key: "jobs", label: "任务管理", icon: ListChecks },
];

/**
 * Standalone admin console at /admin — fully separated from the user workspace.
 * Guarded by <RequireAuth adminOnly> upstream, so we can assume an admin user.
 */
export function AdminPage({ theme, onTheme }: AdminPageProps) {
  const { user, apiClient } = useAuth();
  const navigate = useNavigate();
  const [tab, setTab] = useState<AdminTab>("accounts");
  const admin = useAdminUsers(apiClient, user?.id ?? "");
  const rc = useRuntimeConfig(apiClient);
  const pricing = usePricing(apiClient);
  const orgs = useOrgs(apiClient);
  const adminJobs = useAdminJobs(apiClient);

  useEffect(() => {
    if (tab === "runtime" && !rc.config) void rc.load();
    if (tab === "billing" && !pricing.pricing) void pricing.load();
  }, [tab, rc, pricing]);

  return (
    <div className="admin-shell">
      <aside className="admin-rail">
        <div className="brand-row">
          <div className="brand-mark">
            <Presentation size={18} />
          </div>
          <strong>管理控制台</strong>
        </div>

        <nav className="admin-nav" aria-label="管理导航">
          {TABS.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.key}
                className={`admin-nav-item ${tab === item.key ? "active" : ""}`}
                onClick={() => setTab(item.key)}
              >
                <Icon size={17} />
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>

        <div className="admin-rail-footer">
          <ThemeSwitcher theme={theme} onChange={onTheme} />
          <button
            className="secondary-command admin-back"
            onClick={() => navigate("/")}
          >
            <ArrowLeft size={16} />
            <span>返回工作台</span>
          </button>
        </div>
      </aside>

      <main className="admin-main">
        <header className="admin-header">
          <div className="admin-header-title">
            {(() => {
              const active = TABS.find((item) => item.key === tab) ?? TABS[0];
              const Icon = active.icon;
              return (
                <>
                  <Icon size={20} />
                  <h1>{active.label}</h1>
                </>
              );
            })()}
          </div>
          <div className="admin-header-account">
            <KeyRound size={15} />
            <span>{user?.username}</span>
          </div>
        </header>

        <div className="admin-content">
          {tab === "accounts" && (
            <AccountsPanel admin={admin} currentUserId={user?.id ?? ""} />
          )}
          {tab === "orgs" && <OrgsPanel orgs={orgs} />}
          {tab === "billing" && <PricingPanel pricing={pricing} />}
          {tab === "runtime" && <RuntimeConfigPanel rc={rc} />}
          {tab === "jobs" && <JobsPanel jobs={adminJobs} />}
        </div>
      </main>
    </div>
  );
}
