"""Clinician-facing routes, each gated to the Clinician role (task 17.4).

This router is the HTTP surface of the Clinician_Dashboard (R19). Every route is
gated with ``require_role(Role.clinician)`` so a Patient or Volunteer session —
or an unauthenticated one — can never reach a clinician resource (R4.5, R20.2):
the dependency raises **401** (redirect to sign-in) when unauthenticated and
**403** (access denied) for the wrong role before any handler body runs. The
current Clinician is resolved from the authenticated session's ``subject_id``.

The routes expose the Review_Service:

* ``GET /clinician/review-queue`` — the completed appointments still
  ``queued_for_review`` that a Clinician can open (R11.1, R19).
* ``GET /clinician/appointments/{id}/findings`` — the appointment's recorded
  questionnaire answers and Test_Results, via ``open_for_review``; an
  appointment that is not completed-and-queued is rejected **409
  not-ready-for-review** (R11.1, R11.2).
* ``POST /clinician/appointments/{id}/decision`` — record a Clinical_Decision.
  The Review_Service's typed rejections map to HTTP per the design's Error
  Handling table: empty content → **400 decision-content-required** (R11.5); an
  unverified license → **403 credential-not-verified** with *nothing stored*
  (R11.6); a not-ready appointment → **409 not-ready-for-review**. On success
  the decision is stored and the appointment marked reviewed (R11.3, R11.4).
* ``POST /clinician/appointments/{id}/decision/approve`` — approve the stored
  decision, which is what makes it (and its referrals) patient-visible (R11.9);
  no stored decision → **409 no-decision-to-approve** (R11.7).
* ``POST /clinician/appointments/{id}/referral`` — issue a specialty Referral
  from the reviewed decision, setting the Patient's ``required_specialty`` so
  the Recommendation_Engine uses it as the hard filter (R12.1, R12.2).

Each route is thin: it resolves the appointment, calls the Review_Service, and
shapes the typed result into the response model. All domain rules (state gating,
license gating, approval visibility) stay in the service.
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, status
from fastapi.exceptions import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.api.deps import AuthSession, get_session, require_role
from app.api.schemas import (
    ClinicianDecisionResponse,
    ClinicianReferralResponse,
    DecisionCreateRequest,
    FindingsResponse,
    HospitalResponse,
    QuestionnaireFinding,
    ReferralCreateRequest,
    ReviewQueueItem,
    TestResultFinding,
)
from app.models.appointment import Appointment
from app.models.enums import AppointmentState, Role
from app.models.people import Clinician
from app.services import review
from app.services.hospitals import all_hospitals

router = APIRouter(prefix="/clinician", tags=["clinician"])

# Every route in this router requires an authenticated Clinician session.
require_clinician = require_role(Role.clinician)


# ---------------------------------------------------------------------------
# Shared resolution helpers
# ---------------------------------------------------------------------------
def _current_clinician(session: AuthSession, db: DBSession) -> Clinician:
    """Load the Clinician behind the authenticated session (R4.5, R20.2).

    ``require_role(Role.clinician)`` has already proven the session's role is
    ``clinician``; this resolves the concrete row by ``subject_id``. A missing
    row (e.g. an account deleted after the token was issued) is treated as 401
    so a stale token cannot act on a nonexistent clinician.
    """
    clinician = db.get(Clinician, session.subject_id)
    if clinician is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "authentication-required"},
        )
    return clinician


def _appointment(db: DBSession, appointment_id: int) -> Appointment:
    """Resolve an appointment by id, or 404 if there is no such appointment.

    Unlike the volunteer/patient routers there is no ownership scoping: any
    verified Clinician reviews the shared review queue (R11.1, R19), so a
    missing appointment is the only not-found case here.
    """
    appointment = db.get(Appointment, appointment_id)
    if appointment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "unknown-appointment"},
        )
    return appointment


def _queue_item(appointment: Appointment) -> ReviewQueueItem:
    """Project an Appointment into its review-queue shape (R11.1, R19)."""
    service = appointment.service_type
    return ReviewQueueItem(
        appointment_id=appointment.id,
        patient_id=appointment.patient_id,
        volunteer_id=appointment.volunteer_id,
        service_type=service.name if service is not None else "",
        state=appointment.state.value,
        queued_for_review=appointment.queued_for_review,
        reviewed=appointment.reviewed,
    )


def _decision_response(
    appointment: Appointment, decision
) -> ClinicianDecisionResponse:
    """Project a ClinicalDecision into the clinician-facing response shape."""
    return ClinicianDecisionResponse(
        id=decision.id,
        appointment_id=appointment.id,
        content=decision.content,
        reviewed=decision.reviewed,
        approved=decision.approved,
    )


# ---------------------------------------------------------------------------
# Review queue — completed appointments queued for review (R11.1, R19)
# ---------------------------------------------------------------------------
@router.get("/review-queue", response_model=List[ReviewQueueItem])
def review_queue(
    session: AuthSession = Depends(require_clinician),
    db: DBSession = Depends(get_session),
) -> List[ReviewQueueItem]:
    """List completed appointments still queued for clinician review (R11.1, R19).

    The queue is every appointment that is ``completed`` *and*
    ``queued_for_review`` — exactly the set a Clinician may open via
    ``open_for_review``. Ordered by appointment id for a stable view.
    """
    _current_clinician(session, db)
    appointments = (
        db.execute(
            select(Appointment)
            .where(Appointment.state == AppointmentState.completed)
            .where(Appointment.queued_for_review.is_(True))
            .order_by(Appointment.id)
        )
        .scalars()
        .all()
    )
    return [_queue_item(a) for a in appointments]


# ---------------------------------------------------------------------------
# Hospital list for referral dropdown (R12.1)
# ---------------------------------------------------------------------------
@router.get("/hospitals", response_model=List[HospitalResponse])
def list_hospitals_for_referral(
    session: AuthSession = Depends(require_clinician),
    db: DBSession = Depends(get_session),
) -> List[HospitalResponse]:
    """List every bundled MA hospital for the referral dropdown (R12.1).

    Resolves the current Clinician first (so a stale token 401s), then returns
    the full MA hospital list projected to ``HospitalResponse``. There is no
    patient-ZIP context here, so the list is alphabetical by ``facility_name``
    rather than ranked by proximity.
    """
    _current_clinician(session, db)
    return [HospitalResponse(**h) for h in all_hospitals()]


# ---------------------------------------------------------------------------
# Findings view (R11.1, R11.2)
# ---------------------------------------------------------------------------
@router.get(
    "/appointments/{appointment_id}/findings",
    response_model=FindingsResponse,
    responses={409: {"description": "appointment-not-ready-for-review"}},
)
def get_findings(
    appointment_id: int,
    session: AuthSession = Depends(require_clinician),
    db: DBSession = Depends(get_session),
) -> FindingsResponse:
    """Open a completed, queued appointment's findings for review (R11.1, R11.2).

    Returns the recorded questionnaire answers and Test_Results for display. An
    appointment that is not completed-and-queued is rejected with **409
    not-ready-for-review** (the Review_Service's state gate), surfacing nothing.
    """
    clinician = _current_clinician(session, db)
    appointment = _appointment(db, appointment_id)
    result = review.open_for_review(db, clinician, appointment)
    if not result.ok:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": result.message},
        )
    return FindingsResponse(
        appointment_id=appointment.id,
        questionnaires=[
            QuestionnaireFinding(
                id=q.id,
                service_type=q.service_type.name if q.service_type is not None else "",
                answers=q.answers,
            )
            for q in result.questionnaires
        ],
        test_results=[
            TestResultFinding(
                id=t.id,
                measurement=t.measurement,
                value=t.value,
                unit=t.unit,
            )
            for t in result.test_results
        ],
    )


# ---------------------------------------------------------------------------
# Record a clinical decision (R11.3-R11.6)
# ---------------------------------------------------------------------------
@router.post(
    "/appointments/{appointment_id}/decision",
    response_model=ClinicianDecisionResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"description": "decision-content-required"},
        403: {"description": "credential-not-verified"},
        409: {"description": "appointment-not-ready-for-review"},
    },
)
def record_decision(
    appointment_id: int,
    payload: DecisionCreateRequest,
    session: AuthSession = Depends(require_clinician),
    db: DBSession = Depends(get_session),
) -> ClinicianDecisionResponse:
    """Record a Clinical_Decision for a queued appointment (R11.3-R11.6).

    Maps the Review_Service's typed rejections to HTTP per the design's Error
    Handling table: empty content → **400 decision-content-required** (R11.5,
    state left unchanged); an unverified license → **403 credential-not-verified**
    with *nothing stored* (R11.6); a not-ready appointment → **409
    not-ready-for-review**. On success the decision is stored and the
    appointment marked reviewed (R11.3, R11.4); it is not yet patient-visible.
    """
    clinician = _current_clinician(session, db)
    appointment = _appointment(db, appointment_id)
    result = review.record_decision(db, clinician, appointment, payload.content)
    if not result.ok:
        if result.message == review.DECISION_CONTENT_REQUIRED_MESSAGE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": result.message},
            )
        if result.message == review.CREDENTIAL_NOT_VERIFIED_MESSAGE:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"message": result.message},
            )
        # NOT_READY_FOR_REVIEW_MESSAGE (or any other precondition failure).
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": result.message},
        )
    return _decision_response(appointment, result.decision)


# ---------------------------------------------------------------------------
# Approve a decision — makes it patient-visible (R11.7, R11.9)
# ---------------------------------------------------------------------------
@router.post(
    "/appointments/{appointment_id}/decision/approve",
    response_model=ClinicianDecisionResponse,
    responses={409: {"description": "no-decision-to-approve"}},
)
def approve_decision(
    appointment_id: int,
    session: AuthSession = Depends(require_clinician),
    db: DBSession = Depends(get_session),
) -> ClinicianDecisionResponse:
    """Approve the appointment's stored Clinical_Decision (R11.7, R11.9).

    Approval is what makes the decision — and any referral issued from it —
    visible to the Patient (R11.9). An appointment with no stored decision is
    rejected with **409 no-decision-to-approve** (R11.7).
    """
    clinician = _current_clinician(session, db)
    appointment = _appointment(db, appointment_id)
    result = review.approve_decision(db, clinician, appointment)
    if not result.ok:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": result.message},
        )
    return _decision_response(appointment, result.decision)


# ---------------------------------------------------------------------------
# Issue a specialty referral (R12.1, R12.2)
# ---------------------------------------------------------------------------
@router.post(
    "/appointments/{appointment_id}/referral",
    response_model=ClinicianReferralResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"description": "referral specialty is required"},
        409: {"description": "no-decision-to-approve"},
    },
)
def issue_referral(
    appointment_id: int,
    payload: ReferralCreateRequest,
    session: AuthSession = Depends(require_clinician),
    db: DBSession = Depends(get_session),
) -> ClinicianReferralResponse:
    """Issue a specialty Referral from the reviewed decision (R12.1, R12.2).

    Requires a stored ClinicalDecision to refer from; otherwise rejected with
    **409 no-decision-to-approve**. An empty specialty is **400**. On success a
    Referral is recorded and the Patient's ``required_specialty`` is set so the
    Recommendation_Engine applies it as the hard specialty filter (R12.2).
    """
    clinician = _current_clinician(session, db)
    appointment = _appointment(db, appointment_id)
    result = review.issue_referral(db, clinician, appointment, payload.specialty)
    if not result.ok:
        if result.message == review.NO_DECISION_TO_APPROVE_MESSAGE:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"message": result.message},
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": result.message},
        )
    referral = result.referral
    return ClinicianReferralResponse(
        id=referral.id,
        appointment_id=appointment.id,
        patient_id=referral.patient_id,
        specialty=referral.specialty,
    )


__all__ = ["router"]
