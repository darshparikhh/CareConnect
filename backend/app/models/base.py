"""Shared SQLAlchemy declarative base.

All ORM models (added in task 2) inherit from ``Base`` so they register against
a single ``MetaData``. Keeping the base in its own module avoids import cycles
between the models package and the database engine module.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for every CareConnect ORM model."""


__all__ = ["Base"]
