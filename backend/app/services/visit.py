"""Visit_Service: authorized visit detail and gated data capture (R9, R10, R13.3, R13.4).

This service is what a Volunteer interacts with during an assigned visit. It
does two things, both tightly gated by the credential-derived
Authorized_Services and the appointment lifecycle state:

1. :func:`visit_detail` — show the requested Service_Type and the visit
   location, plus **only** the Service_Types this Volunteer is actually
   authorized to perform (R9.1, R9.2).
2. :func:`submit_questionnaire` / :func:`submit_test_result` — capture visit
   data, but only when the submission is authorized and well-formed:

   * The appointment's requested Service_Type must be in the Volunteer's
     Authorized_Services (R9.3, R10.4). Otherwise the submission is rejected
     with an ``unauthorized-service`` message and **any previously recorded
     data is retained unchanged**.
   * The appointment must be in the ``accepted`` state (R10.6). Otherwise the
     submission is rejected, prior data retained, and the appointment's
     **current** lifecycle state is returned.
   * A questionnaire must answer every question the Service_Type marks required
     (R10.2); a submission missing any is rejected, prior data retained, and
     **each** missing question is named.
   * A Test_Result is recorded as Synthetic_Data and treated as information
     only — it never establishes treatment and nothing here derives a decision
     or prescription from it (R10.3, R10.7, R13.3, R13.4).

Completion trigger (R10.5)
--------------------------
After a successful submission, the service checks whether **every** required
questionnaire question and **every** required test for the appointment's
requested Service_Type is now present. When that whole-set condition holds, it
asks the appointment state machine (``appointment_state.transition``) to move
the appointment ``accepted -> completed``, which queues it for clinician review.
The Visit_Service never flips the state directly: completion and its
queue-for-review side effect live in one place, the state machine.

Source of truth for authorization
----------------------------------
Authorization is read from :func:`credentials.derive_authorized_service_types`,
the single pure derivation over the Volunteer's verified, condition-satisfied
credentials. The Visit_Service never consults a role or a raw credential flag
directly, so what a Volunteer may capture can never drift from the credential
facts (R9.2, R9.3, R10.4).

Result style follows the rest of the service layer: each operation returns a
small frozen dataclass with ``ok`` and a stable ``message``, never a bare
boolean, so callers (and the UI) have a typed, self-describing outcome.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Set

from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.models.appointment import Appointment, Questionnaire, TestResult
from app.models.credential import ServiceType
from app.models.enums import AppointmentState
from app.models.people import Volunteer
from app.services import appointment_state
from app.services.credentials import derive_authorized_service_types

# Stable messages the UI can key on (mirroring the design's result variants).
UNAUTHORIZED_SERVICE_MESSAGE = "unauthorized-service"
SUBMISSION_RECORDED_MESSAGE = "submission-recorded"


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class VisitDetail:
    """What a Volunteer sees when opening an assigned appointment (R9.1, R9.2).

    ``requested_service_type`` is the Service_Type the appointment was booked
    for; ``location`` is the visit location (the Patient's recorded lat/lng);
    ``authorized_services`` is **only** the Service_Types this Volunteer is
    currently authorized to perform (R9.2) — never the full catalog.
    """

    requested_service_type: ServiceType
    location: Dict[str, float]
    authorized_services: List[ServiceType]


@dataclass(frozen=True)
class SubmissionResult:
    """Outcome of a questionnaire/test submission.

    ``ok`` is True only when the submission was recorded. ``message`` carries a
    stable identifier for the outcome. On any rejection, previously recorded
    data for the appointment is left unchanged (R10.2, R10.4, R10.6).

    The optional fields are populated to let the caller act on a rejection
    without re-deriving anything:

    * ``current_state`` — the appointment's current lifecycle state, set on a
      wrong-state rejection (R10.6).
    * ``missing_questions`` — each required question left unanswered, set on a
      missing-required-question rejection (R10.2).
    * ``completed`` — True when this submission completed the appointment and
      queued it for review (R10.5).
    """

    ok: bool
    message: str
    current_state: Optional[AppointmentState] = None
    missing_questions: List[str] = field(default_factory=list)
    completed: bool = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _split_csv(value: Optional[str]) -> List[str]:
    """Parse a comma-separated identifier list, trimming blanks.

    The Service_Type's ``required_questions`` / ``required_tests`` and a
    Questionnaire's ``required_question_ids`` are stored as comma-separated
    identifiers in the seed. An empty or ``None`` value means "none required".
    Order is preserved and duplicates are collapsed away by callers that need a
    set.
    """
    if not value:
        return []
    return [token.strip() for token in value.split(",") if token.strip()]


def _authorized_service_ids(volunteer: Volunteer) -> Set[int]:
    """The Service_Type ids this Volunteer may perform (credential-derived).

    Thin wrapper over the Credential_Service's pure derivation so the gate here
    reads exactly the same authorization facts as the Matching_Engine and
    Appointment_Service (R9.2, R9.3, R10.4).
    """
    return derive_authorized_service_types(volunteer)


def _is_authorized(volunteer: Volunteer, appointment: Appointment) -> bool:
    """Whether the appointment's requested Service_Type is authorized (R9.3, R10.4)."""
    return appointment.service_type_id in _authorized_service_ids(volunteer)


def _answered_question_ids(appointment: Appointment) -> Set[str]:
    """Every question id answered across the appointment's questionnaires.

    Questionnaire answers are stored as comma-separated answered-question
    identifiers in ``Questionnaire.answers``; completion (R10.5) is about which
    required questions have an answer somewhere against this appointment.
    """
    answered: Set[str] = set()
    for questionnaire in appointment.questionnaires:
        answered.update(_split_csv(questionnaire.answers))
    return answered


def _recorded_test_measurements(appointment: Appointment) -> Set[str]:
    """Every test measurement recorded against the appointment.

    Used to check the Service_Type's required tests are all present (R10.5).
    """
    return {result.measurement for result in appointment.test_results}


def _required_data_complete(appointment: Appointment) -> bool:
    """True when all required questions AND required tests are present (R10.5).

    Reads the required sets from the appointment's requested Service_Type and
    compares them against what has actually been recorded. A Service_Type with
    no required questions/tests is complete as soon as it is in scope, matching
    the seed's ``wellness_check`` (no required tests).
    """
    service_type = appointment.service_type
    required_questions = set(_split_csv(service_type.required_questions))
    required_tests = set(_split_csv(service_type.required_tests))

    questions_ok = required_questions.issubset(_answered_question_ids(appointment))
    tests_ok = required_tests.issubset(_recorded_test_measurements(appointment))
    return questions_ok and tests_ok


def _maybe_complete(
    db: DBSession, appointment: Appointment
) -> bool:
    """Complete + queue-for-review when required data is present (R10.5).

    Delegates the state change to the appointment state machine's
    ``accepted -> completed`` transition, which sets ``queued_for_review``. The
    Visit_Service never sets the state or the flag itself. Returns True iff the
    appointment was transitioned to ``completed`` by this call.
    """
    if not _required_data_complete(appointment):
        return False

    result = appointment_state.transition(
        db, appointment, AppointmentState.completed
    )
    return result.ok and result.state == AppointmentState.completed


def _guard_submission(
    volunteer: Volunteer, appointment: Appointment
) -> Optional[SubmissionResult]:
    """Shared gate for both submission paths; returns a rejection or ``None``.

    Checks authorization first (R9.3, R10.4), then lifecycle state (R10.6). On a
    failure it returns the appropriate rejection ``SubmissionResult`` with no
    data written (so prior data is retained by construction). ``None`` means the
    submission may proceed.
    """
    # Authorization gate: the requested Service_Type must be authorized (R10.4).
    if not _is_authorized(volunteer, appointment):
        return SubmissionResult(ok=False, message=UNAUTHORIZED_SERVICE_MESSAGE)

    # State gate: only the accepted state admits data entry (R10.6). Return the
    # current state so the caller can explain why it was rejected.
    if appointment.state != AppointmentState.accepted:
        return SubmissionResult(
            ok=False,
            message=appointment.state.value,
            current_state=appointment.state,
        )

    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def visit_detail(
    db: DBSession, volunteer: Volunteer, appointment: Appointment
) -> VisitDetail:
    """Show the requested service, location, and authorized services (R9.1, R9.2).

    Returns the appointment's requested :class:`ServiceType`, the visit location
    (the Patient's recorded lat/lng), and **only** the Service_Types this
    Volunteer is currently authorized to perform. Authorization is the pure
    credential derivation, so a Volunteer never sees a service they could not
    actually deliver (R9.2).
    """
    authorized_ids = _authorized_service_ids(volunteer)

    # Resolve the authorized ids to ServiceType rows straight from the pure
    # credential derivation (the single source of truth), rather than from the
    # materialized AuthorizedService join. This stays correct whether or not
    # Credential_Service.recompute_authorized_services has reconciled the join
    # for this Volunteer, so visit_detail never shows a stale or empty set.
    # Ordered stably by Service_Type name.
    authorized_services: List[ServiceType] = []
    if authorized_ids:
        authorized_services = list(
            db.execute(
                select(ServiceType).where(ServiceType.id.in_(authorized_ids))
            )
            .scalars()
            .all()
        )
    authorized_services.sort(key=lambda st: st.name)

    patient = appointment.patient
    location = {"lat": patient.latitude, "lng": patient.longitude}

    return VisitDetail(
        requested_service_type=appointment.service_type,
        location=location,
        authorized_services=authorized_services,
    )


def submit_questionnaire(
    db: DBSession,
    volunteer: Volunteer,
    appointment: Appointment,
    answers: Mapping[str, object],
) -> SubmissionResult:
    """Record questionnaire answers for an accepted, authorized visit (R10.1, R10.2).

    ``answers`` maps question id -> answer. The submission is rejected, with any
    previously recorded answers for the appointment left unchanged, when:

    * the requested Service_Type is not authorized (``unauthorized-service``,
      R10.4),
    * the appointment is not in the ``accepted`` state (current state returned,
      R10.6), or
    * one or more questions marked required for the appointment's Service_Type
      are unanswered — each missing question is named (R10.2).

    On success the answers are recorded as a :class:`Questionnaire` against the
    appointment (R10.1) and, if that makes the full required data set present,
    the appointment is transitioned to ``completed`` and queued for review
    (R10.5).
    """
    rejection = _guard_submission(volunteer, appointment)
    if rejection is not None:
        return rejection

    # Required-question gate (R10.2): every required question must be answered
    # with a non-empty value. Name *each* missing one; write nothing on failure
    # so prior answers are retained.
    required_questions = _split_csv(appointment.service_type.required_questions)
    missing = [
        question_id
        for question_id in required_questions
        if question_id not in answers
        or answers[question_id] is None
        or (isinstance(answers[question_id], str) and not answers[question_id].strip())
    ]
    if missing:
        return SubmissionResult(
            ok=False,
            message="missing-required-questions: " + ", ".join(missing),
            missing_questions=missing,
        )

    # Record the answers (R10.1). Store the answered-question ids as the compact
    # CSV the completion check reads back.
    answered_ids = [
        question_id
        for question_id in answers
        if answers[question_id] is not None
        and not (
            isinstance(answers[question_id], str)
            and not answers[question_id].strip()
        )
    ]
    questionnaire = Questionnaire(
        appointment_id=appointment.id,
        service_type_id=appointment.service_type_id,
        answers=",".join(answered_ids),
        required_question_ids=appointment.service_type.required_questions,
    )
    db.add(questionnaire)
    db.flush()
    # Keep the in-memory relationship consistent for the completion check.
    if questionnaire not in appointment.questionnaires:
        appointment.questionnaires.append(questionnaire)

    completed = _maybe_complete(db, appointment)
    return SubmissionResult(
        ok=True, message=SUBMISSION_RECORDED_MESSAGE, completed=completed
    )


def submit_test_result(
    db: DBSession,
    volunteer: Volunteer,
    appointment: Appointment,
    result: Mapping[str, object],
) -> SubmissionResult:
    """Record an information-only Test_Result for an accepted visit (R10.3, R10.7).

    ``result`` carries at least a ``measurement`` identifier and optionally a
    numeric ``value`` and a ``unit``. The submission is rejected, with any
    previously recorded data left unchanged, when the requested Service_Type is
    not authorized (``unauthorized-service``, R10.4) or the appointment is not
    in the ``accepted`` state (current state returned, R10.6).

    The Test_Result is stored as Synthetic_Data and is **information only**: the
    Visit_Service never derives a decision, treatment, or prescription from it
    (R10.7, R13.3, R13.4). On success, if the full required data set is now
    present the appointment is transitioned to ``completed`` and queued for
    review (R10.5).
    """
    rejection = _guard_submission(volunteer, appointment)
    if rejection is not None:
        return rejection

    measurement = result.get("measurement")
    if measurement is None or (
        isinstance(measurement, str) and not measurement.strip()
    ):
        # A test result with no measurement identifier is meaningless; reject it
        # without writing, so prior data is retained.
        return SubmissionResult(
            ok=False, message="measurement-required", missing_questions=[]
        )

    raw_value = result.get("value")
    value: Optional[float]
    try:
        value = float(raw_value) if raw_value is not None else None
    except (TypeError, ValueError):
        value = None

    unit = result.get("unit")
    test_result = TestResult(
        appointment_id=appointment.id,
        service_type_id=appointment.service_type_id,
        measurement=str(measurement).strip(),
        value=value,
        unit=str(unit) if unit is not None else None,
        # Always Synthetic_Data; a Test_Result is information only (R10.3, R13.3).
        synthetic=True,
    )
    db.add(test_result)
    db.flush()
    if test_result not in appointment.test_results:
        appointment.test_results.append(test_result)

    completed = _maybe_complete(db, appointment)
    return SubmissionResult(
        ok=True, message=SUBMISSION_RECORDED_MESSAGE, completed=completed
    )


__all__ = [
    "UNAUTHORIZED_SERVICE_MESSAGE",
    "SUBMISSION_RECORDED_MESSAGE",
    "VisitDetail",
    "SubmissionResult",
    "visit_detail",
    "submit_questionnaire",
    "submit_test_result",
]
