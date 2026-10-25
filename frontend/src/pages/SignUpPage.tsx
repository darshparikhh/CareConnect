/**
 * Patient sign-up / cover page (R1.1).
 *
 * A self-serve companion to the sign-in cover page: same Times New Roman hero
 * and card styling, but the user supplies only email + password. On submit it
 * creates a patient account (the client fills the remaining required fields
 * with defaults), then signs the new user in exactly like a normal login and
 * routes them to the patient dashboard where they book. A user who is already
 * signed in skips the cover and goes straight to their role dashboard.
 */
import { useState } from "react";
import type { FormEvent } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { ApiError, registerPatient } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { dashboardPathFor } from "../auth/RequireRole";
export function SignUpPage() {
  const { session, loading, signIn } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  // Already signed in? Skip the cover and go to the role dashboard.
  if (!loading && session) {
    return <Navigate to={dashboardPathFor(session.role)} replace />;
  }
  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await registerPatient(email, password);
      // Account created: sign in to store the session like a normal login.
      await signIn(email, password);
      navigate(dashboardPathFor("patient"), { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.code === "account-already-exists") {
        setError("An account with this email already exists — try signing in.");
      } else {
        setError("Could not create account. Please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  };
  const alreadyExists =
    error === "An account with this email already exists — try signing in.";
  return (
    <div className="cc-cover">
      <div className="cc-cover__hero">
        <div className="cc-cover__mark" aria-hidden="true">✚</div>
        <h1 className="cc-cover__title">CareConnect</h1>
        <p className="cc-cover__tagline">
          Bringing preventive healthcare to your doorstep.
        </p>
      </div>
      <section className="cc-cover__card" aria-label="Create account">
        <h2 className="cc-cover__card-title">Create account</h2>
        <form onSubmit={handleSubmit}>
          <div>
            <label htmlFor="email">Email</label>
            <input
              id="email"
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div>
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              autoComplete="new-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          {error && (
            <p role="alert" className="cc-cover__error">
              {error}
              {alreadyExists && (
                <>
                  {" "}
                  <Link to="/sign-in">Sign in</Link>
                </>
              )}
            </p>
          )}
          <button type="submit" className="cc-primary cc-cover__submit" disabled={submitting}>
            {submitting ? "Creating account…" : "Create account"}
          </button>
        </form>
        <p className="cc-cover__alt">
          Already have an account? <Link to="/sign-in">Sign in</Link>
        </p>
      </section>
      <p className="cc-cover__footer">
        Connecting patients, licensed volunteers, and clinicians.
      </p>
    </div>
  );
}
