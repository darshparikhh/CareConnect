/**
 * Decision / referral / approval controls (R19.3, R19.4).
 *
 * For the selected appointment, lets the clinician:
 *  - record a Clinical_Decision (R19.3) — surfacing 400 decision-content-required
 *    and 403 credential-not-verified from the Review_Service;
 *  - issue a hospital Referral (R19.3) — the clinician picks a bundled MA
 *    hospital from a dropdown; its label is stored as the referral specialty;
 *  - approve the stored decision for patient visibility (R19.4) — surfacing
 *    409 no-decision-to-approve.
 *
 * Owns its own form + request state. On a successful record/approve it calls
 * `onChanged` so the parent can refresh the queue (the `reviewed` flag moves).
 */
import { useEffect, useState } from "react";
import { ApiError } from "../../api/client";
import {
  approveDecision,
  fetchHospitals,
  issueReferral,
  recordDecision,
} from "../../api/clinician";
import type {
  ClinicianDecisionResponse,
  ClinicianHospital,
} from "../../api/clinician";

/** The referral value recorded for a hospital — a readable label. */
function hospitalLabel(h: ClinicianHospital): string {
  return `${h.facility_name} — ${h.citytown}`;
}

/** Map an unknown thrown value to a human-readable message for this panel. */
function messageFor(err: unknown): string {
  if (err instanceof Error && err.message === "empty") {
    return "Write instructions for the patient before submitting.";
  }
  if (err instanceof Error && err.message === "no-hospital") {
    return "Select a hospital to refer to.";
  }
  if (err instanceof ApiError) {
    switch (err.code) {
      case "decision-content-required":
        return "A decision needs some content before it can be recorded.";
      case "credential-not-verified":
        return "Your clinician license is not verified, so no decision was recorded.";
      case "no-decision-to-approve":
        return "Record a decision for this appointment before approving or referring.";
      case "not-ready-for-review":
        return "This appointment is not ready for review.";
      default:
        return err.message || "Something went wrong. Please try again.";
    }
  }
  return "Something went wrong. Please try again.";
}

const card: React.CSSProperties = {
  border: "1px solid var(--cc-border)",
  borderRadius: 6,
  padding: "0.75rem",
  background: "var(--cc-surface)",
  color: "var(--cc-text)",
  display: "grid",
  gap: "1rem",
};

const fieldStyle: React.CSSProperties = {
  width: "100%",
  boxSizing: "border-box",
  padding: "0.5rem",
  border: "1px solid var(--cc-border-strong)",
  background: "#0f1a30",
  color: "var(--cc-text)",
  borderRadius: 4,
  font: "inherit",
};

const buttonStyle: React.CSSProperties = {
  padding: "0.5rem 0.9rem",
  border: "1px solid var(--cc-primary)",
  borderRadius: 6,
  background: "var(--cc-primary)",
  color: "#fff",
  cursor: "pointer",
};

export function DecisionPanel({
  appointmentId,
  onChanged,
}: {
  appointmentId: number | null;
  onChanged: () => void;
}) {
  const [decision, setDecision] = useState<ClinicianDecisionResponse | null>(null);
  const [content, setContent] = useState("");
  const [hospitals, setHospitals] = useState<ClinicianHospital[]>([]);
  const [hospitalsError, setHospitalsError] = useState<string | null>(null);
  const [selectedHospital, setSelectedHospital] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // Reset the panel whenever a different appointment is selected.
  useEffect(() => {
    setDecision(null);
    setContent("");
    setSelectedHospital("");
    setBusy(false);
    setError(null);
    setNotice(null);
  }, [appointmentId]);

  // Load the hospital list once an appointment is selected. A load failure is
  // shown quietly and does not block recording a decision.
  useEffect(() => {
    if (appointmentId === null) {
      return;
    }
    let active = true;
    setHospitalsError(null);
    fetchHospitals()
      .then((list) => {
        if (active) {
          setHospitals(list);
        }
      })
      .catch(() => {
        if (active) {
          setHospitalsError("Couldn't load the hospital list.");
        }
      });
    return () => {
      active = false;
    };
  }, [appointmentId]);

  if (appointmentId === null) {
    return (
      <section aria-label="Decision" style={{ ...card }}>
        <h2 style={{ margin: 0 }}>Decision</h2>
        <p style={{ color: "var(--cc-text-muted)", margin: 0 }}>
          Select an appointment to record a decision.
        </p>
      </section>
    );
  }

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await action();
    } catch (err) {
      setError(messageFor(err));
    } finally {
      setBusy(false);
    }
  }

  // One-click submit: record the decision AND approve it so the patient sees it
  // as soon as they refresh. This matches the demo flow — the clinician writes
  // what to do, clicks Submit, and it appears on the patient dashboard.
  const onSubmit = () =>
    run(async () => {
      if (!content.trim()) {
        throw new Error("empty");
      }
      await recordDecision(appointmentId, content);
      const approved = await approveDecision(appointmentId);
      setDecision(approved);
      setNotice("Sent to the patient. They'll see it when they refresh.");
      onChanged();
    });

  const onRefer = () =>
    run(async () => {
      if (!selectedHospital) {
        throw new Error("no-hospital");
      }
      await issueReferral(appointmentId, selectedHospital);
      const label = selectedHospital;
      setSelectedHospital("");
      setNotice(`Referral issued to ${label}.`);
    });

  return (
    <section aria-label="Decision" style={{ ...card }}>
      <h2 style={{ margin: 0 }}>Decision for appointment #{appointmentId}</h2>
      {error && (
        <p role="alert" style={{ color: "var(--cc-danger)", margin: 0 }}>
          {error}
        </p>
      )}
      {notice && (
        <p role="status" style={{ color: "var(--cc-success)", margin: 0 }}>
          {notice}
        </p>
      )}
      {/* Record a clinical decision (R19.3) */}
      <div style={{ display: "grid", gap: "0.5rem" }}>
        <label htmlFor="decision-content">
          <strong>What should the patient do?</strong>
        </label>
        <textarea
          id="decision-content"
          rows={5}
          value={content}
          onChange={(e) => setContent(e.target.value)}
          placeholder="Write instructions for the patient — e.g. You tested positive for COVID-19. Rest, hydrate, take Tylenol for fever, and isolate for 5 days…"
          style={fieldStyle}
        />
        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
          <button type="button" onClick={onSubmit} disabled={busy} style={buttonStyle}>
            {busy ? "Submitting…" : "Submit to patient"}
          </button>
        </div>
      </div>
      {decision && (
        <p style={{ margin: 0, color: "var(--cc-text-muted)" }}>
          Current decision is{" "}
          <strong>{decision.approved ? "approved" : "recorded, not yet approved"}</strong>.
        </p>
      )}
      {/* Issue a referral to a hospital (R19.3) */}
      <div style={{ display: "grid", gap: "0.5rem" }}>
        <label htmlFor="referral-hospital">
          <strong>Refer to a hospital</strong>
        </label>
        {hospitalsError && (
          <p style={{ color: "var(--cc-text-muted)", margin: 0, fontSize: "0.85rem" }}>
            {hospitalsError}
          </p>
        )}
        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
          <select
            id="referral-hospital"
            value={selectedHospital}
            onChange={(e) => setSelectedHospital(e.target.value)}
            style={{ ...fieldStyle, maxWidth: 360 }}
          >
            <option value="" disabled>
              Select a hospital…
            </option>
            {hospitals.map((h) => {
              const label = hospitalLabel(h);
              return (
                <option key={label} value={label}>
                  {label}
                </option>
              );
            })}
          </select>
          <button type="button" onClick={onRefer} disabled={busy} style={buttonStyle}>
            Issue referral
          </button>
        </div>
      </div>
    </section>
  );
}
