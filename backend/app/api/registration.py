"""Registration routes: patient, volunteer, and clinician sign-up (R1, R2, R3).

Exposes the Registration_Service over HTTP. Each route validates and shapes the
JSON body with Pydantic, calls the matching service function, and maps its typed
result to HTTP:

* an account row  → **201 Created** with a minimal :class:`AccountResponse`,
* ``FieldErrors``  → **400** naming each missing required field (R1.2, R2.3, R3.3),
* ``AccountExists``→ **409 account-already-exists** (R1.3).

The mapping itself lives in :func:`app.api.deps.raise_for_registration_error`
so the three routes — and the dashboards wired later — report errors
identically. Registration is public (no session required): these routes are how
a brand-new user gets an account before they can sign in.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session as DBSession

from app.api.deps import get_session, is_registration_rejection, raise_for_registration_error
from app.api.schemas import (
    AccountResponse,
    ClinicianRegistrationRequest,
    PatientRegistrationRequest,
    VolunteerRegistrationRequest,
    declared_credentials_to_dicts,
    insurance_to_dict,
    location_to_dict,
    to_account_response,
)
from app.services.registration import (
    register_clinician,
    register_patient,
    register_volunteer,
)

router = APIRouter(prefix="/register", tags=["registration"])

_REJECTION_RESPONSES = {
    400: {"description": "missing-required-fields"},
    409: {"description": "account-already-exists"},
}


@router.post(
    "/patient",
    response_model=AccountResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_REJECTION_RESPONSES,
)
def register_patient_route(
    payload: PatientRegistrationRequest,
    db: DBSession = Depends(get_session),
) -> AccountResponse:
    """Create a Patient account (R1.1-R1.5, R20.4)."""
    result = register_patient(
        db,
        email=payload.email,
        password=payload.password,
        location=location_to_dict(payload.location),
        insurance=insurance_to_dict(payload.insurance),
        needs=payload.needs,
        pcp=payload.pcp,
        consent=payload.consent,
    )
    if is_registration_rejection(result):
        raise_for_registration_error(result)
    return to_account_response(result)


@router.post(
    "/volunteer",
    response_model=AccountResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_REJECTION_RESPONSES,
)
def register_volunteer_route(
    payload: VolunteerRegistrationRequest,
    db: DBSession = Depends(get_session),
) -> AccountResponse:
    """Create a Volunteer account and record declared credentials (R2)."""
    result = register_volunteer(
        db,
        email=payload.email,
        password=payload.password,
        location=location_to_dict(payload.location),
        declared_credentials=declared_credentials_to_dicts(
            payload.declared_credentials
        ),
    )
    if is_registration_rejection(result):
        raise_for_registration_error(result)
    return to_account_response(result)


@router.post(
    "/clinician",
    response_model=AccountResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_REJECTION_RESPONSES,
)
def register_clinician_route(
    payload: ClinicianRegistrationRequest,
    db: DBSession = Depends(get_session),
) -> AccountResponse:
    """Create a Clinician account with an unverified license credential (R3)."""
    result = register_clinician(
        db,
        email=payload.email,
        password=payload.password,
        license_info=payload.license_info,
    )
    if is_registration_rejection(result):
        raise_for_registration_error(result)
    return to_account_response(result)


__all__ = ["router"]
