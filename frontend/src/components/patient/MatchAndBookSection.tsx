/**
 * Request-match-and-book flow (R17.2) with the consent gate surfaced (R8.5).
 *
 * Flow:
 *  1. The Patient picks a Service_Type and a time window, then requests a match
 *     (POST /patient/matches) to get a ranked list of authorized Volunteers.
 *  2. The Patient books one candidate's slot (POST /patient/bookings).
 *
 * Booking errors from the backend are mapped to readable messages; the
 * consent-required gate is surfaced distinctly so the Patient knows consent
 * must be recorded before a booking can proceed. On a confirmed booking the
 * parent is notified so the appointments list refreshes.
 *
 * Note: the match result returns each candidate's covering slot id, so booking
 * sends that exact slot_id. The backend locks the slot and enforces all safety
 * gates; this UI only surfaces the outcome.
 */

import { useState } from "react";
import type { FormEvent } from "react";
import type { MatchCandidate, MatchResponse } from "../../api/patient";
import { bookVisit, bookingErrorMessage, requestMatch } from "../../api/patient";
import { ApiError } from "../../api/client";
import { Card, ErrorNote, Note } from "./shared";

/** Default service offered in the Boston flu demo seed. */
const DEFAULT_SERVICE_TYPE = "Vaccination";

/** Capitalize the first letter so the field always reads nicely as the user types. */
function capitalizeFirst(value: string): string {
  if (!value) return value;
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function toIsoOrNull(local: string): string | null {
  if (!local) return null;
  // A <input type="datetime-local"> yields a naive local string like
  // "2026-10-30T10:00" (no timezone). The backend stores and compares volunteer
  // availability in naive local time, so we must NOT convert to UTC here — a
  // UTC "Z" timestamp both shifts the hour and crashes the naive comparison.
  // Validate it parses, then pass the local value straight through, ensuring
  // it carries seconds ("...:00") for a consistent ISO-like shape.
  const d = new Date(local);
  if (Number.isNaN(d.getTime())) return null;
  return local.length === 16 ? `${local}:00` : local;
}

export function MatchAndBookSection({
  onBooked,
}: {
  onBooked: () => void;
}) {
  const [serviceType, setServiceType] = useState(DEFAULT_SERVICE_TYPE);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");

  const [matching, setMatching] = useState(false);
  const [matchError, setMatchError] = useState<string | null>(null);
  const [result, setResult] = useState<MatchResponse | null>(null);

  const [bookingId, setBookingId] = useState<number | null>(null);
  const [bookError, setBookError] = useState<string | null>(null);
  const [consentRequired, setConsentRequired] = useState(false);
  const [bookedMessage, setBookedMessage] = useState<string | null>(null);

  const handleMatch = async (e: FormEvent) => {
    e.preventDefault();
    const startIso = toIsoOrNull(start);
    const endIso = toIsoOrNull(end);
    setMatchError(null);
    setResult(null);
    setBookError(null);
    setConsentRequired(false);
    setBookedMessage(null);

    if (!serviceType.trim()) {
      setMatchError("Please enter a service type.");
      return;
    }
    if (!startIso || !endIso) {
      setMatchError("Please choose a valid start and end time.");
      return;
    }
    if (new Date(endIso) <= new Date(startIso)) {
      setMatchError("The end time must be after the start time.");
      return;
    }

    setMatching(true);
    try {
      const res = await requestMatch({
        service_type: serviceType.trim(),
        start: startIso,
        end: endIso,
      });
      setResult(res);
    } catch (err) {
      setMatchError(
        err instanceof ApiError
          ? err.message
          : "Could not request a match. Please try again.",
      );
    } finally {
      setMatching(false);
    }
  };

  const handleBook = async (candidate: MatchCandidate) => {
    const startIso = toIsoOrNull(start);
    const endIso = toIsoOrNull(end);
    setBookError(null);
    setConsentRequired(false);
    setBookedMessage(null);
    if (!startIso || !endIso) {
      setBookError("Please re-request a match with a valid time window.");
      return;
    }
    setBookingId(candidate.volunteer_id);
    try {
      // Book the exact covering slot the match was computed against. The backend
      // enforces the slot/authorization/consent gates.
      const res = await bookVisit({
        volunteer_id: candidate.volunteer_id,
        slot_id: candidate.slot_id,
        service_type: serviceType.trim(),
        requested_start: startIso,
        requested_end: endIso,
      });
      setBookedMessage(res.message || "booking-confirmed");
      onBooked();
    } catch (err) {
      if (err instanceof ApiError && err.code === "consent-required") {
        setConsentRequired(true);
      }
      setBookError(bookingErrorMessage(err));
    } finally {
      setBookingId(null);
    }
  };

  return (
    <Card title="Request a match and book a visit">
      <form onSubmit={handleMatch} style={{ display: "grid", gap: "0.5rem" }}>
        <label style={labelStyle}>
          Service type
          <input
            type="text"
            value={serviceType}
            onChange={(e) => setServiceType(capitalizeFirst(e.target.value))}
            placeholder="Vaccination"
            style={inputStyle}
          />
          <span style={{ color: "var(--cc-text-muted)", fontSize: "0.8rem" }}>
            e.g. Vaccination, Vaccine, Testing, Wellness check
          </span>
        </label>
        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
          <label style={labelStyle}>
            From
            <input
              type="datetime-local"
              value={start}
              onChange={(e) => setStart(e.target.value)}
              style={inputStyle}
            />
          </label>
          <label style={labelStyle}>
            To
            <input
              type="datetime-local"
              value={end}
              onChange={(e) => setEnd(e.target.value)}
              style={inputStyle}
            />
          </label>
        </div>
        <div>
          <button type="submit" disabled={matching} style={buttonStyle}>
            {matching ? "Finding volunteers…" : "Request match"}
          </button>
        </div>
      </form>

      {matchError && <ErrorNote>{matchError}</ErrorNote>}

      {result && (
        <div style={{ marginTop: "0.75rem" }}>
          {result.candidates.length === 0 ? (
            <Note>{result.message ?? "No qualified volunteers were found."}</Note>
          ) : (
            <>
              <h3 style={{ fontSize: "1rem", margin: "0.5rem 0" }}>
                Authorized volunteers ({result.candidates.length})
              </h3>
              <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
                {result.candidates.map((c) => (
                  <li
                    key={c.volunteer_id}
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      padding: "0.5rem 0",
                      borderBottom: "1px solid #eee",
                    }}
                  >
                    <span>
                      <strong>{c.volunteer_name || c.volunteer_email}</strong>
                      <span style={{ color: "#9aa8c0", fontSize: "0.85rem" }}>
                        {" "}
                        · {c.volunteer_email}
                      </span>
                      <br />
                      <span style={{ color: "#9aa8c0", fontSize: "0.85rem" }}>
                        {c.distance_km.toFixed(1)} km · score {c.score.toFixed(3)}
                      </span>
                    </span>
                    <button
                      type="button"
                      onClick={() => handleBook(c)}
                      disabled={bookingId !== null}
                      style={buttonStyle}
                    >
                      {bookingId === c.volunteer_id ? "Booking…" : "Book"}
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}

      {consentRequired && (
        <div style={consentBoxStyle} role="alert">
          <strong>Consent required.</strong> You must record your consent to
          participate before a visit can be booked.
        </div>
      )}
      {bookError && !consentRequired && <ErrorNote>{bookError}</ErrorNote>}
      {bookedMessage && (
        <p style={{ color: "#2e7d32", margin: "0.5rem 0" }} role="status">
          Booking confirmed.
        </p>
      )}
    </Card>
  );
}

const labelStyle = {
  display: "flex",
  flexDirection: "column" as const,
  fontSize: "0.9rem",
  gap: "0.25rem",
};

const inputStyle = {
  padding: "0.4rem",
  border: "1px solid #ccc",
  borderRadius: 4,
  fontSize: "0.95rem",
};

const buttonStyle = {
  padding: "0.4rem 0.9rem",
  border: "1px solid #1565c0",
  background: "#1565c0",
  color: "#fff",
  borderRadius: 4,
  cursor: "pointer",
  fontSize: "0.9rem",
};

const consentBoxStyle = {
  marginTop: "0.75rem",
  padding: "0.75rem",
  border: "1px solid #f57f17",
  background: "#fff8e1",
  borderRadius: 6,
  color: "#7a5900",
};
