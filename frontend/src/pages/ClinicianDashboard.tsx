/**
 * Clinician dashboard (task 21.1, R19).
 *
 * Wires the Review_Service routes into a working view:
 *  - the completed-and-queued review queue (R19.1);
 *  - a findings view of the selected appointment's submitted questionnaires and
 *    test results (R19.2);
 *  - controls to record a decision and issue a referral (R19.3);
 *  - a control to approve a decision for patient visibility (R19.4).
 *
 * The page owns the selected appointment, the queue, and the findings; the
 * DecisionPanel owns its own form + mutation state and calls back on changes so
 * the queue refreshes. All rules live in the backend services behind these
 * routes — this page is presentation and orchestration only.
 */

import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../api/client";
import {
  fetchFindings,
  fetchReviewQueue,
} from "../api/clinician";
import type { FindingsResponse, ReviewQueueItem } from "../api/clinician";
import { DashboardShell } from "../components/DashboardShell";
import { ReviewQueue } from "../components/clinician/ReviewQueue";
import { FindingsView } from "../components/clinician/FindingsView";
import { DecisionPanel } from "../components/clinician/DecisionPanel";

function findingsMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === "not-ready-for-review") {
      return "This appointment is not ready for review yet.";
    }
    return err.message || "Could not load findings.";
  }
  return "Could not load findings.";
}

export function ClinicianDashboard() {
  const [queue, setQueue] = useState<ReviewQueueItem[]>([]);
  const [queueLoading, setQueueLoading] = useState(true);
  const [queueError, setQueueError] = useState<string | null>(null);

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [findings, setFindings] = useState<FindingsResponse | null>(null);
  const [findingsLoading, setFindingsLoading] = useState(false);
  const [findingsError, setFindingsError] = useState<string | null>(null);

  const loadQueue = useCallback(async () => {
    setQueueLoading(true);
    setQueueError(null);
    try {
      setQueue(await fetchReviewQueue());
    } catch (err) {
      setQueueError(
        err instanceof ApiError ? err.message : "Could not load the review queue.",
      );
    } finally {
      setQueueLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadQueue();
  }, [loadQueue]);

  // Load findings whenever the selected appointment changes.
  useEffect(() => {
    if (selectedId === null) {
      setFindings(null);
      setFindingsError(null);
      return;
    }
    let cancelled = false;
    setFindingsLoading(true);
    setFindingsError(null);
    setFindings(null);
    fetchFindings(selectedId)
      .then((result) => {
        if (!cancelled) setFindings(result);
      })
      .catch((err: unknown) => {
        if (!cancelled) setFindingsError(findingsMessage(err));
      })
      .finally(() => {
        if (!cancelled) setFindingsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  return (
    <DashboardShell role="clinician">
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(260px, 1fr) minmax(0, 2fr)",
          gap: "1.25rem",
          alignItems: "start",
        }}
      >
        <ReviewQueue
          items={queue}
          selectedId={selectedId}
          onSelect={setSelectedId}
          loading={queueLoading}
          error={queueError}
        />

        <div style={{ display: "grid", gap: "1.25rem" }}>
          <FindingsView
            findings={findings}
            loading={findingsLoading}
            error={findingsError}
          />
          <DecisionPanel appointmentId={selectedId} onChanged={() => void loadQueue()} />
        </div>
      </div>
    </DashboardShell>
  );
}
