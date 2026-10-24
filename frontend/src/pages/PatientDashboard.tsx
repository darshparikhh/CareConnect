/**
 * Patient dashboard (task 19.1).
 *
 * Composes the four patient views over the role-gated /patient routes:
 *  - upcoming appointments with lifecycle states (R17.1),
 *  - the request-match-and-book flow with the consent gate surfaced (R17.2),
 *  - approved-only clinical decisions, referrals, and medications (R17.3, R13.1),
 *  - ranked Recommended_Doctors with proximity, specialty, and insurance-
 *    compatibility status (R17.4).
 *
 * All safety gates (authorization, consent, approval, verified-insurance) are
 * enforced by the backend services; this page only renders their results. A
 * local reload counter refreshes the appointments list after a booking.
 */

import { useState } from "react";
import { DashboardShell } from "../components/DashboardShell";
import { AppointmentsSection } from "../components/patient/AppointmentsSection";
import { MatchAndBookSection } from "../components/patient/MatchAndBookSection";
import { ApprovedCareSection } from "../components/patient/ApprovedCareSection";
import { RecommendationsSection } from "../components/patient/RecommendationsSection";
import { NearbyHospitalsSection } from "../components/patient/NearbyHospitalsSection";

export function PatientDashboard() {
  // Bumped after a confirmed booking so the appointments list re-fetches.
  const [reloadKey, setReloadKey] = useState(0);

  return (
    <DashboardShell role="patient">
      <div style={{ maxWidth: 720, margin: "0 auto" }}>
        <AppointmentsSection reloadKey={reloadKey} />
        <MatchAndBookSection onBooked={() => setReloadKey((k) => k + 1)} />
        <ApprovedCareSection />
        <RecommendationsSection />
        <NearbyHospitalsSection />
      </div>
    </DashboardShell>
  );
}
