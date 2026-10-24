"""Appointment and the visit data captured against it.

The ``Appointment`` carries the lifecycle ``state`` plus the ``queued_for_review``
and ``reviewed`` flags used by the completion/review flow (R8.10, R10.5, R11.4).
``Questionnaire`` and ``Test_Result`` are the visit data Volunteers submit; a
Test_Result is information only (R10.7, R13.3).
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import AppointmentState


class Appointment(Base):
    """A booking linking a Patient, Volunteer, slot, and Service_Type (R8)."""

    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    volunteer_id: Mapped[int] = mapped_column(
        ForeignKey("volunteers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    slot_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("availability_slots.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    service_type_id: Mapped[int] = mapped_column(
        ForeignKey("service_types.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    state: Mapped[AppointmentState] = mapped_column(
        Enum(AppointmentState, name="appointment_state"),
        nullable=False,
        default=AppointmentState.booked,
    )
    queued_for_review: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    reviewed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    requested_start: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    requested_end: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )

    patient: Mapped["Patient"] = relationship(
        "Patient", back_populates="appointments"
    )
    volunteer: Mapped["Volunteer"] = relationship(
        "Volunteer", back_populates="appointments"
    )
    service_type: Mapped["ServiceType"] = relationship("ServiceType")
    slot: Mapped[Optional["AvailabilitySlot"]] = relationship(
        "AvailabilitySlot",
        back_populates="appointment",
        foreign_keys="AvailabilitySlot.appointment_id",
        uselist=False,
    )
    questionnaires: Mapped[List["Questionnaire"]] = relationship(
        "Questionnaire", back_populates="appointment", cascade="all, delete-orphan"
    )
    test_results: Mapped[List["TestResult"]] = relationship(
        "TestResult", back_populates="appointment", cascade="all, delete-orphan"
    )
    decision: Mapped[Optional["ClinicalDecision"]] = relationship(
        "ClinicalDecision",
        back_populates="appointment",
        uselist=False,
        cascade="all, delete-orphan",
    )


class Questionnaire(Base):
    """Answers captured for an appointment's Service_Type (R10.1, R10.2).

    ``answers`` and ``required_question_ids`` are stored as compact text; the
    Visit_Service decides completion against the Service_Type's required set.
    """

    __tablename__ = "questionnaires"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    appointment_id: Mapped[int] = mapped_column(
        ForeignKey("appointments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    service_type_id: Mapped[int] = mapped_column(
        ForeignKey("service_types.id", ondelete="RESTRICT"), nullable=False
    )
    answers: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    required_question_ids: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    appointment: Mapped[Appointment] = relationship(
        "Appointment", back_populates="questionnaires"
    )
    service_type: Mapped["ServiceType"] = relationship("ServiceType")


class TestResult(Base):
    """A synthetic measurement captured during a visit; information only (R10.3, R10.7, R13.3)."""

    __tablename__ = "test_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    appointment_id: Mapped[int] = mapped_column(
        ForeignKey("appointments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    service_type_id: Mapped[int] = mapped_column(
        ForeignKey("service_types.id", ondelete="RESTRICT"), nullable=False
    )
    measurement: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    unit: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    appointment: Mapped[Appointment] = relationship(
        "Appointment", back_populates="test_results"
    )
    service_type: Mapped["ServiceType"] = relationship("ServiceType")


from app.models.availability import AvailabilitySlot  # noqa: E402,F401
from app.models.clinical import ClinicalDecision  # noqa: E402,F401
from app.models.credential import ServiceType  # noqa: E402,F401
from app.models.people import Patient, Volunteer  # noqa: E402,F401

__all__ = ["Appointment", "Questionnaire", "TestResult"]
