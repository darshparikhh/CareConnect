"""Unit-level checks for the Auth_Service (task 4.1).

These are minimal sanity checks that the core pieces behave: authenticate
accepts valid credentials and rejects invalid ones, the session carries the
right role, and authorize/require_role gate correctly. The broader role-based
access example tests (task 4.2) are intentionally out of scope here.
"""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.database import get_session
from app.models.enums import Role
from app.models.people import Clinician, Patient, Volunteer
from app.security import hash_password
from app.services.auth import (
    AuthenticationFailed,
    authenticate,
    authorize,
    require_role,
)


def _make_patient(db: Session) -> Patient:
    patient = Patient(
        email="pat@example.com",
        password_hash=hash_password("correct-horse"),
        role=Role.patient,
        latitude=42.36,
        longitude=-71.06,
        consent_given=True,
    )
    db.add(patient)
    db.commit()
    db.refresh(patient)
    return patient


def _make_volunteer(db: Session) -> Volunteer:
    vol = Volunteer(
        email="vol@example.com",
        password_hash=hash_password("vol-pass"),
        role=Role.volunteer,
        latitude=42.35,
        longitude=-71.07,
    )
    db.add(vol)
    db.commit()
    db.refresh(vol)
    return vol


# --- authenticate ----------------------------------------------------------


def test_authenticate_accepts_valid_credentials(db_session: Session) -> None:
    patient = _make_patient(db_session)
    session = authenticate(db_session, "pat@example.com", "correct-horse")
    assert session.subject_id == patient.id
    assert session.role is Role.patient
    assert session.token  # a signed token was issued


def test_authenticate_is_case_insensitive_on_email(db_session: Session) -> None:
    _make_patient(db_session)
    session = authenticate(db_session, "PAT@EXAMPLE.COM", "correct-horse")
    assert session.role is Role.patient


def test_authenticate_rejects_wrong_password(db_session: Session) -> None:
    _make_patient(db_session)
    with pytest.raises(AuthenticationFailed):
        authenticate(db_session, "pat@example.com", "wrong")


def test_authenticate_rejects_unknown_email(db_session: Session) -> None:
    with pytest.raises(AuthenticationFailed):
        authenticate(db_session, "nobody@example.com", "whatever")


def test_authenticate_resolves_role_across_tables(db_session: Session) -> None:
    _make_volunteer(db_session)
    session = authenticate(db_session, "vol@example.com", "vol-pass")
    assert session.role is Role.volunteer


# --- authorize -------------------------------------------------------------


def test_authorize_allows_matching_role(db_session: Session) -> None:
    _make_patient(db_session)
    session = authenticate(db_session, "pat@example.com", "correct-horse")
    assert authorize(session, Role.patient) is True


def test_authorize_denies_other_roles(db_session: Session) -> None:
    _make_patient(db_session)
    session = authenticate(db_session, "pat@example.com", "correct-horse")
    assert authorize(session, Role.volunteer) is False
    assert authorize(session, Role.clinician) is False


def test_authorize_denies_none_session() -> None:
    assert authorize(None, Role.patient) is False


# --- FastAPI dependency gating --------------------------------------------


def _build_app(db_session: Session) -> FastAPI:
    app = FastAPI()

    # Route the dependency's db to the test session so the token-resolution
    # check (account still exists) runs against the same data.
    app.dependency_overrides[get_session] = lambda: db_session

    @app.get("/patient")
    def patient_only(session=Depends(require_role(Role.patient))):
        return {"role": session.role.value}

    return app


def test_dependency_returns_401_when_unauthenticated(db_session: Session) -> None:
    _make_patient(db_session)
    client = TestClient(_build_app(db_session))
    resp = client.get("/patient")
    assert resp.status_code == 401
    assert resp.json()["detail"]["redirect"] == "/sign-in"


def test_dependency_allows_matching_role(db_session: Session) -> None:
    _make_patient(db_session)
    session = authenticate(db_session, "pat@example.com", "correct-horse")
    client = TestClient(_build_app(db_session))
    resp = client.get(
        "/patient", headers={"Authorization": f"Bearer {session.token}"}
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "patient"


def test_dependency_returns_403_for_wrong_role(db_session: Session) -> None:
    _make_patient(db_session)
    _make_volunteer(db_session)
    vol_session = authenticate(db_session, "vol@example.com", "vol-pass")
    client = TestClient(_build_app(db_session))
    resp = client.get(
        "/patient", headers={"Authorization": f"Bearer {vol_session.token}"}
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["message"] == "access-denied"
