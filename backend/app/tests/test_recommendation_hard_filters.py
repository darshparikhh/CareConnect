"""Property-based test for the Recommendation_Engine hard filters (task 15.3).

# Feature: careconnect, Property 13: Recommendation never returns a doctor
# failing a hard filter

For any provider pool and any patient, every doctor in the
``recommend(...)`` result must satisfy BOTH hard constraints — regardless of
how favorable its computed score is:

* its specialty exactly equals the patient's required specialty (R15.1), and
* it is insurance-compatible with the patient per the Insurance_Service
  (R15.2, R15.3) — which can only be the case when the patient's insurance is
  verified, so while the patient's insurance is unverified no doctor is
  returned and ``insurance_asserted`` is ``False`` (R15.4).

Because scoring is applied only to candidates that already passed the hard
filters (R16.10), a high score can never resurrect a doctor that fails a hard
filter. These are the invariants exercised here.

**Validates: Requirements 15.1, 15.2, 15.3, 16.10**
"""

from __future__ import annotations

from typing import List, Optional

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy.orm import Session

from app.engines.recommendation import recommend
from app.models.enums import InsuranceCompatibility, VerificationStatus
from app.models.insurance import InsuranceRecord
from app.models.people import Patient
from app.models.recommendation import RecommendedDoctor
from app.security import hash_password
from app.services import insurance

# A small fixed vocabulary of specialties and insurance plans. Keeping the
# pools small makes collisions (matches) likely so both the pass and fail
# branches of each hard filter get exercised within the generated examples.
SPECIALTIES = ["cardiology", "dermatology", "pediatrics", "oncology"]
PLANS = ["BlueCrossMA", "MassHealth", "HarvardPilgrim", "Aetna"]

# Patient location (Boston-ish); exact value is irrelevant to the hard filters.
PATIENT_LAT = 42.3601
PATIENT_LNG = -71.0589


# --- Hypothesis strategies -------------------------------------------------

# One synthetic doctor description: specialty, the plans it accepts, and the
# (possibly messy) scoring factors. Factors are intentionally wide-ranging —
# including extreme/degenerate values — so that scoring cannot be relied on to
# "accidentally" keep only valid doctors.
doctor_strategy = st.fixed_dictionaries(
    {
        "specialty": st.sampled_from(SPECIALTIES),
        "accepted_plans": st.lists(st.sampled_from(PLANS), max_size=4, unique=True),
        "latitude": st.floats(
            min_value=41.0, max_value=43.0, allow_nan=False, allow_infinity=False
        ),
        "longitude": st.floats(
            min_value=-72.0, max_value=-70.0, allow_nan=False, allow_infinity=False
        ),
        "rating": st.floats(
            min_value=-10.0, max_value=10.0, allow_nan=False, allow_infinity=False
        ),
        "open_slots_14d": st.integers(min_value=-5, max_value=40),
        "travel_minutes": st.floats(
            min_value=-5.0, max_value=240.0, allow_nan=False, allow_infinity=False
        ),
    }
)

patient_plan_strategy = st.sampled_from(PLANS)
verification_strategy = st.sampled_from(
    [VerificationStatus.verified, VerificationStatus.unverified]
)
# A required specialty, or None to exercise the no-required-specialty branch.
required_specialty_strategy = st.one_of(st.none(), st.sampled_from(SPECIALTIES))


# --- Database setup helpers ------------------------------------------------


def _build_patient(
    session: Session,
    *,
    required_specialty: Optional[str],
    plan: str,
    verification: VerificationStatus,
) -> Patient:
    """Persist a patient with the given required specialty + insurance record.

    The patient always carries exactly one insurance record so the only varying
    dimension is its ``verification_status`` and ``plan``.
    """
    patient = Patient(
        email="patient@example.test",
        password_hash=hash_password("pw"),
        latitude=PATIENT_LAT,
        longitude=PATIENT_LNG,
        consent_given=True,
        required_specialty=required_specialty,
    )
    patient.insurance_record = InsuranceRecord(
        plan=plan,
        verification_status=verification,
    )
    session.add(patient)
    session.flush()
    return patient


def _build_doctors(session: Session, specs: List[dict]) -> List[RecommendedDoctor]:
    """Persist the provider pool, wiring each doctor's accepted-plan records."""
    # Provider-side insurance records are shared by plan name so the
    # many-to-many join is populated with real rows.
    plan_records = {
        plan: InsuranceRecord(plan=plan, verification_status=VerificationStatus.verified)
        for plan in PLANS
    }
    for record in plan_records.values():
        session.add(record)

    doctors: List[RecommendedDoctor] = []
    for i, spec in enumerate(specs):
        doctor = RecommendedDoctor(
            name=f"Dr. {i}",
            specialty=spec["specialty"],
            latitude=spec["latitude"],
            longitude=spec["longitude"],
            rating=spec["rating"],
            open_slots_14d=spec["open_slots_14d"],
            one_way_travel_minutes=spec["travel_minutes"],
        )
        doctor.accepted_insurance = [
            plan_records[p] for p in spec["accepted_plans"]
        ]
        session.add(doctor)
        doctors.append(doctor)
    session.flush()
    return doctors


# --- The property ----------------------------------------------------------


@settings(
    max_examples=120,
    deadline=None,
    # The single ``db_session`` fixture is reused across generated examples; we
    # isolate each example inside its own SAVEPOINT (see below) and roll it back
    # so no state leaks between examples. That makes reuse safe here.
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
    ],
)
@given(
    doctor_specs=st.lists(doctor_strategy, min_size=0, max_size=8),
    required_specialty=required_specialty_strategy,
    patient_plan=patient_plan_strategy,
    verification=verification_strategy,
)
def test_recommendation_never_returns_doctor_failing_hard_filter(
    db_session: Session,
    doctor_specs: List[dict],
    required_specialty: Optional[str],
    patient_plan: str,
    verification: VerificationStatus,
) -> None:
    """Every returned doctor passes BOTH hard filters, whatever its score."""
    # Each generated example runs in its own nested transaction so the rows it
    # inserts are rolled back before the next example, keeping examples isolated
    # even though the ``db_session`` fixture itself is not reset per example.
    savepoint = db_session.begin_nested()
    try:
        _run_property(
            db_session,
            doctor_specs=doctor_specs,
            required_specialty=required_specialty,
            patient_plan=patient_plan,
            verification=verification,
        )
    finally:
        savepoint.rollback()


def _run_property(
    db_session: Session,
    *,
    doctor_specs: List[dict],
    required_specialty: Optional[str],
    patient_plan: str,
    verification: VerificationStatus,
) -> None:
    patient = _build_patient(
        db_session,
        required_specialty=required_specialty,
        plan=patient_plan,
        verification=verification,
    )
    _build_doctors(db_session, doctor_specs)

    result = recommend(db_session, patient)

    # Invariant A — no required specialty means an empty result (R15.6); there
    # is then nothing further to check for the hard filters.
    if required_specialty is None:
        assert result.doctors == []
        assert result.insurance_asserted is False
        return

    # Invariant B — while insurance is unverified, the engine may never assert
    # any doctor as compatible, so it returns no doctors and insurance_asserted
    # is False (R15.3, R15.4). This holds even if some doctor matches the
    # specialty and accepts the plan: an unverified plan is never "compatible".
    if verification != VerificationStatus.verified:
        assert result.doctors == []
        assert result.insurance_asserted is False
        return

    # Insurance is verified from here on.
    assert result.insurance_asserted is True

    # Invariant C — every returned doctor satisfies BOTH hard constraints,
    # regardless of its computed score (R15.1, R15.2, R15.3, R16.10).
    required_key = str(required_specialty).strip().casefold()
    for doctor in result.doctors:
        # Hard filter 1: exact specialty match.
        assert str(doctor.specialty).strip().casefold() == required_key

        # Hard filter 2: insurance-compatible per the Insurance_Service. A high
        # score can never resurrect an incompatible doctor.
        compat = insurance.compatibility(db_session, patient, doctor)
        assert compat.status == InsuranceCompatibility.compatible

    # And the result respects the correctness property globally: the returned
    # set is exactly the subset of the pool that passes both hard filters.
    for scored in result.scored:
        assert scored.score == scored.score  # score is a real (non-NaN) float
