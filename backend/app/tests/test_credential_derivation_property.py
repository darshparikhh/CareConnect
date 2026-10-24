"""Property-based test for authorized-service derivation (task 5.2).

# Feature: careconnect, Property 6: Authorized_Services reflect only verified,
# condition-satisfied credentials

*For any* set of a volunteer's credentials, a Service_Type is in the
volunteer's Authorized_Services if and only if some credential that authorizes
it is verified AND has all recorded conditions satisfied AND (if an expiry is
recorded) is not expired.

Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.6, 5.7

The test generates volunteers with randomized credentials — varying
verification status, satisfied/unsatisfied conditions, expiry, and which
service types each authorizes — and asserts:

* ``derive_authorized_service_types`` returns EXACTLY the set of Service_Type
  ids conferred by at least one credential that is verified, fully
  condition-satisfied, and unexpired (the independent oracle below);
* ``recompute_authorized_services`` reconciles the ``AuthorizedService`` join
  rows to match that same derived set; and
* ``recompute_authorized_services`` is idempotent.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterator, List, Set, Tuple

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.database import create_db_engine, init_db
from app.models.credential import (
    AuthorizedService,
    Credential,
    CredentialCondition,
    ServiceType,
)
from app.models.enums import Role, VerificationStatus
from app.models.people import Volunteer
from app.services.credentials import (
    derive_authorized_service_types,
    recompute_authorized_services,
)

# A fixed reference instant so expiry is deterministic across examples.
NOW = datetime(2025, 1, 1, 12, 0, 0)

# The pool of Service_Type ids a credential may authorize. Kept small so that
# credentials frequently overlap on service types, exercising the "authorized
# by at least one effective credential" (union) semantics.
SERVICE_TYPE_COUNT = 5


# --- generators ------------------------------------------------------------

# One credential spec: (is_verified, condition_satisfied_flags, expiry_choice,
# authorized_service_type_indices). expiry_choice is one of "none", "future",
# "past" to exercise the three expiry branches.
_condition_flags = st.lists(st.booleans(), min_size=0, max_size=4)
_expiry_choice = st.sampled_from(["none", "future", "past"])
_authorized_indices = st.sets(
    st.integers(min_value=0, max_value=SERVICE_TYPE_COUNT - 1),
    min_size=0,
    max_size=SERVICE_TYPE_COUNT,
)

_credential_spec = st.tuples(
    st.booleans(),
    _condition_flags,
    _expiry_choice,
    _authorized_indices,
)

# A volunteer: a list of credential specs (possibly empty).
_volunteer_spec = st.lists(_credential_spec, min_size=0, max_size=6)


def _expires_at(choice: str):
    if choice == "none":
        return None
    if choice == "future":
        return NOW + timedelta(days=30)
    return NOW - timedelta(days=1)  # past -> expired


def _spec_is_effective(spec) -> bool:
    """Independent oracle: does this credential spec currently confer services?"""
    is_verified, condition_flags, expiry_choice, _indices = spec
    if not is_verified:
        return False
    if not all(condition_flags):
        return False
    if expiry_choice == "past":
        return False
    return True


# --- database helpers ------------------------------------------------------


@pytest.fixture()
def engine() -> Iterator[Engine]:
    """A fresh in-memory engine reused across all hypothesis examples.

    Each example builds and tears down its own volunteer/credentials inside a
    rolled-back transaction, so a single engine is safe and fast.
    """
    eng = create_db_engine("sqlite:///:memory:")
    init_db(bind=eng)
    try:
        yield eng
    finally:
        eng.dispose()


def _build_volunteer(
    session: Session, service_types: List[ServiceType], volunteer_spec
) -> Tuple[Volunteer, Set[int]]:
    """Persist a volunteer with the given credential specs.

    Returns the volunteer and the independently-computed expected set of
    authorized Service_Type ids (the oracle).
    """
    volunteer = Volunteer(
        email="vol@example.com",
        password_hash="x",
        role=Role.volunteer,
        latitude=42.0,
        longitude=-71.0,
    )
    session.add(volunteer)
    session.flush()

    expected: Set[int] = set()
    for i, spec in enumerate(volunteer_spec):
        is_verified, condition_flags, expiry_choice, indices = spec
        credential = Credential(
            type=f"cred-{i}",
            volunteer_id=volunteer.id,
            status=(
                VerificationStatus.verified
                if is_verified
                else VerificationStatus.unverified
            ),
            expires_at=_expires_at(expiry_choice),
        )
        credential.authorizes_service_types = [service_types[j] for j in indices]
        credential.conditions = [
            CredentialCondition(kind=f"cond-{k}", satisfied=flag)
            for k, flag in enumerate(condition_flags)
        ]
        session.add(credential)

        if _spec_is_effective(spec):
            expected.update(service_types[j].id for j in indices)

    session.flush()
    session.refresh(volunteer)
    return volunteer, expected


@given(volunteer_spec=_volunteer_spec)
@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_authorized_services_reflect_only_effective_credentials(
    engine: Engine, volunteer_spec
) -> None:
    # Feature: careconnect, Property 6: Authorized_Services reflect only
    # verified, condition-satisfied credentials.
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    session = factory()
    try:
        service_types = [
            ServiceType(name=f"service-{i}") for i in range(SERVICE_TYPE_COUNT)
        ]
        session.add_all(service_types)
        session.flush()

        volunteer, expected = _build_volunteer(session, service_types, volunteer_spec)

        # (1) Pure derivation equals the independent oracle EXACTLY.
        derived = derive_authorized_service_types(volunteer, now=NOW)
        assert derived == expected

        # (2) recompute reconciles the join rows to match the derivation.
        recompute_authorized_services(session, volunteer, now=NOW)
        join_ids = set(
            session.execute(
                select(AuthorizedService.service_type_id).where(
                    AuthorizedService.volunteer_id == volunteer.id
                )
            ).scalars()
        )
        assert join_ids == expected

        # (3) recompute is idempotent: a second call leaves the join unchanged.
        recompute_authorized_services(session, volunteer, now=NOW)
        join_ids_again = set(
            session.execute(
                select(AuthorizedService.service_type_id).where(
                    AuthorizedService.volunteer_id == volunteer.id
                )
            ).scalars()
        )
        assert join_ids_again == expected
    finally:
        session.rollback()
        session.close()
