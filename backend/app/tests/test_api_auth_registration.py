"""End-to-end tests for the auth and registration API (task 17.1).

These drive the real FastAPI app through a ``TestClient``, overriding only the
database session dependency so each test runs against the isolated per-test
SQLite database from ``conftest``. They exercise the full request path:
Pydantic validation → service → HTTP mapping.

Covered:

* ``/health`` works.
* A user registered through the API can sign in and receives a token; the
  token authorizes ``/auth/session`` and carries the right role.
* Invalid credentials get 401 authentication-failed.
* Each registration route maps success (201), missing fields (400 + named
  fields), and duplicate email (409) correctly.
"""

from __future__ import annotations

from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import get_session
from app.main import create_app


@pytest.fixture()
def client(db_engine: Engine) -> Iterator[TestClient]:
    """A TestClient whose DB session is bound to the per-test engine.

    The session dependency is overridden with a transactional session on the
    isolated engine so the full app (routers, middleware) runs against a clean
    database per test.
    """
    app = create_app()
    factory = sessionmaker(
        bind=db_engine, autoflush=False, expire_on_commit=False, future=True
    )

    def _override_get_session() -> Iterator[Session]:
        session = factory()
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


# --- health ----------------------------------------------------------------


def test_health_ok(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# --- sign-in ---------------------------------------------------------------


def test_registered_patient_can_sign_in_and_use_session(client: TestClient) -> None:
    reg = client.post(
        "/register/patient",
        json={
            "email": "jane@example.com",
            "password": "s3cret",
            "location": {"lat": 42.36, "lng": -71.06},
            "insurance": {"plan": "BlueCrossMA", "network": "PPO-Northeast"},
            "needs": "flu vaccination",
            "pcp": "Dr. Internist",
            "consent": True,
        },
    )
    assert reg.status_code == 201, reg.text
    assert reg.json()["role"] == "patient"

    signin = client.post(
        "/auth/sign-in",
        json={"email": "jane@example.com", "password": "s3cret"},
    )
    assert signin.status_code == 200, signin.text
    body = signin.json()
    token = body["token"]
    assert token
    assert body["role"] == "patient"

    session = client.get(
        "/auth/session", headers={"Authorization": f"Bearer {token}"}
    )
    assert session.status_code == 200
    assert session.json()["role"] == "patient"


def test_sign_in_with_invalid_credentials_is_401(client: TestClient) -> None:
    client.post(
        "/register/patient",
        json={
            "email": "bob@example.com",
            "password": "right-pass",
            "location": {"lat": 42.36, "lng": -71.06},
            "insurance": {"plan": "BlueCrossMA"},
            "needs": "vaccination",
            "pcp": "Dr. X",
            "consent": True,
        },
    )
    resp = client.post(
        "/auth/sign-in",
        json={"email": "bob@example.com", "password": "wrong-pass"},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"]["message"] == "authentication-failed"


def test_session_without_token_is_401_with_redirect(client: TestClient) -> None:
    resp = client.get("/auth/session")
    assert resp.status_code == 401
    assert resp.json()["detail"]["redirect"] == "/sign-in"


# --- patient registration mapping -----------------------------------------


def test_patient_registration_missing_fields_400_names_fields(
    client: TestClient,
) -> None:
    resp = client.post("/register/patient", json={"email": "x@example.com"})
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["message"] == "missing-required-fields"
    missing = set(detail["missing_fields"])
    # password, location, insurance, needs, pcp, consent were all absent.
    assert {"password", "location", "insurance", "needs", "pcp", "consent"} <= missing


def test_patient_registration_duplicate_email_409(client: TestClient) -> None:
    payload = {
        "email": "dup@example.com",
        "password": "pw",
        "location": {"lat": 42.3, "lng": -71.0},
        "insurance": {"plan": "BlueCrossMA"},
        "needs": "vaccination",
        "pcp": "Dr. X",
        "consent": True,
    }
    first = client.post("/register/patient", json=payload)
    assert first.status_code == 201
    second = client.post("/register/patient", json=payload)
    assert second.status_code == 409
    assert second.json()["detail"]["message"] == "account-already-exists"


# --- volunteer registration mapping ----------------------------------------


def test_volunteer_registration_success_201(client: TestClient) -> None:
    resp = client.post(
        "/register/volunteer",
        json={
            "email": "vol@example.com",
            "password": "pw",
            "location": {"lat": 42.36, "lng": -71.05},
            "declared_credentials": [
                {
                    "type": "vaccination_certification",
                    "service_types": ["vaccination"],
                    "conditions": [{"kind": "state_license_MA", "satisfied": True}],
                }
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["role"] == "volunteer"


def test_volunteer_registration_missing_fields_400(client: TestClient) -> None:
    resp = client.post("/register/volunteer", json={"email": "v2@example.com"})
    assert resp.status_code == 400
    missing = set(resp.json()["detail"]["missing_fields"])
    assert {"password", "location"} <= missing


def test_volunteer_can_sign_in_after_registration(client: TestClient) -> None:
    client.post(
        "/register/volunteer",
        json={
            "email": "vlog@example.com",
            "password": "vpw",
            "location": {"lat": 42.36, "lng": -71.05},
        },
    )
    signin = client.post(
        "/auth/sign-in", json={"email": "vlog@example.com", "password": "vpw"}
    )
    assert signin.status_code == 200
    assert signin.json()["role"] == "volunteer"


# --- clinician registration mapping ----------------------------------------


def test_clinician_registration_success_201(client: TestClient) -> None:
    resp = client.post(
        "/register/clinician",
        json={
            "email": "doc@example.com",
            "password": "pw",
            "license_info": "MA-LICENSE-12345",
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["role"] == "clinician"


def test_clinician_registration_missing_fields_400(client: TestClient) -> None:
    resp = client.post("/register/clinician", json={"email": "d2@example.com"})
    assert resp.status_code == 400
    missing = set(resp.json()["detail"]["missing_fields"])
    assert {"password", "license_info"} <= missing


def test_clinician_registration_duplicate_email_409(client: TestClient) -> None:
    payload = {
        "email": "docdup@example.com",
        "password": "pw",
        "license_info": {"license": "L-1", "type": "medical_license"},
    }
    assert client.post("/register/clinician", json=payload).status_code == 201
    second = client.post("/register/clinician", json=payload)
    assert second.status_code == 409
    assert second.json()["detail"]["message"] == "account-already-exists"
