import { Navigate, Route, Routes } from "react-router-dom";

import { RequireAuth } from "./components/RequireAuth";
import { useTheme } from "./hooks/useTheme";
import { AdminPage } from "./pages/AdminPage";
import { LoginPage } from "./pages/LoginPage";
import { WorkspacePage } from "./pages/WorkspacePage";

/**
 * Route shell only. The old 1806-line monolith is now split across:
 *   /login  → LoginPage        (account password + SSO ticket)
 *   /       → WorkspacePage    (chat / preview workspace)
 *   /admin  → AdminPage        (admin-only console)
 * Theme is owned here so every route shares one source of truth.
 */
export default function App() {
  const { theme, setTheme } = useTheme();

  return (
    <Routes>
      <Route
        path="/login"
        element={<LoginPage theme={theme} onTheme={setTheme} />}
      />
      <Route
        path="/"
        element={
          <RequireAuth>
            <WorkspacePage theme={theme} onTheme={setTheme} />
          </RequireAuth>
        }
      />
      <Route
        path="/admin"
        element={
          <RequireAuth adminOnly>
            <AdminPage theme={theme} onTheme={setTheme} />
          </RequireAuth>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
