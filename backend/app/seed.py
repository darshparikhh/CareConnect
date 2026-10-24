"""Deterministic synthetic-data seeding for the CareConnect demo and tests.

Builds a small, self-consistent world: service types, provider insurance plans,
recommendable doctors, ten Boston-area volunteers (each authorized for the
demo PCR/vaccination service), a verified + an unverified clinician, and the
headline Boston patient. Everything is synthetic.

The demo service is a repurposed ``vaccination`` Service_Type that drives a
realistic PCR symptom screen (two readable questions) plus a recorded PCR test
result. A verified clinician (``clinician.verified@example.com``) reviews the
completed visit; the Boston patient (``boston.flu.patient@example.com``) then
sees the approved decision and nearby hospitals.

Determinism: every field except the rolling availability slots (anchored to
``datetime.now()`` so a demo user picking a near date always lands on a slot)
is stable across runs. Passwords use a fixed-salt PBKDF2 hash that the
Auth_Service can verify.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.availability import AvailabilitySlot
from app.models.credential import Credential, CredentialCondition, ServiceType
from app.models.enums import Role, SlotStatus, VerificationStatus
from app.models.insurance import InsuranceRecord
from app.models.people import Clinician, Patient, Volunteer
from app.models.recommendation import RecommendedDoctor

_PASSWORD_SALT = b"careconnect-synthetic-seed"
_DEMO_PASSWORD = "password"
_EPOCH = datetime(2025, 1, 6, 9, 0, 0)  # fixed Monday for stable timestamps


def _hash_password(password: str) -> str:
    """Stable, self-describing PBKDF2 hash the Auth_Service can verify."""
    iterations = 100_000
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), _PASSWORD_SALT, iterations
    )
    return "pbkdf2_sha256${iters}${salt}${digest}".format(
        iters=iterations, salt=_PASSWORD_SALT.hex(), digest=digest.hex()
    )


@dataclass
class SeedResult:
    """Key records produced by :func:`seed`, for the demo and tests."""

    service_types: Dict[str, ServiceType] = field(default_factory=dict)
    volunteers: List[Volunteer] = field(default_factory=list)
    clinicians: List[Clinician] = field(default_factory=list)
    doctors: List[RecommendedDoctor] = field(default_factory=list)
    boston_patient: Patient = None  # type: ignore[assignment]
    vaccination: ServiceType = None  # type: ignore[assignment]


def _seed_service_types(session: Session) -> Dict[str, ServiceType]:
    """Create the Service_Types. The demo ``vaccination`` service drives a PCR
    symptom screen (two readable questions) plus a required ``pcr_test`` result."""
    service_types = [
        ServiceType(
            name="vaccination",
            required_tests="pcr_test",
            required_questions="What are your symptoms?,When did this onset occur?",
        ),
        ServiceType(name="specimen_collection", required_tests=None, required_questions=None),
        ServiceType(name="diagnostic_test", required_tests="rapid_antigen", required_questions=None),
        ServiceType(name="wellness_check", required_tests=None, required_questions=None),
    ]
    session.add_all(service_types)
    session.flush()
    return {st.name: st for st in service_types}


def _add_slot(
    volunteer: Volunteer,
    *,
    start: Optional[datetime] = None,
    start_hour: Optional[int] = None,
    duration_hours: int = 2,
    base_day: Optional[datetime] = None,
) -> AvailabilitySlot:
    """Attach one available slot to ``volunteer``."""
    if start is None:
        day = base_day or _EPOCH
        hour = start_hour if start_hour is not None else 9
        start = day.replace(hour=hour, minute=0, second=0, microsecond=0)
    slot = AvailabilitySlot(
        start=start,
        end=start + timedelta(hours=duration_hours),
        status=SlotStatus.available,
    )
    volunteer.availability_slots.append(slot)
    return slot


def _seed_volunteers(
    session: Session, service_types: Dict[str, ServiceType]
) -> List[Volunteer]:
    """Create the 10 Boston-area stand-in volunteers, each fully authorized for
    the demo vaccination/PCR service (verified credential + satisfied MA
    state-license condition)."""
    vaccination = service_types["vaccination"]

    # (display name, email, lat, lng, neighborhood)
    standin_specs = [
        ("Maria Alvarez", "maria.alvarez@careconnect.org", 42.3736, -71.0712, "Beacon Hill"),
        ("James Chen", "james.chen@careconnect.org", 42.3493, -71.0785, "Back Bay"),
        ("Aisha Rahman", "aisha.rahman@careconnect.org", 42.3388, -71.0765, "South End"),
        ("David O'Brien", "david.obrien@careconnect.org", 42.3188, -71.0846, "Roxbury"),
        ("Sofia Rossi", "sofia.rossi@careconnect.org", 42.3875, -71.0995, "Charlestown"),
        ("Marcus Johnson", "marcus.johnson@careconnect.org", 42.3426, -71.1030, "Fenway"),
        ("Priya Patel", "priya.patel@careconnect.org", 42.3601, -71.0589, "Downtown"),
        ("Liam Murphy", "liam.murphy@careconnect.org", 42.3297, -71.1043, "Mission Hill"),
        ("Grace Kim", "grace.kim@careconnect.org", 42.3505, -71.1054, "Allston"),
        ("Noah Williams", "noah.williams@careconnect.org", 42.3464, -71.0972, "Kenmore"),
    ]
    volunteers: List[Volunteer] = []
    for _name, email, lat, lng, _hood in standin_specs:
        volunteers.append(
            Volunteer(
                email=email,
                password_hash=_hash_password(_DEMO_PASSWORD),
                role=Role.volunteer,
                latitude=lat,
                longitude=lng,
            )
        )
    session.add_all(volunteers)
    session.flush()

    for volunteer in volunteers:
        cred = Credential(
            type="vaccination_certification",
            volunteer_id=volunteer.id,
            status=VerificationStatus.verified,
            verifying_authority="MA-DPH",
            verified_at=_EPOCH,
            expires_at=_EPOCH.replace(year=2027),
        )
        cred.authorizes_service_types.append(vaccination)
        cred.conditions.append(
            CredentialCondition(kind="state_license_MA", satisfied=True)
        )
        volunteer.credentials.append(cred)
    session.flush()

    # Availability: fixed epoch-day slots (for any fixed-date usage) plus wide
    # rolling slots across the next 14 days so a near-future pick always lands
    # on a covering window a patient can book a narrow requested time inside.
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    for volunteer in volunteers:
        _add_slot(volunteer, start_hour=9, duration_hours=2)
        _add_slot(volunteer, start_hour=13, duration_hours=2)
        for day_offset in range(0, 14):
            day = (now + timedelta(days=day_offset)).replace(hour=8)
            _add_slot(volunteer, start=day, duration_hours=4)
    session.flush()

    # Materialize the derived Authorized_Services join for every volunteer.
    from app.services.credentials import recompute_authorized_services
    for volunteer in volunteers:
        recompute_authorized_services(session, volunteer)
    session.flush()
    return volunteers


def _seed_clinicians(session: Session) -> List[Clinician]:
    """One verified and one unverified clinician for contrast."""
    verified = Clinician(
        email="clinician.verified@example.com",
        password_hash=_hash_password(_DEMO_PASSWORD),
        role=Role.clinician,
        latitude=42.3611,
        longitude=-71.0590,
    )
    unverified = Clinician(
        email="clinician.unverified@example.com",
        password_hash=_hash_password(_DEMO_PASSWORD),
        role=Role.clinician,
        latitude=42.3615,
        longitude=-71.0585,
    )
    session.add_all([verified, unverified])
    session.flush()
    verified.credentials.append(
        Credential(
            type="medical_license",
            clinician_id=verified.id,
            status=VerificationStatus.verified,
            verifying_authority="MA-BORM",
            verified_at=_EPOCH,
            expires_at=_EPOCH.replace(year=2028),
        )
    )
    unverified.credentials.append(
        Credential(
            type="medical_license",
            clinician_id=unverified.id,
            status=VerificationStatus.unverified,
        )
    )
    session.flush()
    return [verified, unverified]


def _seed_provider_insurance(session: Session) -> List[InsuranceRecord]:
    """Provider-side reference plans (patient_id IS NULL) to verify against."""
    plans = [
        InsuranceRecord(patient_id=None, plan="BlueCrossMA", network="MA",
                        verification_status=VerificationStatus.verified),
        InsuranceRecord(patient_id=None, plan="HarvardPilgrim", network="MA",
                        verification_status=VerificationStatus.verified),
    ]
    session.add_all(plans)
    session.flush()
    return plans


def _seed_doctors(session: Session, provider_plans: List[InsuranceRecord]) -> List[RecommendedDoctor]:
    """Recommendable providers incl. a cardiologist accepting BlueCrossMA."""
    blue = provider_plans[0]
    cardiologist = RecommendedDoctor(
        name="Dr. Ada Cardio", specialty="cardiology",
        latitude=42.3605, longitude=-71.0580, rating=4.7,
        open_slots_14d=10, one_way_travel_minutes=12.0,
    )
    cardiologist.accepted_insurance.append(blue)
    generalist = RecommendedDoctor(
        name="Dr. Ben General", specialty="general_practice",
        latitude=42.3700, longitude=-71.0500, rating=4.2,
        open_slots_14d=6, one_way_travel_minutes=20.0,
    )
    generalist.accepted_insurance.append(blue)
    doctors = [cardiologist, generalist]
    session.add_all(doctors)
    session.flush()
    return doctors


def _seed_patients(session: Session) -> Patient:
    """The headline Boston flu patient with BlueCrossMA + a Boston ZIP."""
    boston = Patient(
        email="boston.flu.patient@example.com",
        password_hash=_hash_password(_DEMO_PASSWORD),
        role=Role.patient,
        latitude=42.3601,
        longitude=-71.0589,
        needs="flu vaccination",
        pcp="Dr. Ben General",
        consent_given=True,
        required_specialty="cardiology",
        zip_code="02118",
    )
    boston.insurance_record = InsuranceRecord(
        plan="BlueCrossMA", network="MA",
        verification_status=VerificationStatus.unverified,
    )
    session.add(boston)
    session.flush()
    return boston


def seed(session: Session) -> SeedResult:
    """Seed the full synthetic world and return the key records."""
    service_types = _seed_service_types(session)
    provider_plans = _seed_provider_insurance(session)
    doctors = _seed_doctors(session, provider_plans)
    volunteers = _seed_volunteers(session, service_types)
    clinicians = _seed_clinicians(session)
    boston_patient = _seed_patients(session)
    session.flush()
    return SeedResult(
        service_types=service_types,
        volunteers=volunteers,
        clinicians=clinicians,
        doctors=doctors,
        boston_patient=boston_patient,
        vaccination=service_types["vaccination"],
    )


__all__ = ["seed", "SeedResult"]
