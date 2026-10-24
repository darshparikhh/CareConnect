"""Auth_Service: authentication, session issuance, and role-based access.

This implements the design's ``Auth_Service`` (R4, R20.2):

* :func:`authenticate` checks an email/password against the three account
  tables (Patient, Volunteer, Clinician), and on success returns an
  :class:`AuthSession` carrying the account id and its role. Invalid
  credentials raise :class:`AuthenticationFailed` (R4.1, R4.2).
* :func:`authorize` is a pure allow/deny check of a session's role against a
  required resource role (R4.3-R4.5, R20.2).
* The FastAPI dependency factory :func:`require_role` builds a dependency that
  validates the session token from the request, resolves the role, and enforces
  access: unauthenticated dashboard requests get **401** with a
  redirect-to-sign-in hint (R4.6), and a mismatched role gets **403** access
  denied (R4.3-R4.5, R20.2). :func:`get_current_session` is the authenticated-
  but-any-role dependency.

Access is enforced here, server-side, not merely hidden in the UI, because
Requirement 4 demands denial rather than cosmetic hiding.

The session mechanism is a stateless signed token (see :mod:`app.security`):
the Auth_Service hands the client a token at sign-in, and every subsequent
request presents it via the ``Authorization: Bearer <token>`` header (or, as a
convenience for the SPA, a ``session`` cookie). The token is tamper-evident, so
a client cannot forge a role.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Type, Union

from fastapi import Depends, Request, status
from fastapi.exceptions import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.database import get_session
from app.models.enums import Role
from app.models.people import Clinician, Patient, Volunteer
from app.security import (
    sign_session_token,
    verify_password,
    verify_session_token,
)

# The three account entities, keyed by the role they carry. This is the single
# place that maps a Role to its backing table, used by both authentication and
# session resolution.
_ACCOUNT_MODELS = {
    Role.patient: Patient,
    Role.volunteer: Volunteer,
    Role.clinician: Clinician,
}

# Where unauthenticated users are redirected (R4.6). Surfaced in the 401 so the
# SPA knows where to send the user.
SIGN_IN_PATH = "/sign-in"


class AuthenticationFailed(Exception):
    """Raised when credentials do not match any account (R4.2).

    Deliberately carries a generic message so callers cannot distinguish
    "unknown email" from "wrong password".
    """

    def __init__(self, message: str = "authentication-failed") -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class AuthSession:
    """An authenticated session carrying the signed-in account's role.

    ``token`` is the signed session string the client stores and replays on
    each request; ``subject_id`` and ``role`` are the resolved identity.
    """

    subject_id: int
    role: Role
    token: str

    @property
    def is_authenticated(self) -> bool:
        return True


def _find_account(db: DBSession, email: str) -> Optional[object]:
    """Locate the single account matching ``email`` across the three tables.

    Emails are unique within each table; the design treats a single email as a
    single account, so the first match across tables wins.
    """
    normalized = (email or "").strip().lower()
    if not normalized:
        return None
    for model in _ACCOUNT_MODELS.values():
        account = db.execute(
            select(model).where(model.email == normalized)
        ).scalar_one_or_none()
        if account is not None:
            return account
    return None


def authenticate(db: DBSession, email: str, password: str) -> AuthSession:
    """Authenticate credentials and establish a session (R4.1, R4.2).

    Looks up the account by email, verifies the password against the stored
    hash, and on success returns an :class:`AuthSession` whose token encodes the
    account's role. On any failure (unknown email, bad password) raises
    :class:`AuthenticationFailed` with a uniform message so the two cases are
    indistinguishable to the caller.
    """
    account = _find_account(db, email)
    if account is None:
        raise AuthenticationFailed()
    if not verify_password(password or "", getattr(account, "password_hash", None)):
        raise AuthenticationFailed()

    role = account.role if isinstance(account.role, Role) else Role(account.role)
    token = sign_session_token(account.id, role.value)
    return AuthSession(subject_id=account.id, role=role, token=token)


def authorize(session: Optional[AuthSession], resource_role: Union[Role, str]) -> bool:
    """Return True if ``session`` may access a resource owned by ``resource_role``.

    A role grants access to its own dashboard/records and denies the other two
    (R4.3-R4.5, R20.2). An absent/unauthenticated session is always denied.
    """
    if session is None:
        return False
    required = resource_role if isinstance(resource_role, Role) else Role(resource_role)
    return session.role == required


def _extract_token(request: Request) -> Optional[str]:
    """Pull the session token from the Authorization header or session cookie.

    Supports ``Authorization: Bearer <token>`` (API clients) and a ``session``
    cookie (convenient for the SPA), in that order of precedence.
    """
    header = request.headers.get("Authorization")
    if header:
        scheme, _, value = header.partition(" ")
        if scheme.lower() == "bearer" and value.strip():
            return value.strip()
    cookie = request.cookies.get("session")
    if cookie:
        return cookie
    return None


def resolve_session(request: Request, db: DBSession) -> Optional[AuthSession]:
    """Validate the request's token and resolve it to a live account session.

    Returns an :class:`AuthSession` when the token's signature is valid *and*
    the referenced account still exists with the claimed role; otherwise
    ``None`` (treated as unauthenticated). Re-checking the account against the
    database means a revoked/deleted account cannot keep using an old token.
    """
    token = _extract_token(request)
    verified = verify_session_token(token)
    if verified is None:
        return None
    subject_id, role_value = verified
    try:
        role = Role(role_value)
    except ValueError:
        return None
    model = _ACCOUNT_MODELS.get(role)
    if model is None:
        return None
    account = db.get(model, subject_id)
    if account is None:
        return None
    return AuthSession(subject_id=subject_id, role=role, token=token or "")


def _unauthenticated_error() -> HTTPException:
    """401 with a redirect-to-sign-in hint for unauthenticated access (R4.6)."""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "message": "authentication-required",
            "redirect": SIGN_IN_PATH,
        },
        headers={"Location": SIGN_IN_PATH, "WWW-Authenticate": "Bearer"},
    )


def _forbidden_error() -> HTTPException:
    """403 access denied for a valid session with the wrong role (R4.3-R4.5)."""
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"message": "access-denied"},
    )


def get_current_session(
    request: Request, db: DBSession = Depends(get_session)
) -> AuthSession:
    """FastAPI dependency: require an authenticated session of any role.

    Raises 401 (with redirect to sign-in) when the request carries no valid
    session (R4.6).
    """
    session = resolve_session(request, db)
    if session is None:
        raise _unauthenticated_error()
    return session


def require_role(resource_role: Union[Role, str]):
    """Build a FastAPI dependency gating a route to a single role.

    The returned dependency validates the session, resolves the role, and:

    * raises **401** (redirect to sign-in) if unauthenticated (R4.6), then
    * raises **403** (access denied) if the authenticated role is not
      ``resource_role`` (R4.3-R4.5, R20.2),
    * otherwise returns the :class:`AuthSession` for the handler to use.
    """
    required = resource_role if isinstance(resource_role, Role) else Role(resource_role)

    def _dependency(
        session: AuthSession = Depends(get_current_session),
    ) -> AuthSession:
        if not authorize(session, required):
            raise _forbidden_error()
        return session

    return _dependency


__all__ = [
    "AuthSession",
    "AuthenticationFailed",
    "SIGN_IN_PATH",
    "authenticate",
    "authorize",
    "resolve_session",
    "get_current_session",
    "require_role",
]
