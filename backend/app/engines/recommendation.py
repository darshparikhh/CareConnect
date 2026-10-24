"""Recommendation_Engine: weighted doctor recommendation (R12.2, R15, R16).

This implements the design's **Data Science Component 2: Recommendation_Engine**.
It is a pure, deterministic function that, given a Patient, produces a ranked
list of :class:`~app.models.recommendation.RecommendedDoctor` records plus a
small result bundle describing filter outcomes, the weights actually used, and
any advisory message.

Pipeline (exactly as specified in the design):

1. **Preprocess (R16.9)** — clean provider Synthetic_Data (repair malformed
   records, coerce types, bound ratings to a valid range, default missing
   availability/travel), then compute geospatial Proximity (haversine distance
   from the Patient) for *every* provider. Normalization happens only after
   cleaning.
2. **Hard filters (R15 — never overridden by score)**, in order:

   0. If the Patient has no recorded ``required_specialty`` (only set via a
      Referral, R12.2) → empty result + no-required-specialty message (R15.6).
   1. Exact specialty match: ``doctor.specialty == patient.required_specialty``
      (R15.1).
   2. Verified-insurance compatibility via
      :func:`app.services.insurance.compatibility` — a doctor is kept only when
      that call returns ``compatible`` (R15.2). While the Patient's insurance is
      unverified the service returns ``unknown``; such doctors are never kept
      and compatibility is never asserted (R15.3, R15.4).

   If no doctor passes both → empty + no-compatible-doctors message (R15.5).
3. **Weights (R16.7, R16.8)** — validate configured weights (each in
   ``[0, 1]`` and summing to ``1.0 ± 0.001``); on failure fall back to the
   defaults ``(0.40, 0.30, 0.20, 0.10)`` and attach an invalid-weights message.
4. **Normalize (R16.2, R16.3)** D, A, R, T to ``[0, 1]`` with ``1.0`` most
   favorable, inverting distance (D) and travel time (T); when every candidate
   shares a factor's value, that factor is ``1.0`` for all (degenerate case).
5. **Score (R16.1)** ``S = 0.40·D + 0.30·A + 0.20·R + 0.10·T`` applied only to
   candidates that passed the hard filters (R16.10).
6. **Rank / cap** — sort by descending S, tie-break by ascending Proximity when
   scores are within ``0.001`` (R16.5, R16.6); return at most 50 (R15.7).

The function is a pure read: it mutates nothing in the database and never
commits. The cleaning step operates on in-memory copies of the provider factors
so the ``RecommendedDoctor`` ORM objects are left untouched.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.models.people import Patient
from app.models.recommendation import RecommendedDoctor
from app.services import insurance

# Default scoring weights for (D, A, R, T) — proximity, availability, rating,
# travel convenience (R16.1). Used when no valid override is supplied.
DEFAULT_WEIGHTS: Tuple[float, float, float, float] = (0.40, 0.30, 0.20, 0.10)

# Tolerance used both for weight-sum validation (R16.7/R16.8) and for the
# score tie-break window (R16.6).
TOLERANCE = 0.001

# Maximum number of recommendations returned (R15.7).
MAX_RESULTS = 50

# Rating is bounded to this inclusive range during cleaning (R16.9). The seed's
# synthetic ratings are on a 0-5 scale.
RATING_MIN = 0.0
RATING_MAX = 5.0

# Earth mean radius in kilometers, for the haversine proximity computation.
_EARTH_RADIUS_KM = 6371.0088

# Stable advisory messages surfaced to callers/UI.
NO_REQUIRED_SPECIALTY_MESSAGE = "no required specialty has been recorded"
NO_COMPATIBLE_DOCTORS_MESSAGE = "no compatible doctors were found"
INVALID_WEIGHTS_MESSAGE = (
    "configured scoring weights are invalid; default weights were applied"
)


@dataclass(frozen=True)
class ScoredDoctor:
    """A candidate that passed the hard filters, with its computed score.

    ``proximity_km`` is the haversine distance from the Patient (computed before
    normalization, R16.9) and doubles as the deterministic tie-break key
    (R16.6). The normalized factors are retained for transparency/debugging.
    """

    doctor: RecommendedDoctor
    score: float
    proximity_km: float
    normalized_distance: float
    normalized_availability: float
    normalized_rating: float
    normalized_travel: float


@dataclass(frozen=True)
class RecommendationResult:
    """The Recommendation_Engine's output bundle.

    ``doctors`` is the ranked, capped list of recommended providers (possibly
    empty). ``scored`` carries the parallel per-candidate scoring detail.
    ``weights`` is the (D, A, R, T) tuple actually used for scoring — always a
    valid tuple (validated-or-default). ``message`` is an advisory string
    (no-required-specialty, no-compatible-doctors, or invalid-weights) or
    ``None``. ``insurance_asserted`` is ``False`` whenever the Patient's
    insurance is unverified, reflecting that no doctor is asserted compatible
    (R15.4).
    """

    doctors: List[RecommendedDoctor] = field(default_factory=list)
    scored: List[ScoredDoctor] = field(default_factory=list)
    weights: Tuple[float, float, float, float] = DEFAULT_WEIGHTS
    message: Optional[str] = None
    insurance_asserted: bool = False


# ---------------------------------------------------------------------------
# Cleaned, in-memory view of a provider's scoring factors
# ---------------------------------------------------------------------------
@dataclass
class _CleanDoctor:
    """A repaired, type-coerced view of a provider's scoring factors.

    Produced by :func:`_preprocess` so normalization/scoring never sees a
    malformed value. Wraps the original ORM object so the final result can hand
    back real :class:`RecommendedDoctor` instances.
    """

    doctor: RecommendedDoctor
    latitude: float
    longitude: float
    rating: float
    open_slots_14d: float
    travel_minutes: float
    proximity_km: float = 0.0


def _coerce_float(value: object, default: float) -> float:
    """Coerce ``value`` to a finite float, falling back to ``default``.

    Handles ``None``, non-numeric strings, and NaN/inf by returning ``default``;
    numeric strings like ``"4.5"`` are parsed. This is the type-coercion /
    malformed-record repair required by R16.9.
    """
    if value is None:
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(result):
        return default
    return result


def _bound(value: float, low: float, high: float) -> float:
    """Clamp ``value`` into the inclusive ``[low, high]`` range."""
    if value < low:
        return low
    if value > high:
        return high
    return value


def _preprocess(
    doctors: Sequence[RecommendedDoctor], patient: Patient
) -> List[_CleanDoctor]:
    """Clean provider data and compute haversine proximity (R16.9).

    For every provider: coerce factor types, bound the rating to ``[0, 5]``,
    treat missing/negative availability as ``0`` and missing/negative travel
    time as ``0`` minutes, and compute the haversine distance from the Patient.
    Records with an unusable (non-numeric) location are dropped — without a
    location the provider cannot be placed on the map and thus cannot be scored
    for proximity. This runs before any normalization.
    """
    patient_lat = _coerce_float(patient.latitude, default=math.nan)
    patient_lng = _coerce_float(patient.longitude, default=math.nan)
    patient_located = math.isfinite(patient_lat) and math.isfinite(patient_lng)

    cleaned: List[_CleanDoctor] = []
    for doctor in doctors:
        lat = _coerce_float(doctor.latitude, default=math.nan)
        lng = _coerce_float(doctor.longitude, default=math.nan)
        if not (math.isfinite(lat) and math.isfinite(lng)):
            # Malformed/unusable location: drop the record (R16.9 cleaning).
            continue

        rating = _bound(
            _coerce_float(doctor.rating, default=RATING_MIN), RATING_MIN, RATING_MAX
        )
        # Availability and travel are non-negative; repair bad values to 0.
        slots = max(0.0, _coerce_float(doctor.open_slots_14d, default=0.0))
        travel = max(0.0, _coerce_float(doctor.one_way_travel_minutes, default=0.0))

        proximity = (
            _haversine_km(patient_lat, patient_lng, lat, lng)
            if patient_located
            else 0.0
        )

        cleaned.append(
            _CleanDoctor(
                doctor=doctor,
                latitude=lat,
                longitude=lng,
                rating=rating,
                open_slots_14d=slots,
                travel_minutes=travel,
                proximity_km=proximity,
            )
        )
    return cleaned


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometers between two lat/lng points.

    Standard haversine formula over the Earth's mean radius. Deterministic and
    symmetric; returns ``0.0`` for identical points.
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


# ---------------------------------------------------------------------------
# Weight validation (R16.7, R16.8)
# ---------------------------------------------------------------------------
def _validate_weights(
    weights: Sequence[float],
) -> Tuple[Tuple[float, float, float, float], bool]:
    """Validate configured weights, falling back to defaults on failure.

    Valid weights are exactly four values, each in ``[0.0, 1.0]``, summing to
    ``1.0 ± TOLERANCE`` (R16.7). Any violation → defaults are returned and the
    second element is ``True`` to signal the invalid-weights message (R16.8).
    """
    if weights is None or len(tuple(weights)) != 4:
        return DEFAULT_WEIGHTS, True

    values = tuple(weights)
    try:
        coerced = tuple(float(w) for w in values)
    except (TypeError, ValueError):
        return DEFAULT_WEIGHTS, True

    if any((not math.isfinite(w)) or w < 0.0 or w > 1.0 for w in coerced):
        return DEFAULT_WEIGHTS, True
    if abs(sum(coerced) - 1.0) > TOLERANCE:
        return DEFAULT_WEIGHTS, True

    return (coerced[0], coerced[1], coerced[2], coerced[3]), False


# ---------------------------------------------------------------------------
# Normalization (R16.2, R16.3)
# ---------------------------------------------------------------------------
def _normalize(values: Sequence[float], *, invert: bool) -> List[float]:
    """Min-max normalize ``values`` to ``[0, 1]`` with 1.0 most favorable.

    For direct factors (availability, rating) higher raw values map to higher
    normalized values. For inverse factors (distance, travel time) the direction
    is flipped so smaller raw values map to higher normalized values (R16.2).

    Degenerate case (R16.3): when every value is equal (``max == min``) the
    factor cannot discriminate, so every candidate receives ``1.0``.
    """
    lo = min(values)
    hi = max(values)
    span = hi - lo
    if span <= 0.0:
        # All-equal: non-discriminating factor neutralized to 1.0 for everyone.
        return [1.0 for _ in values]

    normalized: List[float] = []
    for value in values:
        unit = (value - lo) / span  # 0 at min, 1 at max
        normalized.append(1.0 - unit if invert else unit)
    return normalized


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def recommend(
    session: DBSession,
    patient: Patient,
    weights: Sequence[float] = DEFAULT_WEIGHTS,
) -> RecommendationResult:
    """Recommend doctors for ``patient`` (R12.2, R15, R16).

    Pure and deterministic: for a fixed database state and inputs the output is
    always identical. See the module docstring for the full pipeline.

    ``weights`` is the optional ``(D, A, R, T)`` override; invalid weights are
    ignored in favour of the defaults with an advisory message (R16.8).
    """
    # --- Hard filter 0: required specialty must exist (R15.6) ---
    required_specialty = patient.required_specialty
    if required_specialty is None or str(required_specialty).strip() == "":
        return RecommendationResult(
            doctors=[],
            scored=[],
            weights=DEFAULT_WEIGHTS,
            message=NO_REQUIRED_SPECIALTY_MESSAGE,
            insurance_asserted=False,
        )

    # Load the provider pool and preprocess/clean + compute proximity (R16.9).
    providers = list(session.execute(select(RecommendedDoctor)).scalars())
    cleaned = _preprocess(providers, patient)

    # Whether insurance is verified at all — drives insurance_asserted (R15.4).
    record = patient.insurance_record
    insurance_verified = (
        record is not None
        and record.verification_status is not None
        and getattr(record.verification_status, "value", record.verification_status)
        == "verified"
    )

    # --- Hard filter 1: exact specialty match (R15.1) ---
    # --- Hard filter 2: verified-insurance compatibility (R15.2, R15.4) ---
    required_key = str(required_specialty).strip().casefold()
    candidates: List[_CleanDoctor] = []
    for clean in cleaned:
        if str(clean.doctor.specialty).strip().casefold() != required_key:
            continue
        # Never assert compatibility while unverified: compatibility() returns
        # ``unknown`` and the doctor is excluded (R15.3, R15.4).
        result = insurance.compatibility(session, patient, clean.doctor)
        if not result.is_compatible:
            continue
        candidates.append(clean)

    # --- No candidate passed both hard filters (R15.5) ---
    if not candidates:
        return RecommendationResult(
            doctors=[],
            scored=[],
            weights=DEFAULT_WEIGHTS,
            message=NO_COMPATIBLE_DOCTORS_MESSAGE,
            insurance_asserted=insurance_verified,
        )

    # --- Validate weights, fall back to defaults on failure (R16.7, R16.8) ---
    used_weights, invalid = _validate_weights(weights)
    message = INVALID_WEIGHTS_MESSAGE if invalid else None

    # --- Normalize D, A, R, T across the filtered candidates (R16.2, R16.3) ---
    distances = [c.proximity_km for c in candidates]
    availabilities = [c.open_slots_14d for c in candidates]
    ratings = [c.rating for c in candidates]
    travels = [c.travel_minutes for c in candidates]

    norm_d = _normalize(distances, invert=True)  # nearer → higher
    norm_a = _normalize(availabilities, invert=False)  # more slots → higher
    norm_r = _normalize(ratings, invert=False)  # higher rating → higher
    norm_t = _normalize(travels, invert=True)  # shorter travel → higher

    w_d, w_a, w_r, w_t = used_weights

    # --- Score only candidates that passed the hard filters (R16.1, R16.10) ---
    scored: List[ScoredDoctor] = []
    for clean, d, a, r, t in zip(candidates, norm_d, norm_a, norm_r, norm_t):
        score = w_d * d + w_a * a + w_r * r + w_t * t
        scored.append(
            ScoredDoctor(
                doctor=clean.doctor,
                score=score,
                proximity_km=clean.proximity_km,
                normalized_distance=d,
                normalized_availability=a,
                normalized_rating=r,
                normalized_travel=t,
            )
        )

    # --- Rank: descending S, tie-break ascending proximity within 0.001 ---
    # (R16.5, R16.6). Sorting by (-score, proximity) does not honour the 0.001
    # tie window on its own, so quantize the score into 0.001 buckets for the
    # primary key and use proximity as the secondary key. Within a bucket the
    # nearer provider ranks first; this is fully deterministic.
    def _sort_key(item: ScoredDoctor) -> Tuple[float, float]:
        bucket = round(item.score / TOLERANCE)
        return (-bucket, item.proximity_km)

    scored.sort(key=_sort_key)

    # --- Cap at 50 (R15.7) ---
    scored = scored[:MAX_RESULTS]

    return RecommendationResult(
        doctors=[s.doctor for s in scored],
        scored=scored,
        weights=used_weights,
        message=message,
        insurance_asserted=insurance_verified,
    )


__all__ = [
    "DEFAULT_WEIGHTS",
    "TOLERANCE",
    "MAX_RESULTS",
    "NO_REQUIRED_SPECIALTY_MESSAGE",
    "NO_COMPATIBLE_DOCTORS_MESSAGE",
    "INVALID_WEIGHTS_MESSAGE",
    "ScoredDoctor",
    "RecommendationResult",
    "recommend",
]
