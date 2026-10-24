/**
 * Upcoming appointments with their lifecycle states (R17.1).
 *
 * Reads GET /patient/appointments and renders each appointment with its
 * service type, slot window, and current state. A `reloadKey` prop lets the
 * parent refresh the list after a successful booking.
 */

import { useCallback } from "react";
import type { Appointment, AppointmentState } from "../../api/patient";
import { listAppointments } from "../../api/patient";
import { Card, ErrorNote, Note, Pill, formatDateTime } from "./shared";
import type { Tone } from "./shared";
import { useAsyncData } from "./shared";

const STATE_TONE: Record<AppointmentState, Tone> = {
  booked: "info",
  accepted: "success",
  completed: "neutral",
  cancelled: "danger",
};

function AppointmentRow({ appointment }: { appointment: Appointment }) {
  return (
    <li style={{ padding: "0.5rem 0", borderBottom: "1px solid #eee" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <strong>{appointment.service_type || "Visit"}</strong>
        <Pill
          label={appointment.state}
          tone={STATE_TONE[appointment.state] ?? "neutral"}
        />
      </div>
      <div style={{ color: "#555", fontSize: "0.9rem" }}>
        {formatDateTime(appointment.slot_start)} —{" "}
        {formatDateTime(appointment.slot_end)}
      </div>
    </li>
  );
}

export function AppointmentsSection({ reloadKey }: { reloadKey: number }) {
  const loader = useCallback(() => listAppointments(), []);
  const { data, loading, error } = useAsyncData(loader, [reloadKey]);

  return (
    <Card title="Upcoming appointments">
      {loading && <Note>Loading appointments…</Note>}
      {error && <ErrorNote>{error}</ErrorNote>}
      {!loading && !error && (data?.length ?? 0) === 0 && (
        <Note>No appointments yet. Request a match below to book a visit.</Note>
      )}
      {!loading && !error && data && data.length > 0 && (
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {data.map((a) => (
            <AppointmentRow key={a.id} appointment={a} />
          ))}
        </ul>
      )}
    </Card>
  );
}
