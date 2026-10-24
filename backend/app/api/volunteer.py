"""Volunteer-facing routes, each gated to the Volunteer role (task 17.3).

This router is the HTTP surface of the Volunteer_Dashboard (R18). Every route is
gated with ``require_role(Role.volunteer)`` so a Patient or Clinician session —
or an unauthenticated one — can never reach a volunteer resource (R4.4, R20.2):
the dependency raises **401** (redirect to sign-in) when unauthenticated and
**403** (access denied) for the wrong role before any handler body runs. The
current Volunteer is resolved from the authenticated session's ``subject_id``.

The routes expose the Availability_Service, the appointment state machine, and
the Visit_Service:

* ``GET /volunteer/slots`` and ``POST /volunteer/slots`` — list and add
  availability slots (R6.1); the new slot is recorded ``available``.
* ``DELETE /volunteer/slots/{slot_id}`` — remove a slot (R6.2); a slot that
  holds an assigned appointment is rejected with **409 slot-has-appointment**
  (R6.3).
* ``GET /volunteer/appointments`` — the Volunteer's assigned appointments with
  their lifecycle states (R18.1).
* ``POST /volunteer/appointments/{id}/accept`` — accept an assigned appointment
  (``booked -> accepted``, R8.6), and ``.../decline`` — decline it
  (``booked -> cancelled``, R8.7). An invalid transition maps to **409
  invalid-transition** with the preserved current state.
* ``GET /volunteer/appointments/{id}/visit`` — open the visit detail for an
  assigned appointment, showing only the Volunteer's authorized services
  (R9.1, R9.2).
* ``POST /volunteer/appointments/{id}/questionnaire`` and
  ``.../test-result`` — submit a questionnaire (R10.1) or a Test_Result
  (R10.3). The Visit_Service's typed rejections map to HTTP per the design's
  Error Handling table: unauthorized-service → **403**; wrong-state → **409**
  with the current state; missing-required-questions → **400** with the named
  questions.

Each route is thin: it validates input with the Pydantic schemas, resolves the
appointment and confirms it belongs to the current Volunteer, calls the
service, and shapes the typed result into the response model. All domain rules
(authorization, lifecycle, completion trigger) stay in the services.
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, status
from fastapi.exceptions import HTTPException
from sqlalchemy.orm import Session as DBSession

from app.api.deps import AuthSession, get_session, require_role
from app.api.schemas import (
    QuestionnaireSubmission,
    ServiceTypeSummary,
    SlotCreateRequest,
    SlotResponse,
    SubmissionResponse,
    TestResultSubmission,
    VisitDetailResponse,
    VolunteerAppointmentResponse,
)
from app.api.schemas import Location
from app.models.appointment import Appointment
from app.models.availability import AvailabilitySlot
from app.models.enums import AppointmentState, Role
from app.models.people import Volunteer
from app.services import availability as availability_service
from app.services import visit as visit_service
from app.services.appointment_state import (
    INVALID_TRANSITION_MESSAGE,
    transition,
)
from app.services.availability import SlotHasAppointment
from app.services.visit import UNAUTHORIZED_SERVICE_MESSAGE

router = APIRouter(prefix="/volunteer", tags=["volunteer"])

# Every route in this router requires an authenticated Volunteer session.
require_volunteer = require_role(Role.volunteer)


# ---------------------------------------------------------------------------
# Shared resolution helpers
# ---------------------------------------------------------------------------
def _current_volunteer(session: AuthSession, db: DBSession) -> Volunteer:
    """Load the Volunteer behind the authenticated session (R4.4, R20.2).

    ``require_role(Role.volunteer)`` has already proven the session's role is
    ``volunteer``; this resolves the concrete row by ``subject_id``. A missing
    row (e.g. an account deleted after the token was issued) is treated as 401
    so a stale token cannot act on a nonexistent volunteer.
    """
    volunteer = db.get(Volunteer, session.subject_id)
    if volunteer is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "authentication-required"},
        )
    return volunteer


def _own_slot(db: DBSession, volunteer: Volunteer, slot_id: int) -> AvailabilitySlot:
    """Resolve a slot, confirming it belongs to the current Volunteer.

    A slot that does not exist, or that belongs to a different Volunteer, is a
    404 — a Volunteer must never be able to read or mutate another Volunteer's
    availability (R4.4, R20.2).
    """
    slot = db.get(AvailabilitySlot, slot_id)
    if slot is None or slot.volunteer_id != volunteer.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "unknown-slot"},
        )
    return slot


def _own_appointment(
    db: DBSession, volunteer: Volunteer, appointment_id: int
) -> Appointment:
    """Resolve an appointment, confirming it is assigned to this Volunteer.

    An appointment that does not exist, or that is assigned to a different
    Volunteer, is a 404 so a Volunteer can only act on their own assignments
    (R4.4, R20.2).
    """
    appointment = db.get(Appointment, appointment_id)
    if appointment is None or appointment.volunteer_id != volunteer.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "unknown-appointment"},
        )
    return appointment


def _slot_response(slot: AvailabilitySlot) -> SlotResponse:
    """Project an AvailabilitySlot into its Volunteer-facing response shape."""
    return SlotResponse(
        id=slot.id,
        start=slot.start,
        end=slot.end,
        status=slot.status.value,
    )


def _appointment_response(appointment: Appointment) -> VolunteerAppointmentResponse:
    """Project an Appointment into the Volunteer-facing response shape (R18.1)."""
    slot = appointment.slot
    service = appointment.service_type
    return VolunteerAppointmentResponse(
        id=appointment.id,
        patient_id=appointment.patient_id,
        service_type=service.name if service is not None else "",
        state=appointment.state.value,
        slot_start=(appointment.requested_start or (slot.start if slot is not None else None)),
        slot_end=(appointment.requested_end or (slot.end if slot is not None else None)),
        queued_for_review=appointment.queued_for_review,
        reviewed=appointment.reviewed,
    )


def _service_type_summary(service_type) -> ServiceTypeSummary:
    """Project a Service_Type into the visit-detail summary shape."""
    return ServiceTypeSummary(id=service_type.id, name=service_type.name)


# ---------------------------------------------------------------------------
# Availability management (R6.1, R6.2, R6.3)
# ---------------------------------------------------------------------------
@router.get("/slots", response_model=List[SlotResponse])
def list_slots(
    session: AuthSession = Depends(require_volunteer),
    db: DBSession = Depends(get_session),
) -> List[SlotResponse]:
    """List the Volunteer's availability slots (R6)."""
    volunteer = _current_volunteer(session, db)
    slots = sorted(volunteer.availability_slots, key=lambda s: (s.start, s.id))
    return [_slot_response(s) for s in slots]


@router.post(
    "/slots",
    response_model=SlotResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_slot(
    payload: SlotCreateRequest,
    session: AuthSession = Depends(require_volunteer),
    db: DBSession = Depends(get_session),
) -> SlotResponse:
    """Record a new availability slot for the Volunteer (R6.1).

    The Availability_Service records the slot as ``available`` and unassigned;
    the created slot is returned.
    """
    volunteer = _current_volunteer(session, db)
    slot = availability_service.add_slot(db, volunteer, payload.start, payload.end)
    return _slot_response(slot)


@router.delete(
    "/slots/{slot_id}",
    response_model=SlotResponse,
    responses={
        404: {"description": "unknown slot"},
        409: {"description": "slot-has-appointment"},
    },
)
def remove_slot(
    slot_id: int,
    session: AuthSession = Depends(require_volunteer),
    db: DBSession = Depends(get_session),
) -> SlotResponse:
    """Remove one of the Volunteer's availability slots (R6.2, R6.3).

    A free slot is marked ``unavailable`` and returned (R6.2). A slot holding an
    assigned appointment is rejected: the Availability_Service raises
    :class:`SlotHasAppointment`, mapped here to **409 slot-has-appointment**
    (R6.3), leaving the slot untouched.
    """
    volunteer = _current_volunteer(session, db)
    slot = _own_slot(db, volunteer, slot_id)
    try:
        removed = availability_service.remove_slot(db, slot)
    except SlotHasAppointment as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": exc.message},
        )
    return _slot_response(removed)


# ---------------------------------------------------------------------------
# Assigned appointments with lifecycle states (R18.1)
# ---------------------------------------------------------------------------
@router.get("/appointments", response_model=List[VolunteerAppointmentResponse])
def list_appointments(
    session: AuthSession = Depends(require_volunteer),
    db: DBSession = Depends(get_session),
) -> List[VolunteerAppointmentResponse]:
    """List the Volunteer's assigned appointments with their states (R18.1)."""
    volunteer = _current_volunteer(session, db)
    appointments = sorted(volunteer.appointments, key=lambda a: a.id)
    return [_appointment_response(a) for a in appointments]


# ---------------------------------------------------------------------------
# Accept / decline an assigned appointment (R8.6, R8.7)
# ---------------------------------------------------------------------------
def _transition_or_409(
    db: DBSession, appointment: Appointment, target: AppointmentState
) -> VolunteerAppointmentResponse:
    """Apply a lifecycle transition, mapping a rejection to 409 (R8.6-R8.9).

    On an invalid transition the state machine preserves the current state and
    returns :data:`INVALID_TRANSITION_MESSAGE`; this maps that to **409** and
    surfaces the preserved ``current_state`` so the dashboard can explain why
    the action was refused (e.g. accepting an already-cancelled appointment).
    """
    result = transition(db, appointment, target)
    if not result.ok:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": result.message or INVALID_TRANSITION_MESSAGE,
                "current_state": result.state.value,
            },
        )
    return _appointment_response(appointment)


@router.post(
    "/appointments/{appointment_id}/accept",
    response_model=VolunteerAppointmentResponse,
    responses={409: {"description": "invalid-transition"}},
)
def accept_appointment(
    appointment_id: int,
    session: AuthSession = Depends(require_volunteer),
    db: DBSession = Depends(get_session),
) -> VolunteerAppointmentResponse:
    """Accept an assigned appointment: ``booked -> accepted`` (R8.6)."""
    volunteer = _current_volunteer(session, db)
    appointment = _own_appointment(db, volunteer, appointment_id)
    return _transition_or_409(db, appointment, AppointmentState.accepted)


@router.post(
    "/appointments/{appointment_id}/decline",
    response_model=VolunteerAppointmentResponse,
    responses={409: {"description": "invalid-transition"}},
)
def decline_appointment(
    appointment_id: int,
    session: AuthSession = Depends(require_volunteer),
    db: DBSession = Depends(get_session),
) -> VolunteerAppointmentResponse:
    """Decline an assigned appointment: ``booked -> cancelled`` (R8.7).

    The state machine's ``* -> cancelled`` side effect returns the slot to the
    available pool.
    """
    volunteer = _current_volunteer(session, db)
    appointment = _own_appointment(db, volunteer, appointment_id)
    return _transition_or_409(db, appointment, AppointmentState.cancelled)


# ---------------------------------------------------------------------------
# Visit detail — only authorized services shown (R9.1, R9.2)
# ---------------------------------------------------------------------------
@router.get(
    "/appointments/{appointment_id}/visit",
    response_model=VisitDetailResponse,
)
def get_visit_detail(
    appointment_id: int,
    session: AuthSession = Depends(require_volunteer),
    db: DBSession = Depends(get_session),
) -> VisitDetailResponse:
    """Open the visit detail for an assigned appointment (R9.1, R9.2).

    Shows the requested Service_Type, the visit location, and **only** the
    Service_Types this Volunteer is currently authorized to perform — never the
    full catalog (R9.2). The gating lives in the Visit_Service.
    """
    volunteer = _current_volunteer(session, db)
    appointment = _own_appointment(db, volunteer, appointment_id)
    detail = visit_service.visit_detail(db, volunteer, appointment)
    return VisitDetailResponse(
        requested_service_type=_service_type_summary(detail.requested_service_type),
        location=Location(lat=detail.location["lat"], lng=detail.location["lng"]),
        authorized_services=[
            _service_type_summary(st) for st in detail.authorized_services
        ],
    )


# ---------------------------------------------------------------------------
# Questionnaire / test-result submission (R10.1, R10.3)
# ---------------------------------------------------------------------------
def _submission_to_http(result) -> SubmissionResponse:
    """Map a Visit_Service SubmissionResult to a response or an HTTP error.

    Per the design's Error Handling table:

    * ``unauthorized-service`` → **403** (prior data retained, R9.3, R10.4).
    * missing-required-questions → **400** with each named question (R10.2).
    * wrong appointment state → **409** with the returned current state (R10.6).

    A successful submission is projected into :class:`SubmissionResponse`,
    carrying ``completed`` when this submission completed the appointment's
    required data set and queued it for review (R10.5).
    """
    if result.ok:
        return SubmissionResponse(
            ok=True, message=result.message, completed=result.completed
        )

    if result.message == UNAUTHORIZED_SERVICE_MESSAGE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"message": result.message},
        )

    if result.missing_questions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": result.message,
                "missing_questions": list(result.missing_questions),
            },
        )

    if result.current_state is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": result.message,
                "current_state": result.current_state.value,
            },
        )

    # Any other rejection (e.g. measurement-required) is a bad request.
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"message": result.message},
    )


@router.post(
    "/appointments/{appointment_id}/questionnaire",
    response_model=SubmissionResponse,
    responses={
        400: {"description": "missing-required-questions"},
        403: {"description": "unauthorized-service"},
        409: {"description": "wrong appointment state"},
    },
)
def submit_questionnaire(
    appointment_id: int,
    payload: QuestionnaireSubmission,
    session: AuthSession = Depends(require_volunteer),
    db: DBSession = Depends(get_session),
) -> SubmissionResponse:
    """Submit questionnaire answers for an accepted, authorized visit (R10.1).

    The Visit_Service enforces the authorization, lifecycle-state, and
    required-question gates; its typed rejections are mapped to HTTP here. On
    success the appointment may auto-complete and queue for review (R10.5).
    """
    volunteer = _current_volunteer(session, db)
    appointment = _own_appointment(db, volunteer, appointment_id)
    result = visit_service.submit_questionnaire(
        db, volunteer, appointment, payload.answers
    )
    return _submission_to_http(result)


@router.post(
    "/appointments/{appointment_id}/test-result",
    response_model=SubmissionResponse,
    responses={
        400: {"description": "measurement-required"},
        403: {"description": "unauthorized-service"},
        409: {"description": "wrong appointment state"},
    },
)
def submit_test_result(
    appointment_id: int,
    payload: TestResultSubmission,
    session: AuthSession = Depends(require_volunteer),
    db: DBSession = Depends(get_session),
) -> SubmissionResponse:
    """Submit an information-only Test_Result for an accepted visit (R10.3).

    Recorded as Synthetic_Data; never establishes treatment (R10.7). The
    Visit_Service enforces the authorization and lifecycle-state gates; its
    typed rejections are mapped to HTTP here. On success the appointment may
    auto-complete and queue for review (R10.5).
    """
    volunteer = _current_volunteer(session, db)
    appointment = _own_appointment(db, volunteer, appointment_id)
    result = visit_service.submit_test_result(
        db,
        volunteer,
        appointment,
        {
            "measurement": payload.measurement,
            "value": payload.value,
            "unit": payload.unit,
        },
    )
    return _submission_to_http(result)


__all__ = ["router"]
