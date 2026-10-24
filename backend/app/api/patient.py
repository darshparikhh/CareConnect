"""Patient-facing routes, each gated to the Patient role (task 17.2).
This router is the HTTP surface of the Patient_Dashboard (R17). Every route is
gated with ``require_role(Role.patient)`` so a Volunteer or Clinician session —
or an unauthenticated one — can never reach a patient resource (R4.3, R20.2):
the dependency raises **401** (redirect to sign-in) when unauthenticated and
**403** (access denied) for the wrong role before any handler body runs. The
current Patient is resolved from the authenticated session's ``subject_id``.
The routes expose the Matching_Engine, Appointment_Service, Review_Service
visibility helpers, and Recommendation_Engine:
* ``POST /patient/matches`` — rank authorized, available Volunteers for a
  requested Service_Type at a chosen time window (R7.1).
* ``POST /patient/bookings`` — book a selected Volunteer + slot for a
  Service_Type, mapping the three booking gates to HTTP per the design's Error
  Handling table (slot-unavailable → 409; not-authorized / consent-required →
  403) (R8.1).
* ``GET /patient/appointments`` — the Patient's appointments with their
  lifecycle states (R17.1).
* ``GET /patient/decisions`` and ``GET /patient/referrals`` — only
  Clinician-**approved** Clinical_Decisions and Referrals (R11.9), read through
  the Review_Service visibility helpers so the approval gate is applied in one
  place.
* ``GET /patient/medications`` — only approved, verified-prescribed Medications
  (R13.1).
* ``POST /patient/recommendations`` — ranked Recommended_Doctors with proximity,
  specialty, and insurance-compatibility status (R15.1, R16.1, R17.4).
Each route is thin: it validates input with the Pydantic schemas, calls the
engine/service, and shapes the typed result into the response model. All domain
rules stay in the engines/services.
"""
from __future__ import annotations
from typing import List
from fastapi import APIRouter, Depends, status
from fastapi.exceptions import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DBSession
from app.api.deps import AuthSession, get_session, require_role
from app.api.schemas import (
    AppointmentResponse,
    BookingResponse,
    BookRequest,
    DecisionResponse,
    HospitalResponse,
    MatchCandidate,
    MatchRequest,
    MatchResponse,
    MedicationResponse,
    RecommendationRequest,
    RecommendationResponse,
    RecommendedDoctorResponse,
    ReferralResponse,
)
from app.engines import matching, recommendation
from app.models.availability import AvailabilitySlot
from app.models.credential import ServiceType
from app.models.enums import Role
from app.models.people import Patient, Volunteer
from app.services import review
from app.services.appointment import (
    ConsentRequired,
    NotAuthorized,
    SlotUnavailable,
    book,
)
from app.services.insurance import compatibility
from app.services.hospitals import nearby_hospitals
router = APIRouter(prefix="/patient", tags=["patient"])
# Every route in this router requires an authenticated Patient session.
require_patient = require_role(Role.patient)


def _name_from_email(email: str) -> str:
    """Derive a friendly display name from an email local-part.

    e.g. "aisha.rahman@careconnect.org" -> "Aisha Rahman". Falls back to the
    raw email when it has no usable local-part.
    """
    local = (email or "").split("@", 1)[0]
    parts = [p for p in local.replace("_", ".").split(".") if p]
    if not parts:
        return email or ""
    return " ".join(w.capitalize() for w in parts)

# Maps free-text service terms a patient might type (vaccine, flu shot, test,
# ...) onto the canonical seeded ServiceType names. Keys are already normalized
# (stripped + lowercased); the incoming name is normalized the same way before
# lookup so matching is case-insensitive. The canonical seeded names are:
# "vaccination", "specimen_collection", "diagnostic_test", "wellness_check".
_SERVICE_TYPE_SYNONYMS = {
    # Vaccination
    "vaccine": "vaccination",
    "vaccines": "vaccination",
    "vaccination": "vaccination",
    "vaccinations": "vaccination",
    "flu shot": "vaccination",
    "flu vaccine": "vaccination",
    "flu vaccination": "vaccination",
    "shot": "vaccination",
    # Diagnostic test
    "test": "diagnostic_test",
    "tests": "diagnostic_test",
    "testing": "diagnostic_test",
    "diagnostic test": "diagnostic_test",
    "diagnostic": "diagnostic_test",
    "diagnostic_test": "diagnostic_test",
    # Specimen collection
    "specimen": "specimen_collection",
    "specimen collection": "specimen_collection",
    "specimen_collection": "specimen_collection",
    "sample": "specimen_collection",
    "blood test": "specimen_collection",
    "lab": "specimen_collection",
    "lab work": "specimen_collection",
    # Wellness check
    "wellness": "wellness_check",
    "wellness check": "wellness_check",
    "wellness_check": "wellness_check",
    "checkup": "wellness_check",
    "check up": "wellness_check",
}
# ---------------------------------------------------------------------------
# Shared resolution helpers
# ---------------------------------------------------------------------------
def _current_patient(session: AuthSession, db: DBSession) -> Patient:
    """Load the Patient behind the authenticated session (R4.3, R20.2).
    ``require_role(Role.patient)`` has already proven the session's role is
    ``patient``; this resolves the concrete row by ``subject_id``. A missing row
    (e.g. an account deleted after the token was issued) is treated as 401 so a
    stale token cannot act on a nonexistent patient.
    """
    patient = db.get(Patient, session.subject_id)
    if patient is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "authentication-required"},
        )
    return patient
def _service_type_by_name(db: DBSession, name: str) -> ServiceType:
    """Resolve a Service_Type by name, case-insensitively and synonym-aware.
    Patients type service names freely ("Vaccination", "Vaccine", "flu shot"),
    so a naive exact, case-sensitive lookup 404s on everything but the one
    stored spelling. Resolution here:
    1. Normalizes the incoming name (strip whitespace, lowercase).
    2. Maps common synonyms onto the canonical seeded name via
       ``_SERVICE_TYPE_SYNONYMS`` (an unknown term falls through unchanged).
    3. Resolves the row by a case-insensitive comparison against
       ``ServiceType.name`` so stored casing never matters.
    An unknown free-text term that is neither a synonym nor an existing service
    name still 404s with the original ``unknown-service-type`` behavior.
    """
    normalized = (name or "").strip().lower()
    canonical = _SERVICE_TYPE_SYNONYMS.get(normalized, normalized)
    service_type = db.execute(
        select(ServiceType).where(func.lower(ServiceType.name) == canonical)
    ).scalar_one_or_none()
    if service_type is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "unknown-service-type", "service_type": name},
        )
    return service_type
def _appointment_response(appointment) -> AppointmentResponse:
    """Project an Appointment into its Patient-facing response shape."""
    slot = appointment.slot
    service = appointment.service_type
    slot_start = appointment.requested_start or (slot.start if slot is not None else None)
    slot_end = appointment.requested_end or (slot.end if slot is not None else None)
    return AppointmentResponse(
        id=appointment.id,
        volunteer_id=appointment.volunteer_id,
        service_type=service.name if service is not None else "",
        state=appointment.state.value,
        slot_start=slot_start,
        slot_end=slot_end,
        queued_for_review=appointment.queued_for_review,
        reviewed=appointment.reviewed,
    )
# ---------------------------------------------------------------------------
# Match request (R7.1)
# ---------------------------------------------------------------------------
@router.post(
    "/matches",
    response_model=MatchResponse,
    responses={404: {"model": None}},
)
def request_match(
    payload: MatchRequest,
    session: AuthSession = Depends(require_patient),
    db: DBSession = Depends(get_session),
) -> MatchResponse:
    """Rank authorized, available Volunteers for the requested window (R7.1).
    Resolves the Patient and the requested Service_Type, then delegates all
    ranking to the Matching_Engine. Returns the ranked candidates with the
    evidence behind each rank; an empty result carries the engine's
    no-qualified-volunteers advisory (R7.6).
    """
    patient = _current_patient(session, db)
    service_type = _service_type_by_name(db, payload.service_type)
    chosen_time = matching.ChosenTime(start=payload.start, end=payload.end)
    if payload.weights is not None and len(payload.weights) == 3:
        weights = matching.MatchWeights(*payload.weights)
    else:
        weights = matching.DEFAULT_WEIGHTS
    ranked, message = matching.match(
        db, patient, service_type, chosen_time, weights
    )
    candidates = [
        MatchCandidate(
            volunteer_id=result.volunteer.id,
            slot_id=result.slot_id,
            volunteer_email=result.volunteer.email,
            volunteer_name=_name_from_email(result.volunteer.email),
            score=result.score,
            distance_km=result.distance_km,
            availability_count=result.availability_count,
            qualification_count=result.qualification_count,
        )
        for result in ranked
    ]
    return MatchResponse(
        service_type=service_type.name,
        candidates=candidates,
        message=message,
    )
@router.post(
    "/bookings",
    response_model=BookingResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_booking(
    payload: BookRequest,
    session: AuthSession = Depends(require_patient),
    db: DBSession = Depends(get_session),
) -> BookingResponse:
    """Book a selected Volunteer + slot for a Service_Type (R8.1).
    Maps the Appointment_Service's three booking gates to HTTP per the design's
    Error Handling table: ``slot-unavailable`` -> 409, ``not-authorized`` and
    ``consent-required`` -> 403. On success returns the confirmed appointment.
    """
    patient = _current_patient(session, db)
    service_type = _service_type_by_name(db, payload.service_type)
    volunteer = db.get(Volunteer, payload.volunteer_id)
    if volunteer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "unknown-volunteer", "volunteer_id": payload.volunteer_id},
        )
    slot = db.get(AvailabilitySlot, payload.slot_id)
    if slot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "unknown-slot", "slot_id": payload.slot_id},
        )
    try:
        result = book(
            db,
            patient,
            volunteer,
            slot,
            service_type,
            requested_start=payload.requested_start,
            requested_end=payload.requested_end,
        )
    except SlotUnavailable:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "slot-unavailable"},
        )
    except NotAuthorized:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"message": "not-authorized"},
        )
    except ConsentRequired:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"message": "consent-required"},
        )
    db.commit()
    return BookingResponse(appointment=_appointment_response(result.appointment))
@router.get("/appointments", response_model=List[AppointmentResponse])
def list_appointments(
    session: AuthSession = Depends(require_patient),
    db: DBSession = Depends(get_session),
) -> List[AppointmentResponse]:
    """List the Patient's appointments with their lifecycle states (R17.1)."""
    patient = _current_patient(session, db)
    return [
        _appointment_response(appointment)
        for appointment in sorted(patient.appointments, key=lambda a: a.id)
    ]
@router.get("/decisions", response_model=List[DecisionResponse])
def list_decisions(
    session: AuthSession = Depends(require_patient),
    db: DBSession = Depends(get_session),
) -> List[DecisionResponse]:
    """Only Clinician-approved Clinical_Decisions are visible (R11.9)."""
    patient = _current_patient(session, db)
    out: List[DecisionResponse] = []
    for appointment in sorted(patient.appointments, key=lambda a: a.id):
        decision = review.decision_for_patient(appointment)
        if decision is None:
            continue
        out.append(
            DecisionResponse(
                id=decision.id,
                appointment_id=appointment.id,
                content=decision.content,
                approved=decision.approved,
            )
        )
    return out
@router.get("/referrals", response_model=List[ReferralResponse])
def list_referrals(
    session: AuthSession = Depends(require_patient),
    db: DBSession = Depends(get_session),
) -> List[ReferralResponse]:
    """Only referrals riding on an approved decision are visible (R11.9, R12)."""
    patient = _current_patient(session, db)
    out: List[ReferralResponse] = []
    for appointment in sorted(patient.appointments, key=lambda a: a.id):
        for referral in review.referrals_for_patient(appointment):
            out.append(
                ReferralResponse(
                    id=referral.id,
                    appointment_id=appointment.id,
                    specialty=referral.specialty,
                )
            )
    return out
@router.get("/medications", response_model=List[MedicationResponse])
def list_medications(
    session: AuthSession = Depends(require_patient),
    db: DBSession = Depends(get_session),
) -> List[MedicationResponse]:
    """Only approved, verified-prescribed Medications are visible (R13.1)."""
    patient = _current_patient(session, db)
    return [
        MedicationResponse(id=med.id, name=med.name, approved=med.approved)
        for med in review.medications_for_patient(patient)
    ]
@router.post("/recommendations", response_model=RecommendationResponse)
def request_recommendations(
    payload: RecommendationRequest,
    session: AuthSession = Depends(require_patient),
    db: DBSession = Depends(get_session),
) -> RecommendationResponse:
    """Rank Recommended_Doctors with proximity, specialty, insurance (R15/16/17.4)."""
    patient = _current_patient(session, db)
    weights = payload.weights if payload.weights is not None else recommendation.DEFAULT_WEIGHTS
    result = recommendation.recommend(db, patient, weights)
    doctors: List[RecommendedDoctorResponse] = []
    for scored in result.scored:
        doctor = scored.doctor
        status_result = compatibility(db, patient, doctor)
        insurance_status = getattr(
            status_result.status, "value", str(status_result.status)
        )
        doctors.append(
            RecommendedDoctorResponse(
                id=doctor.id,
                name=doctor.name,
                specialty=doctor.specialty,
                rating=doctor.rating,
                proximity_km=scored.proximity_km,
                score=scored.score,
                insurance_status=insurance_status,
            )
        )
    return RecommendationResponse(
        doctors=doctors,
        message=result.message,
        insurance_asserted=result.insurance_asserted,
    )


@router.get("/hospitals", response_model=List[HospitalResponse])
def list_hospitals(
    session: AuthSession = Depends(require_patient),
    db: DBSession = Depends(get_session),
) -> List[HospitalResponse]:
    """Nearby MA hospitals ranked by ZIP proximity to the Patient (demo feature).

    Represents the post-referral "show nearby hospitals by the patient's ZIP"
    step. Data is served from a locally bundled CMS dataset (the CMS API blocks
    server-side calls), so this works fully offline. The Patient's own
    ``zip_code`` drives the ranking; a patient with no ZIP falls back to a
    default MA ZIP ("02118", Boston Medical Center area) rather than 500ing.
    """
    patient = _current_patient(session, db)
    patient_zip = patient.zip_code or "02118"
    return [HospitalResponse(**hospital) for hospital in nearby_hospitals(patient_zip, limit=10)]
