/**
 * Shared API types mirroring the CareConnect FastAPI contract.
 *
 * These shapes track the backend's Pydantic schemas (see
 * backend/app/api/schemas.py). Keep them in sync when the API changes.
 */

/** The three roles CareConnect recognizes. Matches the backend `Role` enum. */
export type Role = "patient" | "volunteer" | "clinician";

/** All valid roles as a runtime list, for guards and iteration. */
export const ROLES: readonly Role[] = ["patient", "volunteer", "clinician"];

/** Narrow an arbitrary string to a known Role. */
export function isRole(value: unknown): value is Role {
  return typeof value === "string" && (ROLES as readonly string[]).includes(value);
}

/**
 * Successful sign-in / session response.
 * Matches `SessionResponse` on the backend: { token, role, subject_id }.
 */
export interface SessionResponse {
  token: string;
  role: Role;
  subjectId: number;
}

/**
 * The error body FastAPI returns under `detail` for auth and validation
 * failures. `message` carries the uniform error code (e.g.
 * "authentication-failed"); `redirect` is present on the unauthenticated
 * session case (R4.6); `missing_fields` names registration gaps.
 */
export interface ApiErrorDetail {
  message?: string;
  redirect?: string;
  missing_fields?: string[];
}
