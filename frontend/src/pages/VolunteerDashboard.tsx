/**
 * Volunteer dashboard (R18).
 *
 * Composes the volunteer-facing views on top of the shared DashboardShell:
 *  - assigned appointments with their lifecycle states, plus accept/decline
 *    and per-appointment visit detail + data entry (R18.1, R18.3);
 *  - each visit detail shows only the Service_Types the Volunteer is
 *    authorized to perform (R18.4);
 *  - an interface to set and remove availability slots, surfacing the
 *    slot-has-appointment conflict (R18.2).
 *
 * All data flows through the volunteer API module (src/api/volunteer.ts),
 * which calls the Bearer-gated `/volunteer` routes.
 */

import { DashboardShell } from "../components/DashboardShell";
import { AssignedAppointments } from "../components/volunteer/AssignedAppointments";
import { AvailabilityManager } from "../components/volunteer/AvailabilityManager";

export function VolunteerDashboard() {
  return (
    <DashboardShell role="volunteer">
      <AssignedAppointments />
      <AvailabilityManager />
    </DashboardShell>
  );
}
