/**
 * Visit detail + data entry for one assigned appointment (R18.3, R18.4).
 *
 * Opens the visit detail through the Visit_Service and renders:
 *  - the requested Service_Type and visit location,
 *  - ONLY the Service_Types this Volunteer is authorized to perform (R18.4),
 *  - a single symptom question and a test-result entry with two dropdowns
 *    (disease + positive/negative), submitted through the Visit_Service (R18.3).
 *
 * The single required question is "If you are getting tested, what are your
 * symptoms?". The test result is captured as a disease (COVID-19, Flu, Strep
 * throat, Other) plus a Positive (green) / Negative (red) result; it is sent to
 * the backend as measurement = disease, unit = result, so it flows through the
 * existing Test_Result API unchanged.
 */

import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import {
  getVisitDetail,
  submitQuestionnaire,
  submitTestResult,
  type VisitDetail,
} from "../../api/volunteer";
import { describeError, styles } from "./shared";

/** The single required questionnaire question id (must match the seed). */
const SYMPTOMS_QUESTION = "If you are getting tested - what are your symptoms?";

/** Diseases the test result can report. */
const DISEASES = ["COVID-19", "Flu", "Strep throat", "Other"] as const;

export function VisitDetailPanel({
  appointmentId,
  onSubmitted,
}: {
  appointmentId: number;
  /** Called after a submission so the parent can refresh appointment state. */
  onSubmitted?: () => void;
}) {
  const [detail, setDetail] = useState<VisitDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Questionnaire: a single free-text symptoms answer.
  const [symptoms, setSymptoms] = useState("");
  const [qError, setQError] = useState<string | null>(null);
  const [qNotice, setQNotice] = useState<string | null>(null);
  const [qSubmitting, setQSubmitting] = useState(false);

  // Test result: disease + positive/negative dropdowns.
  const [disease, setDisease] = useState<string>("COVID-19");
  const [result, setResult] = useState<"Positive" | "Negative" | "">("");
  const [tError, setTError] = useState<string | null>(null);
  const [tNotice, setTNotice] = useState<string | null>(null);
  const [tSubmitting, setTSubmitting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      setDetail(await getVisitDetail(appointmentId));
    } catch (err) {
      setLoadError(describeError(err));
    } finally {
      setLoading(false);
    }
  }, [appointmentId]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleSubmitQuestionnaire = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setQError(null);
    setQNotice(null);
    if (!symptoms.trim()) {
      setQError("Please describe the symptoms.");
      return;
    }
    setQSubmitting(true);
    try {
      const res = await submitQuestionnaire(appointmentId, {
        [SYMPTOMS_QUESTION]: symptoms.trim(),
      });
      setQNotice(
        res.completed
          ? "Symptoms submitted. The visit is complete and sent to the clinician."
          : "Symptoms submitted.",
      );
      onSubmitted?.();
    } catch (err) {
      setQError(describeError(err));
    } finally {
      setQSubmitting(false);
    }
  };

  const handleSubmitTestResult = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setTError(null);
    setTNotice(null);
    if (!result) {
      setTError("Please choose a result (Positive or Negative).");
      return;
    }
    setTSubmitting(true);
    try {
      // Flows through the existing Test_Result API: measurement = disease,
      // unit = result. The required test id is "pcr_test" in the seed, so the
      // measurement must be that id for completion to trigger — we send the
      // disease as the value label and keep measurement = "pcr_test".
      const res = await submitTestResult(appointmentId, {
        measurement: "pcr_test",
        value: null,
        unit: `${disease}: ${result}`,
      });
      setTNotice(
        res.completed
          ? "Result submitted. The visit is complete and sent to the clinician."
          : "Result submitted.",
      );
      onSubmitted?.();
    } catch (err) {
      setTError(describeError(err));
    } finally {
      setTSubmitting(false);
    }
  };

  if (loading) {
    return <p style={styles.muted}>Loading visit detail…</p>;
  }
  if (loadError) {
    return (
      <p role="alert" style={styles.error}>
        {loadError}
      </p>
    );
  }
  if (!detail) {
    return null;
  }

  const resultColor =
    result === "Positive" ? "#6fcf97" : result === "Negative" ? "#e5767b" : undefined;

  return (
    <div>
      <div style={styles.card}>
        <h4 style={{ marginTop: 0 }}>Visit detail</h4>
        <p>
          <strong>Requested service:</strong>{" "}
          {detail.requested_service_type.name}
        </p>
        <p>
          <strong>Location:</strong> {detail.location.lat.toFixed(4)},{" "}
          {detail.location.lng.toFixed(4)}
        </p>
        <div>
          <strong>Your authorized services for this visit:</strong>
          {detail.authorized_services.length === 0 ? (
            <p style={styles.muted}>
              You have no authorized services for this visit.
            </p>
          ) : (
            <ul>
              {detail.authorized_services
                .filter(
                  (srv) => srv.name === detail.requested_service_type.name,
                )
                .map((srv) => (
                  <li key={srv.id}>{srv.name}</li>
                ))}
            </ul>
          )}
        </div>
      </div>

      {/* Single symptom question */}
      <form onSubmit={handleSubmitQuestionnaire} style={styles.card}>
        <h4 style={{ marginTop: 0 }}>Questionnaire</h4>
        <label style={{ ...styles.label, width: "100%" }}>
          If you are getting tested, what are your symptoms?
          <textarea
            rows={3}
            value={symptoms}
            onChange={(e) => setSymptoms(e.target.value)}
            style={{ ...styles.input, width: "100%", resize: "vertical" }}
            placeholder="e.g. fever, sore throat, cough"
          />
        </label>
        <div style={{ marginTop: "0.6rem" }}>
          <button type="submit" style={styles.primaryButton} disabled={qSubmitting}>
            {qSubmitting ? "Submitting…" : "Submit symptoms"}
          </button>
        </div>
        {qError && (
          <p role="alert" style={styles.error}>
            {qError}
          </p>
        )}
        {qNotice && <p style={styles.success}>{qNotice}</p>}
      </form>

      {/* Test result: disease + positive/negative dropdowns */}
      <form onSubmit={handleSubmitTestResult} style={styles.card}>
        <h4 style={{ marginTop: 0 }}>Test result</h4>
        <div style={styles.row}>
          <label style={styles.label}>
            Disease
            <select
              value={disease}
              onChange={(e) => setDisease(e.target.value)}
              style={styles.input}
            >
              {DISEASES.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
          </label>
          <label style={styles.label}>
            Result
            <select
              value={result}
              onChange={(e) =>
                setResult(e.target.value as "Positive" | "Negative" | "")
              }
              style={{
                ...styles.input,
                color: resultColor,
                fontWeight: result ? 700 : 400,
              }}
            >
              <option value="">Select…</option>
              <option value="Positive" style={{ color: "#6fcf97" }}>
                Positive
              </option>
              <option value="Negative" style={{ color: "#e5767b" }}>
                Negative
              </option>
            </select>
          </label>
          <button type="submit" style={styles.primaryButton} disabled={tSubmitting}>
            {tSubmitting ? "Submitting…" : "Submit result"}
          </button>
        </div>
        {result && (
          <p style={{ margin: "0.5rem 0 0", color: resultColor, fontWeight: 700 }}>
            {disease}: {result}
          </p>
        )}
        {tError && (
          <p role="alert" style={styles.error}>
            {tError}
          </p>
        )}
        {tNotice && <p style={styles.success}>{tNotice}</p>}
      </form>
    </div>
  );
}
