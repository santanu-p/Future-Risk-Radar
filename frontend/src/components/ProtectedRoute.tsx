/** Protected route wrapper — redirects to /login when not authenticated. */

import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuthStore } from "../store/authStore";

export default function ProtectedRoute() {
  const { isAuthenticated, isExpired, logout } = useAuthStore();
  const location = useLocation();

  // If token has expired, force logout
  if (isAuthenticated && isExpired()) {
    logout();
  }

  if (!isAuthenticated) {
    // Preserve the intended destination for redirect after login
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  return <Outlet />;
}
