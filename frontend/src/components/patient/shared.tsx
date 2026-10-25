/**
 * Small shared helpers for the patient dashboard components (task 19.1).
 *
 * Keeps styling minimal and co-located so each section component stays focused
 * on its data. Nothing here is patient-business-logic; it is presentation only.
 */

import type { CSSProperties, ReactNode } from "react";
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError } from "../../api/client";
import { clearSession } from "../../auth/storage";

/** A dashboard card with a title and body. */
export function Card({
  title,
  children,
  actions,
}: {
  title: string;
  children: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <section style={cardStyle}>
      <div style={cardHeaderStyle}>
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{title}</h2>
        {actions}
      </div>
      <div>{children}</div>
    </section>
  );
}

/** A small colored status pill. */
export function Pill({ label, tone }: { label: string; tone: Tone }) {
  return <span style={{ ...pillStyle, ...toneStyle[tone] }}>{label}</span>;
}

export type Tone = "neutral" | "info" | "success" | "warning" | "danger";

/** Inline error/empty/loading message. */
export function Note({ children }: { children: ReactNode }) {
  return <p style={{ color: "#555", margin: "0.25rem 0" }}>{children}</p>;
}

/** Inline error message styled distinctly. */
export function ErrorNote({ children }: { children: ReactNode }) {
  return (
    <p style={{ color: "#b00020", margin: "0.25rem 0" }} role="alert">
      {children}
    </p>
  );
}

/**
 * Generic async-data hook: runs `loader` on mount and exposes
 * data / loading / error plus a `reload` callback. Converts `ApiError` into a
 * readable message.
 */
export function useAsyncData<T>(
  loader: () => Promise<T>,
  deps: ReadonlyArray<unknown> = [],
): {
  data: T | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
} {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  const navigate = useNavigate();

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    loader()
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        // A 401 means the stored session is missing/stale/invalid. Rather than
        // splashing "authentication-required" across every card, clear the bad
        // session and send the user to sign in cleanly.
        if (err instanceof ApiError && err.status === 401) {
          clearSession();
          navigate("/sign-in", { replace: true });
          return;
        }
        setError(
          err instanceof ApiError
            ? err.message
            : "Something went wrong loading this section.",
        );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick, ...deps]);

  return { data, loading, error, reload };
}

/** Format an ISO timestamp for display, tolerating null. */
export function formatDateTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}

// ---------------------------------------------------------------------------
// Styles (minimal, inline to avoid adding a CSS pipeline)
// ---------------------------------------------------------------------------

const cardStyle: CSSProperties = {
  border: "1px solid var(--cc-border)",
  borderRadius: 10,
  padding: "1.1rem 1.15rem",
  marginBottom: "1.15rem",
  background: "var(--cc-surface)",
  boxShadow: "var(--cc-shadow)",
};

const cardHeaderStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  marginBottom: "0.75rem",
};

const pillStyle: CSSProperties = {
  display: "inline-block",
  padding: "0.1rem 0.5rem",
  borderRadius: 999,
  fontSize: "0.8rem",
  fontWeight: 600,
};

const toneStyle: Record<Tone, CSSProperties> = {
  neutral: { background: "rgba(154,168,192,0.16)", color: "#c7d2e4", border: "1px solid rgba(154,168,192,0.35)" },
  info: { background: "rgba(77,132,196,0.18)", color: "#8fc0f0", border: "1px solid rgba(77,132,196,0.45)" },
  success: { background: "var(--cc-success-bg)", color: "var(--cc-success)", border: "1px solid rgba(111,207,151,0.4)" },
  warning: { background: "var(--cc-warning-bg)", color: "var(--cc-warning)", border: "1px solid rgba(228,179,99,0.4)" },
  danger: { background: "var(--cc-danger-bg)", color: "var(--cc-danger)", border: "1px solid rgba(229,118,123,0.4)" },
};
