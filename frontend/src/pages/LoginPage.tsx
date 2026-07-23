import { type FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  AlertCircle,
  Eye,
  EyeOff,
  LoaderCircle,
  LogIn,
  Presentation,
} from "lucide-react";

import { ApiError } from "../api";
import { LoadingScreen } from "../components/LoadingScreen";
import { ThemeSwitcher } from "../components/ThemeSwitcher";
import { useAuth } from "../hooks/authContext";
import type { AppTheme } from "../types";

interface LoginPageProps {
  theme: AppTheme;
  onTheme: (theme: AppTheme) => void;
}

/**
 * Standalone login page (replaces the old console-style modal). Account
 * password sign-in lives here; the SSO ticket flow is handled upstream in
 * AuthProvider — when a ticket lands, the probe logs the user straight in and
 * this page is skipped via the redirect below.
 */
export function LoginPage({ theme, onTheme }: LoginPageProps) {
  const { user, checking, authError, login } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  if (checking) return <LoadingScreen />;
  if (user) {
    navigate("/", { replace: true });
    return <LoadingScreen />;
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const name = username.trim();
    if (!name || !password || busy) return;
    setBusy(true);
    setError("");
    try {
      await login(name, password);
      navigate("/", { replace: true });
    } catch (reason) {
      setError(
        reason instanceof ApiError && reason.status === 401
          ? "用户名或密码错误"
          : "服务暂时不可用，请稍后再试",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-shell">
      <aside className="login-hero" aria-hidden="true">
        <div className="login-hero-glow" />
        <div className="login-hero-content">
          <div className="login-hero-mark">
            <Presentation size={26} />
          </div>
          <h2>叙卷</h2>
          <p>把文档、网页与想法，一句话变成可直接编辑的原生 PPT。</p>
          <ul className="login-hero-points">
            <li>多角色协作生成，真实 PowerPoint 图形</li>
            <li>实时预览每一页，边聊边改</li>
            <li>一键导出 .pptx，交付即用</li>
          </ul>
        </div>
      </aside>

      <main className="login-main">
        <div className="login-topbar">
          <ThemeSwitcher theme={theme} onChange={onTheme} />
        </div>
        <form className="login-card" onSubmit={submit}>
          <div className="login-card-head">
            <div className="auth-mark">
              <LogIn size={22} />
            </div>
            <h1>登录工作台</h1>
            <span>使用管理员分配的账号登录</span>
          </div>

          <label className="login-field">
            <span>用户名</span>
            <input
              value={username}
              maxLength={100}
              autoComplete="username"
              autoFocus
              onChange={(event) => setUsername(event.target.value)}
              aria-label="用户名"
            />
          </label>

          <label className="login-field">
            <span>密码</span>
            <div className="login-secret">
              <input
                type={showPassword ? "text" : "password"}
                value={password}
                maxLength={1024}
                autoComplete="current-password"
                onChange={(event) => setPassword(event.target.value)}
                aria-label="密码"
              />
              <button
                type="button"
                className="icon-button"
                onClick={() => setShowPassword((shown) => !shown)}
                aria-label={showPassword ? "隐藏密码" : "显示密码"}
                title={showPassword ? "隐藏密码" : "显示密码"}
              >
                {showPassword ? <EyeOff size={17} /> : <Eye size={17} />}
              </button>
            </div>
          </label>

          {(error || authError) && (
            <div className="login-error" role="alert">
              <AlertCircle size={15} />
              <span>{error || authError}</span>
            </div>
          )}

          <button
            className="primary-command login-submit"
            type="submit"
            disabled={busy || !username.trim() || !password}
          >
            {busy ? (
              <LoaderCircle className="spin" size={18} />
            ) : (
              <LogIn size={18} />
            )}
            <span>登录</span>
          </button>

          <p className="login-hint">
            组织用户可通过带 SSO 票据的专属链接一键进入，无需在此登录。
          </p>
        </form>
      </main>
    </div>
  );
}
