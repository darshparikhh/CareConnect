"""Smoke tests for the backend foundation (task 1).

These assert the project scaffolding is wired correctly: the app imports and
serves a health check, the SQLite engine enforces foreign keys and runs
transactional sessions, and the isolated test fixtures work.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app import __version__
from app.database import create_db_engine, session_scope
from app.main import create_app


def test_app_imports_and_health_check_ok() -> None:
    app = create_app()
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_sqlite_engine_enforces_foreign_keys() -> None:
    engine = create_db_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        pragma = conn.execute(text("PRAGMA foreign_keys")).scalar()
    # 1 means foreign-key enforcement is on.
    assert pragma == 1


def test_db_session_fixture_is_usable(db_session: Session) -> None:
    result = db_session.execute(text("SELECT 1")).scalar()
    assert result == 1


def test_in_memory_engine_fixture_is_usable(in_memory_engine: Engine) -> None:
    with in_memory_engine.connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar() == 1


def test_session_scope_commits_and_rolls_back(db_engine: Engine) -> None:
    from sqlalchemy.orm import sessionmaker

    factory = sessionmaker(bind=db_engine, future=True, expire_on_commit=False)

    with db_engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS smoke (id INTEGER PRIMARY KEY)"))

    # Commit path: row persists after the scope exits.
    with session_scope(factory) as session:
        session.execute(text("INSERT INTO smoke (id) VALUES (1)"))

    with factory() as check:
        assert check.execute(text("SELECT COUNT(*) FROM smoke")).scalar() == 1

    # Rollback path: an error inside the scope leaves no new row.
    try:
        with session_scope(factory) as session:
            session.execute(text("INSERT INTO smoke (id) VALUES (2)"))
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    with factory() as check:
        assert check.execute(text("SELECT COUNT(*) FROM smoke")).scalar() == 1
