"""Enumerations shared across the CareConnect data model.

These mirror the design's ``Enumerations`` section. They are plain ``str``-backed
``enum.Enum`` subclasses so SQLAlchemy stores the human-readable value (e.g.
``"booked"``) in SQLite while application code works with the typed members.
"""

from __future__ import annotations

import enum


class AppointmentState(str, enum.Enum):
    """The appointment lifecycle state (always exactly one of these)."""

    booked = "booked"
    accepted = "accepted"
    completed = "completed"
    cancelled = "cancelled"


class VerificationStatus(str, enum.Enum):
    """Verification status for credentials and insurance records."""

    unverified = "unverified"
    verified = "verified"


class SlotStatus(str, enum.Enum):
    """Availability-slot assignment state."""

    available = "available"
    unavailable = "unavailable"


class InsuranceCompatibility(str, enum.Enum):
    """Patient/doctor insurance compatibility as reported to the UI."""

    compatible = "compatible"
    incompatible = "incompatible"
    unknown = "unknown"


class Role(str, enum.Enum):
    """Account role used for role-based access control."""

    patient = "patient"
    volunteer = "volunteer"
    clinician = "clinician"


__all__ = [
    "AppointmentState",
    "VerificationStatus",
    "SlotStatus",
    "InsuranceCompatibility",
    "Role",
]
