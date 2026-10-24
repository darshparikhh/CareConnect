/**
 * Volunteer-facing API calls backing the Volunteer_Dashboard (R18).
 *
 * Thin wrappers over the shared `request` helper from `./client`, each hitting
 * a route under the Bearer-gated `/volunteer` prefix (see backend
 * app/api/volunteer.py). The wire shapes mirror the backend's Pydantic
 * response models in app/api/schemas.py.
 *
 * Every call passes `{ auth: true }` so the client attaches the stored Bearer
 * token; a wrong-role or unauthenticated session is rejected by the backend
 * before any handler runs. Domain rejections (slot-has-appointment,
 * invalid-transition, unauthorized-service, missing-required-questions,
 * wrong-state) surface as `ApiError` with the backend's `code`/`message`,
 * which the dashboard components translate into user-facing text.
 */

import { ApiError, request } from "./client";

export { ApiError };

/** An availability slot as projected by the backend (SlotResponse). */
export interface VolunteerSlot {
  id: number;
  /** ISO-8601 start timestamp. */
  start: string;
  /** ISO-8601 end timestamp. */
  end: string;
  /** Slot status, e.g. "available" | "booked" | "unavailable". */
  status: string;
}

/** An assigned appointment with its lifecycle state (VolunteerAppointmentResponse). */
export interface VolunteerAppointment {
  id: number;
  patient_id: number;
  service_type: string;
  state: string;
  slot_start: string | null;
  slot_end: string | null;
  queued_for_review: boolean;
  reviewed: boolean;
}

/** A Service_Type summary shown in the visit detail (ServiceTypeSummary). */
export interface ServiceTypeSummary {
  id: number;
  name: string;
}

/** A geographic point (Location). */
export interface VisitLocation {
  lat: number;
  lng: number;
}

/**
 * The visit detail for an assigned appointment (VisitDetailResponse).
 *
 * `authorized_services` lists ONLY the Service_Types this Volunteer is
 * currently authorized to perform — never the full catalog (R9.2, R18.4).
 */
export interface VisitDetail {
  requested_service_type: ServiceTypeSummary;
  location: VisitLocation;
  authorized_services: ServiceTypeSummary[];
}

/** The outcome of a questionnaire/test submission (SubmissionResponse). */
export interface SubmissionResult {
  ok: boolean;
  message: string;
  /** True when this submission completed the required data set (R10.5). */
  completed: boolean;
}

/** A single information-only Test_Result to submit (TestResultSubmission). */
export interface TestResultInput {
  measurement: string;
  value?: number | null;
  unit?: string | null;
}

// ---------------------------------------------------------------------------
// Availability management (R6, R18.2)
// ---------------------------------------------------------------------------

/** List the Volunteer's availability slots (R6). */
export function listSlots(): Promise<VolunteerSlot[]> {
  return request<VolunteerSlot[]>("/volunteer/slots", { auth: true });
}

/** Add a new availability slot; start/end are ISO-8601 strings (R6.1). */
export function addSlot(start: string, end: string): Promise<VolunteerSlot> {
  return request<VolunteerSlot>("/volunteer/slots", {
    method: "POST",
    auth: true,
    body: { start, end },
  });
}

/**
 * Remove an availability slot (R6.2).
 *
 * A slot holding an assigned appointment is rejected with
 * `409 slot-has-appointment` (R6.3), surfaced as an `ApiError`.
 */
export function removeSlot(slotId: number): Promise<VolunteerSlot> {
  return request<VolunteerSlot>(`/volunteer/slots/${slotId}`, {
    method: "DELETE",
    auth: true,
  });
}

// ---------------------------------------------------------------------------
// Assigned appointments + lifecycle (R18.1, R8.6, R8.7)
// ---------------------------------------------------------------------------

/** List the Volunteer's assigned appointments with their states (R18.1). */
export function listAppointments(): Promise<VolunteerAppointment[]> {
  return request<VolunteerAppointment[]>("/volunteer/appointments", {
    auth: true,
  });
}

/** Accept an assigned appointment: booked -> accepted (R8.6). */
export function acceptAppointment(
  appointmentId: number,
): Promise<VolunteerAppointment> {
  return request<VolunteerAppointment>(
    `/volunteer/appointments/${appointmentId}/accept`,
    { method: "POST", auth: true },
  );
}

/** Decline an assigned appointment: booked -> cancelled (R8.7). */
export function declineAppointment(
  appointmentId: number,
): Promise<VolunteerAppointment> {
  return request<VolunteerAppointment>(
    `/volunteer/appointments/${appointmentId}/decline`,
    { method: "POST", auth: true },
  );
}

// ---------------------------------------------------------------------------
// Visit detail — authorized services only (R9.1, R9.2, R18.4)
// ---------------------------------------------------------------------------

/**
 * Open the visit detail for an assigned appointment (R9.1, R9.2, R18.4).
 *
 * The backend returns only the Service_Types this Volunteer is authorized to
 * perform — never the full catalog.
 */
export function getVisitDetail(appointmentId: number): Promise<VisitDetail> {
  return request<VisitDetail>(
    `/volunteer/appointments/${appointmentId}/visit`,
    { auth: true },
  );
}

// ---------------------------------------------------------------------------
// Questionnaire / test-result submission (R10.1, R10.3, R18.3)
// ---------------------------------------------------------------------------

/**
 * Submit questionnaire answers for an accepted, authorized visit (R10.1).
 *
 * Rejections surface as `ApiError`: unauthorized-service (403),
 * missing-required-questions (400, with `missingFields`), wrong state (409).
 */
export function submitQuestionnaire(
  appointmentId: number,
  answers: Record<string, unknown>,
): Promise<SubmissionResult> {
  return request<SubmissionResult>(
    `/volunteer/appointments/${appointmentId}/questionnaire`,
    { method: "POST", auth: true, body: { answers } },
  );
}

/**
 * Submit an information-only Test_Result for an accepted visit (R10.3).
 *
 * Rejections surface as `ApiError`: unauthorized-service (403), wrong state
 * (409), or a measurement/validation error (400).
 */
export function submitTestResult(
  appointmentId: number,
  result: TestResultInput,
): Promise<SubmissionResult> {
  return request<SubmissionResult>(
    `/volunteer/appointments/${appointmentId}/test-result`,
    {
      method: "POST",
      auth: true,
      body: {
        measurement: result.measurement,
        value: result.value ?? null,
        unit: result.unit ?? null,
      },
    },
  );
}
