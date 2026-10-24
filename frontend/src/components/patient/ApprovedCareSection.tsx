/**
 * Approved-only clinical care: decisions, referrals, and medications.
 *
 * The backend already withholds anything unapproved (R17.3, R11.9) and anything
 * not verified-prescribed-and-approved (R13.1); these routes return only what
 * the Patient is allowed to see. This component renders exactly what the API
 * returns, so the approval gate is enforced server-side and simply reflected
 * here.
 */

import { useCallback } from "react";
import type { Decision, Medication, Referral } from "../../api/patient";
import {
  listDecisions,
  listMedications,
  listReferrals,
} from "../../api/patient";
import { Card, ErrorNote, Note } from "./shared";
import { useAsyncData } from "./shared";

export function ApprovedCareSection() {
  const decisionsLoader = useCallback(() => listDecisions(), []);
  const referralsLoader = useCallback(() => listReferrals(), []);
  const medsLoader = useCallback(() => listMedications(), []);

  const decisions = useAsyncData<Decision[]>(decisionsLoader);
  const referrals = useAsyncData<Referral[]>(referralsLoader);
  const medications = useAsyncData<Medication[]>(medsLoader);

  return (
    <Card title="Approved results">
      <p style={{ color: "#555", margin: "0 0 0.75rem", fontSize: "0.85rem" }}>
        Decisions, referrals, and medications appear here only after a clinician
        has approved them.
      </p>

      <h3 style={subHeadStyle}>Clinical decisions</h3>
      {decisions.loading && <Note>Loading…</Note>}
      {decisions.error && <ErrorNote>{decisions.error}</ErrorNote>}
      {!decisions.loading &&
        !decisions.error &&
        (decisions.data?.length ?? 0) === 0 && (
          <Note>No approved decisions yet.</Note>
        )}
      {!decisions.loading && !decisions.error && decisions.data && (
        <ul style={listStyle}>
          {decisions.data.map((d) => (
            <li key={d.id} style={itemStyle}>
              {d.content}
            </li>
          ))}
        </ul>
      )}

      <h3 style={subHeadStyle}>Referrals</h3>
      {referrals.loading && <Note>Loading…</Note>}
      {referrals.error && <ErrorNote>{referrals.error}</ErrorNote>}
      {!referrals.loading &&
        !referrals.error &&
        (referrals.data?.length ?? 0) === 0 && (
          <Note>No approved referrals yet.</Note>
        )}
      {!referrals.loading && !referrals.error && referrals.data && (
        <ul style={listStyle}>
          {referrals.data.map((r) => (
            <li key={r.id} style={itemStyle}>
              Referral to <strong>{r.specialty}</strong>
            </li>
          ))}
        </ul>
      )}

      <h3 style={subHeadStyle}>Medications</h3>
      {medications.loading && <Note>Loading…</Note>}
      {medications.error && <ErrorNote>{medications.error}</ErrorNote>}
      {!medications.loading &&
        !medications.error &&
        (medications.data?.length ?? 0) === 0 && (
          <Note>No approved medications.</Note>
        )}
      {!medications.loading && !medications.error && medications.data && (
        <ul style={listStyle}>
          {medications.data.map((m) => (
            <li key={m.id} style={itemStyle}>
              {m.name}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

const subHeadStyle = {
  fontSize: "0.95rem",
  margin: "0.75rem 0 0.25rem",
};

const listStyle = {
  listStyle: "none" as const,
  padding: 0,
  margin: 0,
};

const itemStyle = {
  padding: "0.4rem 0",
  borderBottom: "1px solid #eee",
};
