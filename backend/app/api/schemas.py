"""Shared Pydantic v2 request/response models for the REST API.

These are the wire contracts the API layer speaks. They are deliberately thin:
they validate and shape JSON, then hand plain values to the services, which own
all business rules. Keeping schemas here (rather than inline per router) gives
the patient/volunteer/clinician route tasks (17.2-17.4) one place to reuse the
common shapes — a location, an insurance record, the error envelope — so every
route reports errors the same way.

Error envelope
--------------
The services return typed outcome objects (``FieldErrors``, ``AccountExists``,
``AuthenticationFailed``). The API maps each to an HTTP status and a small JSON
body with a stable ``message`` field, plus optional detail (e.g. the list of
missing fields). :class:`ErrorResponse` documents that envelope so the SPA
(task 18+) and the OpenAPI schema agree on the shape.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _as_naive_local(value):
    """Drop any timezone so a client-sent UTC ``Z`` time compares against the
    naive datetimes stored for availability slots. A tz-aware value is coerced
    to naive by dropping tzinfo (the wall-clock fields are kept as-is); a naive
    value passes through unchanged. Prevents the 500 the matching comparison
    throws on offset-aware vs naive datetimes.
    """
    from datetime import datetime as _dt
    if isinstance(value, _dt) and value.tzinfo is not None:
        return value.replace(tzinfo=None)
    return value


# ---------------------------------------------------------------------------
# Shared value objects
# ---------------------------------------------------------------------------
class Location(BaseModel):
    """A geographic point usable by both DS engines (R1.5, R2.4)."""

    lat: float = Field(..., description="Latitude in decimal degrees.")
    lng: float = Field(..., description="Longitude in decimal degrees.")


class InsuranceInput(BaseModel):
    """Patient insurance at registration; plan required, network optional."""

    plan: str = Field(..., description="Insurance plan name.")
    network: Optional[str] = Field(
        default=None, description="Optional network/tier identifier."
    )


class CredentialConditionInput(BaseModel):
    """A declared condition on a credential (state/training/supervision)."""

    kind: str = Field(..., description="Condition identifier, e.g. state_license_MA.")
    satisfied: bool = Field(
        default=False, description="Whether the condition is currently satisfied."
    )


class DeclaredCredentialInput(BaseModel):
    """A credential a volunteer declares at registration (recorded unverified)."""

    type: str = Field(..., description="Credential type, e.g. vaccination_certification.")
    service_types: List[str] = Field(
        default_factory=list,
        description="Service_Type names this credential claims to authorize.",
    )
    conditions: List[CredentialConditionInput] = Field(
        default_factory=list,
        description="Declared conditions attached to the credential.",
    )


# ---------------------------------------------------------------------------
# Error envelope
# ---------------------------------------------------------------------------
class ErrorResponse(BaseModel):
    """The uniform error body every route returns on a rejected request.

    ``message`` is a stable machine-readable code (e.g. ``authentication-failed``,
    ``account-already-exists``); ``missing_fields`` is populated for validation
    rejections so the client can highlight every missing field at once.
    """

    message: str
    missing_fields: Optional[List[str]] = None
    redirect: Optional[str] = None


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
class SignInRequest(BaseModel):
    """Credentials submitted at sign-in (R4.1, R4.2)."""

    email: str = Field(..., description="Account email.")
    password: str = Field(..., description="Account password.")


class SessionResponse(BaseModel):
    """The established session returned on successful sign-in (R4.1).

    Carries the signed session token the client replays on every subsequent
    request, plus the resolved identity so the SPA can route to the right
    role-scoped dashboard without decoding the token.
    """

    token: str = Field(..., description="Signed session token (Bearer).")
    role: str = Field(..., description="Account role: patient | volunteer | clinician.")
    subject_id: int = Field(..., description="The authenticated account's id.")


# ---------------------------------------------------------------------------
# Registration requests
# ---------------------------------------------------------------------------
class PatientRegistrationRequest(BaseModel):
    """Patient sign-up payload (R1.1).

    All fields are modeled as present-or-null so a *missing* field reaches the
    Registration_Service as ``None`` and is reported by name (R1.2), rather than
    being rejected by schema validation with a generic 422. This keeps the
    "name each missing required field" behaviour owned by the service.
    """

    model_config = ConfigDict(extra="ignore")

    email: Optional[str] = None
    password: Optional[str] = None
    location: Optional[Location] = None
    insurance: Optional[InsuranceInput] = None
    needs: Optional[str] = None
    pcp: Optional[str] = Field(default=None, description="Primary care physician.")
    consent: bool = Field(
        default=False, description="Patient consent to participate (R20.4)."
    )


class VolunteerRegistrationRequest(BaseModel):
    """Volunteer sign-up payload (R2.1).

    Declared credentials are optional at registration and are recorded as
    unverified by the Credential_Service (R2.2).
    """

    model_config = ConfigDict(extra="ignore")

    email: Optional[str] = None
    password: Optional[str] = None
    location: Optional[Location] = None
    declared_credentials: List[DeclaredCredentialInput] = Field(default_factory=list)


class ClinicianRegistrationRequest(BaseModel):
    """Clinician sign-up payload (R3.1).

    ``license_info`` accepts either a free-text license string or an object; both
    are recorded as an unverified license credential (R3.2).
    """

    model_config = ConfigDict(extra="ignore")

    email: Optional[str] = None
    password: Optional[str] = None
    license_info: Optional[Union[str, Dict[str, Any]]] = None


# ---------------------------------------------------------------------------
# Registration responses
# ---------------------------------------------------------------------------
class AccountResponse(BaseModel):
    """The account created by a successful registration (201).

    A minimal projection of the new account — never the password hash — enough
    for the SPA to confirm creation and route the user to sign-in.
    """

    id: int
    email: str
    role: str


def to_account_response(account: Any) -> AccountResponse:
    """Project a Patient/Volunteer/Clinician ORM row into an AccountResponse."""
    role = account.role
    role_value = role.value if hasattr(role, "value") else str(role)
    return AccountResponse(id=account.id, email=account.email, role=role_value)


def location_to_dict(location: Optional[Location]) -> Optional[Dict[str, float]]:
    """Convert a validated ``Location`` to the dict the services expect."""
    if location is None:
        return None
    return {"lat": location.lat, "lng": location.lng}


def insurance_to_dict(
    insurance: Optional[InsuranceInput],
) -> Optional[Dict[str, Optional[str]]]:
    """Convert a validated ``InsuranceInput`` to the dict the services expect."""
    if insurance is None:
        return None
    return {"plan": insurance.plan, "network": insurance.network}


def declared_credentials_to_dicts(
    credentials: Sequence[DeclaredCredentialInput],
) -> List[Dict[str, Any]]:
    """Convert declared-credential models into the service's mapping form."""
    out: List[Dict[str, Any]] = []
    for cred in credentials:
        out.append(
            {
                "type": cred.type,
                "service_types": list(cred.service_types),
                "conditions": [
                    {"kind": c.kind, "satisfied": c.satisfied}
                    for c in cred.conditions
                ],
            }
        )
    return out


# ---------------------------------------------------------------------------
# Patient dashboard (task 17.2)
# ---------------------------------------------------------------------------
#
# These are the wire shapes for the five patient-facing routes: request a match,
# book a visit, list upcoming appointments, read approved decisions/referrals,
# read approved medications, and get ranked doctor recommendations. They stay
# thin — validate JSON, hand plain values to the engines/services, and project
# ORM rows back out — so the Patient_Dashboard (task 19) and OpenAPI agree on
# the contract.


class MatchRequest(BaseModel):
    """A Patient's request to rank authorized Volunteers (R7.1).

    ``service_type`` is the Service_Type name; ``start``/``end`` bound the full
    window the Patient wants covered (the Matching_Engine's ``ChosenTime``).
    ``weights`` optionally overrides the (proximity, availability, qualification)
    scoring weights; omitted → the engine defaults.
    """

    model_config = ConfigDict(extra="ignore")

    service_type: str = Field(..., description="Requested Service_Type name.")
    start: datetime = Field(..., description="Start of the chosen time window.")
    end: datetime = Field(..., description="End of the chosen time window.")

    @field_validator("start", "end")
    @classmethod
    def _strip_tz(cls, v):
        return _as_naive_local(v)
    weights: Optional[List[float]] = Field(
        default=None,
        description="Optional (w_prox, w_avail, w_qual) scoring weights.",
    )


class MatchCandidate(BaseModel):
    """One ranked Volunteer in a match result, with the evidence behind its rank."""

    volunteer_id: int
    slot_id: int
    volunteer_email: str = ""
    volunteer_name: str = ""
    score: float
    distance_km: float
    availability_count: int
    qualification_count: int


class MatchResponse(BaseModel):
    """The ranked candidate list plus the optional no-volunteers message (R7.6)."""

    service_type: str
    candidates: List[MatchCandidate] = Field(default_factory=list)
    message: Optional[str] = None


class BookRequest(BaseModel):
    """A Patient's request to book a specific Volunteer slot (R8.1).

    Identifies the chosen Volunteer, their available slot, and the requested
    Service_Type by name. The Appointment_Service enforces the slot/authorization/
    consent gates.
    """

    model_config = ConfigDict(extra="ignore")

    volunteer_id: int = Field(..., description="The selected Volunteer's id.")
    slot_id: int = Field(..., description="The selected available slot's id.")
    service_type: str = Field(..., description="Requested Service_Type name.")
    requested_start: Optional[datetime] = Field(
        default=None, description="Start of the specific window the Patient chose."
    )
    requested_end: Optional[datetime] = Field(
        default=None, description="End of the specific window the Patient chose."
    )

    @field_validator("requested_start", "requested_end")
    @classmethod
    def _strip_tz(cls, v):
        return _as_naive_local(v)


class AppointmentResponse(BaseModel):
    """An appointment projected for the Patient, with its lifecycle state (R17.1)."""

    id: int
    volunteer_id: int
    service_type: str
    state: str
    slot_start: Optional[datetime] = None
    slot_end: Optional[datetime] = None
    queued_for_review: bool
    reviewed: bool


class BookingResponse(BaseModel):
    """The confirmed booking returned on a successful book (R8.1, R8.2)."""

    appointment: AppointmentResponse
    message: str = "booking-confirmed"


class DecisionResponse(BaseModel):
    """An approved Clinical_Decision visible to the Patient (R11.9)."""

    id: int
    appointment_id: int
    content: str
    approved: bool


class ReferralResponse(BaseModel):
    """An approved Referral visible to the Patient (R11.9, R12)."""

    id: int
    appointment_id: int
    specialty: str


class MedicationResponse(BaseModel):
    """An approved, verified-prescribed Medication visible to the Patient (R13.1)."""

    id: int
    name: str
    approved: bool


class RecommendationRequest(BaseModel):
    """Optional scoring-weight override for the doctor recommendation (R16).

    Omitted or invalid weights fall back to the engine defaults with an advisory
    message (R16.8).
    """

    model_config = ConfigDict(extra="ignore")

    weights: Optional[List[float]] = Field(
        default=None,
        description="Optional (D, A, R, T) scoring weights.",
    )


class RecommendedDoctorResponse(BaseModel):
    """One ranked provider with the fields the dashboard shows (R16.1, R17.4).

    Carries proximity, specialty, and the insurance-compatibility status so the
    Patient_Dashboard can render exactly what R17.4 requires.
    """

    id: int
    name: str
    specialty: str
    rating: Optional[float] = None
    proximity_km: float
    score: float
    insurance_status: str


class RecommendationResponse(BaseModel):
    """The ranked doctor list plus engine advisories (R15.5/R15.6/R16.8)."""

    doctors: List[RecommendedDoctorResponse] = Field(default_factory=list)
    message: Optional[str] = None
    insurance_asserted: bool = False


class HospitalResponse(BaseModel):
    """A nearby MA hospital ranked by ZIP-code proximity to the patient.

    Projects a trimmed record from the locally bundled CMS dataset (see
    ``app/services/hospitals.py``). ``hospital_overall_rating`` is passed
    through verbatim (including ``"Not Available"``); ``zip_distance`` is the
    absolute numeric ZIP difference used for ranking (smaller is closer).
    """

    facility_name: str
    address: str
    citytown: str
    zip_code: str
    telephone_number: str
    hospital_type: str
    hospital_overall_rating: str
    zip_distance: int


__all__ = [
    "Location",
    "InsuranceInput",
    "CredentialConditionInput",
    "DeclaredCredentialInput",
    "ErrorResponse",
    "SignInRequest",
    "SessionResponse",
    "PatientRegistrationRequest",
    "VolunteerRegistrationRequest",
    "ClinicianRegistrationRequest",
    "AccountResponse",
    "to_account_response",
    "location_to_dict",
    "insurance_to_dict",
    "declared_credentials_to_dicts",
    "MatchRequest",
    "MatchCandidate",
    "MatchResponse",
    "BookRequest",
    "AppointmentResponse",
    "BookingResponse",
    "DecisionResponse",
    "ReferralResponse",
    "MedicationResponse",
    "RecommendationRequest",
    "RecommendedDoctorResponse",
    "RecommendationResponse",
    "HospitalResponse",
    "SlotCreateRequest",
    "SlotResponse",
    "VolunteerAppointmentResponse",
    "ServiceTypeSummary",
    "VisitDetailResponse",
    "QuestionnaireSubmission",
    "TestResultSubmission",
    "SubmissionResponse",
]


# ---------------------------------------------------------------------------
# Volunteer dashboard (task 17.3)
# ---------------------------------------------------------------------------
#
# Wire shapes for the volunteer-facing routes: manage availability slots,
# list assigned appointments with their lifecycle states, accept/decline an
# assigned appointment, open an assigned visit's detail, and submit a
# questionnaire or a test result. They stay thin — validate JSON, hand plain
# values to the Availability/Appointment-state/Visit services, and project the
# typed results back out — so the Volunteer_Dashboard (R18) and OpenAPI agree
# on the contract.


class SlotCreateRequest(BaseModel):
    """A Volunteer offering a new availability slot (R6.1).

    ``start``/``end`` bound the bookable window. The slot is recorded as
    ``available`` and unassigned by the Availability_Service.
    """

    model_config = ConfigDict(extra="ignore")

    start: datetime = Field(..., description="Start of the availability window.")
    end: datetime = Field(..., description="End of the availability window.")


class SlotResponse(BaseModel):
    """An availability slot projected for the Volunteer (R6)."""

    id: int
    start: datetime
    end: datetime
    status: str


class VolunteerAppointmentResponse(BaseModel):
    """An appointment projected for the assigned Volunteer, with its state (R18).

    Mirrors the patient-facing shape but keyed to the Volunteer's view: it
    carries the Patient id instead of the Volunteer id, plus the lifecycle
    state and the review flags.
    """

    id: int
    patient_id: int
    service_type: str
    state: str
    slot_start: Optional[datetime] = None
    slot_end: Optional[datetime] = None
    queued_for_review: bool
    reviewed: bool


class ServiceTypeSummary(BaseModel):
    """A Service_Type projected into the visit-detail view (R9.1, R9.2)."""

    id: int
    name: str


class VisitDetailResponse(BaseModel):
    """What a Volunteer sees when opening an assigned appointment (R9.1, R9.2).

    ``requested_service_type`` is what the appointment was booked for;
    ``location`` is the visit location; ``authorized_services`` is **only** the
    Service_Types this Volunteer is currently authorized to perform — never the
    full catalog (R9.2).
    """

    requested_service_type: ServiceTypeSummary
    location: Location
    authorized_services: List[ServiceTypeSummary] = Field(default_factory=list)


class QuestionnaireSubmission(BaseModel):
    """Questionnaire answers submitted for an accepted, authorized visit (R10.1).

    ``answers`` maps question id -> answer value. The Visit_Service enforces the
    required-question, authorization, and state gates.
    """

    model_config = ConfigDict(extra="ignore")

    answers: Dict[str, Any] = Field(
        default_factory=dict, description="question_id -> answer value."
    )


class TestResultSubmission(BaseModel):
    """A single information-only Test_Result submitted for a visit (R10.3).

    ``measurement`` names the recorded measurement; ``value`` and ``unit`` are
    optional. Recorded as Synthetic_Data; never establishes treatment (R10.7).
    """

    model_config = ConfigDict(extra="ignore")

    measurement: str = Field(..., description="Measurement identifier.")
    value: Optional[float] = Field(default=None, description="Optional numeric value.")
    unit: Optional[str] = Field(default=None, description="Optional unit.")


class SubmissionResponse(BaseModel):
    """The outcome of a successful questionnaire/test submission (R10.1, R10.3, R10.5).

    ``completed`` is True when this submission completed the appointment's
    required data set and queued it for clinician review (R10.5).
    """

    ok: bool = True
    message: str
    completed: bool = False


# ---------------------------------------------------------------------------
# Clinician dashboard (task 17.4)
# ---------------------------------------------------------------------------
#
# Wire shapes for the clinician-facing routes that back the Clinician_Dashboard
# (R19): the review queue of completed-and-queued appointments, the findings
# view for one appointment, recording a clinical decision, approving it, and
# issuing a specialty referral. They stay thin — validate JSON and project the
# Review_Service's typed results back out — so the dashboard (task 21) and
# OpenAPI agree on the contract. Every backing route is gated to the Clinician
# role (R4.5, R20.2).


class ReviewQueueItem(BaseModel):
    """One completed appointment awaiting clinician review (R11.1, R19).

    The review queue lists appointments that are ``completed`` and still
    ``queued_for_review``; ``reviewed`` tells the dashboard which ones already
    carry a recorded decision.
    """

    appointment_id: int
    patient_id: int
    volunteer_id: int
    service_type: str
    state: str
    queued_for_review: bool
    reviewed: bool


class QuestionnaireFinding(BaseModel):
    """A questionnaire's recorded answers, projected for the findings view (R11.1)."""

    id: int
    service_type: str
    answers: Optional[str] = None


class TestResultFinding(BaseModel):
    """A recorded Test_Result, projected for the findings view (R11.1, R10.7)."""

    id: int
    measurement: str
    value: Optional[float] = None
    unit: Optional[str] = None


class FindingsResponse(BaseModel):
    """The findings opened for review on a completed appointment (R11.1).

    Carries the appointment's recorded questionnaire answers and Test_Results
    for display. Only reachable when the appointment is completed-and-queued;
    otherwise the route rejects with the not-ready-for-review message.
    """

    appointment_id: int
    questionnaires: List[QuestionnaireFinding] = Field(default_factory=list)
    test_results: List[TestResultFinding] = Field(default_factory=list)


class DecisionCreateRequest(BaseModel):
    """A clinician recording a Clinical_Decision for a queued appointment (R11.3).

    ``content`` must be non-empty; the Review_Service rejects empty content and
    an unverified license, persisting nothing in either case (R11.5, R11.6).
    """

    model_config = ConfigDict(extra="ignore")

    content: str = Field(..., description="The clinician's decision text.")


class ReferralCreateRequest(BaseModel):
    """A clinician issuing a specialty Referral from a reviewed decision (R12.1).

    ``specialty`` becomes the Patient's ``required_specialty`` so the
    Recommendation_Engine applies it as the hard specialty filter (R12.2).
    """

    model_config = ConfigDict(extra="ignore")

    specialty: str = Field(..., description="Recommended specialty for the referral.")


class ClinicianDecisionResponse(BaseModel):
    """A Clinical_Decision projected for the clinician's own view (R11.3, R11.9).

    Unlike the patient-facing shape this is not approval-gated: the deciding
    clinician sees the decision and its ``approved`` flag immediately after
    recording it, before approval makes it patient-visible.
    """

    id: int
    appointment_id: int
    content: str
    reviewed: bool
    approved: bool


class ClinicianReferralResponse(BaseModel):
    """A Referral projected for the clinician's own view (R12.1, R12.2)."""

    id: int
    appointment_id: int
    patient_id: int
    specialty: str


__all__ += [
    "ReviewQueueItem",
    "QuestionnaireFinding",
    "TestResultFinding",
    "FindingsResponse",
    "DecisionCreateRequest",
    "ReferralCreateRequest",
    "ClinicianDecisionResponse",
    "ClinicianReferralResponse",
]
