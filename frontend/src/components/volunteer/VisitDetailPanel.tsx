/**
 * Visit detail + data entry for one assigned appointment (R18.3, R18.4).
 *
 * Opens the visit detail through the Visit_Service and renders:
 *  - the requested Service_Type and visit location,
 *  - ONLY the Service_Types this Volunteer is authorized to perform (R18.4) —
 *    the backend never returns the full catalog,
 *  - a questionnaire form and a test-result form that submit through the
 *    Visit_Service (R18.3). Submission rejections (unauthorized-service,
 *    missing-required-questions, wrong state) are surfaced inline.
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

/** One editable questionnaire answer row (question id -> value). */
interface AnswerRow {
  key: string;
  question: string;
  answer: string;
}

let answerRowSeq = 0;
function newAnswerRow(): AnswerRow {
  answerRowSeq += 1;
  return { key: `answer-${answerRowSeq}`, question: "", answer: "" };
}

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

  // Questionnaire form state.
  const [rows, setRows] = useState<AnswerRow[]>([newAnswerRow()]);
  const [qError, setQError] = useState<string | null>(null);
  const [qNotice, setQNotice] = useState<string | null>(null);
  const [qSubmitting, setQSubmitting] = useState(false);

  // Test-result form state.
  const [measurement, setMeasurement] = useState("");
  const [value, setValue] = useState("");
  const [unit, setUnit] = useState("");
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

  const updateRow = (key: string, patch: Partial<AnswerRow>) => {
    setRows((prev) => prev.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  };

  const handleSubmitQuestionnaire = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setQError(null);
    setQNotice(null);

    const answers: Record<string, unknown> = {};
    for (const row of rows) {
      const q = row.question.trim();
      if (q) answers[q] = row.answer;
    }
    if (Object.keys(answers).length === 0) {
      setQError("Add at least one question and answer.");
      return;
    }

    setQSubmitting(true);
    try {
      const result = await submitQuestionnaire(appointmentId, answers);
      setQNotice(
        result.completed
          ? "Questionnaire submitted. The visit is now complete and queued for review."
          : "Questionnaire submitted.",
      );
      setRows([newAnswerRow()]);
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

    if (!measurement.trim()) {
      setTError("Enter a measurement.");
      return;
    }
    let numericValue: number | null = null;
    if (value.trim() !== "") {
      const parsed = Number(value);
      if (Number.isNaN(parsed)) {
        setTError("Value must be a number.");
        return;
      }
      numericValue = parsed;
    }

    setTSubmitting(true);
    try {
      const result = await submitTestResult(appointmentId, {
        measurement: measurement.trim(),
        value: numericValue,
        unit: unit.trim() || null,
      });
      setTNotice(
        result.completed
          ? "Test result submitted. The visit is now complete and queued for review."
          : "Test result submitted.",
      );
      setMeasurement("");
      setValue("");
      setUnit("");
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
              {detail.authorized_services.map((s) => (
                <li key={s.id}>{s.name}</li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <form onSubmit={handleSubmitQuestionnaire} style={styles.card}>
        <h4 style={{ marginTop: 0 }}>Submit questionnaire</h4>
        {rows.map((row) => (
          <div key={row.key} style={{ ...styles.row, marginBottom: "0.5rem" }}>
            <label style={styles.label}>
              Question id
              <input
                type="text"
                value={row.question}
                onChange={(e) => updateRow(row.key, { question: e.target.value })}
                style={styles.input}
              />
            </label>
            <label style={styles.label}>
              Answer
              <input
                type="text"
                value={row.answer}
                onChange={(e) => updateRow(row.key, { answer: e.target.value })}
                style={styles.input}
              />
            </label>
          </div>
        ))}
        <div style={styles.row}>
          <button
            type="button"
            style={styles.button}
            onClick={() => setRows((prev) => [...prev, newAnswerRow()])}
          >
            Add question
          </button>
          <button type="submit" style={styles.primaryButton} disabled={qSubmitting}>
            {qSubmitting ? "Submitting…" : "Submit questionnaire"}
          </button>
        </div>
        {qError && (
          <p role="alert" style={styles.error}>
            {qError}
          </p>
        )}
        {qNotice && <p style={styles.success}>{qNotice}</p>}
      </form>

      <form onSubmit={handleSubmitTestResult} style={styles.card}>
        <h4 style={{ marginTop: 0 }}>Submit test result</h4>
        <div style={styles.row}>
          <label style={styles.label}>
            Measurement
            <input
              type="text"
              value={measurement}
              onChange={(e) => setMeasurement(e.target.value)}
              style={styles.input}
              required
            />
          </label>
          <label style={styles.label}>
            Value (optional)
            <input
              type="number"
              step="any"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              style={styles.input}
            />
          </label>
          <label style={styles.label}>
            Unit (optional)
            <input
              type="text"
              value={unit}
              onChange={(e) => setUnit(e.target.value)}
              style={styles.input}
            />
          </label>
          <button type="submit" style={styles.primaryButton} disabled={tSubmitting}>
            {tSubmitting ? "Submitting…" : "Submit test result"}
          </button>
        </div>
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
