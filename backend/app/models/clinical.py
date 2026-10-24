"""Clinical artifacts: decisions, referrals, and display-only medications.

A verified Clinician reviews a completed appointment and records a
``ClinicalDecision`` (non-empty, approval-gated for patient visibility). A
``Referral`` issued from a decision sets the Patient's required specialty for the
Recommendation_Engine. A ``Medication`` is display-only: created only by a
verified Clinician and shown only when approved (R11, R12, R13).
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class ClinicalDecision(Base):
    """A clinician's reviewed, approval-gated decision on an appointment (R11)."""

    __tablename__ = "clinical_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    appointment_id: Mapped[int] = mapped_column(
        ForeignKey("appointments.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    clinician_id: Mapped[int] = mapped_column(
        ForeignKey("clinicians.id", ondelete="CASCADE"), nullable=False, index=True
    )
    content: Mapped[str] = mapped_column(String, nullable=False)
    reviewed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    appointment: Mapped["Appointment"] = relationship(
        "Appointment", back_populates="decision"
    )
    clinician: Mapped["Clinician"] = relationship(
        "Clinician", back_populates="decisions"
    )
    referrals: Mapped[List["Referral"]] = relationship(
        "Referral", back_populates="clinical_decision", cascade="all, delete-orphan"
    )


class Referral(Base):
    """A specialty referral that sets the Patient's required specialty (R12)."""

    __tablename__ = "referrals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    clinical_decision_id: Mapped[int] = mapped_column(
        ForeignKey("clinical_decisions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    specialty: Mapped[str] = mapped_column(String, nullable=False)

    clinical_decision: Mapped[ClinicalDecision] = relationship(
        "ClinicalDecision", back_populates="referrals"
    )
    patient: Mapped["Patient"] = relationship("Patient", back_populates="referrals")


class Medication(Base):
    """A display-only medication: verified-clinician-created, approval-gated (R13)."""

    __tablename__ = "medications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    prescribing_clinician_id: Mapped[int] = mapped_column(
        ForeignKey("clinicians.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    patient: Mapped["Patient"] = relationship(
        "Patient", back_populates="medications"
    )
    prescribing_clinician: Mapped["Clinician"] = relationship("Clinician")


from app.models.appointment import Appointment  # noqa: E402,F401
from app.models.people import Clinician, Patient  # noqa: E402,F401


__all__ = ["ClinicalDecision", "Referral", "Medication"]
