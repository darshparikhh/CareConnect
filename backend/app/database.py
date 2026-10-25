"""SQLAlchemy engine, session factory, and the transactional session dependency.

This module is the single place the rest of the backend gets a database
connection. It:

* builds a SQLAlchemy ``Engine`` against a file-based SQLite database (the URL
  comes from :mod:`app.config`),
* enforces SQLite foreign-key constraints on every connection (SQLite leaves
  them off by default, which would silently break the credential/appointment
  relationships added in later tasks),
* exposes a ``SessionLocal`` factory, and
* provides :func:`get_session`, a FastAPI dependency that yields a session
  wrapped in a transaction: it commits on success and rolls back on any error,
  then always closes the session.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_database_url
from app.models.base import Base


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def create_db_engine(database_url: str | None = None) -> Engine:
    """Create a configured SQLAlchemy engine.

    For SQLite we pass ``check_same_thread=False`` so the engine can be shared
    across FastAPI's worker threads, and register a pragma that turns on
    foreign-key enforcement for every new connection.
    """
    url = database_url or get_database_url()
    if _is_sqlite(url):
        engine = create_engine(
            url, connect_args={"check_same_thread": False}, future=True
        )

        @event.listens_for(engine, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        return engine

    # Non-sqlite backends (e.g. hosted Postgres): a normal pooled engine with
    # pre-ping so stale connections are recycled transparently.
    return create_engine(url, pool_pre_ping=True, future=True)


# Module-level engine and session factory bound to the configured database.
engine: Engine = create_db_engine()
SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    future=True,
)


def init_db(bind: Engine | None = None) -> None:
    """Create all tables registered on ``Base.metadata``.

    Importing the models package registers every entity's table on the shared
    metadata; calling this then creates any that do not yet exist.
    """
    # Imported for its import side effect: loading every model module so the
    # tables are registered on Base.metadata before create_all runs.
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=bind or engine)


@contextmanager
def session_scope(factory: sessionmaker | None = None) -> Iterator[Session]:
    """Context manager yielding a transactional session.

    Commits on clean exit, rolls back on exception, and always closes. Useful
    for seed scripts and non-request code paths.
    """
    session_factory = factory or SessionLocal
    session: Session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a transactional database session.

    Commits the transaction when the request handler returns successfully,
    rolls it back if the handler raises, and always closes the session so the
    connection is returned to the pool.
    """
    session: Session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


__all__ = [
    "engine",
    "SessionLocal",
    "create_db_engine",
    "init_db",
    "session_scope",
    "get_session",
]
