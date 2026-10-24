"""Authentication routes: sign-in and the current session (R4.1, R4.2, R4.6).

Exposes the Auth_Service over HTTP:

* ``POST /auth/sign-in`` authenticates credentials and, on success, returns the
  signed session token plus the resolved role so the SPA can route to the right
  dashboard (R4.1). Invalid credentials map to **401 authentication-failed**
  (R4.2) — the same uniform message the service raises, so the two failure
  cases (unknown email / wrong password) stay indistinguishable.
* ``GET /auth/session`` echoes the caller's current session, resolved by the
  Auth_Service dependency. An unauthenticated request gets the service's
  **401 + redirect-to-sign-in** response (R4.6), which is exactly the behaviour
  the SPA needs to bounce a logged-out user to the sign-in screen.

The router is intentionally thin: it validates input with Pydantic, calls the
service, and shapes the result. All authentication logic lives in
:mod:`app.services.auth`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from fastapi.exceptions import HTTPException
from sqlalchemy.orm import Session as DBSession

from app.api.deps import get_current_session, get_session
from app.api.schemas import SessionResponse, SignInRequest
from app.services.auth import AuthSession, AuthenticationFailed, authenticate

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/sign-in",
    response_model=SessionResponse,
    responses={401: {"description": "authentication-failed"}},
)
def sign_in(
    payload: SignInRequest,
    db: DBSession = Depends(get_session),
) -> SessionResponse:
    """Authenticate credentials and establish a session (R4.1, R4.2).

    On valid credentials, returns the signed token and role. On invalid
    credentials, the Auth_Service raises ``AuthenticationFailed`` and this
    handler maps it to 401 with the service's uniform message.
    """
    try:
        session = authenticate(db, payload.email, payload.password)
    except AuthenticationFailed as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": exc.message},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return SessionResponse(
        token=session.token,
        role=session.role.value,
        subject_id=session.subject_id,
    )


@router.get("/session", response_model=SessionResponse)
def current_session(
    session: AuthSession = Depends(get_current_session),
) -> SessionResponse:
    """Return the caller's current session (R4.6 for the unauthenticated case).

    The dependency enforces authentication: a request without a valid session
    never reaches this body and instead receives 401 + redirect-to-sign-in.
    """
    return SessionResponse(
        token=session.token,
        role=session.role.value,
        subject_id=session.subject_id,
    )


__all__ = ["router"]
