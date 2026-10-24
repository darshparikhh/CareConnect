/**
 * Nearby MA hospitals ranked by the Patient's ZIP (demo feature).
 *
 * Reads GET /patient/hospitals, which ranks a locally bundled CMS dataset by
 * ZIP-code proximity to the Patient's ZIP (the CMS API blocks server-side
 * calls, so the data ships offline). This surfaces the post-referral "here are
 * hospitals near you" step on the patient dashboard. Rendering only: all
 * ranking happens in the backend service.
 */
import { useCallback } from "react";
import type { Hospital } from "../../api/patient";
import { listHospitals } from "../../api/patient";
import { Card, ErrorNote, Note, Pill } from "./shared";
import type { Tone } from "./shared";
import { useAsyncData } from "./shared";

/** Map a CMS 1–5 overall rating (or "Not Available") to a status tone. */
function ratingTone(rating: string): Tone {
  const n = Number.parseInt(rating, 10);
  if (Number.isNaN(n)) return "neutral";
  if (n >= 4) return "success";
  if (n >= 3) return "info";
  return "warning";
}

function ratingLabel(rating: string): string {
  const n = Number.parseInt(rating, 10);
  return Number.isNaN(n) ? "Rating N/A" : `Rated ${n}/5`;
}

export function NearbyHospitalsSection() {
  const loader = useCallback(() => listHospitals(), []);
  const { data, loading, error } = useAsyncData<Hospital[]>(loader);
  const hospitals = data ?? [];

  return (
    <Card title="Nearby hospitals">
      {loading && <Note>Loading nearby hospitals…</Note>}
      {error && <ErrorNote>{error}</ErrorNote>}
      {!loading && !error && hospitals.length === 0 && (
        <Note>No nearby hospitals found.</Note>
      )}
      {!loading && !error && hospitals.length > 0 && (
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {hospitals.map((h, index) => (
            <li
              key={`${h.facility_name}-${h.zip_code}-${index}`}
              style={{
                padding: "0.6rem 0",
                borderBottom: "1px solid var(--cc-border)",
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
                  {index + 1}. {h.facility_name}
                </strong>
                <Pill
                  label={ratingLabel(h.hospital_overall_rating)}
                  tone={ratingTone(h.hospital_overall_rating)}
                />
              </div>
              <div style={{ color: "#9aa8c0", fontSize: "0.9rem" }}>
                {h.citytown}, MA {h.zip_code} · {h.hospital_type}
              </div>
              {h.telephone_number && (
                <div style={{ color: "#9aa8c0", fontSize: "0.9rem" }}>
                  {h.telephone_number}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
