"""End-to-end tests for the clinician-facing API (task 17.4).

These drive the real FastAPI app through a ``TestClient`` with only the database
session dependency overridden onto the isolated per-test SQLite engine from
``conftest``. They build a small world directly in the database (a patient, a
volunteer, a verified and an unverified clinician, and completed appointments
queued for review) and exercise the full request path through the
Review_Service.

Focus: that each clinician route is reachable by a Clinician session, applies
the Review_Service's state/license/approval gates with the right HTTP mapping,
and — critically — that role-gating rejects a non-clinician with 403 (R4.5,
R20.2).
"""

from __future__ import annotations

from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import get_session
from app.main import create_app
from app.models.appointment import Appointment, Questionnaire, TestResult
from app.models.credential import Credential, ServiceType
from app.models.enums import AppointmentState, Role, VerificationStatus
from app.models.people import Clinician, Patient, Volunteer
from app.services.credentials import CLINICIAN_LICENSE_TYPE
from app.security import hash_password

PATIENT_PASSWORD = "patient-pass"
VOLUNTEER_PASSWORD = "volunteer-pass"
CLINICIAN_PASSWORD = "clinician-pass"


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


def _seed_world(session_factory: sessionmaker) -> dict:
    """Build a small, self-contained world and return the ids needed.

    - a verified clinician (may record decisions) and an unverified clinician
      (decisions rejected, nothing stored),
    - a patient + volunteer,
    - ``appt_ready``: completed + queued (open for review, carries findings),
    - ``appt_not_ready``: still booked (not open for review).
    """
    session: Session = session_factory()
    try:
        vaccination = ServiceType(
            name="vaccination",
            required_questions="allergies",
            required_tests="temperature",
        )
        session.add(vaccination)

        patient = Patient(
            email="patient@example.com",
            password_hash=hash_password(PATIENT_PASSWORD),
            role=Role.patient,
            latitude=42.3601,
            longitude=-71.0589,
            consent_given=True,
        )
        volunteer = Volunteer(
            email="volunteer@example.com",
            password_hash=hash_password(VOLUNTEER_PASSWORD),
            role=Role.volunteer,
            latitude=42.3611,
            longitude=-71.0590,
        )
        verified_clinician = Clinician(
            email="doctor1@example.com",
            password_hash=hash_password(CLINICIAN_PASSWORD),
            role=Role.clinician,
            latitude=42.0,
            longitude=-71.0,
        )
        unverified_clinician = Clinician(
            email="clinician.unverified@example.com",
            password_hash=hash_password(CLINICIAN_PASSWORD),
            role=Role.clinician,
            latitude=42.0,
            longitude=-71.0,
        )
        session.add_all(
            [patient, volunteer, verified_clinician, unverified_clinician]
        )
        session.flush()

        session.add(
            Credential(
                type=CLINICIAN_LICENSE_TYPE,
                clinician_id=verified_clinician.id,
                status=VerificationStatus.verified,
            )
        )
        session.add(
            Credential(
                type=CLINICIAN_LICENSE_TYPE,
                clinician_id=unverified_clinician.id,
                status=VerificationStatus.unverified,
            )
        )

        # A completed + queued appointment carrying findings.
        appt_ready = Appointment(
            patient_id=patient.id,
            volunteer_id=volunteer.id,
            slot_id=None,
            service_type_id=vaccination.id,
            state=AppointmentState.completed,
            queued_for_review=True,
            reviewed=False,
        )
        session.add(appt_ready)
        session.flush()
        session.add(
            Questionnaire(
                appointment_id=appt_ready.id,
                service_type_id=vaccination.id,
                answers='{"allergies": "none"}',
                required_question_ids="allergies",
            )
        )
        session.add(
            TestResult(
                appointment_id=appt_ready.id,
                service_type_id=vaccination.id,
                measurement="temperature",
                value=98.6,
                unit="F",
            )
        )

        # A still-booked appointment: NOT open for review.
        appt_not_ready = Appointment(
            patient_id=patient.id,
            volunteer_id=volunteer.id,
            slot_id=None,
            service_type_id=vaccination.id,
            state=AppointmentState.booked,
            queued_for_review=False,
            reviewed=False,
        )
        session.add(appt_not_ready)
        session.flush()

        ids = {
            "patient_id": patient.id,
            "volunteer_id": volunteer.id,
            "verified_clinician_email": verified_clinician.email,
            "unverified_clinician_email": unverified_clinician.email,
            "appt_ready_id": appt_ready.id,
            "appt_not_ready_id": appt_not_ready.id,
        }
        session.commit()
        return ids
    finally:
        session.close()


def _sign_in(client: TestClient, email: str, password: str) -> str:
    resp = client.post("/auth/sign-in", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_clinician_review_and_decision_flow(
    client: TestClient, session_factory: sessionmaker
) -> None:
    """Happy path: queue → findings → decision → approve → referral (R11, R12)."""
    ids = _seed_world(session_factory)
    token = _sign_in(client, ids["verified_clinician_email"], CLINICIAN_PASSWORD)
    headers = _auth(token)

    # Review queue lists only the completed + queued appointment.
    resp = client.get("/clinician/review-queue", headers=headers)
    assert resp.status_code == 200, resp.text
    queue = resp.json()
    assert [item["appointment_id"] for item in queue] == [ids["appt_ready_id"]]
    assert queue[0]["reviewed"] is False

    # Findings for the ready appointment.
    resp = client.get(
        f"/clinician/appointments/{ids['appt_ready_id']}/findings", headers=headers
    )
    assert resp.status_code == 200, resp.text
    findings = resp.json()
    assert len(findings["questionnaires"]) == 1
    assert len(findings["test_results"]) == 1
    assert findings["test_results"][0]["measurement"] == "temperature"

    # Findings for the not-ready appointment → 409.
    resp = client.get(
        f"/clinician/appointments/{ids['appt_not_ready_id']}/findings",
        headers=headers,
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["message"] == "appointment-not-ready-for-review"

    # Record a decision (success → stored + reviewed).
    resp = client.post(
        f"/clinician/appointments/{ids['appt_ready_id']}/decision",
        json={"content": "Follow up in 6 months."},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    decision = resp.json()
    assert decision["reviewed"] is True
    assert decision["approved"] is False

    # Approve the decision → patient-visible.
    resp = client.post(
        f"/clinician/appointments/{ids['appt_ready_id']}/decision/approve",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["approved"] is True

    # Issue a referral → sets the patient's required specialty.
    resp = client.post(
        f"/clinician/appointments/{ids['appt_ready_id']}/referral",
        json={"specialty": "cardiology"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["specialty"] == "cardiology"

    # Confirm the patient's required_specialty was set.
    session = session_factory()
    try:
        patient = session.get(Patient, ids["patient_id"])
        assert patient.required_specialty == "cardiology"
    finally:
        session.close()


def test_empty_decision_content_rejected_400(
    client: TestClient, session_factory: sessionmaker
) -> None:
    """Empty decision content → 400 decision-content-required (R11.5)."""
    ids = _seed_world(session_factory)
    token = _sign_in(client, ids["verified_clinician_email"], CLINICIAN_PASSWORD)
    resp = client.post(
        f"/clinician/appointments/{ids['appt_ready_id']}/decision",
        json={"content": "   "},
        headers=_auth(token),
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["message"] == "decision content is required"


def test_unverified_license_decision_rejected_403_nothing_stored(
    client: TestClient, session_factory: sessionmaker
) -> None:
    """Unverified license → 403 credential-not-verified; nothing stored (R11.6)."""
    ids = _seed_world(session_factory)
    token = _sign_in(client, ids["unverified_clinician_email"], CLINICIAN_PASSWORD)
    resp = client.post(
        f"/clinician/appointments/{ids['appt_ready_id']}/decision",
        json={"content": "Attempted decision."},
        headers=_auth(token),
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["message"] == "credential-not-verified"

    # Nothing persisted and the appointment is still unreviewed.
    session = session_factory()
    try:
        appt = session.get(Appointment, ids["appt_ready_id"])
        assert appt.decision is None
        assert appt.reviewed is False
    finally:
        session.close()


def test_approve_with_no_decision_rejected_409(
    client: TestClient, session_factory: sessionmaker
) -> None:
    """Approving with no stored decision → 409 no-decision-to-approve (R11.7)."""
    ids = _seed_world(session_factory)
    token = _sign_in(client, ids["verified_clinician_email"], CLINICIAN_PASSWORD)
    resp = client.post(
        f"/clinician/appointments/{ids['appt_ready_id']}/decision/approve",
        headers=_auth(token),
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["message"] == "no decision exists to approve"


def test_role_gating_rejects_non_clinician_403(
    client: TestClient, session_factory: sessionmaker
) -> None:
    """A Patient session is denied clinician routes with 403 (R4.5, R20.2)."""
    ids = _seed_world(session_factory)
    token = _sign_in(client, "patient@example.com", PATIENT_PASSWORD)
    headers = _auth(token)

    assert client.get("/clinician/review-queue", headers=headers).status_code == 403
    assert (
        client.get(
            f"/clinician/appointments/{ids['appt_ready_id']}/findings",
            headers=headers,
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/clinician/appointments/{ids['appt_ready_id']}/decision",
            json={"content": "x"},
            headers=headers,
        ).status_code
        == 403
    )


def test_unauthenticated_rejected_401(client: TestClient) -> None:
    """An unauthenticated request to a clinician route → 401 (R4.6)."""
    assert client.get("/clinician/review-queue").status_code == 401
