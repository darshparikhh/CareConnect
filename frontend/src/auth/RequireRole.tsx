/**
 * Route guards for role-scoped access (R4.3-R4.6).
 *
 *  - `RequireAuth` bounces unauthenticated users to /sign-in.
 *  - `RequireRole` additionally enforces that the session's role matches the
 *    route's role, sending a signed-in user who lands on the wrong dashboard
 *    back to their own.
 *
 * Both render their children (via <Outlet/>) only when access is allowed.
 */

import { Navigate, Outlet, useLocation } from "react-router-dom";
import type { Role } from "../api/types";
import { useAuth } from "./AuthContext";

/** Map a role to its dashboard path. */
export function dashboardPathFor(role: Role): string {
  return `/${role}`;
}

/** Gate that requires any authenticated session. */
export function RequireAuth() {
  const { session, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return <div role="status">Loading…</div>;
  }

  if (!session) {
    // Redirect to sign-in, remembering where the user was headed.
    return <Navigate to="/sign-in" replace state={{ from: location }} />;
  }

  return <Outlet />;
}

/** Gate that requires an authenticated session with a specific role. */
export function RequireRole({ role }: { role: Role }) {
  const { session, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return <div role="status">Loading…</div>;
  }

  if (!session) {
    return <Navigate to="/sign-in" replace state={{ from: location }} />;
  }

  if (session.role !== role) {
    // Signed in, wrong dashboard: send them to their own.
    return <Navigate to={dashboardPathFor(session.role)} replace />;
  }

  return <Outlet />;
}
