"""Shared pytest fixtures providing an isolated SQLite database per test.

The fixtures build a dedicated SQLAlchemy engine against a throwaway database
so tests never touch the file-based development database and never leak state
between each other:

* ``db_engine`` creates a fresh engine on a temp-file SQLite database (file-based
  so the same schema/behaviour as production is exercised, including foreign-key
  enforcement), creates all tables, and disposes/removes it afterward.
* ``db_session`` yields a transactional session bound to that engine and rolls
  back at the end, guaranteeing isolation even within a single database.

Tests that need a purely in-memory database can depend on ``in_memory_engine``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import create_db_engine, init_db
from app.models.base import Base


@pytest.fixture()
def db_engine(tmp_path: Path) -> Iterator[Engine]:
    """A fresh file-based SQLite engine with the full schema, per test."""
    db_path = tmp_path / "test_careconnect.db"
    engine = create_db_engine(f"sqlite:///{db_path}")
    init_db(bind=engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def in_memory_engine() -> Iterator[Engine]:
    """A fresh in-memory SQLite engine with the full schema, per test."""
    engine = create_db_engine("sqlite:///:memory:")
    init_db(bind=engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture()
def db_session(db_engine: Engine) -> Iterator[Session]:
    """A transactional session bound to the per-test file-based engine."""
    factory = sessionmaker(
        bind=db_engine,
        autoflush=False,
        expire_on_commit=False,
        future=True,
    )
    session = factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
