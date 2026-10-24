"""Availability_Service: Volunteer availability slot management.

This implements the design's ``Availability_Service`` (R6, R8.2, R8.7, R8.8):
it owns the lifecycle of :class:`~app.models.availability.AvailabilitySlot`
records and their assignment state.

* :func:`add_slot` records a new slot as ``available`` for a Volunteer (R6.1).
* :func:`remove_slot` marks a slot ``unavailable`` when it holds no assigned
  appointment (R6.2), and rejects removal with a ``slot-has-appointment``
  message when the slot is bound to an active appointment (R6.3).
* :func:`mark_available` / :func:`mark_unavailable` are the small helpers the
  Appointment_Service calls to flip a slot's status on booking (unavailable
  before confirmation, R8.2) and on decline/cancel (back to available, R8.7,
  R8.8).
* :func:`slots_for_matching` exposes a Volunteer's currently available slots to
  the Matching_Engine (R6.4).

A slot "holds an assigned appointment" when its ``appointment_id`` points at an
appointment that is still in an active state (``booked``, ``accepted``, or
``completed``). A ``cancelled`` appointment means the slot was already returned
to the pool (decline/cancel clears assignment and marks it available), so it
does not block removal.

Results follow the style of :mod:`app.services.auth`: the happy path returns the
affected :class:`AvailabilitySlot`, and the one rejection case
(R6.3) raises :class:`SlotHasAppointment`, carrying the stable
``slot-has-appointment`` message the UI surfaces.
"""

from __future__ import annotations

from datetime import datetime
from typing import List

from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.models.appointment import Appointment
from app.models.availability import AvailabilitySlot
from app.models.enums import AppointmentState, SlotStatus
from app.models.people import Volunteer

# Appointment states that represent a live assignment of a slot. A slot bound to
# an appointment in one of these states must not be removed (R6.3); a
# ``cancelled`` appointment has already released its slot, so it does not count.
_ACTIVE_APPOINTMENT_STATES = frozenset(
    {
        AppointmentState.booked,
        AppointmentState.accepted,
        AppointmentState.completed,
    }
)


class SlotHasAppointment(Exception):
    """Raised when removing a slot that holds an assigned appointment (R6.3).

    Carries the stable ``slot-has-appointment`` message required by the spec.
    """

    def __init__(self, message: str = "slot-has-appointment") -> None:
        super().__init__(message)
        self.message = message


def _has_assigned_appointment(db: DBSession, slot: AvailabilitySlot) -> bool:
    """Return True if ``slot`` is bound to an active (non-cancelled) appointment.

    Checks the slot's ``appointment_id`` link and confirms the referenced
    appointment is still in an active state. A missing link or a cancelled
    appointment means the slot is free to remove.
    """
    if slot.appointment_id is None:
        return False
    appointment = db.get(Appointment, slot.appointment_id)
    if appointment is None:
        return False
    return appointment.state in _ACTIVE_APPOINTMENT_STATES


def add_slot(
    db: DBSession, volunteer: Volunteer, start: datetime, end: datetime
) -> AvailabilitySlot:
    """Record a new availability slot as ``available`` for ``volunteer`` (R6.1).

    Creates the slot, attaches it to the Volunteer, flushes so the caller gets a
    populated id, and returns it. The slot starts unassigned
    (``appointment_id is None``) and ``available``.
    """
    slot = AvailabilitySlot(
        volunteer_id=volunteer.id,
        start=start,
        end=end,
        status=SlotStatus.available,
    )
    db.add(slot)
    db.flush()
    return slot


def remove_slot(db: DBSession, slot: AvailabilitySlot) -> AvailabilitySlot:
    """Remove an availability slot (R6.2, R6.3).

    When the slot holds no assigned appointment, mark it ``unavailable`` and
    return it (R6.2). When the slot holds an active assigned appointment, reject
    the removal by raising :class:`SlotHasAppointment` and leave the slot
    untouched (R6.3).
    """
    if _has_assigned_appointment(db, slot):
        raise SlotHasAppointment()
    return mark_unavailable(db, slot)


def mark_available(db: DBSession, slot: AvailabilitySlot) -> AvailabilitySlot:
    """Return ``slot`` to the ``available`` pool (R8.7, R8.8).

    Called by the Appointment_Service when an assigned appointment is declined
    or cancelled, so the slot is matchable again.
    """
    slot.status = SlotStatus.available
    db.add(slot)
    db.flush()
    return slot


def mark_unavailable(db: DBSession, slot: AvailabilitySlot) -> AvailabilitySlot:
    """Mark ``slot`` ``unavailable`` so it is no longer offered for matching.

    Used both by :func:`remove_slot` (R6.2) and by the Appointment_Service to
    take a slot out of circulation before confirming a booking (R8.2).
    """
    slot.status = SlotStatus.unavailable
    db.add(slot)
    db.flush()
    return slot


def slots_for_matching(
    db: DBSession, volunteer: Volunteer
) -> List[AvailabilitySlot]:
    """Expose ``volunteer``'s currently available slots to the Matching_Engine (R6.4).

    Returns only slots whose status is ``available``, ordered by start time so
    the engine's earliest-slot tie-break has a stable input.
    """
    stmt = (
        select(AvailabilitySlot)
        .where(AvailabilitySlot.volunteer_id == volunteer.id)
        .where(AvailabilitySlot.status == SlotStatus.available)
        .order_by(AvailabilitySlot.start)
    )
    return list(db.execute(stmt).scalars().all())


__all__ = [
    "SlotHasAppointment",
    "add_slot",
    "remove_slot",
    "mark_available",
    "mark_unavailable",
    "slots_for_matching",
]
