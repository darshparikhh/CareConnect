/**
 * Shared helpers and inline styles for the Volunteer_Dashboard views (R18).
 *
 * Kept volunteer-local (not in a shared module) so this task owns its own
 * presentation without touching files other parallel tasks edit. The styling
 * is intentionally minimal but usable: plain cards, buttons, and badges.
 */

import type { CSSProperties } from "react";
import { ApiError } from "../../api/volunteer";

/** Format an ISO-8601 timestamp for display, tolerating null/invalid input. */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/**
 * Translate an unknown error into user-facing text, mapping the backend's
 * stable error codes (R6.3, R8.x, R9.3, R10.x) to friendly messages.
 */
export function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    switch (err.code) {
      case "slot-has-appointment":
        return "This slot has an assigned appointment and can't be removed.";
      case "invalid-transition":
        return "That action isn't allowed for this appointment's current state.";
      case "unauthorized-service":
        return "You're not authorized to perform this service for this visit.";
      case "missing-required-questions":
        return err.missingFields && err.missingFields.length > 0
          ? `Missing required answers: ${err.missingFields.join(", ")}.`
          : "Some required questions are unanswered.";
      case "measurement-required":
        return "A measurement is required.";
      default:
        return err.message;
    }
  }
  if (err instanceof Error) return err.message;
  return "Something went wrong. Please try again.";
}

/** A human label for a lifecycle state value. */
export function stateLabel(state: string): string {
  return state
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

export const styles: Record<string, CSSProperties> = {
  section: {
    marginTop: "1.5rem",
  },
  card: {
    border: "1px solid var(--cc-border)",
    borderRadius: "10px",
    padding: "1.1rem 1.15rem",
    marginBottom: "0.85rem",
    background: "var(--cc-surface)",
    boxShadow: "var(--cc-shadow)",
  },
  cardHeader: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "0.75rem",
  },
  badge: {
    display: "inline-block",
    padding: "0.15rem 0.55rem",
    borderRadius: "999px",
    background: "rgba(77,132,196,0.18)",
    color: "#8fc0f0",
    border: "1px solid rgba(77,132,196,0.45)",
    fontSize: "0.8rem",
    fontWeight: 600,
    textTransform: "capitalize",
  },
  row: {
    display: "flex",
    flexWrap: "wrap",
    gap: "0.5rem",
    alignItems: "center",
  },
  button: {
    padding: "0.45rem 0.85rem",
    borderRadius: "7px",
    border: "1px solid var(--cc-border-strong)",
    background: "var(--cc-surface-2)",
    color: "var(--cc-text)",
    cursor: "pointer",
  },
  primaryButton: {
    padding: "0.45rem 0.9rem",
    borderRadius: "7px",
    border: "1px solid var(--cc-primary)",
    background: "var(--cc-primary)",
    color: "#ffffff",
    fontWeight: 600,
    cursor: "pointer",
  },
  error: {
    color: "var(--cc-danger)",
    margin: "0.5rem 0",
  },
  success: {
    color: "var(--cc-success)",
    margin: "0.5rem 0",
  },
  muted: {
    color: "var(--cc-text-muted)",
  },
  input: {
    padding: "0.5rem 0.6rem",
    borderRadius: "7px",
    border: "1px solid var(--cc-border-strong)",
    background: "#0f1a30",
    color: "var(--cc-text)",
  },
  label: {
    display: "flex",
    flexDirection: "column",
    gap: "0.25rem",
    fontSize: "0.9rem",
  },
};
