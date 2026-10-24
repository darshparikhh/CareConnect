/**
 * Ranked Recommended_Doctors with proximity, specialty, and insurance-
 * compatibility status (R17.4).
 *
 * Reads POST /patient/recommendations and renders the ranked list the
 * Recommendation_Engine returns. The backend applies the specialty and
 * verified-insurance hard filters and never asserts compatibility while the
 * Patient's insurance is unverified (R15.4), so each row shows the engine's
 * insurance status verbatim. Advisory messages (no required specialty, no
 * compatible doctors, invalid weights) are surfaced as a note.
 */

import { useCallback } from "react";
import type { InsuranceStatus, RecommendationResponse } from "../../api/patient";
import { getRecommendations } from "../../api/patient";
import { Card, ErrorNote, Note, Pill } from "./shared";
import type { Tone } from "./shared";
import { useAsyncData } from "./shared";

const INSURANCE_TONE: Record<InsuranceStatus, Tone> = {
  compatible: "success",
  incompatible: "danger",
  unknown: "warning",
};

const INSURANCE_LABEL: Record<InsuranceStatus, string> = {
  compatible: "Insurance compatible",
  incompatible: "Insurance incompatible",
  unknown: "Insurance unverified",
};

export function RecommendationsSection() {
  const loader = useCallback(() => getRecommendations(), []);
  const { data, loading, error } = useAsyncData<RecommendationResponse>(loader);

  const doctors = data?.doctors ?? [];

  return (
    <Card title="Recommended doctors">
      {loading && <Note>Loading recommendations…</Note>}
      {error && <ErrorNote>{error}</ErrorNote>}

      {!loading && !error && data?.message && (
        <Note>{data.message}</Note>
      )}

      {!loading && !error && doctors.length === 0 && !data?.message && (
        <Note>No recommended doctors available.</Note>
      )}

      {!loading && !error && doctors.length > 0 && (
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {doctors.map((doc, index) => (
            <li
              key={doc.id}
              style={{
                padding: "0.6rem 0",
                borderBottom: "1px solid #eee",
              }}
            >
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  gap: "0.5rem",
                }}
              >
                <strong>
                  {index + 1}. {doc.name}
                </strong>
                <Pill
                  label={INSURANCE_LABEL[doc.insurance_status]}
                  tone={INSURANCE_TONE[doc.insurance_status] ?? "neutral"}
                />
              </div>
              <div style={{ color: "#555", fontSize: "0.9rem" }}>
                {doc.specialty} · {doc.proximity_km.toFixed(1)} km away
                {typeof doc.rating === "number" && (
                  <> · rated {doc.rating.toFixed(1)}</>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
