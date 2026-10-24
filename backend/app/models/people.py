"""Account entities: Patient, Volunteer, and Clinician.

Each is a distinct table (not single-table inheritance) because their fields and
relationships diverge: a Patient carries consent/insurance/needs, a Volunteer
derives Authorized_Services from credentials, and a Clinician holds a license
credential. All three share email, password hash, role, and a ``location``
stored as ``latitude``/``longitude`` columns (the design's ``location{lat,lng}``)
usable by both DS engines.
"""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import Boolean, Enum, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import Role


class Patient(Base):
    """A patient account (R1, R12.2, R20.4)."""

    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[Role] = mapped_column(
        Enum(Role, name="role"), nullable=False, default=Role.patient
    )

    # location{lat,lng}
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)

    # Comma-separated declared needs; kept simple for the synthetic dataset.
    needs: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # Primary care provider (free text / identifier).
    pcp: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # Patient ZIP used to rank nearby MA hospitals by ZIP-code proximity
    # (see app/services/hospitals.py). Optional so legacy rows stay valid.
    zip_code: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Consent recorded at creation; booking checks it (R8.5, R20.4).
    consent_given: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Set only via a Referral; drives the Recommendation_Engine hard filter (R12.2).
    required_specialty: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    insurance_record: Mapped[Optional["InsuranceRecord"]] = relationship(
        "InsuranceRecord",
        back_populates="patient",
        uselist=False,
        cascade="all, delete-orphan",
    )
    appointments: Mapped[List["Appointment"]] = relationship(
        "Appointment", back_populates="patient", cascade="all, delete-orphan"
    )
    referrals: Mapped[List["Referral"]] = relationship(
        "Referral", back_populates="patient", cascade="all, delete-orphan"
    )
    medications: Mapped[List["Medication"]] = relationship(
        "Medication", back_populates="patient", cascade="all, delete-orphan"
    )


class Volunteer(Base):
    """A volunteer account whose Authorized_Services derive from credentials (R2, R5)."""

    __tablename__ = "volunteers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[Role] = mapped_column(
        Enum(Role, name="role"), nullable=False, default=Role.volunteer
    )

    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)

    credentials: Mapped[List["Credential"]] = relationship(
        "Credential", back_populates="volunteer", cascade="all, delete-orphan"
    )
    availability_slots: Mapped[List["AvailabilitySlot"]] = relationship(
        "AvailabilitySlot", back_populates="volunteer", cascade="all, delete-orphan"
    )
    appointments: Mapped[List["Appointment"]] = relationship(
        "Appointment", back_populates="volunteer", cascade="all, delete-orphan"
    )
    # Derived join recomputed by Credential_Service; never stored independently
    # of a verified credential (R5.2, R5.6, R5.7).
    authorized_services: Mapped[List["AuthorizedService"]] = relationship(
        "AuthorizedService", back_populates="volunteer", cascade="all, delete-orphan"
    )


class Clinician(Base):
    """A clinician account; holds a license Credential (R3)."""

    __tablename__ = "clinicians"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[Role] = mapped_column(
        Enum(Role, name="role"), nullable=False, default=Role.clinician
    )

    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    credentials: Mapped[List["Credential"]] = relationship(
        "Credential", back_populates="clinician", cascade="all, delete-orphan"
    )
    decisions: Mapped[List["ClinicalDecision"]] = relationship(
        "ClinicalDecision", back_populates="clinician", cascade="all, delete-orphan"
    )


# Imports placed at the end to avoid circular imports while keeping the string
# relationship targets resolvable once all model modules are loaded.
from app.models.appointment import Appointment  # noqa: E402,F401
from app.models.clinical import ClinicalDecision, Medication, Referral  # noqa: E402,F401
from app.models.credential import AuthorizedService, Credential  # noqa: E402,F401
from app.models.availability import AvailabilitySlot  # noqa: E402,F401
from app.models.insurance import InsuranceRecord  # noqa: E402,F401


__all__ = ["Patient", "Volunteer", "Clinician"]
