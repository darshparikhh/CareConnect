/**
 * Sign-in / cover page (R4.1, R4.2, R4.6).
 *
 * Doubles as the app's cover page: a centered, Times New Roman branded hero
 * with the CareConnect title and tagline above the sign-in form. On success it
 * routes to the role's dashboard; on a 401 it shows an authentication-failed
 * message. A user redirected here from a protected route returns to their
 * dashboard after signing in.
 */

import { useState } from "react";
import type { FormEvent } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { dashboardPathFor } from "../auth/RequireRole";

export function SignInPage() {
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
      const stored = await signIn(email, password);
      navigate(dashboardPathFor(stored.role), { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.isAuthFailed) {
        setError("Authentication failed. Check your email and password.");
      } else if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError("Something went wrong. Please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="cc-cover">
      <div className="cc-cover__hero">
        <div className="cc-cover__mark" aria-hidden="true">✚</div>
        <h1 className="cc-cover__title">CareConnect</h1>
        <p className="cc-cover__tagline">
          Bringing preventive healthcare to your doorstep.
        </p>
      </div>

      <section className="cc-cover__card" aria-label="Sign in">
        <h2 className="cc-cover__card-title">Sign in</h2>
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
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          {error && (
            <p role="alert" className="cc-cover__error">
              {error}
            </p>
          )}
          <button type="submit" className="cc-primary cc-cover__submit" disabled={submitting}>
            {submitting ? "Signing in…" : "Sign in"}
          </button>
        </form>
        <p className="cc-cover__alt">
          New here? <Link to="/sign-up">Create an account</Link>
        </p>
      </section>

      <p className="cc-cover__footer">
        Connecting patients, licensed volunteers, and clinicians.
      </p>
    </div>
  );
}
