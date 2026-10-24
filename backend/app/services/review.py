"""Review_Service: clinician review, decisions, referrals, medication gating.

This implements the design's ``Review_Service`` (R11, R12, R13): it lets a
verified Clinician review the findings of a completed visit, record and approve
a Clinical_Decision, issue a specialty Referral, and expose approved medications
— while gating everything the Patient can see behind a Clinician's approval.

The service enforces three invariants that the rest of the platform relies on:

* **Review is state-gated.** Only a ``completed`` appointment that is
  ``queued_for_review`` may be opened; any other appointment is denied with a
  not-ready-for-review message (R11.1, R11.2).

* **Clinical authority comes from a verified license, never from data.** A
  decision or a medication is only ever created by a Clinician whose license is
  verified (checked via :func:`is_clinician_license_verified`); an unverified
  clinician's decision is *discarded without being stored* (R11.6, R13.2). A
  prescription is never derived from a Test_Result, a Questionnaire answer, or
  any automated component — the only way a Medication comes into existence is
  :func:`prescribe_medication`, which requires a verified Clinician as an
  explicit actor (R13.3, R13.4).

* **The Patient sees nothing until it is approved.** A recorded decision,
  its referral, and a medication are all withheld from the Patient until the
  prescribing/deciding Clinician marks them approved (R11.8, R11.9, R13.1,
  R13.5). The ``*_for_patient`` read helpers are the single place that filter
  is applied.

This service mutates only the records it owns (the ClinicalDecision, Referral,
Medication, and — for a referral — the Patient's ``required_specialty``) and
never commits; the caller owns the transaction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from sqlalchemy.orm import Session as DBSession

from app.models.appointment import Appointment, Questionnaire, TestResult
from app.models.clinical import ClinicalDecision, Medication, Referral
from app.models.enums import AppointmentState
from app.models.people import Clinician, Patient
from app.services.credentials import is_clinician_license_verified

# Uniform messages, mirroring the indications named in the acceptance criteria
# so callers/UI can key off a stable string.
NOT_READY_FOR_REVIEW_MESSAGE = "appointment-not-ready-for-review"
DECISION_CONTENT_REQUIRED_MESSAGE = "decision content is required"
CREDENTIAL_NOT_VERIFIED_MESSAGE = "credential-not-verified"
NO_DECISION_TO_APPROVE_MESSAGE = "no decision exists to approve"
NOT_AUTHORIZED_TO_PRESCRIBE_MESSAGE = "not-authorized-to-prescribe"


@dataclass(frozen=True)
class FindingsResult:
    """Outcome of :func:`open_for_review`.

    On success ``ok`` is True and ``questionnaires``/``test_results`` carry the
    appointment's recorded findings for display (R11.1). When the appointment is
    not completed-and-queued the result is a denial: ``ok`` is False, the lists
    are empty, and ``message`` carries the not-ready-for-review indication
    (R11.2).
    """

    ok: bool
    questionnaires: List[Questionnaire] = field(default_factory=list)
    test_results: List[TestResult] = field(default_factory=list)
    message: Optional[str] = None


@dataclass(frozen=True)
class DecisionResult:
    """Outcome of :func:`record_decision`.

    On success ``ok`` is True and ``decision`` is the stored ClinicalDecision
    (the appointment is now marked reviewed; R11.3, R11.4). On rejection ``ok``
    is False, ``decision`` is None (nothing was stored — critically so for the
    unverified-license case, R11.6), and ``message`` explains why.
    """

    ok: bool
    decision: Optional[ClinicalDecision] = None
    message: Optional[str] = None


@dataclass(frozen=True)
class ApprovalResult:
    """Outcome of :func:`approve_decision`.

    On success ``ok`` is True and ``decision`` is the now-approved decision,
    visible to the Patient (R11.9). When there is no stored decision to approve
    ``ok`` is False and ``message`` carries the nothing-to-approve indication
    (R11.7).
    """

    ok: bool
    decision: Optional[ClinicalDecision] = None
    message: Optional[str] = None


@dataclass(frozen=True)
class ReferralResult:
    """Outcome of :func:`issue_referral`.

    On success ``ok`` is True, ``referral`` is the recorded Referral, and the
    Patient's ``required_specialty`` has been set to its specialty so the
    Recommendation_Engine uses it as the hard filter (R12.1, R12.2). On
    rejection ``ok`` is False and ``message`` explains why.
    """

    ok: bool
    referral: Optional[Referral] = None
    message: Optional[str] = None


@dataclass(frozen=True)
class MedicationResult:
    """Outcome of :func:`prescribe_medication`.

    On success ``ok`` is True and ``medication`` is the created (unapproved)
    Medication. When the acting clinician's license is unverified the attempt is
    rejected and nothing is persisted (R13.2): ``ok`` is False, ``medication``
    is None, and ``message`` carries the not-authorized-to-prescribe indication.
    """

    ok: bool
    medication: Optional[Medication] = None
    message: Optional[str] = None


def _is_ready_for_review(appointment: Appointment) -> bool:
    """Return True iff ``appointment`` is completed AND queued for review (R11.2)."""
    return (
        appointment.state == AppointmentState.completed
        and appointment.queued_for_review
    )


def open_for_review(
    session: DBSession, clinician: Clinician, appointment: Appointment
) -> FindingsResult:
    """Open a completed, queued appointment's findings for a Clinician (R11.1, R11.2).

    Returns the appointment's recorded Questionnaire answers and Test_Results
    for display only when the appointment is ``completed`` *and*
    ``queued_for_review``. Any other appointment (still booked/accepted, already
    cancelled, or completed but not queued) is denied with the
    not-ready-for-review message and no findings. This is a pure read — it
    mutates nothing.
    """
    if not _is_ready_for_review(appointment):
        return FindingsResult(ok=False, message=NOT_READY_FOR_REVIEW_MESSAGE)

    return FindingsResult(
        ok=True,
        questionnaires=list(appointment.questionnaires),
        test_results=list(appointment.test_results),
    )


def record_decision(
    session: DBSession,
    clinician: Clinician,
    appointment: Appointment,
    content: str,
) -> DecisionResult:
    """Record a Clinical_Decision for a queued appointment (R11.3-R11.6).

    Gates, in order:

    * The appointment must be open for review (completed + queued); otherwise
      the decision is rejected with the not-ready-for-review message and nothing
      is stored.
    * ``content`` must be non-empty (after stripping whitespace); empty or
      missing content is rejected with a content-required message and the
      appointment's review state is left unchanged (R11.5).
    * The clinician's license must be verified; an unverified license causes the
      submitted decision to be **discarded without being stored**, returning the
      credential-not-verified message (R11.6). This check deliberately runs
      before any write so no ClinicalDecision row is ever created for an
      unverified clinician.

    On success the ClinicalDecision is stored (reviewed=True, approved=False)
    and the appointment is marked ``reviewed`` (R11.3, R11.4). The decision is
    not yet visible to the Patient — that requires approval (R11.8).
    """
    if not _is_ready_for_review(appointment):
        return DecisionResult(ok=False, message=NOT_READY_FOR_REVIEW_MESSAGE)

    # Empty/missing content: reject, leave review state unchanged (R11.5).
    if content is None or not content.strip():
        return DecisionResult(ok=False, message=DECISION_CONTENT_REQUIRED_MESSAGE)

    # Unverified license: discard the decision without storing it (R11.6).
    # Checked before any write so nothing is ever persisted for this attempt.
    if not is_clinician_license_verified(clinician):
        return DecisionResult(ok=False, message=CREDENTIAL_NOT_VERIFIED_MESSAGE)

    decision = ClinicalDecision(
        clinician_id=clinician.id,
        content=content,
        reviewed=True,
        approved=False,
    )
    # Assign through the relationship (not just the FK) so the in-memory object
    # graph stays consistent: a caller that already read ``appointment.decision``
    # as None sees the stored decision without a refresh.
    decision.appointment = appointment
    session.add(decision)

    # A stored decision marks the appointment reviewed (R11.4).
    appointment.reviewed = True

    session.flush()
    return DecisionResult(ok=True, decision=decision)


def approve_decision(
    session: DBSession, clinician: Clinician, appointment: Appointment
) -> ApprovalResult:
    """Approve the appointment's stored Clinical_Decision (R11.7, R11.9).

    If the appointment has no stored ClinicalDecision, the approval is rejected
    with the nothing-to-approve message (R11.7). Otherwise the decision is
    marked ``approved``, which is precisely what makes it — and any referral
    issued from it — visible to the Patient (R11.8 -> R11.9).
    """
    decision = appointment.decision
    if decision is None:
        return ApprovalResult(ok=False, message=NO_DECISION_TO_APPROVE_MESSAGE)

    decision.approved = True
    session.flush()
    return ApprovalResult(ok=True, decision=decision)


def issue_referral(
    session: DBSession,
    clinician: Clinician,
    appointment: Appointment,
    specialty: str,
) -> ReferralResult:
    """Issue a specialty Referral for a reviewed appointment (R12.1, R12.2).

    Requires the appointment to already carry a stored ClinicalDecision (a
    referral is issued *from* a reviewed decision); otherwise it is rejected
    with the nothing-to-approve message, since there is no decision to refer
    from. ``specialty`` must be non-empty.

    On success a Referral is recorded against the Patient with the recommended
    specialty, and the Patient's ``required_specialty`` is set to that specialty
    so the Recommendation_Engine applies it as the hard specialty filter
    (R12.2). The referral's visibility to the Patient still follows the parent
    decision's approval state (R11.8); recording it does not reveal it.
    """
    decision = appointment.decision
    if decision is None:
        return ReferralResult(ok=False, message=NO_DECISION_TO_APPROVE_MESSAGE)

    if specialty is None or not specialty.strip():
        return ReferralResult(ok=False, message="referral specialty is required")

    specialty_value = specialty.strip()
    referral = Referral(specialty=specialty_value)
    # Assign through relationships so the decision's ``referrals`` collection and
    # the patient's ``referrals`` stay consistent in the current identity map.
    referral.clinical_decision = decision
    referral.patient = appointment.patient
    session.add(referral)

    # Feed the referred specialty to the Recommendation_Engine as the Patient's
    # required specialty filter (R12.2).
    appointment.patient.required_specialty = specialty_value

    session.flush()
    return ReferralResult(ok=True, referral=referral)


def prescribe_medication(
    session: DBSession,
    clinician: Clinician,
    patient: Patient,
    name: str,
) -> MedicationResult:
    """Create a display-only Medication via a verified Clinician (R13.2, R13.4).

    A Medication is only ever created here, with a Clinician supplied as the
    explicit prescribing actor — there is deliberately no path that derives a
    prescription from a Test_Result, a Questionnaire answer, or any automated
    component (R13.4). If the acting clinician's license is unverified the
    attempt is rejected, nothing is persisted, and the not-authorized-to-
    prescribe message is returned (R13.2).

    The created Medication starts ``approved=False`` and so is withheld from the
    Patient's dashboard until the prescribing Clinician approves it via
    :func:`approve_medication` (R13.1, R13.5).
    """
    if not is_clinician_license_verified(clinician):
        return MedicationResult(ok=False, message=NOT_AUTHORIZED_TO_PRESCRIBE_MESSAGE)

    if name is None or not name.strip():
        return MedicationResult(ok=False, message="medication name is required")

    medication = Medication(name=name.strip(), approved=False)
    # Assign through relationships so the patient's ``medications`` collection
    # and the prescribing clinician link are populated for display reads.
    medication.patient = patient
    medication.prescribing_clinician = clinician
    session.add(medication)
    session.flush()
    return MedicationResult(ok=True, medication=medication)


def approve_medication(
    session: DBSession, clinician: Clinician, medication: Medication
) -> MedicationResult:
    """Approve a Medication so the Patient can see it (R13.5, R13.1).

    Only the prescribing Clinician, whose license must still be verified, may
    approve. On success the medication is marked ``approved`` and becomes
    eligible for the Patient dashboard display; otherwise the attempt is
    rejected with the not-authorized-to-prescribe message.
    """
    if (
        medication.prescribing_clinician_id != clinician.id
        or not is_clinician_license_verified(clinician)
    ):
        return MedicationResult(ok=False, message=NOT_AUTHORIZED_TO_PRESCRIBE_MESSAGE)

    medication.approved = True
    session.flush()
    return MedicationResult(ok=True, medication=medication)


def decision_for_patient(appointment: Appointment) -> Optional[ClinicalDecision]:
    """Return the appointment's decision only if approved, else None (R11.8, R11.9).

    The single place the Patient-visibility gate for a decision is applied: a
    recorded-but-unapproved decision is withheld (returns None); an approved
    decision is returned for display.
    """
    decision = appointment.decision
    if decision is None or not decision.approved:
        return None
    return decision


def referrals_for_patient(appointment: Appointment) -> List[Referral]:
    """Return the appointment's referrals only once its decision is approved (R11.8).

    A referral rides on its parent decision's approval: while the decision is
    unapproved its referrals are withheld from the Patient; once approved they
    are returned.
    """
    decision = decision_for_patient(appointment)
    if decision is None:
        return []
    return list(decision.referrals)


def medications_for_patient(patient: Patient) -> List[Medication]:
    """Return a Patient's medications that are safe to display (R13.1, R13.5).

    Applies both medication gates: the prescribing Clinician's license must be
    verified (R13.1) and the medication must be approved (R13.5). Any medication
    failing either gate is excluded from the display set.
    """
    visible: List[Medication] = []
    for medication in patient.medications:
        clinician = medication.prescribing_clinician
        if (
            medication.approved
            and clinician is not None
            and is_clinician_license_verified(clinician)
        ):
            visible.append(medication)
    return visible


__all__ = [
    "NOT_READY_FOR_REVIEW_MESSAGE",
    "DECISION_CONTENT_REQUIRED_MESSAGE",
    "CREDENTIAL_NOT_VERIFIED_MESSAGE",
    "NO_DECISION_TO_APPROVE_MESSAGE",
    "NOT_AUTHORIZED_TO_PRESCRIBE_MESSAGE",
    "FindingsResult",
    "DecisionResult",
    "ApprovalResult",
    "ReferralResult",
    "MedicationResult",
    "open_for_review",
    "record_decision",
    "approve_decision",
    "issue_referral",
    "prescribe_medication",
    "approve_medication",
    "decision_for_patient",
    "referrals_for_patient",
    "medications_for_patient",
]
