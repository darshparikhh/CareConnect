/**
 * Findings view (R19.2).
 *
 * Displays the submitted questionnaires and test results for the selected
 * appointment, fetched through the Review_Service. A not-ready appointment
 * (409 not-ready-for-review) surfaces as a message rather than data.
 * Presentation only.
 */

import type { FindingsResponse } from "../../api/clinician";

const card: React.CSSProperties = {
  border: "1px solid #d0d7de",
  borderRadius: 6,
  padding: "0.75rem",
  background: "#fff",
};

export function FindingsView({
  findings,
  loading,
  error,
}: {
  findings: FindingsResponse | null;
  loading: boolean;
  error: string | null;
}) {
  return (
    <section aria-label="Findings" style={{ ...card }}>
      <h2 style={{ marginTop: 0 }}>Findings</h2>

      {loading && <p>Loading findings…</p>}
      {error && (
        <p role="alert" style={{ color: "#b42318" }}>
          {error}
        </p>
      )}

      {!loading && !error && !findings && (
        <p style={{ color: "#57606a" }}>
          Select an appointment from the queue to view its findings.
        </p>
      )}

      {!loading && !error && findings && (
        <>
          <h3>Questionnaires</h3>
          {findings.questionnaires.length === 0 ? (
            <p style={{ color: "#57606a" }}>No questionnaires submitted.</p>
          ) : (
            <ul style={{ margin: 0, paddingLeft: "1.1rem" }}>
              {findings.questionnaires.map((q) => (
                <li key={q.id} style={{ marginBottom: "0.4rem" }}>
                  <strong>{q.service_type || "Questionnaire"}</strong>
                  <pre
                    style={{
                      margin: "0.25rem 0 0",
                      padding: "0.5rem",
                      background: "#f6f8fa",
                      borderRadius: 4,
                      whiteSpace: "pre-wrap",
                      wordBreak: "break-word",
                    }}
                  >
                    {q.answers ?? "(no answers recorded)"}
                  </pre>
                </li>
              ))}
            </ul>
          )}

          <h3>Test results</h3>
          {findings.test_results.length === 0 ? (
            <p style={{ color: "#57606a" }}>No test results submitted.</p>
          ) : (
            <ul style={{ margin: 0, paddingLeft: "1.1rem" }}>
              {findings.test_results.map((t) => (
                <li key={t.id}>
                  {t.measurement}
                  {t.value != null ? `: ${t.value}` : ""}
                  {t.unit ? ` ${t.unit}` : ""}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}
