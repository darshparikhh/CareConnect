/**
 * Decision / referral / approval controls (R19.3, R19.4).
 *
 * For the selected appointment, lets the clinician:
 *  - record a Clinical_Decision (R19.3) — surfacing 400 decision-content-required
 *    and 403 credential-not-verified from the Review_Service;
 *  - issue a specialty Referral (R19.3) — surfacing the content/no-decision errors;
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
  issueReferral,
  recordDecision,
} from "../../api/clinician";
import type { ClinicianDecisionResponse } from "../../api/clinician";

/** Map an unknown thrown value to a human-readable message for this panel. */
function messageFor(err: unknown): string {
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
  border: "1px solid #d0d7de",
  borderRadius: 6,
  padding: "0.75rem",
  background: "#fff",
  display: "grid",
  gap: "1rem",
};

const fieldStyle: React.CSSProperties = {
  width: "100%",
  boxSizing: "border-box",
  padding: "0.5rem",
  border: "1px solid #d0d7de",
  borderRadius: 4,
  font: "inherit",
};

const buttonStyle: React.CSSProperties = {
  padding: "0.5rem 0.9rem",
  border: "1px solid #0969da",
  borderRadius: 6,
  background: "#0969da",
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
  const [specialty, setSpecialty] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // Reset the panel whenever a different appointment is selected.
  useEffect(() => {
    setDecision(null);
    setContent("");
    setSpecialty("");
    setBusy(false);
    setError(null);
    setNotice(null);
  }, [appointmentId]);

  if (appointmentId === null) {
    return (
      <section aria-label="Decision" style={{ ...card }}>
        <h2 style={{ margin: 0 }}>Decision</h2>
        <p style={{ color: "#57606a", margin: 0 }}>
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

  const onRecord = () =>
    run(async () => {
      const result = await recordDecision(appointmentId, content);
      setDecision(result);
      setNotice("Decision recorded. Approve it to make it visible to the patient.");
      onChanged();
    });

  const onApprove = () =>
    run(async () => {
      const result = await approveDecision(appointmentId);
      setDecision(result);
      setNotice("Decision approved and now visible to the patient.");
      onChanged();
    });

  const onRefer = () =>
    run(async () => {
      const result = await issueReferral(appointmentId, specialty);
      setSpecialty("");
      setNotice(`Referral issued for ${result.specialty}.`);
    });

  return (
    <section aria-label="Decision" style={{ ...card }}>
      <h2 style={{ margin: 0 }}>Decision for appointment #{appointmentId}</h2>

      {error && (
        <p role="alert" style={{ color: "#b42318", margin: 0 }}>
          {error}
        </p>
      )}
      {notice && (
        <p role="status" style={{ color: "#1a7f37", margin: 0 }}>
          {notice}
        </p>
      )}

      {/* Record a clinical decision (R19.3) */}
      <div style={{ display: "grid", gap: "0.5rem" }}>
        <label htmlFor="decision-content">
          <strong>Clinical decision</strong>
        </label>
        <textarea
          id="decision-content"
          rows={4}
          value={content}
          onChange={(e) => setContent(e.target.value)}
          placeholder="Document your clinical decision…"
          style={fieldStyle}
        />
        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
          <button type="button" onClick={onRecord} disabled={busy} style={buttonStyle}>
            Record decision
          </button>
          <button type="button" onClick={onApprove} disabled={busy} style={buttonStyle}>
            Approve for patient
          </button>
        </div>
      </div>

      {decision && (
        <p style={{ margin: 0, color: "#57606a" }}>
          Current decision is{" "}
          <strong>{decision.approved ? "approved" : "recorded, not yet approved"}</strong>.
        </p>
      )}

      {/* Issue a referral (R19.3) */}
      <div style={{ display: "grid", gap: "0.5rem" }}>
        <label htmlFor="referral-specialty">
          <strong>Referral specialty</strong>
        </label>
        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
          <input
            id="referral-specialty"
            value={specialty}
            onChange={(e) => setSpecialty(e.target.value)}
            placeholder="e.g. cardiology"
            style={{ ...fieldStyle, maxWidth: 260 }}
          />
          <button type="button" onClick={onRefer} disabled={busy} style={buttonStyle}>
            Issue referral
          </button>
        </div>
      </div>
    </section>
  );
}
