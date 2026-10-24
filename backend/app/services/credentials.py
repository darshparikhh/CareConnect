"""Credential_Service: credential recording, verification, and the derived
Authorized_Services set (R5, R11.6, R13.2).

This service is the **single source of truth** for what a Volunteer is actually
authorized to do. The core of it is :func:`recompute_authorized_services`, a
pure function of a Volunteer's credentials and their conditions:

    A Service_Type belongs to a Volunteer's Authorized_Services **iff** some
    credential that authorizes it is verified AND every one of that credential's
    recorded conditions is satisfied AND (if an expiry is recorded) it has not
    expired.

Role alone never authorizes vaccines/specimen/tests — only an explicit, verified,
condition-satisfied credential does (R5.3). Everything that reads authorization
(the Matching_Engine, Appointment_Service) reads the reconciled
``AuthorizedService`` join rows this service maintains, so authorization can
never drift from the credential facts.

Operations
----------
* :func:`record_credential` — attach a declared credential to an owner as
  ``unverified`` (R5 baseline; a declared credential confers nothing yet).
* :func:`verify_credential` — flip a credential to ``verified`` recording the
  verifying authority and timestamp, then recompute the owner's set (R5.1, R5.7).
* :func:`revoke_or_expire` — flip a credential back to ``unverified`` and
  recompute, dropping any Service_Type no longer authorized by *any* remaining
  verified credential (R5.6, R5.7).
* :func:`recompute_authorized_services` — the pure derivation; reconciles the
  ``AuthorizedService`` join rows to exactly match the derived set (R5.2, R5.4,
  R5.6, R5.7).
* :func:`is_clinician_license_verified` — whether a Clinician's license
  credential is verified, gating clinical decisions/prescriptions (R5.5, R11.6,
  R13.2).
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Set, Union

from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.models.credential import (
    AuthorizedService,
    Credential,
    CredentialCondition,
    ServiceType,
)
from app.models.enums import VerificationStatus
from app.models.people import Clinician, Volunteer

# The credential type a Clinician's medical license is recorded under in the
# seed and Registration_Service. is_clinician_license_verified looks for a
# verified credential of this type.
CLINICIAN_LICENSE_TYPE = "medical_license"


class CredentialError(Exception):
    """Raised for invalid Credential_Service operations (e.g. unknown owner)."""


def _is_credential_effective(
    credential: Credential, *, now: Optional[datetime] = None
) -> bool:
    """Return True if ``credential`` currently confers its Service_Types.

    A credential is effective when, and only when, all three hold:

    * its status is ``verified`` (R5.1, R5.2),
    * every recorded condition is satisfied (R5.4), and
    * it has not passed a recorded ``expires_at`` (R5.6).

    This is the atomic predicate the pure derivation is built from. ``now`` is
    injectable so callers/tests can reason about expiry deterministically; it
    defaults to the current time.
    """
    if credential.status != VerificationStatus.verified:
        return False

    # Every recorded condition must be satisfied; any unmet one excludes it.
    for condition in credential.conditions:
        if not condition.satisfied:
            return False

    # A recorded expiry in the past makes the credential no longer effective.
    if credential.expires_at is not None:
        reference = now if now is not None else datetime.utcnow()
        if credential.expires_at <= reference:
            return False

    return True


def derive_authorized_service_types(
    volunteer: Volunteer, *, now: Optional[datetime] = None
) -> Set[int]:
    """Pure derivation: the set of Service_Type ids the Volunteer is authorized for.

    Depends only on the Volunteer's credentials and their conditions (and, for
    expiry, ``now``). No database writes, no side effects — this is the single
    source of truth the reconciliation step and callers build on (R5.7).
    """
    authorized: Set[int] = set()
    for credential in volunteer.credentials:
        if not _is_credential_effective(credential, now=now):
            continue
        for service_type in credential.authorizes_service_types:
            authorized.add(service_type.id)
    return authorized


def recompute_authorized_services(
    session: DBSession, volunteer: Volunteer, *, now: Optional[datetime] = None
) -> List[ServiceType]:
    """Recompute and persist ``volunteer``'s Authorized_Services (R5.2, R5.4-R5.7).

    Derives the authorized Service_Type ids purely from the Volunteer's
    credentials (see :func:`derive_authorized_service_types`) and reconciles the
    ``AuthorizedService`` join rows to match exactly: inserts any newly-earned
    Service_Type and deletes any that no credential still confers (e.g. after a
    revocation or an unmet condition). Returns the resulting list of authorized
    :class:`ServiceType` objects.

    The reconciliation is idempotent: calling it repeatedly with unchanged
    credentials produces the same join rows.
    """
    desired_ids = derive_authorized_service_types(volunteer, now=now)

    existing_rows = (
        session.execute(
            select(AuthorizedService).where(
                AuthorizedService.volunteer_id == volunteer.id
            )
        )
        .scalars()
        .all()
    )
    existing_ids = {row.service_type_id for row in existing_rows}

    # Remove rows no longer backed by any effective credential (R5.6).
    for row in existing_rows:
        if row.service_type_id not in desired_ids:
            session.delete(row)

    # Add rows for newly-authorized Service_Types (R5.1).
    for service_type_id in desired_ids - existing_ids:
        session.add(
            AuthorizedService(
                volunteer_id=volunteer.id, service_type_id=service_type_id
            )
        )

    session.flush()

    if not desired_ids:
        return []
    return list(
        session.execute(
            select(ServiceType).where(ServiceType.id.in_(desired_ids))
        )
        .scalars()
        .all()
    )


def record_credential(
    session: DBSession,
    owner: Union[Volunteer, Clinician],
    credential: Credential,
) -> Credential:
    """Attach a declared ``credential`` to ``owner`` as unverified (R5 baseline).

    A newly declared credential confers nothing until verified: its status is
    forced to ``unverified``. The credential is linked to the correct owner
    (Volunteer or Clinician) and persisted. Because it is unverified, there is
    no change to any Authorized_Services, so no recompute is needed here.
    """
    credential.status = VerificationStatus.unverified

    if isinstance(owner, Volunteer):
        credential.volunteer_id = owner.id
        credential.clinician_id = None
    elif isinstance(owner, Clinician):
        credential.clinician_id = owner.id
        credential.volunteer_id = None
    else:  # pragma: no cover - defensive
        raise CredentialError("owner must be a Volunteer or a Clinician")

    session.add(credential)
    session.flush()
    return credential


def verify_credential(
    session: DBSession,
    credential: Credential,
    authority: str,
    timestamp: Optional[datetime] = None,
    *,
    now: Optional[datetime] = None,
) -> Credential:
    """Mark ``credential`` verified and recompute the owner's set (R5.1, R5.7).

    Records the verifying ``authority`` and the verification ``timestamp``
    (defaulting to the current time), flips status to ``verified``, and — if the
    credential is a Volunteer's — recomputes that Volunteer's Authorized_Services
    so every Service_Type the now-verified credential confers is added (subject
    to all conditions being satisfied and no expiry). A Clinician license has no
    Authorized_Services to recompute; verification simply unblocks clinical
    decisions via :func:`is_clinician_license_verified`.
    """
    credential.status = VerificationStatus.verified
    credential.verifying_authority = authority
    credential.verified_at = timestamp if timestamp is not None else datetime.utcnow()
    session.add(credential)
    session.flush()

    if credential.volunteer is not None:
        recompute_authorized_services(session, credential.volunteer, now=now)

    return credential


def revoke_or_expire(
    session: DBSession,
    credential: Credential,
    *,
    now: Optional[datetime] = None,
) -> Credential:
    """Revoke/expire ``credential``: flip to unverified and recompute (R5.6, R5.7).

    Sets the credential's status back to ``unverified`` and, for a Volunteer's
    credential, recomputes the Authorized_Services. Any Service_Type that was
    authorized *only* by this credential is removed; a Service_Type still
    conferred by another effective credential is retained, because the pure
    derivation reconsiders every credential the Volunteer holds.
    """
    credential.status = VerificationStatus.unverified
    session.add(credential)
    session.flush()

    if credential.volunteer is not None:
        recompute_authorized_services(session, credential.volunteer, now=now)

    return credential


def is_clinician_license_verified(clinician: Clinician) -> bool:
    """Return True if ``clinician`` holds a verified license credential (R5.5).

    Gates the recording/approval of Clinical_Decisions and the creation of
    medication prescriptions (R11.6, R13.2): an unverified (or missing) license
    returns False so callers reject those actions with a credential-not-verified
    indication.
    """
    for credential in clinician.credentials:
        if (
            credential.type == CLINICIAN_LICENSE_TYPE
            and credential.status == VerificationStatus.verified
        ):
            return True
    return False


__all__ = [
    "CLINICIAN_LICENSE_TYPE",
    "CredentialError",
    "derive_authorized_service_types",
    "recompute_authorized_services",
    "record_credential",
    "verify_credential",
    "revoke_or_expire",
    "is_clinician_license_verified",
]
