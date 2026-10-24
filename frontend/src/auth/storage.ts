/**
 * Persistence for the authenticated session (token + role + subject).
 *
 * The session lives in localStorage so a page reload keeps the user signed in.
 * This module is the single reader/writer of that key; the auth context layers
 * React state on top of it.
 */

import type { Role, SessionResponse } from "../api/types";
import { isRole } from "../api/types";

const STORAGE_KEY = "careconnect.session";

/** The persisted session. Mirrors the API's `SessionResponse`. */
export interface StoredSession {
  token: string;
  role: Role;
  subjectId: number;
}

/** Read the persisted session, or null if absent/corrupt. */
export function loadSession(): StoredSession | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<StoredSession>;
    if (
      typeof parsed.token === "string" &&
      isRole(parsed.role) &&
      typeof parsed.subjectId === "number"
    ) {
      return { token: parsed.token, role: parsed.role, subjectId: parsed.subjectId };
    }
  } catch {
    // fall through to clearing a corrupt value
  }
  clearSession();
  return null;
}

/** Persist a session (accepts the API response shape directly). */
export function saveSession(session: SessionResponse): StoredSession {
  const stored: StoredSession = {
    token: session.token,
    role: session.role,
    subjectId: session.subjectId,
  };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(stored));
  return stored;
}

/** Remove the persisted session. */
export function clearSession(): void {
  localStorage.removeItem(STORAGE_KEY);
}

/** The current token, or null — used by the API client's token reader. */
export function currentToken(): string | null {
  return loadSession()?.token ?? null;
}
