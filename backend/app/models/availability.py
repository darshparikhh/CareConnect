"""Volunteer availability slots.

A slot is owned by a Volunteer, carries a start/end window and an
available/unavailable status, and optionally points at the Appointment that
booked it (R6, R8.2).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import SlotStatus


class AvailabilitySlot(Base):
    """A bookable time window offered by a Volunteer (R6, R8.2, R8.7, R8.8)."""

    __tablename__ = "availability_slots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    volunteer_id: Mapped[int] = mapped_column(
        ForeignKey("volunteers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[SlotStatus] = mapped_column(
        Enum(SlotStatus, name="slot_status"),
        nullable=False,
        default=SlotStatus.available,
    )

    # Set when the slot is assigned to an appointment; cleared on decline/cancel.
    # Appointment.slot_id and this column form a cycle (slot<->appointment);
    # use_alter lets SQLAlchemy emit this FK via ALTER so create_all/drop_all can
    # order the two tables despite the cycle.
    appointment_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey(
            "appointments.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_availability_slot_appointment",
        ),
        nullable=True,
    )

    volunteer: Mapped["Volunteer"] = relationship(
        "Volunteer", back_populates="availability_slots"
    )
    appointment: Mapped[Optional["Appointment"]] = relationship(
        "Appointment",
        back_populates="slot",
        foreign_keys=[appointment_id],
    )


from app.models.appointment import Appointment  # noqa: E402,F401
from app.models.people import Volunteer  # noqa: E402,F401


__all__ = ["AvailabilitySlot"]
