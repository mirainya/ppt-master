import { Navigate, useLocation } from "react-router-dom";

import { useAuth } from "../hooks/authContext";
import { LoadingScreen } from "./LoadingScreen";

interface RequireAuthProps {
  children: React.ReactNode;
  /** When true, only administrators may enter; others bounce to the workspace. */
  adminOnly?: boolean;
}

/** Route guard: waits for the session probe, then gates by auth / admin role. */
export function RequireAuth({ children, adminOnly = false }: RequireAuthProps) {
  const { user, checking } = useAuth();
  const location = useLocation();

  if (checking) return <LoadingScreen />;
  if (!user) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }
  if (adminOnly && !user.is_admin) {
    return <Navigate to="/" replace />;
  }
  return <>{children}</>;
}
