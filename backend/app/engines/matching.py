"""Matching_Engine (R7) — DS Component 1.

Ranks qualified Volunteers for a Patient's requested Service_Type at a chosen
time. This is a **pure, deterministic function** over data read from the
database: the Volunteer's credential-derived Authorized_Services, their
availability slots, and the Patient/Volunteer locations. Given the same inputs
it always produces the same ordered output, which makes it unit- and
property-testable (tasks 14.2-14.6).

Pipeline (design "Data Science Component 1: Matching_Engine"):

1. **Hard Filter 1 — Authorization (R7.1, R7.7).** Include a Volunteer only if
   the requested Service_Type is in that Volunteer's current Authorized_Services.
   Authorization is read from :func:`derive_authorized_service_types`, the single
   source of truth derived only from verified, condition-satisfied credentials,
   so an unauthorized Volunteer can never appear regardless of any other factor.
2. **Hard Filter 2 — Availability (R7.2).** Include a Volunteer only if they have
   an ``available`` slot that covers the **full duration** of the chosen time
   (``slot.start <= chosen.start AND slot.end >= chosen.end``).
3. **Empty result (R7.6).** If the candidate set is empty after the hard filters,
   return an empty list plus a "no qualified volunteers are available" message.
4. **Feature extraction + normalization (R7.3).** For each candidate extract
   three raw features — proximity (haversine km), availability (count of
   available slots), and qualification (count of effective verified credentials
   covering the service). Min-max normalize each to ``[0, 1]`` with **1.0 most
   favorable** (proximity inverted since nearer is better). Degenerate case: when
   every candidate shares a feature value, that feature is ``1.0`` for all (this
   also avoids divide-by-zero).
5. **Weighted score (R7.3, R7.4).** ``score = w_prox*D + w_avail*A + w_qual*Q``
   with defaults ``0.5 / 0.3 / 0.2``.
6. **Sort + deterministic tie-break (R7.4, R7.5).** Order by descending score;
   break ties by higher qualification, then nearer proximity, then earliest
   available covering slot.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import List, NamedTuple, Optional, Sequence, Tuple

from sqlalchemy.orm import Session as DBSession

from app.models.availability import AvailabilitySlot
from app.models.credential import ServiceType
from app.models.people import Patient, Volunteer
from app.services.availability import slots_for_matching
from app.services.credentials import (
    _is_credential_effective,
    derive_authorized_service_types,
)

# Earth mean radius in kilometres for the haversine formula.
_EARTH_RADIUS_KM = 6371.0

# Stable message surfaced when no Volunteer satisfies both hard filters (R7.6).
NO_QUALIFIED_VOLUNTEERS = "no qualified volunteers are available"


class MatchWeights(NamedTuple):
    """Scoring weights for the three matching features.

    Defaults ``0.5 / 0.3 / 0.2`` keep nearer and more-available Volunteers higher
    (design "Weighted score and ranking"). Weights are applied as-is; the
    Matching_Engine does not re-validate/normalize them (that is a
    Recommendation_Engine concern, R16.7/R16.8).
    """

    w_prox: float = 0.5
    w_avail: float = 0.3
    w_qual: float = 0.2


DEFAULT_WEIGHTS = MatchWeights()


class ChosenTime(NamedTuple):
    """The window the Patient wants covered (the full requested duration)."""

    start: datetime
    end: datetime


@dataclass(frozen=True)
class MatchResult:
    """One ranked Volunteer and the evidence behind its rank.

    Carries both the raw features and their normalized values so callers/tests
    can inspect exactly why a Volunteer ranks where it does. ``volunteer`` is the
    ORM object; the scalar fields are plain numbers so the result is easy to
    assert on without touching the session.
    """

    volunteer: Volunteer
    score: float
    # Raw (pre-normalization) features.
    distance_km: float
    availability_count: int
    qualification_count: int
    # Normalized features in [0, 1], 1.0 == most favorable.
    proximity_norm: float
    availability_norm: float
    qualification_norm: float
    # Earliest available slot covering the chosen window (tie-break input).
    earliest_slot_start: datetime
    # Id of that earliest covering slot, so callers can book the exact slot the
    # match was computed against (prevents booking a wrong/nonexistent slot).
    slot_id: int


def haversine_km(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """Great-circle distance in kilometres between two lat/long points.

    Uses the haversine formula with a mean Earth radius of 6371 km (design
    "Haversine distance"). Pure and symmetric; identical points return ``0.0``.
    """
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(d_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return _EARTH_RADIUS_KM * c


def _covering_slots(
    slots: Sequence[AvailabilitySlot], chosen: ChosenTime
) -> List[AvailabilitySlot]:
    """Available slots that cover the **full** chosen window (R7.2).

    A slot covers the window iff ``slot.start <= chosen.start`` and
    ``slot.end >= chosen.end``. ``slots`` are already filtered to ``available``
    by :func:`slots_for_matching`; this applies only the duration-coverage test.
    Returned in ascending start order so the earliest covering slot is first.
    """
    covering = [
        slot
        for slot in slots
        if slot.start <= chosen.start and slot.end >= chosen.end
    ]
    covering.sort(key=lambda s: s.start)
    return covering


def _qualification_count(
    volunteer: Volunteer,
    service_type: ServiceType,
    *,
    now: Optional[datetime],
) -> int:
    """Strength of the Volunteer's authorization for ``service_type``.

    Counts the Volunteer's **effective** credentials (verified, all conditions
    satisfied, not expired — the same predicate the Authorized_Services
    derivation uses) that authorize the requested Service_Type. A higher count
    means a stronger qualification match (design "Qualifications").

    Only reached for candidates that already passed the authorization hard
    filter, so this is always ``>= 1``.
    """
    count = 0
    for credential in volunteer.credentials:
        if not _is_credential_effective(credential, now=now):
            continue
        if any(st.id == service_type.id for st in credential.authorizes_service_types):
            count += 1
    return count


def _normalize_direct(values: Sequence[float]) -> List[float]:
    """Min-max normalize to ``[0, 1]`` where a larger raw value is more favorable.

    ``x_norm = (x - min) / (max - min)``. Degenerate case (all equal, i.e.
    ``max == min``): every value maps to ``1.0`` — this neutralizes a
    non-discriminating feature and avoids divide-by-zero (design degenerate
    rule, mirrors R16.3).
    """
    lo = min(values)
    hi = max(values)
    span = hi - lo
    if span == 0:
        return [1.0 for _ in values]
    return [(x - lo) / span for x in values]


def _normalize_inverted(values: Sequence[float]) -> List[float]:
    """Min-max normalize to ``[0, 1]`` where a smaller raw value is more favorable.

    Used for proximity (nearer is better): ``D_norm = 1 - (x - min)/(max - min)``,
    so the nearest candidate scores ``1.0`` and the farthest ``0.0``. Degenerate
    case (all equal): every value maps to ``1.0``.
    """
    lo = min(values)
    hi = max(values)
    span = hi - lo
    if span == 0:
        return [1.0 for _ in values]
    return [1.0 - (x - lo) / span for x in values]


def match(
    session: DBSession,
    patient: Patient,
    service_type: ServiceType,
    chosen_time: ChosenTime,
    weights: MatchWeights = DEFAULT_WEIGHTS,
    *,
    now: Optional[datetime] = None,
) -> Tuple[List[MatchResult], Optional[str]]:
    """Rank authorized, available Volunteers for the Patient's request (R7).

    Returns ``(ranked, message)``:

    * ``ranked`` — the candidate Volunteers ordered best-first as
      :class:`MatchResult`\\ s. Empty when no Volunteer passes both hard filters.
    * ``message`` — ``None`` on success, or :data:`NO_QUALIFIED_VOLUNTEERS` when
      the candidate set is empty (R7.6).

    The function is pure with respect to the database: it only reads
    (authorization, available slots, locations) and performs no writes, so it is
    safe to call repeatedly and deterministic for any fixed input. ``now`` is
    injectable so credential expiry is evaluated deterministically in tests.
    """
    # --- Discover every Volunteer, then apply the two hard filters in order. ---
    volunteers = list(session.query(Volunteer).order_by(Volunteer.id).all())

    # HARD FILTER 1 — Authorization (R7.1, R7.7): the requested Service_Type must
    # be in the Volunteer's credential-derived Authorized_Services. This is never
    # overridden by score. We read the single source of truth directly so the
    # engine can't drift from the credential facts.
    # HARD FILTER 2 — Availability (R7.2): a covering available slot must exist.
    @dataclass
    class _Candidate:
        volunteer: Volunteer
        distance_km: float
        availability_count: int
        qualification_count: int
        earliest_slot_start: datetime
        slot_id: int

    candidates: List[_Candidate] = []
    for volunteer in volunteers:
        authorized_ids = derive_authorized_service_types(volunteer, now=now)
        if service_type.id not in authorized_ids:
            continue  # unauthorized -> excluded regardless of any other factor

        available = slots_for_matching(session, volunteer)
        covering = _covering_slots(available, chosen_time)
        if not covering:
            continue  # no slot covers the full requested duration

        candidates.append(
            _Candidate(
                volunteer=volunteer,
                distance_km=haversine_km(
                    patient.latitude,
                    patient.longitude,
                    volunteer.latitude,
                    volunteer.longitude,
                ),
                # Availability feature: how free the Volunteer is around the
                # chosen time, measured as the number of available slots.
                availability_count=len(available),
                qualification_count=_qualification_count(
                    volunteer, service_type, now=now
                ),
                # Earliest covering slot start feeds the final tie-break.
                earliest_slot_start=covering[0].start,
                # Id of that earliest covering slot — threaded through so the
                # caller books this exact slot rather than guessing one.
                slot_id=covering[0].id,
            )
        )

    # Empty candidate set -> empty result + message (R7.6).
    if not candidates:
        return [], NO_QUALIFIED_VOLUNTEERS

    # --- Feature extraction + min-max normalization to [0, 1] (R7.3). ---
    distances = [c.distance_km for c in candidates]
    avails = [float(c.availability_count) for c in candidates]
    quals = [float(c.qualification_count) for c in candidates]

    proximity_norms = _normalize_inverted(distances)  # nearer -> higher
    availability_norms = _normalize_direct(avails)  # more free -> higher
    qualification_norms = _normalize_direct(quals)  # stronger match -> higher

    # --- Weighted score (R7.3, R7.4). ---
    results: List[MatchResult] = []
    for cand, d_norm, a_norm, q_norm in zip(
        candidates, proximity_norms, availability_norms, qualification_norms
    ):
        score = (
            weights.w_prox * d_norm
            + weights.w_avail * a_norm
            + weights.w_qual * q_norm
        )
        results.append(
            MatchResult(
                volunteer=cand.volunteer,
                score=score,
                distance_km=cand.distance_km,
                availability_count=cand.availability_count,
                qualification_count=cand.qualification_count,
                proximity_norm=d_norm,
                availability_norm=a_norm,
                qualification_norm=q_norm,
                earliest_slot_start=cand.earliest_slot_start,
                slot_id=cand.slot_id,
            )
        )

    # --- Sort descending with the deterministic 3-level tie-break (R7.4, R7.5). ---
    # Python's sort is stable; we build a single key that encodes, in order:
    #   1. higher score           -> negate (ascending sort => descending score)
    #   2. higher qualification   -> negate the raw qualification count
    #   3. nearer proximity       -> ascending distance_km
    #   4. earliest slot          -> ascending slot start
    results.sort(
        key=lambda r: (
            -r.score,
            -r.qualification_count,
            r.distance_km,
            r.earliest_slot_start,
        )
    )

    return results, None


__all__ = [
    "NO_QUALIFIED_VOLUNTEERS",
    "DEFAULT_WEIGHTS",
    "MatchWeights",
    "ChosenTime",
    "MatchResult",
    "haversine_km",
    "match",
]
