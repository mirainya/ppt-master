import { createContext, useContext } from "react";

import type { ApiClient } from "../api";
import type { User } from "../types";

export interface AuthState {
  /** null while the initial session probe is still running. */
  user: User | null;
  /** True until the first `me()` / ticket probe settles. */
  checking: boolean;
  /** Set when the SSO ticket flow or session probe fails hard. */
  authError: string;
  /** Shared singleton client; only meaningful once `user` is present. */
  apiClient: ApiClient;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

export const AuthContext = createContext<AuthState | null>(null);

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth 必须在 <AuthProvider> 内部使用");
  }
  return context;
}
