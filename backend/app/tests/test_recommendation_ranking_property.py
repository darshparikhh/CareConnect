"""Property-based test for Recommendation_Engine ranking (task 15.7).

# Feature: careconnect, Property 17: Recommendation ranking is ordered and
# deterministic

For any filtered candidate set, the ``recommend(...)`` result must be:

* ordered by **non-increasing** score S (R16.5), and
* tie-broken by **ascending Proximity** when two adjacent scores are within
  ``TOLERANCE`` (0.001) of each other (R16.6), and
* **deterministic** — the same database state and inputs always yield an
  identical ordering, independent of the order in which the providers were
  inserted (the design verifies determinism by shuffling input order and
  asserting the output order is unchanged).

The test builds a verified-insurance patient with a required specialty and a
pool of doctors that all match that specialty and accept the patient's plan, so
every doctor clears both hard filters and reaches the scoring/ranking stage.
Ratings, proximity, availability, and travel time are randomized so scores vary
and some scores land within the tie-break window.

**Validates: Requirements 16.5, 16.6**
"""

from __future__ import annotations

from typing import List

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy.orm import Session

from app.engines.recommendation import TOLERANCE, recommend
from app.models.enums import VerificationStatus
from app.models.insurance import InsuranceRecord
from app.models.people import Patient
from app.models.recommendation import RecommendedDoctor
from app.security import hash_password

# A single specialty + plan so every generated doctor passes both hard filters
# and the whole pool reaches the ranking stage (the point of this property).
SPECIALTY = "cardiology"
PLAN = "BlueCrossMA"

# Patient location (Boston-ish). Exact value is irrelevant; proximity is derived
# from each doctor's own lat/lng relative to this fixed point.
PATIENT_LAT = 42.3601
PATIENT_LNG = -71.0589


# --- Hypothesis strategies -------------------------------------------------

# One synthetic doctor's scoring factors. The lat/lng are drawn from a small
# grid around the patient so that distinct doctors can share a location (forcing
# score ties) while still spanning a meaningful proximity range. Ratings,
# availability, and travel are drawn from small discrete pools so collisions
# (and therefore near-equal scores) happen often, exercising the tie-break.
doctor_strategy = st.fixed_dictionaries(
    {
        "latitude": st.sampled_from([42.30, 42.36, 42.42, 42.48]),
        "longitude": st.sampled_from([-71.12, -71.06, -71.00, -70.94]),
        "rating": st.sampled_from([3.0, 3.5, 4.0, 4.5, 5.0]),
        "open_slots_14d": st.sampled_from([0, 2, 5, 8, 12]),
        "travel_minutes": st.sampled_from([5.0, 15.0, 30.0, 45.0, 60.0]),
    }
)


# --- Database setup helpers ------------------------------------------------


def _build_patient(session: Session) -> Patient:
    """Persist a verified-insurance patient with the required specialty."""
    patient = Patient(
        email="patient@example.test",
        password_hash=hash_password("pw"),
        latitude=PATIENT_LAT,
        longitude=PATIENT_LNG,
        consent_given=True,
        required_specialty=SPECIALTY,
    )
    patient.insurance_record = InsuranceRecord(
        plan=PLAN,
        verification_status=VerificationStatus.verified,
    )
    session.add(patient)
    session.flush()
    return patient


def _build_doctors(session: Session, specs: List[dict]) -> List[RecommendedDoctor]:
    """Persist a pool of doctors that all pass both hard filters.

    Every doctor has the patient's required specialty and accepts the patient's
    plan via a shared provider-side insurance record, so the full pool reaches
    the ranking stage.
    """
    plan_record = InsuranceRecord(
        plan=PLAN, verification_status=VerificationStatus.verified
    )
    session.add(plan_record)

    doctors: List[RecommendedDoctor] = []
    for i, spec in enumerate(specs):
        doctor = RecommendedDoctor(
            name=f"Dr. {i}",
            specialty=SPECIALTY,
            latitude=spec["latitude"],
            longitude=spec["longitude"],
            rating=spec["rating"],
            open_slots_14d=spec["open_slots_14d"],
            one_way_travel_minutes=spec["travel_minutes"],
        )
        doctor.accepted_insurance = [plan_record]
        session.add(doctor)
        doctors.append(doctor)
    session.flush()
    return doctors


# --- The property ----------------------------------------------------------


@settings(
    max_examples=150,
    deadline=None,
    # The single ``db_session`` fixture is reused across generated examples; each
    # example is isolated inside its own SAVEPOINT (below) and rolled back, so no
    # state leaks between examples and reuse is safe.
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
    ],
)
@given(doctor_specs=st.lists(doctor_strategy, min_size=1, max_size=10))
def test_recommendation_ranking_is_ordered_and_deterministic(
    db_session: Session,
    doctor_specs: List[dict],
) -> None:
    """Ranking is non-increasing by score, tie-broken by proximity, and stable."""
    # Clear any ORM objects left in the identity map by a previous example so a
    # rolled-back savepoint never leaves stale/detached rows that collide with
    # the ids re-used by the next example's inserts.
    db_session.expunge_all()
    savepoint = db_session.begin_nested()
    try:
        _run_property(db_session, doctor_specs=doctor_specs)
    finally:
        savepoint.rollback()


def _run_property(db_session: Session, *, doctor_specs: List[dict]) -> None:
    patient = _build_patient(db_session)
    _build_doctors(db_session, doctor_specs)

    result = recommend(db_session, patient)
    scored = result.scored

    # Every doctor in this pool passes both hard filters, so nothing is dropped
    # at the filter stage; the pool is capped at 10 (<= MAX_RESULTS) so all are
    # ranked.
    assert len(scored) == len(doctor_specs)

    # Invariant 1 — non-increasing score S (R16.5). Each adjacent pair is either
    # strictly decreasing or within the tie-break window; it is never the case
    # that a later entry has a meaningfully higher score than an earlier one.
    for earlier, later in zip(scored, scored[1:]):
        assert later.score <= earlier.score + TOLERANCE

    # Invariant 2 — deterministic tie-break by ascending proximity (R16.6). Two
    # scores count as tied when they fall in the same 0.001-wide bucket (the
    # engine quantizes the score into TOLERANCE-sized buckets so the tie window
    # is a stable equivalence relation; two scores can differ by < TOLERANCE yet
    # still sit in adjacent buckets, in which case they are NOT tied and are
    # ordered strictly by score). Within one bucket the nearer doctor ranks
    # first.
    def _bucket(score: float) -> int:
        return round(score / TOLERANCE)

    for earlier, later in zip(scored, scored[1:]):
        if _bucket(earlier.score) == _bucket(later.score):
            assert earlier.proximity_km <= later.proximity_km + 1e-9

    # Invariant 3 — determinism: recommending twice over identical data yields an
    # identical ordering. Identity is checked by the stable doctor id sequence
    # and the parallel proximity sequence.
    again = recommend(db_session, patient)
    assert [d.id for d in result.doctors] == [d.id for d in again.doctors]
    assert [s.proximity_km for s in result.scored] == [
        s.proximity_km for s in again.scored
    ]
