"""Nearby-hospitals service over a locally bundled CMS dataset.

The CMS "Hospital General Information" dataset (``xubh-q36u``) blocks
server-side API calls (HTTP 403), so the Massachusetts subset is bundled at
``app/data/ma_hospitals.json`` and loaded once into a module-level cache. This
keeps the feature fully offline for the demo.

The one public entry point, :func:`nearby_hospitals`, is a pure function over
the loaded data: it ranks hospitals by ZIP-code proximity to a patient's ZIP
and returns a trimmed, display-ready projection. There is no network here.

Proximity model: with no lat/long in the trimmed dataset, "closeness" is
approximated by the absolute numeric difference between the hospital's ZIP and
the patient's ZIP (both are 5-digit MA ZIPs, so a smaller difference tends to
mean geographically closer). Hospitals with a missing or non-numeric ZIP sort
last behind every ranked hospital.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

# Bundled dataset lives alongside the app package: app/data/ma_hospitals.json.
_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "ma_hospitals.json"

# Module-level cache so the JSON is parsed once per process, not per request.
_HOSPITALS: Optional[List[dict]] = None

# Sentinel distance for hospitals whose ZIP cannot be parsed numerically; keeps
# them strictly after any hospital that produced a real numeric distance.
_UNRANKED_DISTANCE = 10 ** 9

# Fields the public projection exposes (ratings pass through verbatim, e.g.
# "Not Available"). ``zip_distance`` is computed, not read from the dataset.
_PROJECTION_FIELDS = (
    "facility_name",
    "address",
    "citytown",
    "zip_code",
    "telephone_number",
    "hospital_type",
    "hospital_overall_rating",
)


def _load() -> List[dict]:
    """Load and cache the bundled MA hospital records.

    The loader makes no assumption about how many records the file holds; it
    returns whatever the JSON array contains.
    """
    global _HOSPITALS
    if _HOSPITALS is None:
        with _DATA_PATH.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        _HOSPITALS = list(data)
    return _HOSPITALS


def _zip_distance(hospital_zip: Optional[str], patient_zip_int: Optional[int]) -> int:
    """Absolute numeric ZIP difference, or the unranked sentinel.

    A missing/non-numeric hospital ZIP, or a missing/non-numeric patient ZIP,
    yields the sentinel so such rows sort last.
    """
    if patient_zip_int is None:
        return _UNRANKED_DISTANCE
    try:
        return abs(int(str(hospital_zip).strip()) - patient_zip_int)
    except (TypeError, ValueError):
        return _UNRANKED_DISTANCE


def _parse_patient_zip(zip_code: Optional[str]) -> Optional[int]:
    """Parse the patient's ZIP to an int, or ``None`` if it is not numeric."""
    try:
        return int(str(zip_code).strip())
    except (TypeError, ValueError):
        return None


def _project(hospital: dict, distance: int) -> dict:
    """Project a raw record into the trimmed, display-ready dict."""
    projected = {field: hospital.get(field, "") for field in _PROJECTION_FIELDS}
    projected["zip_distance"] = int(distance)
    return projected


def nearby_hospitals(
    zip_code: str,
    limit: int = 10,
    hospital_type: Optional[str] = None,
) -> List[dict]:
    """Rank MA hospitals by ZIP proximity to ``zip_code`` and return up to ``limit``.

    Args:
        zip_code: The patient's 5-digit MA ZIP to rank against. A non-numeric or
            empty value is tolerated: every hospital then gets the unranked
            sentinel distance and results fall back to the ``facility_name``
            tie-break order.
        limit: Maximum number of hospitals to return. Non-positive values yield
            an empty list.
        hospital_type: Optional exact (case-insensitive) ``hospital_type`` filter
            (e.g. ``"Acute Care Hospitals"``). ``None`` applies no filter.

    Returns:
        A list of trimmed dicts, each with ``facility_name``, ``address``,
        ``citytown``, ``zip_code``, ``telephone_number``, ``hospital_type``,
        ``hospital_overall_rating`` (passed through as-is, including
        ``"Not Available"``) and a computed integer ``zip_distance``. Sorted
        ascending by ``zip_distance``, tie-broken by ``facility_name``.
    """
    if limit <= 0:
        return []

    hospitals = _load()
    patient_zip_int = _parse_patient_zip(zip_code)

    wanted_type = hospital_type.strip().lower() if hospital_type else None

    scored: List[dict] = []
    for hospital in hospitals:
        if wanted_type is not None:
            if (hospital.get("hospital_type") or "").strip().lower() != wanted_type:
                continue
        distance = _zip_distance(hospital.get("zip_code"), patient_zip_int)
        scored.append(_project(hospital, distance))

    scored.sort(key=lambda h: (h["zip_distance"], h["facility_name"]))
    return scored[:limit]
