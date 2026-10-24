/**
 * AuthProvider: owns session state and wires the API client to storage.
 *
 * On mount it restores any persisted session and validates it against
 * `GET /auth/session`; an invalid/expired token is cleared so the user lands
 * on sign-in (R4.6). It also registers the token reader the API client uses to
 * attach the Bearer header on authenticated calls.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import type { Role } from "../api/types";
import { ApiError, getSession, setTokenReader, signIn as apiSignIn } from "../api/client";
import { AuthContext } from "./AuthContext";
import type { AuthContextValue } from "./AuthContext";
import {
  clearSession,
  currentToken,
  loadSession,
  saveSession,
} from "./storage";
import type { StoredSession } from "./storage";

// Attach the persisted token to every authenticated request.
setTokenReader(currentToken);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<StoredSession | null>(() => loadSession());
  const [loading, setLoading] = useState<boolean>(true);

  // Validate a restored token against the backend once on mount.
  useEffect(() => {
    let cancelled = false;
    const restored = loadSession();

    if (!restored) {
      setLoading(false);
      return;
    }

    getSession(restored.token)
      .then((fresh) => {
        if (cancelled) return;
        setSession(saveSession(fresh));
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        // Any auth error (expired/invalid token) clears the session.
        if (err instanceof ApiError && err.status === 401) {
          clearSession();
          setSession(null);
        }
        // Non-auth errors (e.g. backend down) keep the optimistic local session.
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    const response = await apiSignIn(email, password);
    const stored = saveSession(response);
    setSession(stored);
    return stored;
  }, []);

  const signOut = useCallback(() => {
    clearSession();
    setSession(null);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      session,
      loading,
      role: (session?.role ?? null) as Role | null,
      signIn,
      signOut,
    }),
    [session, loading, signIn, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
