"""End-to-end tests for the volunteer-facing API (task 17.3).

These drive the real FastAPI app through a ``TestClient`` with only the database
session dependency overridden onto the isolated per-test SQLite engine from
``conftest``. They build a small world directly in the database (a volunteer
with a verified vaccination credential and an available slot, an assigned
booked appointment for a service that requires a question and a test) and
exercise the full request path through the Availability_Service, the
appointment state machine, and the Visit_Service.

Focus: that each route is reachable by a Volunteer session, returns the shapes
the Volunteer_Dashboard needs, applies the availability/lifecycle/authorization
gates, and — critically — that role-gating rejects a non-volunteer with 403
(R4.4, R20.2).
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import get_session
from app.main import create_app
from app.models.appointment import Appointment
from app.models.availability import AvailabilitySlot
from app.models.credential import Credential, CredentialCondition, ServiceType
from app.models.enums import (
    AppointmentState,
    Role,
    SlotStatus,
    VerificationStatus,
)
from app.models.people import Patient, Volunteer
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


VOLUNTEER_PASSWORD = "volunteer-pass"
PATIENT_PASSWORD = "patient-pass"


def _seed_world(session_factory: sessionmaker) -> dict:
    """Build a self-contained world and return the ids/names the tests need."""
    session: Session = session_factory()
    try:
        # A vaccination service that requires one question and one test, so the
        # completion trigger (R10.5) is observable.
        vaccination = ServiceType(
            name="vaccination",
            required_questions="symptoms",
            required_tests="flu_swab",
        )
        session.add(vaccination)
        session.flush()

        volunteer = Volunteer(
            email="volunteer@example.com",
            password_hash=hash_password(VOLUNTEER_PASSWORD),
            role=Role.volunteer,
            latitude=42.3611,
            longitude=-71.0590,
        )
        session.add(volunteer)
        session.flush()

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

        patient = Patient(
            email="patient@example.com",
            password_hash=hash_password(PATIENT_PASSWORD),
            role=Role.patient,
            latitude=42.3601,
            longitude=-71.0589,
            consent_given=True,
        )
        session.add(patient)
        session.flush()

        # An available slot bound to the booked appointment (as booking would).
        slot = AvailabilitySlot(
            volunteer_id=volunteer.id,
            start=datetime(2030, 1, 1, 9, 0, 0),
            end=datetime(2030, 1, 1, 10, 0, 0),
            status=SlotStatus.unavailable,
        )
        session.add(slot)
        session.flush()

        appointment = Appointment(
            patient_id=patient.id,
            volunteer_id=volunteer.id,
            slot_id=slot.id,
            service_type_id=vaccination.id,
            state=AppointmentState.booked,
        )
        session.add(appointment)
        session.flush()
        slot.appointment_id = appointment.id

        # A spare free slot to exercise add/remove on an unassigned slot.
        free_slot = AvailabilitySlot(
            volunteer_id=volunteer.id,
            start=datetime(2030, 1, 2, 9, 0, 0),
            end=datetime(2030, 1, 2, 10, 0, 0),
            status=SlotStatus.available,
        )
        session.add(free_slot)
        session.flush()

        session.commit()
        return {
            "volunteer_id": volunteer.id,
            "patient_id": patient.id,
            "appointment_id": appointment.id,
            "assigned_slot_id": slot.id,
            "free_slot_id": free_slot.id,
            "service_type": "vaccination",
        }
    finally:
        session.close()


def _sign_in(client: TestClient, email: str, password: str) -> str:
    resp = client.post("/auth/sign-in", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Role gating (R4.4, R20.2)
# ---------------------------------------------------------------------------
def test_volunteer_routes_reject_unauthenticated_401(
    client: TestClient, session_factory: sessionmaker
) -> None:
    _seed_world(session_factory)
    resp = client.get("/volunteer/appointments")
    assert resp.status_code == 401


def test_volunteer_routes_reject_patient_with_403(
    client: TestClient, session_factory: sessionmaker
) -> None:
    world = _seed_world(session_factory)
    token = _sign_in(client, "patient@example.com", PATIENT_PASSWORD)
    appt = world["appointment_id"]

    for method, path, body in [
        ("get", "/volunteer/slots", None),
        ("post", "/volunteer/slots", {"start": "2030-02-01T09:00:00", "end": "2030-02-01T10:00:00"}),
        ("get", "/volunteer/appointments", None),
        ("post", f"/volunteer/appointments/{appt}/accept", None),
        ("post", f"/volunteer/appointments/{appt}/decline", None),
        ("get", f"/volunteer/appointments/{appt}/visit", None),
        ("post", f"/volunteer/appointments/{appt}/questionnaire", {"answers": {}}),
        ("post", f"/volunteer/appointments/{appt}/test-result", {"measurement": "flu_swab"}),
    ]:
        if method == "get":
            resp = client.get(path, headers=_auth(token))
        else:
            resp = client.post(path, json=body, headers=_auth(token))
        assert resp.status_code == 403, f"{path}: {resp.status_code} {resp.text}"


# ---------------------------------------------------------------------------
# Availability management (R6.1, R6.2, R6.3)
# ---------------------------------------------------------------------------
def test_volunteer_can_add_and_remove_slot(
    client: TestClient, session_factory: sessionmaker
) -> None:
    _seed_world(session_factory)
    token = _sign_in(client, "volunteer@example.com", VOLUNTEER_PASSWORD)

    add = client.post(
        "/volunteer/slots",
        json={"start": "2030-03-01T09:00:00", "end": "2030-03-01T10:00:00"},
        headers=_auth(token),
    )
    assert add.status_code == 201, add.text
    new_slot = add.json()
    assert new_slot["status"] == "available"

    remove = client.delete(
        f"/volunteer/slots/{new_slot['id']}", headers=_auth(token)
    )
    assert remove.status_code == 200, remove.text
    assert remove.json()["status"] == "unavailable"


def test_removing_slot_with_appointment_is_409(
    client: TestClient, session_factory: sessionmaker
) -> None:
    world = _seed_world(session_factory)
    token = _sign_in(client, "volunteer@example.com", VOLUNTEER_PASSWORD)

    resp = client.delete(
        f"/volunteer/slots/{world['assigned_slot_id']}", headers=_auth(token)
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["message"] == "slot-has-appointment"


# ---------------------------------------------------------------------------
# Appointment listing + accept/decline lifecycle (R18.1, R8.6, R8.7)
# ---------------------------------------------------------------------------
def test_volunteer_lists_assigned_appointments(
    client: TestClient, session_factory: sessionmaker
) -> None:
    world = _seed_world(session_factory)
    token = _sign_in(client, "volunteer@example.com", VOLUNTEER_PASSWORD)

    resp = client.get("/volunteer/appointments", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    appts = resp.json()
    assert len(appts) == 1
    assert appts[0]["id"] == world["appointment_id"]
    assert appts[0]["state"] == "booked"
    assert appts[0]["patient_id"] == world["patient_id"]


def test_volunteer_can_accept_then_invalid_transition_409(
    client: TestClient, session_factory: sessionmaker
) -> None:
    world = _seed_world(session_factory)
    token = _sign_in(client, "volunteer@example.com", VOLUNTEER_PASSWORD)
    appt = world["appointment_id"]

    accept = client.post(
        f"/volunteer/appointments/{appt}/accept", headers=_auth(token)
    )
    assert accept.status_code == 200, accept.text
    assert accept.json()["state"] == "accepted"

    # accepted -> accepted is not a valid transition: 409, state preserved.
    again = client.post(
        f"/volunteer/appointments/{appt}/accept", headers=_auth(token)
    )
    assert again.status_code == 409, again.text
    detail = again.json()["detail"]
    assert detail["message"] == "invalid-transition"
    assert detail["current_state"] == "accepted"


def test_volunteer_can_decline_booked_appointment(
    client: TestClient, session_factory: sessionmaker
) -> None:
    world = _seed_world(session_factory)
    token = _sign_in(client, "volunteer@example.com", VOLUNTEER_PASSWORD)

    resp = client.post(
        f"/volunteer/appointments/{world['appointment_id']}/decline",
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "cancelled"


# ---------------------------------------------------------------------------
# Visit detail — only authorized services shown (R9.1, R9.2)
# ---------------------------------------------------------------------------
def test_visit_detail_shows_only_authorized_services(
    client: TestClient, session_factory: sessionmaker
) -> None:
    world = _seed_world(session_factory)
    token = _sign_in(client, "volunteer@example.com", VOLUNTEER_PASSWORD)

    resp = client.get(
        f"/volunteer/appointments/{world['appointment_id']}/visit",
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["requested_service_type"]["name"] == "vaccination"
    names = [s["name"] for s in data["authorized_services"]]
    assert names == ["vaccination"]
    assert "lat" in data["location"] and "lng" in data["location"]


# ---------------------------------------------------------------------------
# Questionnaire / test-result submission + completion trigger (R10.1, R10.3, R10.5)
# ---------------------------------------------------------------------------
def test_questionnaire_wrong_state_is_409(
    client: TestClient, session_factory: sessionmaker
) -> None:
    world = _seed_world(session_factory)
    token = _sign_in(client, "volunteer@example.com", VOLUNTEER_PASSWORD)

    # The appointment is still 'booked' (not accepted): submission is rejected.
    resp = client.post(
        f"/volunteer/appointments/{world['appointment_id']}/questionnaire",
        json={"answers": {"symptoms": "cough"}},
        headers=_auth(token),
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["current_state"] == "booked"


def test_questionnaire_missing_required_question_is_400(
    client: TestClient, session_factory: sessionmaker
) -> None:
    world = _seed_world(session_factory)
    token = _sign_in(client, "volunteer@example.com", VOLUNTEER_PASSWORD)
    appt = world["appointment_id"]

    client.post(f"/volunteer/appointments/{appt}/accept", headers=_auth(token))

    resp = client.post(
        f"/volunteer/appointments/{appt}/questionnaire",
        json={"answers": {}},
        headers=_auth(token),
    )
    assert resp.status_code == 400, resp.text
    assert "symptoms" in resp.json()["detail"]["missing_questions"]


def test_submission_completes_and_queues_for_review(
    client: TestClient, session_factory: sessionmaker
) -> None:
    world = _seed_world(session_factory)
    token = _sign_in(client, "volunteer@example.com", VOLUNTEER_PASSWORD)
    appt = world["appointment_id"]

    client.post(f"/volunteer/appointments/{appt}/accept", headers=_auth(token))

    q = client.post(
        f"/volunteer/appointments/{appt}/questionnaire",
        json={"answers": {"symptoms": "cough"}},
        headers=_auth(token),
    )
    assert q.status_code == 200, q.text
    # Question present but the required test is not yet: not complete.
    assert q.json()["completed"] is False

    t = client.post(
        f"/volunteer/appointments/{appt}/test-result",
        json={"measurement": "flu_swab", "value": 1.0},
        headers=_auth(token),
    )
    assert t.status_code == 200, t.text
    # The full required data set is now present → completed + queued.
    assert t.json()["completed"] is True

    appts = client.get("/volunteer/appointments", headers=_auth(token)).json()
    assert appts[0]["state"] == "completed"
    assert appts[0]["queued_for_review"] is True
