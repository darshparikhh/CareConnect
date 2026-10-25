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
  border: "1px solid var(--cc-border)",
  borderRadius: 6,
  padding: "0.75rem",
  background: "var(--cc-surface)",
  color: "var(--cc-text)",
};

/**
 * Display only the volunteer's typed answer text. Stored answers are
 * newline-separated "question id: answer" entries; strip the leading
 * "question id: " prefix from each line so the clinician sees just the typed
 * words. Lines without a ": " are shown unchanged.
 */
function answersForDisplay(answers: string | null | undefined): string {
  if (!answers) return "";
  return answers
    .split("\n")
    .map((line) => {
      const index = line.indexOf(": ");
      return index === -1 ? line : line.slice(index + 2);
    })
    .join("\n");
}
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
        <p role="alert" style={{ color: "var(--cc-danger)" }}>
          {error}
        </p>
      )}
      {!loading && !error && !findings && (
        <p style={{ color: "var(--cc-text-muted)" }}>
          Select an appointment from the queue to view its findings.
        </p>
      )}
      {!loading && !error && findings && (
        <>
          <h3>Questionnaires</h3>
          {findings.questionnaires.length === 0 ? (
            <p style={{ color: "var(--cc-text-muted)" }}>No questionnaires submitted.</p>
          ) : (
            <ul style={{ margin: 0, paddingLeft: "1.1rem" }}>
              {findings.questionnaires.map((q) => (
                <li key={q.id} style={{ marginBottom: "0.4rem" }}>
                  <strong>{q.service_type || "Questionnaire"}</strong>
                  <pre
                    style={{
                      margin: "0.25rem 0 0",
                      padding: "0.5rem",
                      background: "#0f1a30",
                      color: "var(--cc-text)",
                      border: "1px solid var(--cc-border)",
                      borderRadius: 4,
                      whiteSpace: "pre-wrap",
                      wordBreak: "break-word",
                    }}
                  >
                    {answersForDisplay(q.answers) || "(no answers recorded)"}
                  </pre>
                </li>
              ))}
            </ul>
          )}
          <h3>Test results</h3>
          {findings.test_results.length === 0 ? (
            <p style={{ color: "var(--cc-text-muted)" }}>No test results submitted.</p>
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
