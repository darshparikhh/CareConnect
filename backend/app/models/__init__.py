"""SQLAlchemy models and the declarative base for CareConnect.

Importing this package pulls in every entity module so that all tables register
on the shared ``Base.metadata`` and SQLAlchemy can resolve the string-based
relationship targets. ``init_db()`` then creates the full schema.
"""

from app.models.base import Base
from app.models.enums import (
    AppointmentState,
    InsuranceCompatibility,
    Role,
    SlotStatus,
    VerificationStatus,
)
from app.models.people import Clinician, Patient, Volunteer
from app.models.credential import (
    AuthorizedService,
    Credential,
    CredentialCondition,
    ServiceType,
    credential_service_type,
)
from app.models.availability import AvailabilitySlot
from app.models.appointment import Appointment, Questionnaire, TestResult
from app.models.clinical import ClinicalDecision, Medication, Referral
from app.models.insurance import InsuranceRecord, doctor_accepted_insurance
from app.models.recommendation import RecommendedDoctor

__all__ = [
    "Base",
    # enums
    "AppointmentState",
    "VerificationStatus",
    "SlotStatus",
    "InsuranceCompatibility",
    "Role",
    # people
    "Patient",
    "Volunteer",
    "Clinician",
    # credentials / services
    "Credential",
    "CredentialCondition",
    "ServiceType",
    "AuthorizedService",
    "credential_service_type",
    # availability
    "AvailabilitySlot",
    # appointments / visit data
    "Appointment",
    "Questionnaire",
    "TestResult",
    # clinical
    "ClinicalDecision",
    "Referral",
    "Medication",
    # insurance / recommendation
    "InsuranceRecord",
    "doctor_accepted_insurance",
    "RecommendedDoctor",
]
