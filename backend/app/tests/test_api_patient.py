"""End-to-end tests for the patient-facing API (task 17.2).

These drive the real FastAPI app through a ``TestClient`` with only the database
session dependency overridden onto the isolated per-test SQLite engine from
``conftest``. They build a small world directly in the database (a patient, an
authorized volunteer with an available slot, approved/unapproved clinical
artifacts, a recommendable doctor) and exercise the full request path through
the Matching_Engine, Appointment_Service, Review_Service visibility helpers, and
Recommendation_Engine.

Focus: that each route is reachable by a Patient session, returns the shapes the
Patient_Dashboard needs, applies the approval/consent gates, and — critically —
that role-gating rejects a non-patient with 403 (R4.3, R20.2).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import get_session
from app.main import create_app
from app.models.appointment import Appointment
from app.models.availability import AvailabilitySlot
from app.models.clinical import ClinicalDecision, Medication, Referral
from app.models.credential import (
    Credential,
    CredentialCondition,
    ServiceType,
)
from app.services.credentials import CLINICIAN_LICENSE_TYPE
from app.models.enums import (
    AppointmentState,
    Role,
    SlotStatus,
    VerificationStatus,
)
from app.models.insurance import InsuranceRecord
from app.models.people import Clinician, Patient, Volunteer
from app.models.recommendation import RecommendedDoctor
from app.security import hash_password


@pytest.fixture()
def session_factory(db_engine: Engine) -> sessionmaker:
    return sessionmaker(
        bind=db_engine, autoflush=False, expire_on_commit=False, future=True
    )


@pytest.fixture()
def client(session_factory: sessionmaker) -> Iterator[TestClient]:
    app = create_app()

    def _override_get_session() -> Iterator[Session]:
        session = session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    app.dependency_overrides[get_session] = _override_get_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# World builders
# ---------------------------------------------------------------------------
PATIENT_PASSWORD = "patient-pass"
VOLUNTEER_PASSWORD = "volunteer-pass"


def _seed_world(session_factory: sessionmaker) -> dict:
    """Build a small, self-contained world and return the ids/names needed."""
    session: Session = session_factory()
    try:
        vaccination = ServiceType(name="vaccination")
        session.add(vaccination)

        # Provider-side insurance plan (patient_id is NULL) so verification can
        # succeed, plus a doctor that accepts it.
        provider_plan = InsuranceRecord(
            plan="BlueCrossMA",
            network="MA",
            verification_status=VerificationStatus.verified,
            patient_id=None,
        )
        session.add(provider_plan)
        session.flush()

        patient = Patient(
            email="patient@example.com",
            password_hash=hash_password(PATIENT_PASSWORD),
            role=Role.patient,
            latitude=42.3601,
            longitude=-71.0589,
            consent_given=True,
            required_specialty="cardiology",
        )
        session.add(patient)
        session.flush()

        patient_insurance = InsuranceRecord(
            patient_id=patient.id,
            plan="BlueCrossMA",
            network="MA",
            verification_status=VerificationStatus.verified,
        )
        session.add(patient_insurance)

        volunteer = Volunteer(
            email="volunteer@example.com",
            password_hash=hash_password(VOLUNTEER_PASSWORD),
            role=Role.volunteer,
            latitude=42.3611,
            longitude=-71.0590,
        )
        session.add(volunteer)
        session.flush()

        # A verified, condition-satisfied credential authorizing vaccination.
        credential = Credential(
            type="vaccination_certification",
            volunteer_id=volunteer.id,
            status=VerificationStatus.verified,
        )
        credential.authorizes_service_types.append(vaccination)
        credential.conditions.append(
            CredentialCondition(kind="state_license_MA", satisfied=True)
        )
        session.add(credential)

        start = datetime(2030, 1, 1, 9, 0, 0)
        end = datetime(2030, 1, 1, 10, 0, 0)
        slot = AvailabilitySlot(
            volunteer_id=volunteer.id,
            start=start,
            end=end,
            status=SlotStatus.available,
        )
        session.add(slot)

        # A verified clinician who prescribes/decides.
        clinician = Clinician(
            email="clinician@example.com",
            password_hash=hash_password("clinician-pass"),
            role=Role.clinician,
            latitude=42.0,
            longitude=-71.0,
        )
        session.add(clinician)
        session.flush()
        license_cred = Credential(
            type=CLINICIAN_LICENSE_TYPE,
            clinician_id=clinician.id,
            status=VerificationStatus.verified,
        )
        session.add(license_cred)

        # A doctor matching the patient's required specialty + insurance.
        doctor = RecommendedDoctor(
            name="Dr. Heart",
            specialty="cardiology",
            latitude=42.3605,
            longitude=-71.0585,
            rating=4.5,
            open_slots_14d=8,
            one_way_travel_minutes=15.0,
        )
        doctor.accepted_insurance.append(provider_plan)
        session.add(doctor)
        session.flush()

        # --- A completed appointment with an APPROVED decision + referral and
        #     a second with an UNAPPROVED decision (must stay hidden). ---
        appt_approved = Appointment(
            patient_id=patient.id,
            volunteer_id=volunteer.id,
            slot_id=None,
            service_type_id=vaccination.id,
            state=AppointmentState.completed,
            queued_for_review=True,
            reviewed=True,
        )
        session.add(appt_approved)
        session.flush()
        approved_decision = ClinicalDecision(
            appointment_id=appt_approved.id,
            clinician_id=clinician.id,
            content="Follow up in 6 months.",
            reviewed=True,
            approved=True,
        )
        session.add(approved_decision)
        session.flush()
        session.add(
            Referral(
                clinical_decision_id=approved_decision.id,
                patient_id=patient.id,
                specialty="cardiology",
            )
        )

        appt_unapproved = Appointment(
            patient_id=patient.id,
            volunteer_id=volunteer.id,
            slot_id=None,
            service_type_id=vaccination.id,
            state=AppointmentState.completed,
            queued_for_review=True,
            reviewed=True,
        )
        session.add(appt_unapproved)
        session.flush()
        session.add(
            ClinicalDecision(
                appointment_id=appt_unapproved.id,
                clinician_id=clinician.id,
                content="Draft, not yet approved.",
                reviewed=True,
                approved=False,
            )
        )

        # --- Medications: one approved (visible), one unapproved (hidden). ---
        session.add(
            Medication(
                patient_id=patient.id,
                prescribing_clinician_id=clinician.id,
                name="VisibleMed",
                approved=True,
            )
        )
        session.add(
            Medication(
                patient_id=patient.id,
                prescribing_clinician_id=clinician.id,
                name="HiddenMed",
                approved=False,
            )
        )

        session.commit()
        return {
            "patient_id": patient.id,
            "volunteer_id": volunteer.id,
            "slot_id": slot.id,
            "service_type": "vaccination",
        }
    finally:
        session.close()


def _sign_in(client: TestClient, email: str, password: str) -> str:
    resp = client.post(
        "/auth/sign-in", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Role gating (R4.3, R20.2)
# ---------------------------------------------------------------------------
def test_patient_routes_reject_unauthenticated_401(
    client: TestClient, session_factory: sessionmaker
) -> None:
    _seed_world(session_factory)
    resp = client.get("/patient/appointments")
    assert resp.status_code == 401


def test_patient_routes_reject_volunteer_with_403(
    client: TestClient, session_factory: sessionmaker
) -> None:
    _seed_world(session_factory)
    token = _sign_in(client, "volunteer@example.com", VOLUNTEER_PASSWORD)

    for method, path, body in [
        ("get", "/patient/appointments", None),
        ("get", "/patient/decisions", None),
        ("get", "/patient/referrals", None),
        ("get", "/patient/medications", None),
        ("post", "/patient/recommendations", {}),
    ]:
        if method == "get":
            resp = client.get(path, headers=_auth(token))
        else:
            resp = client.post(path, json=body, headers=_auth(token))
        assert resp.status_code == 403, f"{path}: {resp.status_code} {resp.text}"


# ---------------------------------------------------------------------------
# Match + book (R7.1, R8.1)
# ---------------------------------------------------------------------------
def test_patient_can_request_match_and_book(
    client: TestClient, session_factory: sessionmaker
) -> None:
    world = _seed_world(session_factory)
    token = _sign_in(client, "patient@example.com", PATIENT_PASSWORD)

    match_resp = client.post(
        "/patient/matches",
        json={
            "service_type": world["service_type"],
            "start": "2030-01-01T09:00:00",
            "end": "2030-01-01T10:00:00",
        },
        headers=_auth(token),
    )
    assert match_resp.status_code == 200, match_resp.text
    data = match_resp.json()
    assert data["message"] is None
    ids = [c["volunteer_id"] for c in data["candidates"]]
    assert world["volunteer_id"] in ids

    book_resp = client.post(
        "/patient/bookings",
        json={
            "volunteer_id": world["volunteer_id"],
            "slot_id": world["slot_id"],
            "service_type": world["service_type"],
        },
        headers=_auth(token),
    )
    assert book_resp.status_code == 201, book_resp.text
    appt = book_resp.json()["appointment"]
    assert appt["state"] == "booked"
    assert appt["volunteer_id"] == world["volunteer_id"]

    # The slot is now unavailable; a second booking of the same slot → 409.
    again = client.post(
        "/patient/bookings",
        json={
            "volunteer_id": world["volunteer_id"],
            "slot_id": world["slot_id"],
            "service_type": world["service_type"],
        },
        headers=_auth(token),
    )
    assert again.status_code == 409, again.text
    assert again.json()["detail"]["message"] == "slot-unavailable"


def test_booking_without_consent_is_403(
    client: TestClient, session_factory: sessionmaker
) -> None:
    world = _seed_world(session_factory)
    # Revoke the patient's consent directly.
    session = session_factory()
    try:
        patient = session.get(Patient, world["patient_id"])
        patient.consent_given = False
        session.commit()
    finally:
        session.close()

    token = _sign_in(client, "patient@example.com", PATIENT_PASSWORD)
    resp = client.post(
        "/patient/bookings",
        json={
            "volunteer_id": world["volunteer_id"],
            "slot_id": world["slot_id"],
            "service_type": world["service_type"],
        },
        headers=_auth(token),
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["message"] == "consent-required"


# ---------------------------------------------------------------------------
# Approval-gated visibility (R11.9, R13.1)
# ---------------------------------------------------------------------------
def test_patient_sees_only_approved_decisions_and_referrals(
    client: TestClient, session_factory: sessionmaker
) -> None:
    _seed_world(session_factory)
    token = _sign_in(client, "patient@example.com", PATIENT_PASSWORD)

    decisions = client.get("/patient/decisions", headers=_auth(token))
    assert decisions.status_code == 200, decisions.text
    contents = [d["content"] for d in decisions.json()]
    assert "Follow up in 6 months." in contents
    assert "Draft, not yet approved." not in contents

    referrals = client.get("/patient/referrals", headers=_auth(token))
    assert referrals.status_code == 200, referrals.text
    specialties = [r["specialty"] for r in referrals.json()]
    assert specialties == ["cardiology"]


def test_patient_sees_only_approved_medications(
    client: TestClient, session_factory: sessionmaker
) -> None:
    _seed_world(session_factory)
    token = _sign_in(client, "patient@example.com", PATIENT_PASSWORD)

    resp = client.get("/patient/medications", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    names = [m["name"] for m in resp.json()]
    assert names == ["VisibleMed"]


# ---------------------------------------------------------------------------
# Recommendations (R15.1, R16.1, R17.4)
# ---------------------------------------------------------------------------
def test_patient_gets_ranked_recommendations(
    client: TestClient, session_factory: sessionmaker
) -> None:
    _seed_world(session_factory)
    token = _sign_in(client, "patient@example.com", PATIENT_PASSWORD)

    resp = client.post("/patient/recommendations", json={}, headers=_auth(token))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["insurance_asserted"] is True
    assert len(data["doctors"]) == 1
    doctor = data["doctors"][0]
    assert doctor["specialty"] == "cardiology"
    assert doctor["insurance_status"] == "compatible"
    assert "proximity_km" in doctor and "score" in doctor
