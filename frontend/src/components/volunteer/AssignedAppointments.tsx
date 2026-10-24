/**
 * Assigned appointments with lifecycle states (R18.1, R18.3).
 *
 * Lists the Volunteer's assigned appointments and their lifecycle states
 * (R18.1). A `booked` appointment can be accepted (booked -> accepted, R8.6)
 * or declined (booked -> cancelled, R8.7); an invalid transition is surfaced
 * inline. Each appointment can be expanded to open its visit detail — which
 * shows only the Volunteer's authorized services (R18.4) — and submit a
 * questionnaire or test result through the Visit_Service (R18.3).
 */

import { useCallback, useEffect, useState } from "react";
import {
  acceptAppointment,
  declineAppointment,
  listAppointments,
  type VolunteerAppointment,
} from "../../api/volunteer";
import { describeError, formatDateTime, stateLabel, styles } from "./shared";
import { VisitDetailPanel } from "./VisitDetailPanel";

export function AssignedAppointments() {
  const [appointments, setAppointments] = useState<VolunteerAppointment[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [actionError, setActionError] = useState<Record<number, string>>({});
  const [actingId, setActingId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      setAppointments(await listAppointments());
    } catch (err) {
      setLoadError(describeError(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const clearActionError = (id: number) =>
    setActionError((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });

  const runAction = async (
    appointment: VolunteerAppointment,
    action: (id: number) => Promise<VolunteerAppointment>,
  ) => {
    setActingId(appointment.id);
    clearActionError(appointment.id);
    try {
      const updated = await action(appointment.id);
      setAppointments((prev) =>
        prev.map((a) => (a.id === updated.id ? updated : a)),
      );
    } catch (err) {
      setActionError((prev) => ({
        ...prev,
        [appointment.id]: describeError(err),
      }));
    } finally {
      setActingId(null);
    }
  };

  return (
    <section style={styles.section} aria-labelledby="appointments-heading">
      <h2 id="appointments-heading">Assigned appointments</h2>

      {loading && <p style={styles.muted}>Loading appointments…</p>}
      {loadError && (
        <p role="alert" style={styles.error}>
          {loadError}
        </p>
      )}
      {!loading && !loadError && appointments.length === 0 && (
        <p style={styles.muted}>No assigned appointments.</p>
      )}

      {appointments.map((appointment) => {
        const expanded = expandedId === appointment.id;
        const isBooked = appointment.state === "booked";
        const acting = actingId === appointment.id;
        return (
          <div key={appointment.id} style={styles.card}>
            <div style={styles.cardHeader}>
              <div>
                <div>
                  <strong>{appointment.service_type || "Service"}</strong>{" "}
                  <span style={styles.muted}>
                    (patient #{appointment.patient_id})
                  </span>
                </div>
                <div style={styles.muted}>
                  {formatDateTime(appointment.slot_start)} –{" "}
                  {formatDateTime(appointment.slot_end)}
                </div>
                <span style={styles.badge}>{stateLabel(appointment.state)}</span>
                {appointment.queued_for_review && (
                  <span style={{ ...styles.badge, marginLeft: "0.4rem" }}>
                    Queued for review
                  </span>
                )}
                {appointment.reviewed && (
                  <span style={{ ...styles.badge, marginLeft: "0.4rem" }}>
                    Reviewed
                  </span>
                )}
              </div>
              <div style={styles.row}>
                {isBooked && (
                  <>
                    <button
                      type="button"
                      style={styles.primaryButton}
                      disabled={acting}
                      onClick={() => void runAction(appointment, acceptAppointment)}
                    >
                      {acting ? "Working…" : "Accept"}
                    </button>
                    <button
                      type="button"
                      style={styles.button}
                      disabled={acting}
                      onClick={() => void runAction(appointment, declineAppointment)}
                    >
                      Decline
                    </button>
                  </>
                )}
                <button
                  type="button"
                  style={styles.button}
                  onClick={() =>
                    setExpandedId(expanded ? null : appointment.id)
                  }
                  aria-expanded={expanded}
                >
                  {expanded ? "Hide visit" : "Open visit"}
                </button>
              </div>
            </div>

            {actionError[appointment.id] && (
              <p role="alert" style={styles.error}>
                {actionError[appointment.id]}
              </p>
            )}

            {expanded && (
              <div style={{ marginTop: "0.75rem" }}>
                <VisitDetailPanel
                  appointmentId={appointment.id}
                  onSubmitted={() => void load()}
                />
              </div>
            )}
          </div>
        );
      })}
    </section>
  );
}
