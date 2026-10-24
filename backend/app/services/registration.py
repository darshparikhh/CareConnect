"""Registration_Service: create Patient, Volunteer, and Clinician accounts.

Implements the design's ``Registration_Service`` (R1, R2, R3, R20.1, R20.4):

* :func:`register_patient` creates a Patient with its location (lat/lng),
  insurance record, declared needs, primary care physician, and recorded
  consent (R1.1, R1.4, R1.5, R20.4).
* :func:`register_volunteer` creates a Volunteer with its location and records
  each declared credential with an **unverified** status (R2.1, R2.2, R2.4).
* :func:`register_clinician` creates a Clinician and records its license as an
  **unverified** credential (R3.1, R3.2).

Shared rules across all three:

* Missing required fields are rejected by **naming each** missing field
  (R1.2, R2.3, R3.3) via :class:`FieldErrors`.
* A duplicate email — checked across *all three* account tables, matching the
  Auth_Service assumption that one email is one account — is rejected with an
  account-already-exists error (R1.3) via :class:`AccountExists`.
* Passwords are hashed with :func:`app.security.hash_password`, the same
  primitive the Auth_Service verifies against at sign-in, so a password hashed
  here always verifies there.
* All records are Synthetic_Data for the hackathon (R20.1); no real PII.

Credential recording stays loosely coupled to the Credential_Service: if
``app.services.credentials.record_credential`` exists (task 5.1) we delegate to
it so there is a single place credentials are born; otherwise we create the
``Credential`` row directly with ``status=unverified``. Either path yields an
unverified credential, which is all registration promises (R2.2, R3.2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.models.credential import (
    Credential,
    CredentialCondition,
    ServiceType,
)
from app.models.enums import Role, VerificationStatus
from app.models.insurance import InsuranceRecord
from app.models.people import Clinician, Patient, Volunteer
from app.security import hash_password


# ---------------------------------------------------------------------------
# Result / error types
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class FieldErrors:
    """Rejection naming each missing required field (R1.2, R2.3, R3.3).

    ``missing_fields`` lists every absent required field (not just the first),
    so the caller can show the user a complete list in one pass. ``message`` is
    a human-readable summary that also names each field.
    """

    missing_fields: Sequence[str]
    message: str = ""

    def __post_init__(self) -> None:
        if not self.message:
            joined = ", ".join(self.missing_fields)
            object.__setattr__(
                self, "message", "missing required fields: " + joined
            )

    @property
    def ok(self) -> bool:
        return False


@dataclass(frozen=True)
class AccountExists:
    """Rejection for an email already tied to an existing account (R1.3)."""

    email: str
    message: str = "account-already-exists"

    @property
    def ok(self) -> bool:
        return False


# A registration either produces an account row or one of the rejection types.
RegistrationResult = Union[Patient, Volunteer, Clinician, FieldErrors, AccountExists]


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------
def _is_blank(value: Any) -> bool:
    """Treat ``None`` and empty/whitespace-only strings as missing.

    Numbers (e.g. a latitude of ``0.0``) are never blank; only absent values
    and empty strings count as missing so a valid ``0`` coordinate is accepted.
    """
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    return False


def _collect_missing(fields: Mapping[str, Any]) -> List[str]:
    """Return the names of every required field that is blank, in order."""
    return [name for name, value in fields.items() if _is_blank(value)]


def _normalize_email(email: Any) -> str:
    """Lower-case and strip an email the same way Auth_Service does on lookup."""
    if not isinstance(email, str):
        return ""
    return email.strip().lower()


def _email_in_use(db: DBSession, email: str) -> bool:
    """True if ``email`` already exists in any of the three account tables.

    Mirrors Auth_Service's single-account-per-email assumption: an email is in
    use if it appears as a Patient, Volunteer, or Clinician.
    """
    for model in (Patient, Volunteer, Clinician):
        existing = db.execute(
            select(model.id).where(model.email == email)
        ).first()
        if existing is not None:
            return True
    return False


def _coerce_location(location: Any) -> Optional[Dict[str, float]]:
    """Parse a ``location`` input into ``{"lat": ..., "lng": ...}`` or None.

    Accepts a mapping with ``lat``/``lng`` (or ``latitude``/``longitude``) keys
    or a 2-sequence ``(lat, lng)``. Returns ``None`` when the location is
    absent or cannot be parsed into two finite numbers, so the caller reports a
    missing ``location`` field (R1.5, R2.4).
    """
    if location is None:
        return None
    lat: Any
    lng: Any
    if isinstance(location, Mapping):
        lat = location.get("lat", location.get("latitude"))
        lng = location.get("lng", location.get("longitude"))
    elif isinstance(location, Sequence) and not isinstance(location, (str, bytes)):
        if len(location) != 2:
            return None
        lat, lng = location[0], location[1]
    else:
        return None
    if _is_blank(lat) or _is_blank(lng):
        return None
    try:
        return {"lat": float(lat), "lng": float(lng)}
    except (TypeError, ValueError):
        return None


def _coerce_insurance(insurance: Any) -> Optional[Dict[str, Optional[str]]]:
    """Parse ``insurance`` into ``{"plan": ..., "network": ...}`` or None.

    A plan name is required; network is optional. Returns ``None`` when the
    insurance is absent or carries no plan, so the caller reports a missing
    ``insurance`` field (R1.1).
    """
    if insurance is None:
        return None
    if isinstance(insurance, str):
        plan: Any = insurance
        network: Any = None
    elif isinstance(insurance, Mapping):
        plan = insurance.get("plan")
        network = insurance.get("network")
    else:
        return None
    if _is_blank(plan):
        return None
    net = None if _is_blank(network) else str(network)
    return {"plan": str(plan), "network": net}


# ---------------------------------------------------------------------------
# Credential recording (loosely coupled to Credential_Service)
# ---------------------------------------------------------------------------
def _resolve_service_types(
    db: DBSession, names: Sequence[str]
) -> List[ServiceType]:
    """Resolve declared Service_Type names to existing rows (unknown ignored).

    A declared credential may name the services it claims to authorize; we link
    only to Service_Types that already exist in the catalog. Unknown names are
    ignored rather than fatal — registration records the *declaration*, and a
    credential confers nothing until Credential_Service verifies it (R2.2).
    """
    wanted = [n for n in names if not _is_blank(n)]
    if not wanted:
        return []
    rows = db.execute(
        select(ServiceType).where(ServiceType.name.in_(wanted))
    ).scalars().all()
    return list(rows)


def _build_credential(db: DBSession, declared: Mapping[str, Any]) -> Credential:
    """Build one **unverified** ``Credential`` from a declared-credential dict.

    Recognized keys: ``type`` (required; defaults to ``"credential"`` if
    blank), ``service_types`` (list of Service_Type names to link), and
    ``conditions`` (list of ``{"kind": ..., "satisfied": bool}``). The status is
    always ``unverified`` at registration — verification is Credential_Service's
    job (R2.2, R3.2).
    """
    cred_type = declared.get("type")
    credential = Credential(
        type=str(cred_type) if not _is_blank(cred_type) else "credential",
        status=VerificationStatus.unverified,
    )

    service_names = declared.get("service_types") or declared.get("authorizes") or []
    if isinstance(service_names, str):
        service_names = [service_names]
    for service_type in _resolve_service_types(db, list(service_names)):
        credential.authorizes_service_types.append(service_type)

    for cond in declared.get("conditions") or []:
        if isinstance(cond, Mapping):
            kind = cond.get("kind")
            satisfied = bool(cond.get("satisfied", False))
        else:
            kind = cond
            satisfied = False
        if not _is_blank(kind):
            credential.conditions.append(
                CredentialCondition(kind=str(kind), satisfied=satisfied)
            )
    return credential


def _record_credentials(
    db: DBSession,
    owner: Union[Volunteer, Clinician],
    declared_credentials: Sequence[Mapping[str, Any]],
) -> None:
    """Attach each declared credential to ``owner`` as unverified.

    Delegates to ``Credential_Service.record_credential`` when that module is
    available (task 5.1), so there is a single birthplace for credentials;
    otherwise falls back to attaching a locally-built unverified credential.
    Either way the credential ends up unverified and owned by ``owner``.
    """
    record_credential = _try_import_record_credential()
    for declared in declared_credentials:
        if not isinstance(declared, Mapping):
            continue
        credential = _build_credential(db, declared)
        if record_credential is not None:
            # Let the Credential_Service own persistence/recompute if present.
            record_credential(db, owner, credential)
        else:
            if isinstance(owner, Volunteer):
                owner.credentials.append(credential)
            else:
                owner.credentials.append(credential)


def _try_import_record_credential():
    """Return ``Credential_Service.record_credential`` if it exists, else None.

    Imported lazily so Registration_Service does not hard-depend on the
    parallel task's module. Any import/attribute error means "not available
    yet", and we fall back to creating credentials directly.
    """
    try:  # pragma: no cover - exercised only once the parallel task lands
        from app.services import credentials as credential_service
    except Exception:
        return None
    return getattr(credential_service, "record_credential", None)


# ---------------------------------------------------------------------------
# Public registration operations
# ---------------------------------------------------------------------------
def register_patient(
    db: DBSession,
    *,
    email: Any,
    password: Any,
    location: Any,
    insurance: Any,
    needs: Any,
    pcp: Any,
    consent: Any,
) -> RegistrationResult:
    """Create a Patient account (R1).

    Required fields: email, password, location (lat/lng), insurance (plan),
    needs, and primary care physician. Each missing field is named (R1.2).
    A duplicate email is rejected (R1.3). The location is stored as lat/lng
    (R1.5) and the patient's consent is recorded at creation (R20.4). The
    patient's insurance record starts ``unverified`` (R14.1) for the
    Insurance_Service to verify later. All records are Synthetic_Data (R20.1).
    """
    parsed_location = _coerce_location(location)
    parsed_insurance = _coerce_insurance(insurance)

    missing = _collect_missing(
        {
            "email": email,
            "password": password,
            # Report the *input* so a malformed location/insurance that parses
            # to None is surfaced as a missing field by name.
            "location": None if parsed_location is None else "ok",
            "insurance": None if parsed_insurance is None else "ok",
            "needs": needs,
            "pcp": pcp,
        }
    )
    # Consent must be explicitly granted at creation (R20.4). A missing or
    # falsey consent is reported as the "consent" field being required.
    if not bool(consent):
        missing.append("consent")
    if missing:
        return FieldErrors(missing_fields=missing)

    normalized_email = _normalize_email(email)
    if _email_in_use(db, normalized_email):
        return AccountExists(email=normalized_email)

    patient = Patient(
        email=normalized_email,
        password_hash=hash_password(str(password)),
        role=Role.patient,
        latitude=parsed_location["lat"],
        longitude=parsed_location["lng"],
        needs=str(needs),
        pcp=str(pcp),
        consent_given=True,
    )
    # New-patient insurance always starts unverified (R14.1).
    patient.insurance_record = InsuranceRecord(
        plan=parsed_insurance["plan"],
        network=parsed_insurance["network"],
        verification_status=VerificationStatus.unverified,
    )

    db.add(patient)
    db.flush()
    return patient


def register_volunteer(
    db: DBSession,
    *,
    email: Any,
    password: Any,
    location: Any,
    declared_credentials: Optional[Sequence[Mapping[str, Any]]] = None,
) -> RegistrationResult:
    """Create a Volunteer account and record declared credentials (R2).

    Required fields: email, password, and location (lat/lng); each missing
    field is named (R2.3). A duplicate email is rejected (R1.3 applied across
    roles). Location is stored as lat/lng usable by the Matching_Engine (R2.4).
    Each declared credential is recorded as **unverified** (R2.2). All records
    are Synthetic_Data (R20.1).
    """
    parsed_location = _coerce_location(location)

    missing = _collect_missing(
        {
            "email": email,
            "password": password,
            "location": None if parsed_location is None else "ok",
        }
    )
    if missing:
        return FieldErrors(missing_fields=missing)

    normalized_email = _normalize_email(email)
    if _email_in_use(db, normalized_email):
        return AccountExists(email=normalized_email)

    volunteer = Volunteer(
        email=normalized_email,
        password_hash=hash_password(str(password)),
        role=Role.volunteer,
        latitude=parsed_location["lat"],
        longitude=parsed_location["lng"],
    )
    db.add(volunteer)
    db.flush()

    _record_credentials(db, volunteer, list(declared_credentials or []))
    db.flush()
    return volunteer


def register_clinician(
    db: DBSession,
    *,
    email: Any,
    password: Any,
    license_info: Any,
) -> RegistrationResult:
    """Create a Clinician account with an unverified license credential (R3).

    Required fields: email, password, and license information; each missing
    field is named (R3.3). A duplicate email is rejected (R1.3 applied across
    roles). The license is recorded as an **unverified** credential (R3.2) so
    the Clinician cannot record decisions until Credential_Service verifies it
    (R5.5). All records are Synthetic_Data (R20.1).
    """
    missing = _collect_missing(
        {
            "email": email,
            "password": password,
            "license_info": license_info,
        }
    )
    if missing:
        return FieldErrors(missing_fields=missing)

    normalized_email = _normalize_email(email)
    if _email_in_use(db, normalized_email):
        return AccountExists(email=normalized_email)

    clinician = Clinician(
        email=normalized_email,
        password_hash=hash_password(str(password)),
        role=Role.clinician,
    )
    db.add(clinician)
    db.flush()

    # Normalize the license input into a declared-credential dict so it flows
    # through the same unverified-credential recording path.
    if isinstance(license_info, Mapping):
        declared = dict(license_info)
        declared.setdefault("type", "clinician_license")
    else:
        declared = {"type": "clinician_license", "license": str(license_info)}
    _record_credentials(db, clinician, [declared])
    db.flush()
    return clinician


__all__ = [
    "FieldErrors",
    "AccountExists",
    "RegistrationResult",
    "register_patient",
    "register_volunteer",
    "register_clinician",
]
