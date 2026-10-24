/**
 * Auth context definition and the `useAuth` hook.
 *
 * Kept separate from the provider component so the context value type and the
 * hook can be imported without pulling in the provider's React tree.
 */

import { createContext, useContext } from "react";
import type { Role } from "../api/types";
import type { StoredSession } from "./storage";

/** What the rest of the app consumes to read and mutate auth state. */
export interface AuthContextValue {
  /** The current session, or null when signed out. */
  session: StoredSession | null;
  /** True while the initial session restore is in flight. */
  loading: boolean;
  /** Convenience: the current role, or null. */
  role: Role | null;
  /** Authenticate and persist on success; throws `ApiError` on failure. */
  signIn: (email: string, password: string) => Promise<StoredSession>;
  /** Clear the session and local state. */
  signOut: () => void;
}

export const AuthContext = createContext<AuthContextValue | undefined>(undefined);

/** Access the auth context. Throws if used outside <AuthProvider>. */
export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (ctx === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}
