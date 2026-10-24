"""Shared API dependencies and service-result → HTTP mapping helpers.

This is the seam between the typed outcome objects the services return and the
HTTP responses the routers emit. Centralizing it here means every router — the
auth/registration ones built now and the patient/volunteer/clinician ones built
in tasks 17.2-17.4 — maps the same outcome to the same status code and body,
so the API's error contract stays consistent.

Two things live here:

* Thin re-exports of the Auth_Service dependencies (``get_session``,
  ``get_current_session``, ``require_role``) so routers import their wiring from
  one place rather than reaching into the service module directly.
* :func:`raise_for_registration_error`, which translates a
  :class:`FieldErrors` / :class:`AccountExists` result into the right
  ``HTTPException`` (400 with the named missing fields / 409 account-exists),
  matching the design's Error Handling table.
"""

from __future__ import annotations

from typing import NoReturn, Union

from fastapi import status
from fastapi.exceptions import HTTPException

from app.database import get_session
from app.services.auth import (
    AuthSession,
    get_current_session,
    require_role,
)
from app.services.registration import AccountExists, FieldErrors

# Stable machine-readable error codes used across the API.
ACCOUNT_EXISTS_MESSAGE = "account-already-exists"
VALIDATION_MESSAGE = "missing-required-fields"


def _validation_error(result: FieldErrors) -> HTTPException:
    """400 naming each missing required field (R1.2, R2.3, R3.3)."""
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={
            "message": VALIDATION_MESSAGE,
            "missing_fields": list(result.missing_fields),
        },
    )


def _account_exists_error(result: AccountExists) -> HTTPException:
    """409 for a duplicate email (R1.3)."""
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"message": result.message, "email": result.email},
    )


def raise_for_registration_error(
    result: Union[FieldErrors, AccountExists],
) -> NoReturn:
    """Raise the HTTPException matching a registration rejection result.

    Routers call this only after confirming the result is a rejection (i.e. not
    an account row). ``FieldErrors`` → 400 with the field list; ``AccountExists``
    → 409. A truly unexpected type raises a 500 rather than silently passing.
    """
    if isinstance(result, FieldErrors):
        raise _validation_error(result)
    if isinstance(result, AccountExists):
        raise _account_exists_error(result)
    raise HTTPException(  # pragma: no cover - defensive; services return the above
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={"message": "unexpected-registration-result"},
    )


def is_registration_rejection(result: object) -> bool:
    """True if a registration result is a rejection rather than an account."""
    return isinstance(result, (FieldErrors, AccountExists))


__all__ = [
    "AuthSession",
    "get_session",
    "get_current_session",
    "require_role",
    "ACCOUNT_EXISTS_MESSAGE",
    "VALIDATION_MESSAGE",
    "raise_for_registration_error",
    "is_registration_rejection",
]
