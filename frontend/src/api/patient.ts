/**
 * Patient-facing API calls for the Patient_Dashboard (task 19.1).
 *
 * Every call reuses the shared `request` helper from `client.ts` with
 * `{ auth: true }` so the stored Bearer token is attached; the backend gates
 * each route to the Patient role. The types here mirror the backend's Pydantic
 * response models in `backend/app/api/schemas.py` (patient dashboard section).
 *
 * This module is patient-only; it does not modify the shared client.
 */

import { ApiError, request } from "./client";

// ---------------------------------------------------------------------------
// Wire types (mirror backend/app/api/schemas.py)
// ---------------------------------------------------------------------------

/** Appointment lifecycle states (backend AppointmentState enum). */
export type AppointmentState =
  | "booked"
  | "accepted"
  | "completed"
  | "cancelled";

/** An appointment with its lifecycle state (R17.1). */
export interface Appointment {
  id: number;
  volunteer_id: number;
  service_type: string;
  state: AppointmentState;
  slot_start: string | null;
  slot_end: string | null;
  queued_for_review: boolean;
  reviewed: boolean;
}

/** One ranked Volunteer returned by a match request (R7.1). */
export interface MatchCandidate {
  volunteer_id: number;
  slot_id: number;
  volunteer_email: string;
  volunteer_name: string;
  score: number;
  distance_km: number;
  availability_count: number;
  qualification_count: number;
}

/** The ranked candidate list plus an optional no-volunteers message (R7.6). */
export interface MatchResponse {
  service_type: string;
  candidates: MatchCandidate[];
  message: string | null;
}

/** The confirmed booking returned on success (R8.1). */
export interface BookingResponse {
  appointment: Appointment;
  message: string;
}

/** An approved Clinical_Decision visible to the Patient (R17.3, R11.9). */
export interface Decision {
  id: number;
  appointment_id: number;
  content: string;
  approved: boolean;
}

/** An approved Referral visible to the Patient (R17.3). */
export interface Referral {
  id: number;
  appointment_id: number;
  specialty: string;
}

/** An approved, verified-prescribed Medication visible to the Patient (R13.1). */
export interface Medication {
  id: number;
  name: string;
  approved: boolean;
}

/** Insurance-compatibility status for a recommended doctor (R14, R17.4). */
export type InsuranceStatus = "compatible" | "incompatible" | "unknown";

/** One ranked provider with the fields the dashboard shows (R17.4). */
export interface RecommendedDoctor {
  id: number;
  name: string;
  specialty: string;
  rating: number | null;
  proximity_km: number;
  score: number;
  insurance_status: InsuranceStatus;
}

/** The ranked doctor list plus engine advisories (R15/R16). */
export interface RecommendationResponse {
  doctors: RecommendedDoctor[];
  message: string | null;
  insurance_asserted: boolean;
}

/** A nearby MA hospital ranked by ZIP-code proximity (bundled CMS data). */
export interface Hospital {
  facility_name: string;
  address: string;
  citytown: string;
  zip_code: string;
  telephone_number: string;
  hospital_type: string;
  /** Passed through verbatim, including "Not Available". */
  hospital_overall_rating: string;
  /** Absolute numeric ZIP difference used for ranking (smaller is closer). */
  zip_distance: number;
}

// ---------------------------------------------------------------------------
// Request bodies
// ---------------------------------------------------------------------------

/** Request to rank authorized Volunteers for a service at a time window (R7.1). */
export interface MatchRequestBody {
  service_type: string;
  /** ISO-8601 start of the chosen window. */
  start: string;
  /** ISO-8601 end of the chosen window. */
  end: string;
  weights?: [number, number, number];
}

/** Request to book a specific Volunteer slot (R8.1). */
export interface BookRequestBody {
  volunteer_id: number;
  slot_id: number;
  service_type: string;
  requested_start?: string;
  requested_end?: string;
}

// ---------------------------------------------------------------------------
// API calls
// ---------------------------------------------------------------------------

/** Rank authorized, available Volunteers for the Patient's request (R7.1). */
export function requestMatch(body: MatchRequestBody): Promise<MatchResponse> {
  return request<MatchResponse>("/patient/matches", {
    method: "POST",
    body,
    auth: true,
  });
}

/**
 * Book a selected Volunteer + slot for a Service_Type (R8.1).
 *
 * The backend maps the booking gates to HTTP: slot-unavailable -> 409,
 * not-authorized / consent-required -> 403. Those surface as `ApiError` with
 * the `code` set to the backend message; the caller inspects `code` to render
 * the consent gate and booking errors.
 */
export function bookVisit(body: BookRequestBody): Promise<BookingResponse> {
  return request<BookingResponse>("/patient/bookings", {
    method: "POST",
    body,
    auth: true,
  });
}

/** List the Patient's appointments with their lifecycle states (R17.1). */
export function listAppointments(): Promise<Appointment[]> {
  return request<Appointment[]>("/patient/appointments", { auth: true });
}

/** List only Clinician-approved Clinical_Decisions (R17.3, R11.9). */
export function listDecisions(): Promise<Decision[]> {
  return request<Decision[]>("/patient/decisions", { auth: true });
}

/** List only approved Referrals (R17.3). */
export function listReferrals(): Promise<Referral[]> {
  return request<Referral[]>("/patient/referrals", { auth: true });
}

/** List only approved, verified-prescribed Medications (R13.1). */
export function listMedications(): Promise<Medication[]> {
  return request<Medication[]>("/patient/medications", { auth: true });
}

/** Return ranked Recommended_Doctors for the Patient (R15, R16, R17.4). */
export function getRecommendations(
  weights?: [number, number, number, number],
): Promise<RecommendationResponse> {
  return request<RecommendationResponse>("/patient/recommendations", {
    method: "POST",
    body: weights ? { weights } : {},
    auth: true,
  });
}

/** List nearby MA hospitals ranked by the Patient's ZIP (bundled CMS data). */
export function listHospitals(): Promise<Hospital[]> {
  return request<Hospital[]>("/patient/hospitals", { auth: true });
}

/**
 * Human-readable message for a booking failure, keyed off the backend's
 * stable `code`. Surfaces the consent gate (R17.2) distinctly from the other
 * booking errors.
 */
export function bookingErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    switch (err.code) {
      case "consent-required":
        return "Consent is required before booking. Please record your consent to proceed.";
      case "not-authorized":
        return "The selected volunteer is not authorized for this service.";
      case "slot-unavailable":
        return "That slot was just taken. Please request a new match and try another.";
      default:
        return err.message || "Booking failed. Please try again.";
    }
  }
  return "Booking failed. Please try again.";
}
