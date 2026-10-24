"""Appointment lifecycle state machine (R8.6-R8.10, R10.5).

This module owns the authoritative transition machinery for the appointment
lifecycle. The design models the lifecycle as an **explicit transition table**
(the "Appointment Lifecycle State Machine" section): only the enumerated
transitions are valid, any other requested transition is rejected with the
current state preserved, and specific side effects are bound to particular
transitions.

Scope: this module owns the ``transition`` machinery only. The initial creation
of an appointment in the ``booked`` state (booking, with its consent/slot/
authorization gates) belongs to the Appointment_Service ``book`` operation
(task 10.1) and is intentionally out of scope here.

Valid transition allow-list (exactly the design table / R8.9):

====================  ==================  ==========================================
From                  To                  Trigger
====================  ==================  ==========================================
booked                accepted            Volunteer accepts (R8.6)
booked                cancelled           Volunteer declines (R8.7) / Patient cancels (R8.8)
booked                completed           required data recorded (R8.9, R10.5)
accepted              completed           required data recorded (R8.9, R10.5)
accepted              cancelled           Patient cancels (R8.8)
====================  ==================  ==========================================

Side effects bound to transitions:

* Any ``* -> cancelled`` transition (decline/cancel) returns the appointment's
  slot to **available** (R8.7, R8.8).
* Any ``* -> completed`` transition queues the appointment for clinician review
  (R10.5), i.e. sets ``queued_for_review = True``.

The recorded state is always exactly one of the four ``AppointmentState``
members (R8.10): because the state column is typed as ``AppointmentState`` and a
transition either lands on an allow-listed target or leaves the state untouched,
the invariant is preserved by construction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet, Optional

from sqlalchemy.orm import Session as DBSession

from app.models.appointment import Appointment
from app.models.enums import AppointmentState, SlotStatus


# The authoritative valid-transition allow-list, mapping each source state to
# the set of states it may move to. This mirrors the design's transition table
# exactly (R8.9). Any (from, to) pair not present here is invalid.
VALID_TRANSITIONS: Dict[AppointmentState, FrozenSet[AppointmentState]] = {
    AppointmentState.booked: frozenset(
        {
            AppointmentState.accepted,
            AppointmentState.cancelled,
            AppointmentState.completed,
        }
    ),
    AppointmentState.accepted: frozenset(
        {
            AppointmentState.completed,
            AppointmentState.cancelled,
        }
    ),
    # Terminal states: no outgoing transitions.
    AppointmentState.completed: frozenset(),
    AppointmentState.cancelled: frozenset(),
}


# The uniform message returned when a transition is not in the allow-list (R8.9).
INVALID_TRANSITION_MESSAGE = "invalid-transition"


def is_valid_transition(
    current: AppointmentState, target: AppointmentState
) -> bool:
    """Return True iff ``current -> target`` is in the valid-transition allow-list.

    This is a pure lookup against :data:`VALID_TRANSITIONS` (R8.9). A transition
    from a state to itself is never valid (it is not listed in the table).
    """
    return target in VALID_TRANSITIONS.get(current, frozenset())


@dataclass(frozen=True)
class TransitionResult:
    """The outcome of a requested transition.

    ``ok`` is True when the transition was applied; False when it was rejected
    as invalid. ``state`` always reports the appointment's state *after* the
    call -- which, on rejection, is the unchanged current state (R8.9). On
    rejection ``message`` carries :data:`INVALID_TRANSITION_MESSAGE`.
    """

    ok: bool
    state: AppointmentState
    message: Optional[str] = None


def _return_slot_to_available(db: DBSession, appointment: Appointment) -> None:
    """Return the appointment's slot to available (R8.7, R8.8).

    Coupling to the Availability_Service is kept loose: if that service is
    present (task 8.1) we delegate to its ``mark_available`` so slot semantics
    live in one place; otherwise we set the slot's status directly. Either way
    the slot is detached from the appointment so it can be matched again.
    """
    slot = appointment.slot
    if slot is None:
        return

    marked = False
    try:  # pragma: no cover - exercised only once Availability_Service lands
        from app.services import availability as availability_service

        mark_available = getattr(availability_service, "mark_available", None)
        if callable(mark_available):
            mark_available(db, slot)
            marked = True
    except ImportError:
        marked = False

    if not marked:
        slot.status = SlotStatus.available

    # Detach the slot from the appointment regardless of which path set the
    # status, so a returned slot is no longer linked to a cancelled appointment.
    slot.appointment_id = None
    appointment.slot_id = None


def _queue_for_review(appointment: Appointment) -> None:
    """Queue a completed appointment for clinician review (R10.5)."""
    appointment.queued_for_review = True


def _apply_side_effects(
    db: DBSession, appointment: Appointment, target_state: AppointmentState
) -> None:
    """Bind the design's side effects to the transition being applied.

    * ``* -> cancelled`` returns the slot to available (R8.7, R8.8).
    * ``* -> completed`` queues the appointment for clinician review (R10.5).
    """
    if target_state == AppointmentState.cancelled:
        _return_slot_to_available(db, appointment)
    elif target_state == AppointmentState.completed:
        _queue_for_review(appointment)


def transition(
    db: DBSession,
    appointment: Appointment,
    target_state: AppointmentState,
) -> TransitionResult:
    """Attempt to move ``appointment`` to ``target_state`` (R8.6-R8.10, R10.5).

    If ``current -> target_state`` is in the valid-transition allow-list, the
    appointment's state is updated, the bound side effects are applied, and a
    successful :class:`TransitionResult` is returned. Otherwise the transition
    is rejected: the current state is preserved unchanged and a result carrying
    :data:`INVALID_TRANSITION_MESSAGE` is returned (R8.9).

    The recorded state after this call is always exactly one of the four
    ``AppointmentState`` members (R8.10).

    ``target_state`` may be passed as an ``AppointmentState`` or its string
    value; an unrecognized value is treated as an invalid transition rather than
    raising, so a bad request can never corrupt the recorded state.
    """
    current = appointment.state

    # Coerce a string target to the enum; an unknown value is simply an invalid
    # transition (the current state is preserved, R8.9).
    if not isinstance(target_state, AppointmentState):
        try:
            target_state = AppointmentState(target_state)
        except ValueError:
            return TransitionResult(
                ok=False, state=current, message=INVALID_TRANSITION_MESSAGE
            )

    if not is_valid_transition(current, target_state):
        # Reject, preserve current state, return invalid-transition (R8.9).
        return TransitionResult(
            ok=False, state=current, message=INVALID_TRANSITION_MESSAGE
        )

    appointment.state = target_state
    _apply_side_effects(db, appointment, target_state)

    return TransitionResult(ok=True, state=target_state, message=None)


__all__ = [
    "VALID_TRANSITIONS",
    "INVALID_TRANSITION_MESSAGE",
    "TransitionResult",
    "is_valid_transition",
    "transition",
]
