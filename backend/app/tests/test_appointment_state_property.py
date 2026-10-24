"""Property-based test for the appointment lifecycle state machine (task 9.2).

# Feature: careconnect, Property 7: Appointment transitions follow only the valid transition graph

Property 7 (design.md "Correctness Properties"): for any appointment and any
requested transition, the transition succeeds if and only if ``(current, target)``
is one of the allow-listed pairs (booked->accepted, booked->cancelled,
booked->completed, accepted->completed, accepted->cancelled); otherwise the
current state is preserved and an invalid-transition message is returned. The
recorded state is always exactly one of booked, accepted, completed, or
cancelled, and the bound side effects hold (any ->cancelled returns the slot to
available; any ->completed queues the appointment for clinician review).

Validates: Requirements 8.6, 8.7, 8.8, 8.9, 8.10
"""

from __future__ import annotations

import itertools
from datetime import datetime, timedelta

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy.orm import Session

from app.models.appointment import Appointment
from app.models.availability import AvailabilitySlot
from app.models.credential import ServiceType
from app.models.enums import AppointmentState, SlotStatus
from app.models.people import Patient, Volunteer
from app.services.appointment_state import (
    INVALID_TRANSITION_MESSAGE,
    VALID_TRANSITIONS,
    transition,
)

# A monotonically increasing counter so every example gets unique, collision-free
# emails/service-type names despite reusing a single function-scoped session.
_seq = itertools.count()

ALL_STATES = list(AppointmentState)


def _is_allow_listed(current: AppointmentState, target: AppointmentState) -> bool:
    """Oracle: is (current, target) in the design's valid-transition allow-list?"""
    return target in VALID_TRANSITIONS.get(current, frozenset())


def _build_appointment(
    db: Session, start_state: AppointmentState
) -> Appointment:
    """Create a persisted appointment in ``start_state`` with an assigned, bookable slot."""
    n = next(_seq)

    patient = Patient(
        email=f"patient{n}@example.test",
        password_hash="x",
        latitude=42.3601,
        longitude=-71.0589,
        consent_given=True,
    )
    volunteer = Volunteer(
        email=f"volunteer{n}@example.test",
        password_hash="x",
        latitude=42.3601,
        longitude=-71.0589,
    )
    service_type = ServiceType(name=f"service-{n}")
    db.add_all([patient, volunteer, service_type])
    db.flush()

    start = datetime(2024, 1, 1, 9, 0) + timedelta(hours=n)
    slot = AvailabilitySlot(
        volunteer_id=volunteer.id,
        start=start,
        end=start + timedelta(hours=1),
        status=SlotStatus.unavailable,
    )
    db.add(slot)
    db.flush()

    appointment = Appointment(
        patient_id=patient.id,
        volunteer_id=volunteer.id,
        slot_id=slot.id,
        service_type_id=service_type.id,
        state=start_state,
        queued_for_review=False,
        reviewed=False,
    )
    db.add(appointment)
    db.flush()

    # Link the slot back to the appointment so a ->cancelled transition has a
    # slot to return to available.
    slot.appointment_id = appointment.id
    db.flush()

    return appointment


def _cleanup(db: Session, appointment: Appointment) -> None:
    """Remove the per-example rows so the single session stays clean across runs."""
    slot = appointment.slot
    patient_id = appointment.patient_id
    volunteer_id = appointment.volunteer_id
    service_type_id = appointment.service_type_id

    # Break the appointment<->slot cycle before deleting either side.
    if slot is not None:
        slot.appointment_id = None
    appointment.slot_id = None
    db.flush()

    db.delete(appointment)
    if slot is not None:
        db.delete(slot)
    db.flush()

    db.query(ServiceType).filter(ServiceType.id == service_type_id).delete()
    db.query(Volunteer).filter(Volunteer.id == volunteer_id).delete()
    db.query(Patient).filter(Patient.id == patient_id).delete()
    db.flush()


@settings(max_examples=150, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    start_state=st.sampled_from(ALL_STATES),
    target_state=st.sampled_from(ALL_STATES),
)
def test_appointment_transitions_follow_valid_graph(
    db_session: Session,
    start_state: AppointmentState,
    target_state: AppointmentState,
) -> None:
    """Property 7: transitions obey the allow-list, preserve state on reject, and bind side effects."""
    appointment = _build_appointment(db_session, start_state)
    # The slot bound to this appointment before the transition is attempted.
    bound_slot = appointment.slot
    try:
        expected_ok = _is_allow_listed(start_state, target_state)

        result = transition(db_session, appointment, target_state)

        # succeeds iff the (current, target) pair is allow-listed.
        assert result.ok is expected_ok

        # Recorded state is always exactly one of the four members (R8.10).
        assert appointment.state in ALL_STATES
        assert isinstance(appointment.state, AppointmentState)
        assert result.state == appointment.state

        if expected_ok:
            # Applied: lands on the requested target, no rejection message.
            assert appointment.state == target_state
            assert result.message is None

            # Bound side effects (R8.7, R8.8, R10.5):
            if target_state == AppointmentState.cancelled:
                # Slot returned to available and detached from the appointment.
                assert appointment.slot_id is None
                assert bound_slot is not None
                assert bound_slot.status == SlotStatus.available
                assert bound_slot.appointment_id is None
            elif target_state == AppointmentState.completed:
                assert appointment.queued_for_review is True
        else:
            # Rejected: current state preserved unchanged, invalid-transition message.
            assert appointment.state == start_state
            assert result.state == start_state
            assert result.message == INVALID_TRANSITION_MESSAGE
            # No side effect fired on a rejected transition.
            assert appointment.queued_for_review is False
            assert appointment.slot_id is not None
    finally:
        _cleanup(db_session, appointment)
