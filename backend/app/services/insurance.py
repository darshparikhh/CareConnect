"""Insurance_Service: insurance verification and compatibility reporting.

This implements the design's ``Insurance_Service`` (R14, feeding R15.2/R15.4):

* :func:`verify_insurance` checks a Patient's recorded insurance against the
  recorded synthetic **provider-side** insurance records. A new patient's
  insurance always starts ``unverified`` (R14.1); a match flips it to
  ``verified`` (R14.2); a mismatch keeps it ``unverified`` and returns a
  could-not-verify message (R14.3).
* :func:`compatibility` reports a Patient/Doctor insurance match as
  ``unknown`` while the Patient's insurance is ``unverified`` (R14.4), and
  otherwise ``compatible`` / ``incompatible`` based on whether the doctor
  accepts the patient's plan. Even a ``compatible`` result carries the caveat
  that network acceptance does not guarantee coverage of a specific service or
  home visit (R14.5).

Matching model
--------------
The recorded Synthetic_Data that a patient's insurance is verified against is
the set of **provider-side** insurance records — ``InsuranceRecord`` rows with
``patient_id IS NULL``. These are the plans the platform knows about (seeded as
BlueCrossMA, MassHealth, HarvardPilgrim, Aetna). A patient's record matches when
its ``plan`` equals a provider plan (case-insensitively); when the patient's
record also names a ``network`` it must agree with the provider plan's network.
A patient plan with no corresponding provider record (e.g. an out-of-state
plan) cannot be verified.

Compatibility is decided against the doctor's own ``accepted_insurance`` set
(the ``doctor_accepted_insurance`` join): the doctor accepts the patient when
one of its accepted plans matches the patient's plan by the same rule.

This service never mutates anything other than the patient's own
``verification_status`` and never commits — the caller owns the transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.models.enums import InsuranceCompatibility, VerificationStatus
from app.models.insurance import InsuranceRecord
from app.models.people import Patient
from app.models.recommendation import RecommendedDoctor

# Surfaced whenever a patient's insurance cannot be matched to a recorded
# provider plan (R14.3). Actionable and uniform so callers/UI can show it.
COULD_NOT_VERIFY_MESSAGE = (
    "insurance information could not be verified against recorded records"
)

# The caveat attached to every compatibility result: network acceptance is not
# a coverage guarantee for a specific service or home visit (R14.5).
NETWORK_ACCEPTANCE_CAVEAT = (
    "network acceptance does not guarantee coverage of a specific service "
    "or home visit"
)


@dataclass(frozen=True)
class VerificationResult:
    """Outcome of :func:`verify_insurance`.

    ``status`` is the patient's resulting verification status. ``message`` is
    ``None`` on success and the could-not-verify message when a match failed
    (R14.3). ``verified`` is a convenience flag.
    """

    status: VerificationStatus
    message: Optional[str] = None

    @property
    def verified(self) -> bool:
        return self.status == VerificationStatus.verified


@dataclass(frozen=True)
class CompatibilityResult:
    """Outcome of :func:`compatibility`.

    ``status`` is one of compatible / incompatible / unknown. ``caveat`` always
    carries the network-acceptance caveat (R14.5) so the UI can surface it even
    on a compatible result. ``message`` explains an ``unknown`` result.
    """

    status: InsuranceCompatibility
    caveat: str = NETWORK_ACCEPTANCE_CAVEAT
    message: Optional[str] = None

    @property
    def is_compatible(self) -> bool:
        return self.status == InsuranceCompatibility.compatible

    @property
    def is_unknown(self) -> bool:
        return self.status == InsuranceCompatibility.unknown


def _normalize(value: Optional[str]) -> str:
    """Case/whitespace-insensitive key for comparing plan/network strings."""
    return (value or "").strip().casefold()


def _plans_match(patient: InsuranceRecord, reference: InsuranceRecord) -> bool:
    """Return True if ``reference`` covers the patient's ``plan`` (and network).

    The plan must match. If the patient's record names a ``network``, the
    reference must name the same network; a patient record with no network is
    matched on plan alone (the reference's network is informational).
    """
    if _normalize(patient.plan) != _normalize(reference.plan):
        return False
    patient_network = _normalize(patient.network)
    if patient_network and patient_network != _normalize(reference.network):
        return False
    return True


def _provider_plans(session: DBSession) -> List[InsuranceRecord]:
    """The recorded provider-side insurance plans (``patient_id IS NULL``)."""
    return list(
        session.execute(
            select(InsuranceRecord).where(InsuranceRecord.patient_id.is_(None))
        ).scalars()
    )


def verify_insurance(session: DBSession, patient: Patient) -> VerificationResult:
    """Verify ``patient``'s insurance against recorded synthetic records.

    Behaviour (R14.1-R14.3):

    * A patient with no insurance record on file is treated as unverified and
      returns the could-not-verify message (there is nothing to match).
    * If the patient's recorded plan matches a recorded provider plan, the
      patient's ``verification_status`` is set to ``verified`` and a success
      result (no message) is returned.
    * Otherwise the status is left ``unverified`` and the could-not-verify
      message is returned.

    The patient's record is mutated in place on success; the caller owns the
    transaction (this never commits).
    """
    record = patient.insurance_record
    if record is None:
        # Nothing recorded to verify — remains unverified (R14.1/R14.3).
        return VerificationResult(
            status=VerificationStatus.unverified,
            message=COULD_NOT_VERIFY_MESSAGE,
        )

    for reference in _provider_plans(session):
        if _plans_match(record, reference):
            record.verification_status = VerificationStatus.verified
            session.flush()
            return VerificationResult(status=VerificationStatus.verified)

    # No match: keep unverified and report it (R14.3).
    record.verification_status = VerificationStatus.unverified
    session.flush()
    return VerificationResult(
        status=VerificationStatus.unverified,
        message=COULD_NOT_VERIFY_MESSAGE,
    )


def compatibility(
    session: DBSession, patient: Patient, doctor: RecommendedDoctor
) -> CompatibilityResult:
    """Report insurance compatibility between ``patient`` and ``doctor``.

    * While the patient's insurance is ``unverified`` (including when the
      patient has no insurance record), the result is ``unknown`` — the service
      never asserts compatibility on unverified data (R14.4, and so R15.4).
    * Once verified, the result is ``compatible`` when the doctor accepts the
      patient's plan and ``incompatible`` otherwise.

    Every result carries the network-acceptance caveat (R14.5): acceptance of
    the patient's network is not a guarantee that a specific service or home
    visit is covered. The caveat is informational and never upgrades an
    ``incompatible`` or ``unknown`` result to ``compatible``.

    This is a pure read — it mutates nothing. Callers that need verification
    should call :func:`verify_insurance` first.
    """
    record = patient.insurance_record
    if record is None or record.verification_status != VerificationStatus.verified:
        return CompatibilityResult(
            status=InsuranceCompatibility.unknown,
            message="patient insurance is unverified",
        )

    for accepted in doctor.accepted_insurance:
        if _plans_match(record, accepted):
            return CompatibilityResult(status=InsuranceCompatibility.compatible)

    return CompatibilityResult(status=InsuranceCompatibility.incompatible)


__all__ = [
    "COULD_NOT_VERIFY_MESSAGE",
    "NETWORK_ACCEPTANCE_CAVEAT",
    "VerificationResult",
    "CompatibilityResult",
    "verify_insurance",
    "compatibility",
]
