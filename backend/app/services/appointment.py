"""Appointment_Service: booking with its safety gates (R8.1-R8.5, R20.4).

This module owns the ``book`` operation — the entry into the appointment
lifecycle. It creates an :class:`~app.models.appointment.Appointment` in the
``booked`` state only after three safety gates pass, and it closes the
concurrent-booking race by taking the slot out of circulation transactionally
before confirming.

The three booking preconditions (design "Appointment_Service", R8.1, R8.4,
R8.5) are checked in this order:

1. **Available slot (R8.3).** The chosen slot must currently report
   ``available``. A slot that is already ``unavailable`` — including one that
   just became unavailable through a concurrent booking of the same slot — is
   rejected with ``slot-unavailable`` and its assignment is left unchanged
   (R8.3).
2. **Authorization (R8.4).** The requested Service_Type must be in the
   Volunteer's **current** Authorized_Services. We read this from the
   Credential_Service's pure derivation
   (:func:`~app.services.credentials.derive_authorized_service_types`), the
   single source of truth, so a booking can never outrun a revoked or
   condition-unmet credential. Otherwise rejected with ``not-authorized``.
3. **Consent (R8.5, R20.4).** The Patient's consent to participate must be
   recorded (``consent_given``). Otherwise rejected with ``consent-required``
   and no appointment is created.

Concurrent-booking race (R8.2, R8.3)
------------------------------------
The slot's availability check and its transition to ``unavailable`` happen in
the **same transaction window**: ``book`` re-reads the slot ``WITH FOR UPDATE``
row lock (best effort — SQLite serializes writers anyway), confirms it is
available, then marks it unavailable and flushes *before* returning the
confirmed appointment. Two concurrent ``book`` calls for the same slot cannot
both see it available: the first to flush the ``unavailable`` status wins, and
the second re-reads an already-unavailable slot and is rejected with
``slot-unavailable``. The appointment is created and linked only after the slot
is secured, so the "booking-confirmed" result always implies a locked slot
(R8.1, R8.2).

Later lifecycle moves (accept/decline/cancel/complete) are **not** handled here;
they go through :func:`app.services.appointment_state.transition`. ``book`` is
only the initial creation and does not use the transition table (there is no
valid transition *into* ``booked``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session as DBSession

from app.models.appointment import Appointment
from app.models.availability import AvailabilitySlot
from app.models.credential import ServiceType
from app.models.enums import AppointmentState, SlotStatus
from app.models.people import Patient, Volunteer
from app.services import availability as availability_service
from app.services.credentials import derive_authorized_service_types


class BookingError(Exception):
    """Base for the three booking-gate rejections.

    Each subclass carries a stable, UI-facing ``message`` so callers surface a
    single documented string per failure mode rather than parsing prose.
    """

    message = "booking-error"

    def __init__(self, message: Optional[str] = None) -> None:
        super().__init__(message or self.message)
        self.message = message or self.message


class SlotUnavailable(BookingError):
    """The chosen slot is not available (R8.3).

    Raised both when the slot is already ``unavailable`` at the start of the
    attempt and when a concurrent booking secured it first; in either case the
    slot assignment is left unchanged.
    """

    message = "slot-unavailable"


class NotAuthorized(BookingError):
    """The Volunteer is not currently authorized for the Service_Type (R8.4)."""

    message = "not-authorized"


class ConsentRequired(BookingError):
    """The Patient has no recorded consent to participate (R8.5, R20.4)."""

    message = "consent-required"


@dataclass(frozen=True)
class BookingResult:
    """A confirmed booking (the ``booking-confirmed`` result, R8.2).

    Returned only after all gates pass and the slot has been secured. ``ok`` is
    always ``True`` here; the rejection paths raise instead, mirroring the
    exception style of the other services.
    """

    appointment: Appointment
    ok: bool = True
    message: str = "booking-confirmed"


def _slot_is_available(slot: AvailabilitySlot) -> bool:
    """Return True when ``slot`` currently reports ``available`` and unassigned.

    An available status with no bound appointment is the only bookable shape; a
    slot already linked to an appointment (``appointment_id`` set) is treated as
    taken even if a stale status lingers.
    """
    return slot.status == SlotStatus.available and slot.appointment_id is None


def book(
    session: DBSession,
    patient: Patient,
    volunteer: Volunteer,
    slot: AvailabilitySlot,
    service_type: ServiceType,
    requested_start: Optional[datetime] = None,
    requested_end: Optional[datetime] = None,
) -> BookingResult:
    """Book ``volunteer`` for ``patient`` on ``slot`` for ``service_type`` (R8.1-R8.5).

    Enforces the three preconditions in order (available slot, authorized
    Service_Type, recorded consent) and, on success, creates exactly one
    ``booked`` appointment, links it to the slot both ways, marks the slot
    ``unavailable`` transactionally, and returns a :class:`BookingResult`
    (``booking-confirmed``).

    Raises :class:`SlotUnavailable`, :class:`NotAuthorized`, or
    :class:`ConsentRequired` on the corresponding gate, creating no appointment
    and leaving the slot assignment unchanged.
    """
    # --- Gate 1: the slot must currently be available (R8.3) -------------
    #
    # Re-read the slot inside this call's transaction and take a row lock so the
    # availability check and the mark-unavailable below are one atomic step,
    # closing the concurrent-booking race (R8.2, R8.3). ``with_for_update`` is a
    # no-op lock on SQLite (writers are serialized by the database), but makes
    # the intent explicit and gives real row-level locking on Postgres/MySQL.
    locked_slot = session.get(
        AvailabilitySlot, slot.id, with_for_update=True
    )
    if locked_slot is None or not _slot_is_available(locked_slot):
        raise SlotUnavailable()

    # --- Gate 2: Service_Type must be in the Volunteer's CURRENT set (R8.4) --
    #
    # Read the single source of truth (the pure credential derivation) rather
    # than any cached join, so a revoked/condition-unmet credential is honored
    # the instant it changes.
    authorized_ids = derive_authorized_service_types(volunteer)
    if service_type.id not in authorized_ids:
        raise NotAuthorized()

    # --- Gate 3: the Patient's consent must be recorded (R8.5, R20.4) --------
    if not patient.consent_given:
        raise ConsentRequired()

    # --- All gates passed: create the appointment and secure the slot --------
    #
    # Create exactly one appointment in the booked state assigned to this
    # Volunteer and associated with the slot (R8.1).
    appointment = Appointment(
        patient_id=patient.id,
        volunteer_id=volunteer.id,
        slot_id=locked_slot.id,
        service_type_id=service_type.id,
        state=AppointmentState.booked,
        queued_for_review=False,
        reviewed=False,
        requested_start=requested_start,
        requested_end=requested_end,
    )
    session.add(appointment)
    # Flush to assign the appointment id so the slot can link back to it.
    session.flush()

    # Link the slot to the appointment and mark it unavailable BEFORE returning
    # the confirmed result, so the slot is out of circulation at the moment of
    # confirmation (R8.2). The mark-unavailable flushes within this same
    # transaction, completing the atomic check-then-lock.
    locked_slot.appointment_id = appointment.id
    availability_service.mark_unavailable(session, locked_slot)

    return BookingResult(appointment=appointment)


__all__ = [
    "BookingError",
    "SlotUnavailable",
    "NotAuthorized",
    "ConsentRequired",
    "BookingResult",
    "book",
]
