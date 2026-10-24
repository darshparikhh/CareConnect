"""Credentials, service types, conditions, and the derived authorized-service join.

A ``Credential`` (held by a Volunteer or a Clinician) authorizes a set of
``ServiceType``s but only confers them when ``status == verified`` AND every one
of its ``conditions`` is satisfied. ``AuthorizedService`` is the derived join
Credential_Service recomputes as the single source of truth for what a Volunteer
may actually do (R5).
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Table,
    Column,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import VerificationStatus


# Many-to-many: which Service_Types a Credential authorizes (R5).
credential_service_type = Table(
    "credential_service_type",
    Base.metadata,
    Column(
        "credential_id",
        ForeignKey("credentials.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "service_type_id",
        ForeignKey("service_types.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class ServiceType(Base):
    """A performable service, e.g. ``vaccination`` (R5, R10.5).

    ``required_tests`` and ``required_questions`` are stored as comma-separated
    identifier lists; Visit_Service uses them to decide completion.
    """

    __tablename__ = "service_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    required_tests: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    required_questions: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    credentials: Mapped[List["Credential"]] = relationship(
        "Credential",
        secondary=credential_service_type,
        back_populates="authorizes_service_types",
    )


class Credential(Base):
    """A declared credential, verifiable to confer its Service_Types (R5).

    Exactly one of ``volunteer_id`` / ``clinician_id`` is set depending on the
    owner. A Clinician's license is modelled as a Credential on the Clinician.
    """

    __tablename__ = "credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String, nullable=False)

    volunteer_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("volunteers.id", ondelete="CASCADE"), nullable=True, index=True
    )
    clinician_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clinicians.id", ondelete="CASCADE"), nullable=True, index=True
    )

    status: Mapped[VerificationStatus] = mapped_column(
        Enum(VerificationStatus, name="verification_status"),
        nullable=False,
        default=VerificationStatus.unverified,
    )
    verifying_authority: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    volunteer: Mapped[Optional["Volunteer"]] = relationship(
        "Volunteer", back_populates="credentials"
    )
    clinician: Mapped[Optional["Clinician"]] = relationship(
        "Clinician", back_populates="credentials"
    )

    authorizes_service_types: Mapped[List[ServiceType]] = relationship(
        "ServiceType",
        secondary=credential_service_type,
        back_populates="credentials",
    )
    conditions: Mapped[List["CredentialCondition"]] = relationship(
        "CredentialCondition",
        back_populates="credential",
        cascade="all, delete-orphan",
    )


class CredentialCondition(Base):
    """A state/training/supervision condition on a Credential (R5.4).

    A Credential confers its Service_Types only when verified AND every one of
    these conditions has ``satisfied == True``.
    """

    __tablename__ = "credential_conditions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    credential_id: Mapped[int] = mapped_column(
        ForeignKey("credentials.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String, nullable=False)
    satisfied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    credential: Mapped[Credential] = relationship(
        "Credential", back_populates="conditions"
    )


class AuthorizedService(Base):
    """Derived join ``(volunteer, service_type)`` recomputed by Credential_Service.

    Only ever present when a verified, condition-satisfied credential authorizes
    the Service_Type (R5.2, R5.6, R5.7).
    """

    __tablename__ = "authorized_services"
    __table_args__ = (
        UniqueConstraint(
            "volunteer_id", "service_type_id", name="uq_authorized_service"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    volunteer_id: Mapped[int] = mapped_column(
        ForeignKey("volunteers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    service_type_id: Mapped[int] = mapped_column(
        ForeignKey("service_types.id", ondelete="CASCADE"), nullable=False, index=True
    )

    volunteer: Mapped["Volunteer"] = relationship(
        "Volunteer", back_populates="authorized_services"
    )
    service_type: Mapped[ServiceType] = relationship("ServiceType")


from app.models.people import Clinician, Volunteer  # noqa: E402,F401


__all__ = [
    "ServiceType",
    "Credential",
    "CredentialCondition",
    "AuthorizedService",
    "credential_service_type",
]
