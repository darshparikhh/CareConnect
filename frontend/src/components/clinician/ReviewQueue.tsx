/**
 * Review queue list (R19.1).
 *
 * Renders the completed-and-queued appointments the clinician may open. Each
 * row is selectable; selecting one drives the findings + decision panels in the
 * parent dashboard. Presentation only — the backend owns which appointments
 * appear in the queue.
 */

import type { ReviewQueueItem } from "../../api/clinician";

const rowBase: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  gap: "0.75rem",
  width: "100%",
  padding: "0.6rem 0.75rem",
  border: "1px solid #d0d7de",
  borderRadius: 6,
  background: "#fff",
  cursor: "pointer",
  textAlign: "left",
};

export function ReviewQueue({
  items,
  selectedId,
  onSelect,
  loading,
  error,
}: {
  items: ReviewQueueItem[];
  selectedId: number | null;
  onSelect: (appointmentId: number) => void;
  loading: boolean;
  error: string | null;
}) {
  return (
    <section aria-label="Review queue">
      <h2>Review queue</h2>
      <p style={{ color: "#57606a", marginTop: 0 }}>
        Completed appointments queued for your review.
      </p>

      {loading && <p>Loading review queue…</p>}
      {error && (
        <p role="alert" style={{ color: "#b42318" }}>
          {error}
        </p>
      )}

      {!loading && !error && items.length === 0 && (
        <p>No appointments are waiting for review.</p>
      )}

      <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "grid", gap: "0.5rem" }}>
        {items.map((item) => {
          const selected = item.appointment_id === selectedId;
          return (
            <li key={item.appointment_id}>
              <button
                type="button"
                aria-pressed={selected}
                onClick={() => onSelect(item.appointment_id)}
                style={{
                  ...rowBase,
                  borderColor: selected ? "#0969da" : "#d0d7de",
                  boxShadow: selected ? "0 0 0 1px #0969da" : "none",
                }}
              >
                <span>
                  <strong>Appointment #{item.appointment_id}</strong>
                  <br />
                  <span style={{ color: "#57606a" }}>
                    {item.service_type || "service"} · patient #{item.patient_id} ·
                    volunteer #{item.volunteer_id}
                  </span>
                </span>
                <span
                  style={{
                    alignSelf: "center",
                    fontSize: "0.85rem",
                    color: item.reviewed ? "#1a7f37" : "#9a6700",
                  }}
                >
                  {item.reviewed ? "reviewed" : "awaiting decision"}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
