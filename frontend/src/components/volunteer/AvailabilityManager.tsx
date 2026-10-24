/**
 * Availability management (R18.2).
 *
 * Lists the Volunteer's availability slots and provides an interface to add a
 * new slot (start/end) and remove an existing one through the
 * Availability_Service. Removing a slot that holds an assigned appointment is
 * rejected by the backend with `409 slot-has-appointment` (R6.3); that is
 * surfaced inline so the Volunteer understands why the removal was refused.
 */

import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import {
  addSlot,
  listSlots,
  removeSlot,
  type VolunteerSlot,
} from "../../api/volunteer";
import { describeError, formatDateTime, styles } from "./shared";

export function AvailabilityManager() {
  const [slots, setSlots] = useState<VolunteerSlot[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Per-slot removal error (keyed by slot id) and the id being removed.
  const [removeError, setRemoveError] = useState<Record<number, string>>({});
  const [removingId, setRemovingId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      setSlots(await listSlots());
    } catch (err) {
      setLoadError(describeError(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  /** Convert a datetime-local value to an ISO-8601 string. */
  const toIso = (local: string): string => new Date(local).toISOString();

  const handleAdd = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setFormError(null);

    if (!start || !end) {
      setFormError("Choose both a start and end time.");
      return;
    }
    if (new Date(end).getTime() <= new Date(start).getTime()) {
      setFormError("End time must be after start time.");
      return;
    }

    setSubmitting(true);
    try {
      const created = await addSlot(toIso(start), toIso(end));
      setSlots((prev) =>
        [...prev, created].sort(
          (a, b) => new Date(a.start).getTime() - new Date(b.start).getTime(),
        ),
      );
      setStart("");
      setEnd("");
    } catch (err) {
      setFormError(describeError(err));
    } finally {
      setSubmitting(false);
    }
  };

  const handleRemove = async (slot: VolunteerSlot) => {
    setRemovingId(slot.id);
    setRemoveError((prev) => {
      const next = { ...prev };
      delete next[slot.id];
      return next;
    });
    try {
      const removed = await removeSlot(slot.id);
      // Reflect the backend's new status (e.g. "unavailable") in place.
      setSlots((prev) =>
        prev.map((s) => (s.id === removed.id ? removed : s)),
      );
    } catch (err) {
      setRemoveError((prev) => ({ ...prev, [slot.id]: describeError(err) }));
    } finally {
      setRemovingId(null);
    }
  };

  return (
    <section style={styles.section} aria-labelledby="availability-heading">
      <h2 id="availability-heading">Availability</h2>

      <form onSubmit={handleAdd} style={styles.card}>
        <div style={styles.row}>
          <label style={styles.label}>
            Start
            <input
              type="datetime-local"
              value={start}
              onChange={(e) => setStart(e.target.value)}
              style={styles.input}
              required
            />
          </label>
          <label style={styles.label}>
            End
            <input
              type="datetime-local"
              value={end}
              onChange={(e) => setEnd(e.target.value)}
              style={styles.input}
              required
            />
          </label>
          <button type="submit" style={styles.primaryButton} disabled={submitting}>
            {submitting ? "Adding…" : "Add slot"}
          </button>
        </div>
        {formError && (
          <p role="alert" style={styles.error}>
            {formError}
          </p>
        )}
      </form>

      {loading && <p style={styles.muted}>Loading slots…</p>}
      {loadError && (
        <p role="alert" style={styles.error}>
          {loadError}
        </p>
      )}
      {!loading && !loadError && slots.length === 0 && (
        <p style={styles.muted}>No availability slots yet.</p>
      )}

      {slots.map((slot) => (
        <div key={slot.id} style={styles.card}>
          <div style={styles.cardHeader}>
            <div>
              <div>
                {formatDateTime(slot.start)} – {formatDateTime(slot.end)}
              </div>
              <span style={styles.badge}>{slot.status}</span>
            </div>
            {slot.status !== "unavailable" && (
              <button
                type="button"
                style={styles.button}
                onClick={() => void handleRemove(slot)}
                disabled={removingId === slot.id}
              >
                {removingId === slot.id ? "Removing…" : "Remove"}
              </button>
            )}
          </div>
          {removeError[slot.id] && (
            <p role="alert" style={styles.error}>
              {removeError[slot.id]}
            </p>
          )}
        </div>
      ))}
    </section>
  );
}
