/**
 * Application routes.
 *
 * Public:
 *   /sign-in            → sign-in screen
 *
 * Role-scoped (guarded by RequireRole so only the matching role can view):
 *   /patient            → Patient dashboard
 *   /volunteer          → Volunteer dashboard
 *   /clinician          → Clinician dashboard
 *
 * The index route redirects to the signed-in user's dashboard, or to /sign-in
 * when unauthenticated (R4.6). Unknown paths fall back to the same index logic.
 */

import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import { dashboardPathFor, RequireRole } from "./auth/RequireRole";
import { SignInPage } from "./pages/SignInPage";
import { PatientDashboard } from "./pages/PatientDashboard";
import { VolunteerDashboard } from "./pages/VolunteerDashboard";
import { ClinicianDashboard } from "./pages/ClinicianDashboard";

/** Redirect the root path to the right place based on auth state. */
function RootRedirect() {
  const { session, loading } = useAuth();
  if (loading) {
    return <div role="status">Loading…</div>;
  }
  return <Navigate to={session ? dashboardPathFor(session.role) : "/sign-in"} replace />;
}

export function App() {
  return (
    <Routes>
      <Route path="/sign-in" element={<SignInPage />} />

      <Route element={<RequireRole role="patient" />}>
        <Route path="/patient" element={<PatientDashboard />} />
      </Route>

      <Route element={<RequireRole role="volunteer" />}>
        <Route path="/volunteer" element={<VolunteerDashboard />} />
      </Route>

      <Route element={<RequireRole role="clinician" />}>
        <Route path="/clinician" element={<ClinicianDashboard />} />
      </Route>

      <Route path="/" element={<RootRedirect />} />
      <Route path="*" element={<RootRedirect />} />
    </Routes>
  );
}
