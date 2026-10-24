# Feature: careconnect, Property 1: Matching never returns an unauthorized volunteer
"""Property-based test for the Matching_Engine authorization hard filter (task 14.2).

Property 1 (design "Correctness Properties"):

    *For any* set of volunteers and any patient request for a Service_Type, every
    volunteer in the Matching_Engine result has that Service_Type in their
    credential-derived Authorized_Services, regardless of their score on any
    other factor.

**Validates: Requirements 7.1, 7.7**

The test generates a world of volunteers with *randomized* credentials — varied
verification status, condition satisfaction, expiry (past/future/none), and the
set of Service_Types each credential authorizes — plus randomized availability
slots, and a randomly chosen requested Service_Type and chosen-time window. It
then calls :func:`app.engines.matching.match` and asserts the hard invariant:

    every returned volunteer has the requested Service_Type in its
    credential-derived Authorized_Services (``derive_authorized_service_types``),

so no unauthorized volunteer ever appears regardless of proximity, availability,
qualification count, or final score.

Authorization is read from the single source of truth
(:func:`derive_authorized_service_types`) at the same ``now`` passed to
``match`` so expiry is evaluated identically on both sides.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import List

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import create_db_engine, init_db
from app.engines.matching import ChosenTime, match
from app.models.availability import AvailabilitySlot
from app.models.base import Base
from app.models.credential import (
    AuthorizedService,
    Credential,
    CredentialCondition,
    ServiceType,
)
from app.models.enums import Role, SlotStatus, VerificationStatus
from app.models.people import Patient, Volunteer
from app.services.credentials import derive_authorized_service_types

# A fixed reference instant so credential expiry and chosen-time windows are
# evaluated deterministically. ``match`` is called with ``now=_NOW``.
_NOW = datetime(2024, 6, 1, 12, 0, 0)

# The pool of Service_Types we seed once per database. Credentials authorize a
# random subset of these and the patient requests one of them.
_SERVICE_TYPE_NAMES = ("vaccination", "specimen_collection", "wellness_check")


# --- Hypothesis strategies for one randomized credential ------------------

# A single credential description: whether it is verified, whether every one of
# its conditions is satisfied, how its expiry sits relative to _NOW, and which
# Service_Types (by index into the seeded pool) it authorizes. The matrix of
# these covers the authorization predicate: only verified + all-conditions-
# satisfied + not-expired credentials should confer their Service_Types.
_credential_strategy = st.fixed_dictionaries(
    {
        "verified": st.booleans(),
        # Number of recorded conditions (0..3) and whether each is satisfied.
        "conditions": st.lists(st.booleans(), min_size=0, max_size=3),
        # Expiry relative to _NOW: none, already expired, or still valid.
        "expiry": st.sampled_from(("none", "past", "future")),
        # Which seeded Service_Types this credential authorizes (by index).
        "service_indexes": st.lists(
            st.integers(min_value=0, max_value=len(_SERVICE_TYPE_NAMES) - 1),
            min_size=0,
            max_size=len(_SERVICE_TYPE_NAMES),
            unique=True,
        ),
    }
)

# One volunteer: a location, a handful of randomized credentials, and a handful
# of availability slots (some of which may cover the chosen window, some not).
_volunteer_strategy = st.fixed_dictionaries(
    {
        "lat": st.floats(min_value=-80.0, max_value=80.0, allow_nan=False),
        "lng": st.floats(min_value=-170.0, max_value=170.0, allow_nan=False),
        "credentials": st.lists(_credential_strategy, min_size=0, max_size=3),
        # Each slot: start offset (hours from _NOW) and duration (hours).
        "slots": st.lists(
            st.fixed_dictionaries(
                {
                    "start_offset_h": st.integers(min_value=-12, max_value=12),
                    "duration_h": st.integers(min_value=1, max_value=8),
                    "available": st.booleans(),
                }
            ),
            min_size=0,
            max_size=3,
        ),
    }
)

_world_strategy = st.fixed_dictionaries(
    {
        "volunteers": st.lists(_volunteer_strategy, min_size=0, max_size=5),
        # Index of the requested Service_Type into the seeded pool.
        "requested_index": st.integers(
            min_value=0, max_value=len(_SERVICE_TYPE_NAMES) - 1
        ),
        # Chosen-time window: start offset (hours from _NOW) and duration.
        "chosen_start_offset_h": st.integers(min_value=-6, max_value=6),
        "chosen_duration_h": st.integers(min_value=1, max_value=4),
        # Patient location.
        "patient_lat": st.floats(min_value=-80.0, max_value=80.0, allow_nan=False),
        "patient_lng": st.floats(min_value=-170.0, max_value=170.0, allow_nan=False),
    }
)


# --- Per-module engine so hypothesis can drive many examples --------------


@pytest.fixture(scope="module")
def _engine() -> Engine:
    """A single in-memory SQLite engine reused across all hypothesis examples.

    Hypothesis runs the body many times; a module-scoped engine avoids rebuilding
    the schema per example. Each example wipes the mutable tables itself for
    isolation (see ``_reset``).
    """
    engine = create_db_engine("sqlite:///:memory:")
    init_db(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def _session_factory(_engine: Engine):
    return sessionmaker(
        bind=_engine, autoflush=False, expire_on_commit=False, future=True
    )


def _reset(session: Session) -> None:
    """Delete all mutable rows so each hypothesis example starts clean."""
    for model in (
        AuthorizedService,
        AvailabilitySlot,
        CredentialCondition,
        Credential,
        Patient,
        Volunteer,
        ServiceType,
    ):
        session.query(model).delete()
    session.flush()


def _seed_service_types(session: Session) -> List[ServiceType]:
    types = [ServiceType(name=name) for name in _SERVICE_TYPE_NAMES]
    session.add_all(types)
    session.flush()
    return types


def _build_credential(
    desc: dict, service_types: List[ServiceType]
) -> Credential:
    """Materialize one randomized credential from a strategy description."""
    if desc["expiry"] == "none":
        expires_at = None
    elif desc["expiry"] == "past":
        expires_at = _NOW - timedelta(days=1)
    else:  # future
        expires_at = _NOW + timedelta(days=30)

    credential = Credential(
        type="test_credential",
        status=(
            VerificationStatus.verified
            if desc["verified"]
            else VerificationStatus.unverified
        ),
        expires_at=expires_at,
    )
    credential.authorizes_service_types = [
        service_types[i] for i in desc["service_indexes"]
    ]
    credential.conditions = [
        CredentialCondition(kind=f"cond_{n}", satisfied=satisfied)
        for n, satisfied in enumerate(desc["conditions"])
    ]
    return credential


def _build_volunteer(
    session: Session, index: int, desc: dict, service_types: List[ServiceType]
) -> Volunteer:
    volunteer = Volunteer(
        email=f"vol{index}@example.com",
        password_hash="x",
        role=Role.volunteer,
        latitude=desc["lat"],
        longitude=desc["lng"],
    )
    volunteer.credentials = [
        _build_credential(cred_desc, service_types)
        for cred_desc in desc["credentials"]
    ]
    for slot_desc in desc["slots"]:
        start = _NOW + timedelta(hours=slot_desc["start_offset_h"])
        end = start + timedelta(hours=slot_desc["duration_h"])
        volunteer.availability_slots.append(
            AvailabilitySlot(
                start=start,
                end=end,
                status=(
                    SlotStatus.available
                    if slot_desc["available"]
                    else SlotStatus.unavailable
                ),
            )
        )
    session.add(volunteer)
    session.flush()
    return volunteer


@settings(
    max_examples=150,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(world=_world_strategy)
def test_matching_never_returns_unauthorized_volunteer(
    _session_factory, world: dict
) -> None:
    """Every matched volunteer is authorized for the requested Service_Type.

    Builds a randomized world, runs ``match`` with the shared ``_NOW``, and
    asserts the authorization hard invariant for every result — independent of
    whether the result set is empty, ranked, or full.
    """
    session: Session = _session_factory()
    try:
        _reset(session)
        service_types = _seed_service_types(session)

        for i, vol_desc in enumerate(world["volunteers"]):
            _build_volunteer(session, i, vol_desc, service_types)

        patient = Patient(
            email="patient@example.com",
            password_hash="x",
            role=Role.patient,
            latitude=world["patient_lat"],
            longitude=world["patient_lng"],
            consent_given=True,
        )
        session.add(patient)
        session.flush()

        requested = service_types[world["requested_index"]]
        chosen_start = _NOW + timedelta(hours=world["chosen_start_offset_h"])
        chosen = ChosenTime(
            start=chosen_start,
            end=chosen_start + timedelta(hours=world["chosen_duration_h"]),
        )

        results, _message = match(
            session, patient, requested, chosen, now=_NOW
        )

        for result in results:
            authorized_ids = derive_authorized_service_types(
                result.volunteer, now=_NOW
            )
            assert requested.id in authorized_ids, (
                "Matching returned a volunteer not authorized for the requested "
                f"Service_Type: volunteer id={result.volunteer.id}, "
                f"requested={requested.name}, authorized ids={authorized_ids}"
            )
    finally:
        session.rollback()
        session.close()
