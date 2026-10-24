"""Insurance records for patients and the doctor acceptance join.

A patient has at most one ``InsuranceRecord`` whose ``verification_status`` gates
compatibility reporting (R14). Providers accept a set of insurance plans, modelled
as a many-to-many between ``RecommendedDoctor`` and ``InsuranceRecord``.
"""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import (
    Column,
    Enum,
    ForeignKey,
    Integer,
    String,
    Table,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import VerificationStatus


# Many-to-many: which insurance plans a provider accepts (R15, R16).
doctor_accepted_insurance = Table(
    "doctor_accepted_insurance",
    Base.metadata,
    Column(
        "doctor_id",
        ForeignKey("recommended_doctors.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "insurance_record_id",
        ForeignKey("insurance_records.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class InsuranceRecord(Base):
    """A patient or provider insurance record with a verification status (R14)."""

    __tablename__ = "insurance_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    patient_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"),
        nullable=True,
        unique=True,
        index=True,
    )
    plan: Mapped[str] = mapped_column(String, nullable=False)
    network: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    verification_status: Mapped[VerificationStatus] = mapped_column(
        Enum(VerificationStatus, name="verification_status"),
        nullable=False,
        default=VerificationStatus.unverified,
    )

    patient: Mapped[Optional["Patient"]] = relationship(
        "Patient", back_populates="insurance_record"
    )
    accepting_doctors: Mapped[List["RecommendedDoctor"]] = relationship(
        "RecommendedDoctor",
        secondary=doctor_accepted_insurance,
        back_populates="accepted_insurance",
    )


from app.models.people import Patient  # noqa: E402,F401
from app.models.recommendation import RecommendedDoctor  # noqa: E402,F401


__all__ = ["InsuranceRecord", "doctor_accepted_insurance"]
