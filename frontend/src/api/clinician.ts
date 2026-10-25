/**
 * Clinician dashboard API calls (task 21.1).
 *
 * Thin wrappers over the shared `request` helper for the Bearer-gated
 * `/clinician/*` routes (see backend/app/api/clinician.py). Each call attaches
 * the clinician's token via `{ auth: true }` and returns the backend's typed
 * response shape. All domain errors surface as `ApiError` from the client, so
 * callers inspect `err.status` / `err.code` to render the right message:
 *
 *  - record decision: 400 `decision-content-required`, 403 `credential-not-verified`
 *  - approve decision: 409 `no-decision-to-approve`
 *  - findings: 409 `not-ready-for-review`
 *  - referral: 400 (empty specialty), 409 `no-decision-to-approve`
 */

import { request } from "./client";

/** One completed appointment awaiting review (R19.1). Mirrors `ReviewQueueItem`. */
export interface ReviewQueueItem {
  appointment_id: number;
  patient_id: number;
  volunteer_id: number;
  service_type: string;
  state: string;
  queued_for_review: boolean;
  reviewed: boolean;
}

/** A questionnaire's recorded answers, for the findings view (R19.2). */
export interface QuestionnaireFinding {
  id: number;
  service_type: string;
  answers?: string | null;
}

/** A recorded Test_Result, for the findings view (R19.2). */
export interface TestResultFinding {
  id: number;
  measurement: string;
  value?: number | null;
  unit?: string | null;
}

/** The findings opened for a completed appointment (R19.2). */
export interface FindingsResponse {
  appointment_id: number;
  questionnaires: QuestionnaireFinding[];
  test_results: TestResultFinding[];
}

/** A Clinical_Decision projected for the clinician's own view (R19.3, R19.4). */
export interface ClinicianDecisionResponse {
  id: number;
  appointment_id: number;
  content: string;
  reviewed: boolean;
  approved: boolean;
}

/** A Referral projected for the clinician's own view (R19.3). */
export interface ClinicianReferralResponse {
  id: number;
  appointment_id: number;
  patient_id: number;
  specialty: string;
}

/** A bundled MA hospital for the referral dropdown. Mirrors `HospitalResponse`. */
export interface ClinicianHospital {
  facility_name: string;
  address: string;
  citytown: string;
  zip_code: string;
  telephone_number: string;
  hospital_type: string;
  hospital_overall_rating: string;
  zip_distance: number;
}

/**
 * GET the review queue: completed appointments still queued for review (R19.1).
 */
export function fetchReviewQueue(): Promise<ReviewQueueItem[]> {
  return request<ReviewQueueItem[]>("/clinician/review-queue", { auth: true });
}

/**
 * GET an appointment's findings — submitted questionnaires + test results (R19.2).
 * A not-ready appointment rejects with 409 `not-ready-for-review`.
 */
export function fetchFindings(appointmentId: number): Promise<FindingsResponse> {
  return request<FindingsResponse>(
    `/clinician/appointments/${appointmentId}/findings`,
    { auth: true },
  );
}

/**
 * POST a clinical decision for a queued appointment (R19.3).
 * Rejects 400 `decision-content-required` (empty) or 403
 * `credential-not-verified` (unverified license), persisting nothing.
 */
export function recordDecision(
  appointmentId: number,
  content: string,
): Promise<ClinicianDecisionResponse> {
  return request<ClinicianDecisionResponse>(
    `/clinician/appointments/${appointmentId}/decision`,
    { method: "POST", body: { content }, auth: true },
  );
}

/**
 * POST to approve the appointment's stored decision, making it patient-visible
 * (R19.4). Rejects 409 `no-decision-to-approve` when none is stored.
 */
export function approveDecision(
  appointmentId: number,
): Promise<ClinicianDecisionResponse> {
  return request<ClinicianDecisionResponse>(
    `/clinician/appointments/${appointmentId}/decision/approve`,
    { method: "POST", auth: true },
  );
}

/**
 * GET the full list of bundled MA hospitals for the referral dropdown (R19.3).
 */
export function fetchHospitals(): Promise<ClinicianHospital[]> {
  return request<ClinicianHospital[]>("/clinician/hospitals", { auth: true });
}

/**
 * POST a specialty referral from the reviewed decision (R19.3).
 * Rejects 400 (empty specialty) or 409 `no-decision-to-approve`.
 */
export function issueReferral(
  appointmentId: number,
  specialty: string,
): Promise<ClinicianReferralResponse> {
  return request<ClinicianReferralResponse>(
    `/clinician/appointments/${appointmentId}/referral`,
    { method: "POST", body: { specialty }, auth: true },
  );
}
