"""Recommendable providers scored by the Recommendation_Engine.

A ``RecommendedDoctor`` is provider Synthetic_Data distinct from a Clinician
unless they are the same person. It carries the raw factors the engine cleans,
normalizes, and scores: specialty, ``location{lat,lng}``, rating, open slots in a
14-day window, and one-way travel minutes, plus the set of accepted insurance
plans (R15, R16).
"""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class RecommendedDoctor(Base):
    """A provider record ranked by the Recommendation_Engine (R15, R16)."""

    __tablename__ = "recommended_doctors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    specialty: Mapped[str] = mapped_column(String, nullable=False, index=True)

    # location{lat,lng}
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)

    rating: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    open_slots_14d: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    one_way_travel_minutes: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )

    accepted_insurance: Mapped[List["InsuranceRecord"]] = relationship(
        "InsuranceRecord",
        secondary="doctor_accepted_insurance",
        back_populates="accepting_doctors",
    )


from app.models.insurance import InsuranceRecord  # noqa: E402,F401


__all__ = ["RecommendedDoctor"]
