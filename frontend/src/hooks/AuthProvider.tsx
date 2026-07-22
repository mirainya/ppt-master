import {
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { ApiClient, ApiError } from "../api";
import type { User } from "../types";
import { AuthContext, type AuthState } from "./authContext";

/** Consume a `?sso_ticket=` / `#sso_ticket=` param once, scrubbing it from the URL. */
function extractOrgTicket(): string | null {
  const url = new URL(window.location.href);
  const fragment = new URLSearchParams(url.hash.slice(1));
  const ticket =
    fragment.get("sso_ticket") || url.searchParams.get("sso_ticket");
  if (ticket) {
    fragment.delete("sso_ticket");
    url.searchParams.delete("sso_ticket");
    url.hash = fragment.toString();
    window.history.replaceState(
      {},
      "",
      `${url.pathname}${url.search}${url.hash}`,
    );
  }
  return ticket;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const apiClient = useMemo(() => new ApiClient(), []);
  const [user, setUser] = useState<User | null>(null);
  const [checking, setChecking] = useState(true);
  const [authError, setAuthError] = useState("");
  const probeRef = useRef<Promise<User> | null>(null);
  const ticketRef = useRef<string | null>(null);
  if (ticketRef.current === null) {
    ticketRef.current = extractOrgTicket() ?? "";
  }

  useEffect(() => {
    let active = true;
    const ticket = ticketRef.current || null;
    if (!probeRef.current) {
      probeRef.current = ticket
        ? apiClient.consumeOrgTicket(ticket)
        : apiClient.me();
    }
    probeRef.current
      .then((probed) => {
        if (active) setUser(probed);
      })
      .catch((reason: unknown) => {
        if (!active) return;
        if (!ticket && reason instanceof ApiError && reason.status === 401) {
          return; // Anonymous visitor — expected, show the login page.
        }
        setAuthError(ticket ? "工作台登录链接无效或已过期" : "认证服务不可用");
      })
      .finally(() => {
        if (active) setChecking(false);
      });
    return () => {
      active = false;
    };
  }, [apiClient]);

  const login = useCallback(
    async (username: string, password: string) => {
      const authed = await apiClient.login(username, password);
      setAuthError("");
      setUser(authed);
    },
    [apiClient],
  );

  const logout = useCallback(async () => {
    try {
      await apiClient.logout();
    } finally {
      setUser(null);
    }
  }, [apiClient]);

  const value: AuthState = {
    user,
    checking,
    authError,
    apiClient,
    login,
    logout,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
