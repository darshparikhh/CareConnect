/**
 * Typed HTTP client for the CareConnect backend.
 *
 * Responsibilities:
 *  - resolve the base URL (VITE_API_BASE_URL, default http://localhost:8000),
 *  - attach the stored Bearer token to authenticated requests,
 *  - parse FastAPI's `{ detail: ... }` error envelope into a typed `ApiError`
 *    on any non-2xx response,
 *  - expose the handful of calls the sign-in flow and session handling need.
 *
 * The dashboard tasks (19-21) add their own calls on top of `request`.
 */

import type { ApiErrorDetail, Role, SessionResponse } from "./types";
import { isRole } from "./types";

/** Base URL of the backend, configurable at build time, with a dev default. */
export const API_BASE_URL: string =
  import.meta.env.VITE_API_BASE_URL?.replace(/\/+$/, "") ?? "http://localhost:8000";

/**
 * A typed error for any non-2xx API response.
 *
 * `code` is the backend's uniform message (e.g. "authentication-failed"),
 * `redirect` is set when the backend wants the client to bounce to a route
 * (the unauthenticated-session case points at "/sign-in", R4.6), and
 * `missingFields` surfaces registration validation gaps.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly code?: string;
  readonly redirect?: string;
  readonly missingFields?: string[];

  constructor(
    status: number,
    detail?: ApiErrorDetail | string,
    fallbackMessage?: string,
  ) {
    const parsed = ApiError.parseDetail(detail);
    super(parsed.message ?? fallbackMessage ?? `Request failed (${status})`);
    this.name = "ApiError";
    this.status = status;
    this.code = parsed.message;
    this.redirect = parsed.redirect;
    this.missingFields = parsed.missing_fields;
  }

  /** Was this an authentication failure (bad credentials)? */
  get isAuthFailed(): boolean {
    return this.status === 401 && this.code === "authentication-failed";
  }

  /** Is this an unauthenticated response the client should redirect on (R4.6)? */
  get isUnauthenticated(): boolean {
    return this.status === 401 && typeof this.redirect === "string";
  }

  private static parseDetail(
    detail?: ApiErrorDetail | string,
  ): ApiErrorDetail {
    if (!detail) return {};
    if (typeof detail === "string") return { message: detail };
    return detail;
  }
}

/** Options accepted by the low-level `request` helper. */
interface RequestOptions {
  method?: string;
  /** JSON body; serialized automatically. */
  body?: unknown;
  /** Attach the stored Bearer token. Defaults to false (public call). */
  auth?: boolean;
  /** Explicit token override (used before a token is persisted). */
  token?: string | null;
  signal?: AbortSignal;
}

/** Reads the Bearer token from the persisted session, if any. */
type TokenReader = () => string | null;

// Set by the auth layer so the client can attach the current token without a
// hard dependency on the storage module. Defaults to a no-op reader.
let tokenReader: TokenReader = () => null;

/** Register how the client should obtain the current Bearer token. */
export function setTokenReader(reader: TokenReader): void {
  tokenReader = reader;
}

/**
 * Perform a request against the API and return parsed JSON, or throw `ApiError`
 * on any non-2xx response. A 204/empty body resolves to `undefined`.
 */
export async function request<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const { method = "GET", body, auth = false, token, signal } = options;

  const headers: Record<string, string> = {};
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
  }

  const bearer = token !== undefined ? token : auth ? tokenReader() : null;
  if (bearer) {
    headers["Authorization"] = `Bearer ${bearer}`;
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal,
  });

  if (!response.ok) {
    throw await errorFromResponse(response);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const text = await response.text();
  if (!text) {
    return undefined as T;
  }
  return JSON.parse(text) as T;
}

/** Build a typed `ApiError` from a failed response, tolerating non-JSON bodies. */
async function errorFromResponse(response: Response): Promise<ApiError> {
  let detail: ApiErrorDetail | string | undefined;
  try {
    const data = (await response.json()) as { detail?: ApiErrorDetail | string };
    detail = data?.detail;
  } catch {
    detail = undefined;
  }
  return new ApiError(response.status, detail);
}

/** Raw shape returned by the backend's session endpoints. */
interface RawSessionResponse {
  token: string;
  role: string;
  subject_id: number;
}

function toSessionResponse(raw: RawSessionResponse): SessionResponse {
  if (!isRole(raw.role)) {
    throw new ApiError(500, `Unexpected role from server: ${raw.role}`);
  }
  return { token: raw.token, role: raw.role as Role, subjectId: raw.subject_id };
}

/**
 * Authenticate with email + password (R4.1, R4.2).
 * Throws `ApiError` with `isAuthFailed` true on invalid credentials.
 */
export async function signIn(
  email: string,
  password: string,
): Promise<SessionResponse> {
  const raw = await request<RawSessionResponse>("/auth/sign-in", {
    method: "POST",
    body: { email, password },
  });
  return toSessionResponse(raw);
}

/**
 * Fetch the current session using the stored Bearer token (R4.6).
 * Throws `ApiError` with `isUnauthenticated` true when no valid session.
 */
export async function getSession(
  token?: string | null,
): Promise<SessionResponse> {
  const raw = await request<RawSessionResponse>("/auth/session", {
    auth: token === undefined,
    token: token,
  });
  return toSessionResponse(raw);
}
